"""任务调度服务.

负责调度规则 CRUD、Cron 计算、到期规则查询与执行审计写入.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dsl.models.enums import (
    TaskScheduleRunStatus,
    TaskScheduleTriggerType,
)
from dsl.models.task import Task
from dsl.models.task_schedule import TaskSchedule
from dsl.models.task_schedule_run import TaskScheduleRun
from dsl.schemas.task_schedule_schema import (
    TaskScheduleCreateSchema,
    TaskScheduleUpdateSchema,
)
from utils.helpers import utc_now_naive
from utils.logger import logger


@dataclass(frozen=True)
class _CronFieldMatchSpec:
    """Cron 字段匹配规格.

    Attributes:
        allowed_value_set: 允许值集合
        is_wildcard: 字段是否为通配符
    """

    allowed_value_set: set[int]
    is_wildcard: bool


@dataclass(frozen=True)
class _ParsedCronExpression:
    """解析后的 5 段 Cron 表达式."""

    minute_spec: _CronFieldMatchSpec
    hour_spec: _CronFieldMatchSpec
    day_of_month_spec: _CronFieldMatchSpec
    month_spec: _CronFieldMatchSpec
    day_of_week_spec: _CronFieldMatchSpec


class TaskScheduleService:
    """任务调度服务类."""

    @staticmethod
    def _ensure_timezone_valid(timezone_name_str: str) -> ZoneInfo:
        """校验并返回时区对象.

        Args:
            timezone_name_str: IANA 时区名称

        Returns:
            ZoneInfo: 时区对象

        Raises:
            ValueError: 时区名称无效时抛出
        """
        try:
            return ZoneInfo(timezone_name_str)
        except ZoneInfoNotFoundError as timezone_error:
            raise ValueError(
                f"Invalid timezone_name: {timezone_name_str}"
            ) from timezone_error

    @staticmethod
    def _parse_cron_field(
        raw_field_text: str,
        minimum_value_int: int,
        maximum_value_int: int,
        *,
        normalize_weekday_bool: bool = False,
    ) -> _CronFieldMatchSpec:
        """解析 Cron 单个字段.

        Args:
            raw_field_text: 字段原始文本
            minimum_value_int: 最小允许值
            maximum_value_int: 最大允许值
            normalize_weekday_bool: 是否按 weekday 规则归一化 7->0

        Returns:
            _CronFieldMatchSpec: 解析后的匹配规则

        Raises:
            ValueError: 字段格式不合法时抛出
        """
        normalized_field_text = raw_field_text.strip()
        if normalized_field_text == "*":
            return _CronFieldMatchSpec(
                allowed_value_set=set(range(minimum_value_int, maximum_value_int + 1)),
                is_wildcard=True,
            )

        allowed_value_set: set[int] = set()
        field_segment_list = [
            field_segment.strip()
            for field_segment in normalized_field_text.split(",")
            if field_segment.strip()
        ]
        if not field_segment_list:
            raise ValueError(f"Invalid cron field: {raw_field_text}")

        for field_segment_text in field_segment_list:
            step_size_int = 1
            base_expression_text = field_segment_text
            if "/" in field_segment_text:
                slash_split_list = field_segment_text.split("/", maxsplit=1)
                if len(slash_split_list) != 2:
                    raise ValueError(
                        f"Invalid cron field segment: {field_segment_text}"
                    )
                base_expression_text, raw_step_text = slash_split_list
                try:
                    step_size_int = int(raw_step_text)
                except ValueError as value_error:
                    raise ValueError(
                        f"Invalid cron step value: {field_segment_text}"
                    ) from value_error
                if step_size_int <= 0:
                    raise ValueError(
                        f"Cron step must be positive: {field_segment_text}"
                    )

            if base_expression_text == "*":
                range_start_int = minimum_value_int
                range_end_int = maximum_value_int
            elif "-" in base_expression_text:
                raw_start_text, raw_end_text = base_expression_text.split(
                    "-", maxsplit=1
                )
                try:
                    range_start_int = int(raw_start_text)
                    range_end_int = int(raw_end_text)
                except ValueError as value_error:
                    raise ValueError(
                        f"Invalid cron range segment: {field_segment_text}"
                    ) from value_error
            else:
                try:
                    range_start_int = int(base_expression_text)
                    range_end_int = range_start_int
                except ValueError as value_error:
                    raise ValueError(
                        f"Invalid cron number segment: {field_segment_text}"
                    ) from value_error

            if range_start_int > range_end_int:
                raise ValueError(f"Cron range start > end: {field_segment_text}")
            if range_start_int < minimum_value_int or range_end_int > maximum_value_int:
                raise ValueError(f"Cron field out of range: {field_segment_text}")

            for cron_value_int in range(
                range_start_int,
                range_end_int + 1,
                step_size_int,
            ):
                normalized_cron_value_int = (
                    0
                    if normalize_weekday_bool and cron_value_int == 7
                    else cron_value_int
                )
                allowed_value_set.add(normalized_cron_value_int)

        if not allowed_value_set:
            raise ValueError(f"Invalid cron field: {raw_field_text}")

        return _CronFieldMatchSpec(
            allowed_value_set=allowed_value_set,
            is_wildcard=False,
        )

    @staticmethod
    def parse_cron_expression(cron_expr_text: str) -> _ParsedCronExpression:
        """解析 5 段 Cron 表达式.

        Args:
            cron_expr_text: Cron 表达式文本

        Returns:
            _ParsedCronExpression: 解析后的结构

        Raises:
            ValueError: 表达式不合法时抛出
        """
        cron_field_list = cron_expr_text.strip().split()
        if len(cron_field_list) != 5:
            raise ValueError("Cron expression must contain exactly 5 fields")

        minute_spec = TaskScheduleService._parse_cron_field(
            cron_field_list[0],
            0,
            59,
        )
        hour_spec = TaskScheduleService._parse_cron_field(
            cron_field_list[1],
            0,
            23,
        )
        day_of_month_spec = TaskScheduleService._parse_cron_field(
            cron_field_list[2],
            1,
            31,
        )
        month_spec = TaskScheduleService._parse_cron_field(
            cron_field_list[3],
            1,
            12,
        )
        day_of_week_spec = TaskScheduleService._parse_cron_field(
            cron_field_list[4],
            0,
            7,
            normalize_weekday_bool=True,
        )

        return _ParsedCronExpression(
            minute_spec=minute_spec,
            hour_spec=hour_spec,
            day_of_month_spec=day_of_month_spec,
            month_spec=month_spec,
            day_of_week_spec=day_of_week_spec,
        )

    @staticmethod
    def _is_cron_match(
        parsed_cron_expression_obj: _ParsedCronExpression,
        candidate_local_datetime: datetime,
    ) -> bool:
        """判断某个本地时间是否命中 Cron 规则.

        Args:
            parsed_cron_expression_obj: 解析后的 Cron
            candidate_local_datetime: 候选本地时间

        Returns:
            bool: 命中时返回 True
        """
        minute_matched_bool = (
            candidate_local_datetime.minute
            in parsed_cron_expression_obj.minute_spec.allowed_value_set
        )
        hour_matched_bool = (
            candidate_local_datetime.hour
            in parsed_cron_expression_obj.hour_spec.allowed_value_set
        )
        month_matched_bool = (
            candidate_local_datetime.month
            in parsed_cron_expression_obj.month_spec.allowed_value_set
        )

        day_of_month_matched_bool = (
            candidate_local_datetime.day
            in parsed_cron_expression_obj.day_of_month_spec.allowed_value_set
        )

        cron_weekday_int = (candidate_local_datetime.weekday() + 1) % 7
        day_of_week_matched_bool = (
            cron_weekday_int
            in parsed_cron_expression_obj.day_of_week_spec.allowed_value_set
        )

        if (
            parsed_cron_expression_obj.day_of_month_spec.is_wildcard
            and parsed_cron_expression_obj.day_of_week_spec.is_wildcard
        ):
            day_matched_bool = True
        elif parsed_cron_expression_obj.day_of_month_spec.is_wildcard:
            day_matched_bool = day_of_week_matched_bool
        elif parsed_cron_expression_obj.day_of_week_spec.is_wildcard:
            day_matched_bool = day_of_month_matched_bool
        else:
            # 与常见 Cron 实现保持一致：当 DOM 与 DOW 同时限制时按 OR 匹配。
            day_matched_bool = day_of_month_matched_bool or day_of_week_matched_bool

        return (
            minute_matched_bool
            and hour_matched_bool
            and month_matched_bool
            and day_matched_bool
        )

    @staticmethod
    def normalize_run_at_to_utc_naive(
        run_at_datetime: datetime,
        timezone_name_str: str,
    ) -> datetime:
        """把输入 run_at 归一化到 UTC naive.

        Args:
            run_at_datetime: 输入时间（可为 naive/aware）
            timezone_name_str: 调度时区

        Returns:
            datetime: UTC 语义 naive 时间
        """
        target_timezone = TaskScheduleService._ensure_timezone_valid(timezone_name_str)
        if run_at_datetime.tzinfo is None:
            aware_run_at_datetime = run_at_datetime.replace(tzinfo=target_timezone)
        else:
            aware_run_at_datetime = run_at_datetime.astimezone(target_timezone)
        return aware_run_at_datetime.astimezone(UTC).replace(tzinfo=None)

    @staticmethod
    def compute_next_cron_run_at(
        *,
        cron_expr_text: str,
        timezone_name_str: str,
        reference_utc_naive_datetime: datetime,
    ) -> datetime:
        """计算下一次 Cron 触发时间（UTC naive）.

        Args:
            cron_expr_text: Cron 表达式（5 段）
            timezone_name_str: IANA 时区名称
            reference_utc_naive_datetime: 参考 UTC naive 时间（下一次触发需严格晚于它）

        Returns:
            datetime: 下次触发时间（UTC naive）

        Raises:
            ValueError: Cron 规则不合法或无法在搜索窗口内找到下次触发点
        """
        parsed_cron_expression = TaskScheduleService.parse_cron_expression(
            cron_expr_text
        )
        target_timezone = TaskScheduleService._ensure_timezone_valid(timezone_name_str)

        reference_utc_aware_datetime = reference_utc_naive_datetime.replace(tzinfo=UTC)
        reference_local_aware_datetime = reference_utc_aware_datetime.astimezone(
            target_timezone
        )
        candidate_local_aware_datetime = reference_local_aware_datetime.replace(
            second=0, microsecond=0
        ) + timedelta(minutes=1)

        max_search_minutes_int = 366 * 24 * 60 * 2
        for _ in range(max_search_minutes_int):
            if TaskScheduleService._is_cron_match(
                parsed_cron_expression,
                candidate_local_aware_datetime,
            ):
                return candidate_local_aware_datetime.astimezone(UTC).replace(
                    tzinfo=None
                )
            candidate_local_aware_datetime += timedelta(minutes=1)

        raise ValueError("Unable to find next cron occurrence within the search window")

    @staticmethod
    def compute_next_run_at(
        *,
        trigger_type: TaskScheduleTriggerType,
        timezone_name_str: str,
        run_at_utc_naive_datetime: datetime | None,
        cron_expr_text: str | None,
        reference_utc_naive_datetime: datetime,
    ) -> datetime:
        """计算下一次触发时间.

        Args:
            trigger_type: 触发类型
            timezone_name_str: IANA 时区名称
            run_at_utc_naive_datetime: 一次性触发时间（UTC naive）
            cron_expr_text: Cron 表达式
            reference_utc_naive_datetime: 参考时间

        Returns:
            datetime: 下一次触发时间（UTC naive）

        Raises:
            ValueError: 参数不合法时抛出
        """
        TaskScheduleService._ensure_timezone_valid(timezone_name_str)

        if trigger_type == TaskScheduleTriggerType.ONCE:
            if run_at_utc_naive_datetime is None:
                raise ValueError("run_at is required when trigger_type=once")
            return run_at_utc_naive_datetime

        if not cron_expr_text:
            raise ValueError("cron_expr is required when trigger_type=cron")
        return TaskScheduleService.compute_next_cron_run_at(
            cron_expr_text=cron_expr_text,
            timezone_name_str=timezone_name_str,
            reference_utc_naive_datetime=reference_utc_naive_datetime,
        )

    @staticmethod
    def validate_schedule_definition(
        *,
        trigger_type: TaskScheduleTriggerType,
        timezone_name_str: str,
        run_at_utc_naive_datetime: datetime | None,
        cron_expr_text: str | None,
    ) -> None:
        """校验调度定义字段组合是否合法.

        Args:
            trigger_type: 触发类型
            timezone_name_str: IANA 时区名称
            run_at_utc_naive_datetime: 一次性触发时间（UTC naive）
            cron_expr_text: Cron 表达式

        Raises:
            ValueError: 字段组合不合法时抛出
        """
        TaskScheduleService._ensure_timezone_valid(timezone_name_str)
        if trigger_type == TaskScheduleTriggerType.ONCE:
            if run_at_utc_naive_datetime is None:
                raise ValueError("run_at is required when trigger_type=once")
            if cron_expr_text:
                raise ValueError("cron_expr must be empty when trigger_type=once")
            return

        if run_at_utc_naive_datetime is not None:
            raise ValueError("run_at must be empty when trigger_type=cron")
        if not cron_expr_text:
            raise ValueError("cron_expr is required when trigger_type=cron")
        TaskScheduleService.parse_cron_expression(cron_expr_text)

    @staticmethod
    def create_task_schedule(
        db_session: Session,
        task_obj: Task,
        task_schedule_create_schema: TaskScheduleCreateSchema,
    ) -> TaskSchedule:
        """创建任务调度规则.

        Args:
            db_session: 数据库会话
            task_obj: 任务对象
            task_schedule_create_schema: 创建请求数据

        Returns:
            TaskSchedule: 新建规则对象

        Raises:
            ValueError: 调度参数不合法时抛出
        """
        normalized_timezone_name_str = task_schedule_create_schema.timezone_name.strip()
        normalized_run_at_utc_naive_datetime: datetime | None = None
        if task_schedule_create_schema.run_at is not None:
            normalized_run_at_utc_naive_datetime = (
                TaskScheduleService.normalize_run_at_to_utc_naive(
                    task_schedule_create_schema.run_at,
                    normalized_timezone_name_str,
                )
            )
        normalized_cron_expr_text = (
            task_schedule_create_schema.cron_expr.strip()
            if task_schedule_create_schema.cron_expr
            else None
        )
        TaskScheduleService.validate_schedule_definition(
            trigger_type=task_schedule_create_schema.trigger_type,
            timezone_name_str=normalized_timezone_name_str,
            run_at_utc_naive_datetime=normalized_run_at_utc_naive_datetime,
            cron_expr_text=normalized_cron_expr_text,
        )

        next_run_at_utc_naive_datetime: datetime | None = None
        if task_schedule_create_schema.is_enabled:
            next_run_at_utc_naive_datetime = TaskScheduleService.compute_next_run_at(
                trigger_type=task_schedule_create_schema.trigger_type,
                timezone_name_str=normalized_timezone_name_str,
                run_at_utc_naive_datetime=normalized_run_at_utc_naive_datetime,
                cron_expr_text=normalized_cron_expr_text,
                reference_utc_naive_datetime=utc_now_naive(),
            )

        created_task_schedule_obj = TaskSchedule(
            task_id=task_obj.id,
            run_account_id=task_obj.run_account_id,
            schedule_name=task_schedule_create_schema.schedule_name.strip(),
            action_type=task_schedule_create_schema.action_type,
            trigger_type=task_schedule_create_schema.trigger_type,
            run_at=normalized_run_at_utc_naive_datetime,
            cron_expr=normalized_cron_expr_text,
            timezone_name=normalized_timezone_name_str,
            is_enabled=task_schedule_create_schema.is_enabled,
            next_run_at=next_run_at_utc_naive_datetime,
        )
        db_session.add(created_task_schedule_obj)
        db_session.commit()
        db_session.refresh(created_task_schedule_obj)
        return created_task_schedule_obj

    @staticmethod
    def list_task_schedules(
        db_session: Session,
        task_id_str: str,
    ) -> list[TaskSchedule]:
        """查询任务下全部调度规则.

        Args:
            db_session: 数据库会话
            task_id_str: 任务 ID

        Returns:
            list[TaskSchedule]: 规则列表
        """
        return (
            db_session.query(TaskSchedule)
            .filter(TaskSchedule.task_id == task_id_str)
            .order_by(TaskSchedule.created_at.desc())
            .all()
        )

    @staticmethod
    def get_task_schedule_by_id(
        db_session: Session,
        task_id_str: str,
        schedule_id_str: str,
    ) -> TaskSchedule | None:
        """按 ID 查询任务下的调度规则.

        Args:
            db_session: 数据库会话
            task_id_str: 任务 ID
            schedule_id_str: 规则 ID

        Returns:
            TaskSchedule | None: 匹配规则或 None
        """
        return (
            db_session.query(TaskSchedule)
            .filter(
                TaskSchedule.id == schedule_id_str,
                TaskSchedule.task_id == task_id_str,
            )
            .first()
        )

    @staticmethod
    def update_task_schedule(
        db_session: Session,
        task_schedule_obj: TaskSchedule,
        task_schedule_update_schema: TaskScheduleUpdateSchema,
    ) -> TaskSchedule:
        """更新任务调度规则.

        Args:
            db_session: 数据库会话
            task_schedule_obj: 待更新规则
            task_schedule_update_schema: 更新请求数据

        Returns:
            TaskSchedule: 更新后的规则对象

        Raises:
            ValueError: 调度参数不合法时抛出
        """
        provided_field_name_set = task_schedule_update_schema.model_fields_set

        updated_schedule_name_str = (
            task_schedule_update_schema.schedule_name.strip()
            if "schedule_name" in provided_field_name_set
            and task_schedule_update_schema.schedule_name is not None
            else task_schedule_obj.schedule_name
        )
        updated_action_type = (
            task_schedule_update_schema.action_type
            if "action_type" in provided_field_name_set
            and task_schedule_update_schema.action_type is not None
            else task_schedule_obj.action_type
        )
        updated_trigger_type = (
            task_schedule_update_schema.trigger_type
            if "trigger_type" in provided_field_name_set
            and task_schedule_update_schema.trigger_type is not None
            else task_schedule_obj.trigger_type
        )
        updated_timezone_name_str = (
            task_schedule_update_schema.timezone_name.strip()
            if "timezone_name" in provided_field_name_set
            and task_schedule_update_schema.timezone_name is not None
            else task_schedule_obj.timezone_name
        )
        updated_is_enabled_bool = (
            task_schedule_update_schema.is_enabled
            if "is_enabled" in provided_field_name_set
            and task_schedule_update_schema.is_enabled is not None
            else task_schedule_obj.is_enabled
        )

        updated_run_at_utc_naive_datetime = task_schedule_obj.run_at
        if "run_at" in provided_field_name_set:
            if task_schedule_update_schema.run_at is None:
                updated_run_at_utc_naive_datetime = None
            else:
                updated_run_at_utc_naive_datetime = (
                    TaskScheduleService.normalize_run_at_to_utc_naive(
                        task_schedule_update_schema.run_at,
                        updated_timezone_name_str,
                    )
                )

        updated_cron_expr_text = task_schedule_obj.cron_expr
        if "cron_expr" in provided_field_name_set:
            if task_schedule_update_schema.cron_expr is None:
                updated_cron_expr_text = None
            else:
                normalized_cron_expr_text = (
                    task_schedule_update_schema.cron_expr.strip()
                )
                updated_cron_expr_text = (
                    normalized_cron_expr_text if normalized_cron_expr_text else None
                )

        TaskScheduleService.validate_schedule_definition(
            trigger_type=updated_trigger_type,
            timezone_name_str=updated_timezone_name_str,
            run_at_utc_naive_datetime=updated_run_at_utc_naive_datetime,
            cron_expr_text=updated_cron_expr_text,
        )

        next_run_at_utc_naive_datetime: datetime | None = None
        if updated_is_enabled_bool:
            next_run_at_utc_naive_datetime = TaskScheduleService.compute_next_run_at(
                trigger_type=updated_trigger_type,
                timezone_name_str=updated_timezone_name_str,
                run_at_utc_naive_datetime=updated_run_at_utc_naive_datetime,
                cron_expr_text=updated_cron_expr_text,
                reference_utc_naive_datetime=utc_now_naive(),
            )

        task_schedule_obj.schedule_name = updated_schedule_name_str
        task_schedule_obj.action_type = updated_action_type
        task_schedule_obj.trigger_type = updated_trigger_type
        task_schedule_obj.timezone_name = updated_timezone_name_str
        task_schedule_obj.is_enabled = updated_is_enabled_bool
        task_schedule_obj.run_at = updated_run_at_utc_naive_datetime
        task_schedule_obj.cron_expr = updated_cron_expr_text
        task_schedule_obj.next_run_at = next_run_at_utc_naive_datetime

        db_session.commit()
        db_session.refresh(task_schedule_obj)
        return task_schedule_obj

    @staticmethod
    def delete_task_schedule(
        db_session: Session,
        task_schedule_obj: TaskSchedule,
    ) -> None:
        """删除任务调度规则.

        Args:
            db_session: 数据库会话
            task_schedule_obj: 待删除规则
        """
        db_session.delete(task_schedule_obj)
        db_session.commit()

    @staticmethod
    def list_task_schedule_runs(
        db_session: Session,
        task_id_str: str,
        *,
        limit_int: int,
    ) -> list[TaskScheduleRun]:
        """查询任务调度执行记录.

        Args:
            db_session: 数据库会话
            task_id_str: 任务 ID
            limit_int: 最大记录数

        Returns:
            list[TaskScheduleRun]: 执行记录列表
        """
        return (
            db_session.query(TaskScheduleRun)
            .filter(TaskScheduleRun.task_id == task_id_str)
            .order_by(TaskScheduleRun.created_at.desc())
            .limit(limit_int)
            .all()
        )

    @staticmethod
    def list_due_enabled_schedules(
        db_session: Session,
        *,
        now_utc_naive_datetime: datetime,
        max_dispatch_count_int: int,
    ) -> list[TaskSchedule]:
        """查询到期且启用的调度规则.

        Args:
            db_session: 数据库会话
            now_utc_naive_datetime: 当前时间（UTC naive）
            max_dispatch_count_int: 最大派发条数

        Returns:
            list[TaskSchedule]: 待派发规则列表
        """
        return (
            db_session.query(TaskSchedule)
            .filter(
                TaskSchedule.is_enabled.is_(True),
                TaskSchedule.next_run_at.is_not(None),
                TaskSchedule.next_run_at <= now_utc_naive_datetime,
            )
            .order_by(TaskSchedule.next_run_at.asc(), TaskSchedule.created_at.asc())
            .limit(max_dispatch_count_int)
            .all()
        )

    @staticmethod
    def claim_schedule_for_dispatch(
        db_session: Session,
        *,
        task_schedule_obj: TaskSchedule,
        planned_run_at_utc_naive_datetime: datetime,
        triggered_at_utc_naive_datetime: datetime,
        should_advance_schedule_bool: bool,
    ) -> bool:
        """领取调度执行窗口，避免同一窗口被重复分发.

        Args:
            db_session: 数据库会话
            task_schedule_obj: 调度规则
            planned_run_at_utc_naive_datetime: 本次计划触发时间
            triggered_at_utc_naive_datetime: 本次触发时间
            should_advance_schedule_bool: 是否推进下一次调度

        Returns:
            bool: 是否成功领取
        """
        next_run_at_utc_naive_datetime = task_schedule_obj.next_run_at
        next_is_enabled_bool = task_schedule_obj.is_enabled
        if should_advance_schedule_bool:
            if task_schedule_obj.trigger_type == TaskScheduleTriggerType.ONCE:
                next_is_enabled_bool = False
                next_run_at_utc_naive_datetime = None
            else:
                next_run_at_utc_naive_datetime = (
                    TaskScheduleService.compute_next_run_at(
                        trigger_type=task_schedule_obj.trigger_type,
                        timezone_name_str=task_schedule_obj.timezone_name,
                        run_at_utc_naive_datetime=task_schedule_obj.run_at,
                        cron_expr_text=task_schedule_obj.cron_expr,
                        reference_utc_naive_datetime=planned_run_at_utc_naive_datetime,
                    )
                )

        claimed_schedule_count_int = (
            db_session.query(TaskSchedule)
            .filter(
                and_(
                    TaskSchedule.id == task_schedule_obj.id,
                    TaskSchedule.is_enabled.is_(True),
                    TaskSchedule.next_run_at == planned_run_at_utc_naive_datetime,
                )
            )
            .update(
                {
                    TaskSchedule.last_triggered_at: triggered_at_utc_naive_datetime,
                    TaskSchedule.is_enabled: next_is_enabled_bool,
                    TaskSchedule.next_run_at: next_run_at_utc_naive_datetime,
                    TaskSchedule.updated_at: utc_now_naive(),
                },
                synchronize_session=False,
            )
        )
        if claimed_schedule_count_int == 0:
            db_session.rollback()
            return False

        db_session.commit()
        db_session.refresh(task_schedule_obj)
        return True

    @staticmethod
    def create_schedule_run_record(
        db_session: Session,
        *,
        task_schedule_obj: TaskSchedule,
        planned_run_at_utc_naive_datetime: datetime,
        triggered_at_utc_naive_datetime: datetime,
        run_status: TaskScheduleRunStatus,
        skip_reason_str: str | None = None,
        error_message_str: str | None = None,
    ) -> TaskScheduleRun | None:
        """创建调度执行记录.

        Args:
            db_session: 数据库会话
            task_schedule_obj: 调度规则
            planned_run_at_utc_naive_datetime: 计划触发时间
            triggered_at_utc_naive_datetime: 实际触发时间
            run_status: 执行状态
            skip_reason_str: 跳过原因
            error_message_str: 失败原因

        Returns:
            TaskScheduleRun | None: 记录对象；若重复触发窗口冲突则返回 None
        """
        schedule_run_record_obj = TaskScheduleRun(
            schedule_id=task_schedule_obj.id,
            task_id=task_schedule_obj.task_id,
            planned_run_at=planned_run_at_utc_naive_datetime,
            triggered_at=triggered_at_utc_naive_datetime,
            finished_at=triggered_at_utc_naive_datetime,
            run_status=run_status,
            skip_reason=skip_reason_str,
            error_message=error_message_str,
        )
        db_session.add(schedule_run_record_obj)
        try:
            db_session.commit()
        except IntegrityError:
            db_session.rollback()
            return None
        db_session.refresh(schedule_run_record_obj)
        return schedule_run_record_obj

    @staticmethod
    def mark_schedule_triggered(
        db_session: Session,
        *,
        task_schedule_obj: TaskSchedule,
        planned_run_at_utc_naive_datetime: datetime,
        triggered_at_utc_naive_datetime: datetime,
        should_advance_schedule_bool: bool,
    ) -> TaskSchedule:
        """更新调度规则触发后的状态.

        Args:
            db_session: 数据库会话
            task_schedule_obj: 调度规则
            planned_run_at_utc_naive_datetime: 本次计划触发时间
            triggered_at_utc_naive_datetime: 本次触发时间
            should_advance_schedule_bool: 是否推进下一次调度（自动触发为 True，run-now 为 False）

        Returns:
            TaskSchedule: 更新后的规则对象
        """
        task_schedule_obj.last_triggered_at = triggered_at_utc_naive_datetime

        if should_advance_schedule_bool:
            if task_schedule_obj.trigger_type == TaskScheduleTriggerType.ONCE:
                task_schedule_obj.is_enabled = False
                task_schedule_obj.next_run_at = None
            else:
                task_schedule_obj.next_run_at = TaskScheduleService.compute_next_run_at(
                    trigger_type=task_schedule_obj.trigger_type,
                    timezone_name_str=task_schedule_obj.timezone_name,
                    run_at_utc_naive_datetime=task_schedule_obj.run_at,
                    cron_expr_text=task_schedule_obj.cron_expr,
                    reference_utc_naive_datetime=planned_run_at_utc_naive_datetime,
                )

        db_session.commit()
        db_session.refresh(task_schedule_obj)
        return task_schedule_obj

    @staticmethod
    def mark_schedule_last_result(
        db_session: Session,
        *,
        task_schedule_obj: TaskSchedule,
        run_status: TaskScheduleRunStatus,
    ) -> None:
        """更新规则最近一次执行结果.

        Args:
            db_session: 数据库会话
            task_schedule_obj: 调度规则
            run_status: 结果状态
        """
        task_schedule_obj.last_result_status = run_status
        db_session.commit()

    @staticmethod
    def apply_schedule_dispatch_result(
        db_session: Session,
        *,
        task_schedule_obj: TaskSchedule,
        planned_run_at_utc_naive_datetime: datetime,
        triggered_at_utc_naive_datetime: datetime,
        run_status: TaskScheduleRunStatus,
        should_advance_schedule_bool: bool,
        schedule_already_claimed_bool: bool = False,
        skip_reason_str: str | None = None,
        error_message_str: str | None = None,
    ) -> TaskScheduleRun | None:
        """统一写入一次调度执行结果.

        Args:
            db_session: 数据库会话
            task_schedule_obj: 调度规则
            planned_run_at_utc_naive_datetime: 计划触发时间
            triggered_at_utc_naive_datetime: 实际触发时间
            run_status: 执行结果
            should_advance_schedule_bool: 是否推进下一次调度
            schedule_already_claimed_bool: 调度窗口是否已在动作分发前领取
            skip_reason_str: 跳过原因
            error_message_str: 失败原因

        Returns:
            TaskScheduleRun | None: 写入的执行记录；若命中唯一键冲突则返回 None
        """
        created_schedule_run_record_obj = (
            TaskScheduleService.create_schedule_run_record(
                db_session,
                task_schedule_obj=task_schedule_obj,
                planned_run_at_utc_naive_datetime=planned_run_at_utc_naive_datetime,
                triggered_at_utc_naive_datetime=triggered_at_utc_naive_datetime,
                run_status=run_status,
                skip_reason_str=skip_reason_str,
                error_message_str=error_message_str,
            )
        )
        if created_schedule_run_record_obj is None:
            logger.info(
                "Skipped duplicated schedule run record: schedule=%s planned_run_at=%s",
                task_schedule_obj.id[:8],
                planned_run_at_utc_naive_datetime.isoformat(),
            )
            if schedule_already_claimed_bool:
                TaskScheduleService.mark_schedule_last_result(
                    db_session,
                    task_schedule_obj=task_schedule_obj,
                    run_status=run_status,
                )
            return None

        if not schedule_already_claimed_bool:
            TaskScheduleService.mark_schedule_triggered(
                db_session,
                task_schedule_obj=task_schedule_obj,
                planned_run_at_utc_naive_datetime=planned_run_at_utc_naive_datetime,
                triggered_at_utc_naive_datetime=triggered_at_utc_naive_datetime,
                should_advance_schedule_bool=should_advance_schedule_bool,
            )
        TaskScheduleService.mark_schedule_last_result(
            db_session,
            task_schedule_obj=task_schedule_obj,
            run_status=run_status,
        )
        return created_schedule_run_record_obj
