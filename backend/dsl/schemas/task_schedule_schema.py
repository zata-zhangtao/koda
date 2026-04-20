"""任务调度 Schema 定义.

提供任务调度规则与执行审计的请求/响应模型.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.dsl.models.enums import (
    TaskScheduleActionType,
    TaskScheduleRunStatus,
    TaskScheduleTriggerType,
)
from backend.dsl.schemas.base import DSLResponseSchema
from utils.settings import config


class TaskScheduleCreateSchema(BaseModel):
    """创建任务调度规则请求.

    Attributes:
        schedule_name: 规则名称
        action_type: 调度动作类型
        trigger_type: 触发类型（once/cron）
        run_at: 一次性触发时间
        cron_expr: Cron 表达式（5 段）
        timezone_name: IANA 时区名称
        is_enabled: 是否启用
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    schedule_name: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="规则名称",
    )
    action_type: TaskScheduleActionType = Field(..., description="调度动作类型")
    trigger_type: TaskScheduleTriggerType = Field(..., description="触发类型")
    run_at: datetime | None = Field(None, description="一次性触发时间")
    cron_expr: str | None = Field(None, max_length=100, description="Cron 表达式")
    timezone_name: str = Field(
        default=config.APP_TIMEZONE,
        min_length=1,
        max_length=64,
        description="IANA 时区名称",
    )
    is_enabled: bool = Field(default=True, description="是否启用")

    @model_validator(mode="after")
    def validate_trigger_fields(self) -> "TaskScheduleCreateSchema":
        """校验触发类型相关字段.

        Returns:
            TaskScheduleCreateSchema: 当前实例

        Raises:
            ValueError: 字段组合不合法时抛出
        """
        if self.trigger_type == TaskScheduleTriggerType.ONCE:
            if self.run_at is None:
                raise ValueError("run_at is required when trigger_type=once")
            if self.cron_expr is not None and self.cron_expr.strip() != "":
                raise ValueError("cron_expr must be empty when trigger_type=once")
        else:
            if self.cron_expr is None or self.cron_expr.strip() == "":
                raise ValueError("cron_expr is required when trigger_type=cron")
            if self.run_at is not None:
                raise ValueError("run_at must be empty when trigger_type=cron")

        try:
            ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as timezone_error:
            raise ValueError(
                f"Invalid timezone_name: {self.timezone_name}"
            ) from timezone_error

        return self


class TaskScheduleUpdateSchema(BaseModel):
    """更新任务调度规则请求.

    Attributes:
        schedule_name: 规则名称（可选）
        action_type: 调度动作类型（可选）
        trigger_type: 触发类型（可选）
        run_at: 一次性触发时间（可选）
        cron_expr: Cron 表达式（可选）
        timezone_name: IANA 时区名称（可选）
        is_enabled: 是否启用（可选）
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    schedule_name: str | None = Field(
        None,
        min_length=1,
        max_length=120,
        description="规则名称",
    )
    action_type: TaskScheduleActionType | None = Field(None, description="调度动作类型")
    trigger_type: TaskScheduleTriggerType | None = Field(None, description="触发类型")
    run_at: datetime | None = Field(None, description="一次性触发时间")
    cron_expr: str | None = Field(None, max_length=100, description="Cron 表达式")
    timezone_name: str | None = Field(
        None,
        min_length=1,
        max_length=64,
        description="IANA 时区名称",
    )
    is_enabled: bool | None = Field(None, description="是否启用")

    @model_validator(mode="after")
    def validate_timezone_name_if_present(self) -> "TaskScheduleUpdateSchema":
        """校验 timezone_name 字段（当请求中提供时）.

        Returns:
            TaskScheduleUpdateSchema: 当前实例

        Raises:
            ValueError: 时区名称无效时抛出
        """
        if self.timezone_name is None:
            return self

        try:
            ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as timezone_error:
            raise ValueError(
                f"Invalid timezone_name: {self.timezone_name}"
            ) from timezone_error

        return self


class TaskScheduleResponseSchema(DSLResponseSchema):
    """任务调度规则响应.

    Attributes:
        id: 规则 ID
        task_id: 任务 ID
        run_account_id: 运行账户 ID
        schedule_name: 规则名称
        action_type: 调度动作类型（`start_task` / `resume_task` / `review_task`）
        trigger_type: 触发类型
        run_at: 一次性触发时间
        cron_expr: Cron 表达式
        timezone_name: IANA 时区名称
        is_enabled: 是否启用
        next_run_at: 下次计划触发时间
        last_triggered_at: 最近一次触发时间
        last_result_status: 最近一次执行结果
        created_at: 创建时间
        updated_at: 更新时间
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: str = Field(..., description="规则 ID")
    task_id: str = Field(..., description="任务 ID")
    run_account_id: str = Field(..., description="运行账户 ID")
    schedule_name: str = Field(..., description="规则名称")
    action_type: TaskScheduleActionType = Field(..., description="调度动作类型")
    trigger_type: TaskScheduleTriggerType = Field(..., description="触发类型")
    run_at: datetime | None = Field(None, description="一次性触发时间")
    cron_expr: str | None = Field(None, description="Cron 表达式")
    timezone_name: str = Field(..., description="IANA 时区名称")
    is_enabled: bool = Field(..., description="是否启用")
    next_run_at: datetime | None = Field(None, description="下次计划触发时间")
    last_triggered_at: datetime | None = Field(None, description="最近一次触发时间")
    last_result_status: TaskScheduleRunStatus | None = Field(
        None,
        description="最近一次执行结果",
    )
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class TaskScheduleRunResponseSchema(DSLResponseSchema):
    """任务调度执行记录响应.

    Attributes:
        id: 运行记录 ID
        schedule_id: 规则 ID
        task_id: 任务 ID
        planned_run_at: 计划触发时间
        triggered_at: 实际触发时间
        finished_at: 处理完成时间
        run_status: 执行结果
        skip_reason: 跳过原因
        error_message: 失败信息
        created_at: 创建时间
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: str = Field(..., description="运行记录 ID")
    schedule_id: str = Field(..., description="规则 ID")
    task_id: str = Field(..., description="任务 ID")
    planned_run_at: datetime = Field(..., description="计划触发时间")
    triggered_at: datetime = Field(..., description="实际触发时间")
    finished_at: datetime | None = Field(None, description="处理完成时间")
    run_status: TaskScheduleRunStatus = Field(..., description="执行结果")
    skip_reason: str | None = Field(None, description="跳过原因")
    error_message: str | None = Field(None, description="失败信息")
    created_at: datetime = Field(..., description="创建时间")
