"""任务调度规则模型.

定义任务级定时/周期调度配置，用于驱动自动触发链路.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.dsl.models.enums import (
    TaskScheduleActionType,
    TaskScheduleRunStatus,
    TaskScheduleTriggerType,
)
from utils.database import Base
from utils.helpers import utc_now_naive

if TYPE_CHECKING:
    from backend.dsl.models.task import Task
    from backend.dsl.models.task_schedule_run import TaskScheduleRun


class TaskSchedule(Base):
    """任务调度规则.

    Attributes:
        id (str): UUID 主键
        task_id (str): 关联任务 ID
        run_account_id (str): 所属运行账户 ID（快照）
        schedule_name (str): 规则名称
        action_type (TaskScheduleActionType): 调度动作类型
        trigger_type (TaskScheduleTriggerType): 触发类型（once/cron）
        run_at (datetime | None): 一次性触发时间（UTC naive）
        cron_expr (str | None): Cron 表达式（5 段）
        timezone_name (str): IANA 时区名称
        is_enabled (bool): 是否启用
        next_run_at (datetime | None): 下次计划触发时间（UTC naive）
        last_triggered_at (datetime | None): 最近一次实际触发时间（UTC naive）
        last_result_status (TaskScheduleRunStatus | None): 最近一次执行结果
        created_at (datetime): 创建时间
        updated_at (datetime): 更新时间
    """

    __tablename__ = "task_schedules"

    __table_args__ = (
        Index(
            "idx_task_schedules_task_enabled_next_run",
            "task_id",
            "is_enabled",
            "next_run_at",
        ),
        Index(
            "idx_task_schedules_run_account_created_at",
            "run_account_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("run_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    schedule_name: Mapped[str] = mapped_column(String(120), nullable=False)
    action_type: Mapped[TaskScheduleActionType] = mapped_column(
        Enum(
            TaskScheduleActionType,
            values_callable=lambda enum_member_list: [
                enum_member.value for enum_member in enum_member_list
            ],
        ),
        nullable=False,
    )
    trigger_type: Mapped[TaskScheduleTriggerType] = mapped_column(
        Enum(
            TaskScheduleTriggerType,
            values_callable=lambda enum_member_list: [
                enum_member.value for enum_member in enum_member_list
            ],
        ),
        nullable=False,
    )
    run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cron_expr: Mapped[str | None] = mapped_column(String(100), nullable=True)
    timezone_name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_result_status: Mapped[TaskScheduleRunStatus | None] = mapped_column(
        Enum(
            TaskScheduleRunStatus,
            values_callable=lambda enum_member_list: [
                enum_member.value for enum_member in enum_member_list
            ],
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        onupdate=utc_now_naive,
    )

    task: Mapped["Task"] = relationship("Task", back_populates="task_schedules")
    schedule_runs: Mapped[list["TaskScheduleRun"]] = relationship(
        "TaskScheduleRun",
        back_populates="task_schedule",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        """返回模型的字符串表示.

        Returns:
            str: 格式化的字符串表示
        """
        return (
            f"<TaskSchedule(id={self.id[:8]}..., task_id={self.task_id[:8]}..., "
            f"action={self.action_type.value}, trigger={self.trigger_type.value})>"
        )
