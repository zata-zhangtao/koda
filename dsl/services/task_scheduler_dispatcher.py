"""任务调度分发器.

负责把到期调度规则分发到既有任务动作链路（start_task/resume_task/review_task）。
"""

from __future__ import annotations

import asyncio
import threading

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from dsl.models.enums import TaskScheduleActionType, TaskScheduleRunStatus
from dsl.models.task_schedule import TaskSchedule
from dsl.models.task_schedule_run import TaskScheduleRun
from dsl.services.task_schedule_service import TaskScheduleService
from utils.database import SessionLocal
from utils.helpers import utc_now_naive
from utils.logger import logger


class TaskSchedulerDispatcher:
    """任务调度分发器."""

    @staticmethod
    def _run_background_task_in_thread(
        task_schedule_id_str: str,
        background_task_callable,
    ) -> None:
        """在独立线程中运行 Starlette BackgroundTask.

        Args:
            task_schedule_id_str: 调度规则 ID
            background_task_callable: 可调用对象
        """

        def _thread_runner() -> None:
            try:
                asyncio.run(background_task_callable())
            except Exception as background_task_error:  # pragma: no cover
                logger.exception(
                    "Scheduled task worker crashed for schedule %s...: %s",
                    task_schedule_id_str[:8],
                    background_task_error,
                )

        background_thread = threading.Thread(target=_thread_runner, daemon=True)
        background_thread.start()

    @staticmethod
    def _dispatch_task_action_via_existing_api(
        task_schedule_obj: TaskSchedule,
        db_session: Session,
    ) -> None:
        """复用现有任务 API 路由逻辑执行调度动作.

        Args:
            task_schedule_obj: 调度规则
            db_session: 数据库会话

        Raises:
            HTTPException: 复用路由中的业务校验异常
            RuntimeError: 背景任务未成功注册时抛出
        """
        import dsl.api.tasks as task_api_module

        background_tasks = BackgroundTasks()
        if task_schedule_obj.action_type == TaskScheduleActionType.START_TASK:
            task_api_module.start_task(
                task_id=task_schedule_obj.task_id,
                background_tasks=background_tasks,
                db_session=db_session,
            )
        elif task_schedule_obj.action_type == TaskScheduleActionType.RESUME_TASK:
            task_api_module.resume_task(
                task_id=task_schedule_obj.task_id,
                background_tasks=background_tasks,
                db_session=db_session,
            )
        else:
            task_api_module.review_task(
                task_id=task_schedule_obj.task_id,
                background_tasks=background_tasks,
                db_session=db_session,
            )

        if not background_tasks.tasks:
            raise RuntimeError("No background task was scheduled by task action")

        for background_task_obj in background_tasks.tasks:
            TaskSchedulerDispatcher._run_background_task_in_thread(
                task_schedule_obj.id,
                background_task_obj,
            )

    @staticmethod
    def _dispatch_single_schedule(
        db_session: Session,
        *,
        task_schedule_obj: TaskSchedule,
        planned_run_at_utc_naive_datetime,
        should_advance_schedule_bool: bool,
    ) -> TaskScheduleRun | None:
        """分发单条调度规则并写入执行审计.

        Args:
            db_session: 数据库会话
            task_schedule_obj: 调度规则
            planned_run_at_utc_naive_datetime: 本次计划触发时间
            should_advance_schedule_bool: 是否推进下一次调度

        Returns:
            TaskScheduleRun | None: 执行记录对象；若命中唯一键冲突则返回 None
        """
        triggered_at_utc_naive_datetime = utc_now_naive()
        run_status = TaskScheduleRunStatus.FAILED
        skip_reason_str: str | None = None
        error_message_str: str | None = None

        if should_advance_schedule_bool:
            is_schedule_claimed = TaskScheduleService.claim_schedule_for_dispatch(
                db_session,
                task_schedule_obj=task_schedule_obj,
                planned_run_at_utc_naive_datetime=planned_run_at_utc_naive_datetime,
                triggered_at_utc_naive_datetime=triggered_at_utc_naive_datetime,
                should_advance_schedule_bool=should_advance_schedule_bool,
            )
            if not is_schedule_claimed:
                logger.info(
                    "Skipped dispatch for unclaimed schedule window: schedule=%s planned_run_at=%s",
                    task_schedule_obj.id[:8],
                    planned_run_at_utc_naive_datetime.isoformat(),
                )
                return None

        try:
            TaskSchedulerDispatcher._dispatch_task_action_via_existing_api(
                task_schedule_obj,
                db_session,
            )
            run_status = TaskScheduleRunStatus.SUCCEEDED
        except HTTPException as http_error:
            db_session.rollback()
            if http_error.status_code == 409:
                run_status = TaskScheduleRunStatus.SKIPPED
                skip_reason_str = str(http_error.detail)
            else:
                error_message_str = str(http_error.detail)
        except Exception as dispatch_error:
            db_session.rollback()
            error_message_str = str(dispatch_error)

        return TaskScheduleService.apply_schedule_dispatch_result(
            db_session,
            task_schedule_obj=task_schedule_obj,
            planned_run_at_utc_naive_datetime=planned_run_at_utc_naive_datetime,
            triggered_at_utc_naive_datetime=triggered_at_utc_naive_datetime,
            run_status=run_status,
            should_advance_schedule_bool=should_advance_schedule_bool,
            schedule_already_claimed_bool=should_advance_schedule_bool,
            skip_reason_str=skip_reason_str,
            error_message_str=error_message_str,
        )

    @staticmethod
    def dispatch_due_schedules(max_dispatch_count_int: int) -> int:
        """分发当前到期的调度规则.

        Args:
            max_dispatch_count_int: 本轮最多派发条数

        Returns:
            int: 本轮实际处理的调度条数（去重后）
        """
        if max_dispatch_count_int <= 0:
            return 0

        db_session = SessionLocal()
        try:
            now_utc_naive_datetime = utc_now_naive()
            due_task_schedule_obj_list = TaskScheduleService.list_due_enabled_schedules(
                db_session,
                now_utc_naive_datetime=now_utc_naive_datetime,
                max_dispatch_count_int=max_dispatch_count_int,
            )
            if not due_task_schedule_obj_list:
                return 0

            processed_schedule_count_int = 0
            for due_task_schedule_obj in due_task_schedule_obj_list:
                planned_run_at_utc_naive_datetime = (
                    due_task_schedule_obj.next_run_at or now_utc_naive_datetime
                )
                created_schedule_run_obj = TaskSchedulerDispatcher._dispatch_single_schedule(
                    db_session,
                    task_schedule_obj=due_task_schedule_obj,
                    planned_run_at_utc_naive_datetime=planned_run_at_utc_naive_datetime,
                    should_advance_schedule_bool=True,
                )
                if created_schedule_run_obj is not None:
                    processed_schedule_count_int += 1

            return processed_schedule_count_int
        finally:
            db_session.close()

    @staticmethod
    def dispatch_schedule_run_now(
        db_session: Session,
        *,
        task_schedule_obj: TaskSchedule,
    ) -> TaskScheduleRun:
        """立即触发一次调度规则（调试入口）.

        Args:
            db_session: 数据库会话
            task_schedule_obj: 调度规则

        Returns:
            TaskScheduleRun: 本次触发生成的执行记录

        Raises:
            ValueError: 若命中同一计划时间的唯一键冲突
        """
        planned_run_at_utc_naive_datetime = utc_now_naive()
        created_schedule_run_obj = TaskSchedulerDispatcher._dispatch_single_schedule(
            db_session,
            task_schedule_obj=task_schedule_obj,
            planned_run_at_utc_naive_datetime=planned_run_at_utc_naive_datetime,
            should_advance_schedule_bool=False,
        )
        if created_schedule_run_obj is None:
            raise ValueError("Duplicate schedule run window detected")
        return created_schedule_run_obj
