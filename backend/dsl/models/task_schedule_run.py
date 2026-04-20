"""任务调度执行审计模型.

定义每一次调度派发尝试的结果记录，便于追踪成功/失败/跳过原因.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.dsl.models.enums import TaskScheduleRunStatus
from utils.database import Base
from utils.helpers import utc_now_naive

if TYPE_CHECKING:
    from backend.dsl.models.task import Task
    from backend.dsl.models.task_schedule import TaskSchedule


class TaskScheduleRun(Base):
    """任务调度执行记录.

    Attributes:
        id (str): UUID 主键
        schedule_id (str): 调度规则 ID
        task_id (str): 关联任务 ID（冗余快照）
        planned_run_at (datetime): 本次计划触发时间（UTC naive）
        triggered_at (datetime): 实际触发时间（UTC naive）
        finished_at (datetime | None): 处理完成时间（UTC naive）
        run_status (TaskScheduleRunStatus): 执行结果状态
        skip_reason (str | None): 跳过原因
        error_message (str | None): 失败原因
        created_at (datetime): 创建时间
    """

    __tablename__ = "task_schedule_runs"

    __table_args__ = (
        UniqueConstraint(
            "schedule_id",
            "planned_run_at",
            name="uq_task_schedule_runs_schedule_planned",
        ),
        Index(
            "idx_task_schedule_runs_task_created_at",
            "task_id",
            "created_at",
        ),
        Index(
            "idx_task_schedule_runs_schedule_created_at",
            "schedule_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    schedule_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("task_schedules.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    planned_run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    run_status: Mapped[TaskScheduleRunStatus] = mapped_column(
        Enum(
            TaskScheduleRunStatus,
            values_callable=lambda enum_member_list: [
                enum_member.value for enum_member in enum_member_list
            ],
        ),
        nullable=False,
    )
    skip_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)

    task_schedule: Mapped["TaskSchedule"] = relationship(
        "TaskSchedule",
        back_populates="schedule_runs",
    )
    task: Mapped["Task"] = relationship(
        "Task",
        back_populates="task_schedule_runs",
    )

    def __repr__(self) -> str:
        """返回模型的字符串表示.

        Returns:
            str: 格式化的字符串表示
        """
        return (
            f"<TaskScheduleRun(id={self.id[:8]}..., schedule_id={self.schedule_id[:8]}..., "
            f"status={self.run_status.value})>"
        )
