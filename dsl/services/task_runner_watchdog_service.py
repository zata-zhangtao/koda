"""任务 Runner 看门狗服务.

负责周期扫描卡在 AI 执行阶段（prd_generating / implementation_in_progress /
self_review_in_progress / test_in_progress）却没有活跃 runner 进程的任务，
自动触发 resume 完成补救。

典型触发场景：服务器重启后 BackgroundTask 丢失，或 runner 进程意外崩溃后
状态未能回写到 changes_requested。
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from dsl.models.enums import TaskLifecycleStatus, WorkflowStage
from dsl.models.task import Task
from utils.database import SessionLocal
from utils.helpers import utc_now_naive
from utils.logger import logger


# 判定为"卡死"的最短阶段停留时间（分钟）
_STUCK_THRESHOLD_MINUTES = 5

# 单任务本次服务进程内最多自动 resume 次数，防止无限循环
_MAX_AUTO_RESUME_PER_SESSION = 3

# 需要看门狗监控的 AI 执行阶段集合
_WATCHED_RUNNING_STAGES = {
    WorkflowStage.PRD_GENERATING,
    WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
    WorkflowStage.SELF_REVIEW_IN_PROGRESS,
    WorkflowStage.TEST_IN_PROGRESS,
}

# 进程内 resume 计数：task_id -> 本次服务进程已 resume 次数
_session_resume_counts: dict[str, int] = {}


def _run_background_task_in_thread(background_task_callable) -> None:
    """在独立线程中运行 Starlette BackgroundTask（沿用 TaskSchedulerDispatcher 的做法）.

    Args:
        background_task_callable: 可调用对象
    """
    import asyncio
    import threading

    def _thread_runner() -> None:
        try:
            asyncio.run(background_task_callable())
        except Exception as thread_error:  # pragma: no cover
            logger.exception(
                "Watchdog background task runner crashed: %s",
                thread_error,
            )

    background_thread = threading.Thread(target=_thread_runner, daemon=True)
    background_thread.start()


def _attempt_resume_stuck_task(
    task_id_str: str,
    db_session: Session,
) -> bool:
    """尝试对单个卡死任务发起 resume.

    Args:
        task_id_str: 任务 UUID 字符串
        db_session: 数据库会话

    Returns:
        bool: resume 调度成功返回 True，被跳过或失败返回 False
    """
    import dsl.api.tasks as task_api_module

    background_tasks = BackgroundTasks()
    try:
        task_api_module.resume_task(
            task_id=task_id_str,
            background_tasks=background_tasks,
            db_session=db_session,
        )
    except Exception as resume_error:
        logger.warning(
            "Watchdog: resume_task raised for task %s...: %s",
            task_id_str[:8],
            resume_error,
        )
        return False

    if not background_tasks.tasks:
        return False

    for background_task_obj in background_tasks.tasks:
        _run_background_task_in_thread(background_task_obj)

    return True


class TaskRunnerWatchdogService:
    """任务 Runner 看门狗服务."""

    @staticmethod
    def scan_and_resume_stuck_tasks() -> int:
        """扫描卡死任务并自动 resume.

        判定条件（同时满足）：
        - lifecycle_status == OPEN
        - workflow_stage 属于 _WATCHED_RUNNING_STAGES
        - stage_updated_at 早于 _STUCK_THRESHOLD_MINUTES 分钟前
        - is_task_automation_running() 返回 False（无活跃 runner 进程）
        - 本次服务进程内 resume 次数未超过 _MAX_AUTO_RESUME_PER_SESSION

        Returns:
            int: 本轮成功发起 resume 的任务数
        """
        from dsl.services.automation_runner import is_task_automation_running

        stuck_deadline_datetime = utc_now_naive() - timedelta(
            minutes=_STUCK_THRESHOLD_MINUTES
        )

        db_session: Session = SessionLocal()
        try:
            stuck_task_candidate_list = (
                db_session.query(Task)
                .filter(
                    Task.lifecycle_status == TaskLifecycleStatus.OPEN,
                    Task.workflow_stage.in_(
                        [stage.value for stage in _WATCHED_RUNNING_STAGES]
                    ),
                    Task.stage_updated_at <= stuck_deadline_datetime,
                )
                .all()
            )
        finally:
            db_session.close()

        resumed_task_count_int = 0
        for stuck_task_obj in stuck_task_candidate_list:
            task_id_str = stuck_task_obj.id

            if is_task_automation_running(task_id_str):
                continue

            prior_resume_count_int = _session_resume_counts.get(task_id_str, 0)
            if prior_resume_count_int >= _MAX_AUTO_RESUME_PER_SESSION:
                logger.warning(
                    "Watchdog: task %s... has been auto-resumed %s time(s) this session "
                    "(stage=%s), giving up to avoid infinite loop.",
                    task_id_str[:8],
                    prior_resume_count_int,
                    stuck_task_obj.workflow_stage,
                )
                continue

            logger.info(
                "Watchdog: detected stuck task %s... (stage=%s, stuck_for>%sm, "
                "session_resumes=%s), attempting auto-resume.",
                task_id_str[:8],
                stuck_task_obj.workflow_stage,
                _STUCK_THRESHOLD_MINUTES,
                prior_resume_count_int,
            )

            action_db_session: Session = SessionLocal()
            try:
                resume_success_bool = _attempt_resume_stuck_task(
                    task_id_str=task_id_str,
                    db_session=action_db_session,
                )
            finally:
                action_db_session.close()

            if resume_success_bool:
                _session_resume_counts[task_id_str] = prior_resume_count_int + 1
                resumed_task_count_int += 1
                logger.info(
                    "Watchdog: successfully scheduled resume for task %s... "
                    "(session_resume_count=%s)",
                    task_id_str[:8],
                    _session_resume_counts[task_id_str],
                )

        return resumed_task_count_int
