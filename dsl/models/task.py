"""Task 模型定义.

定义开发任务的 ORM 模型，用于组织和分组开发日志.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from utils.database import Base

from dsl.models.enums import TaskLifecycleStatus, WorkflowStage

if TYPE_CHECKING:
    from dsl.models.dev_log import DevLog
    from dsl.models.project import Project
    from dsl.models.run_account import RunAccount


class Task(Base):
    """开发任务模型.

    表示一个开发工作单元，包含多个开发日志条目.

    Attributes:
        id (str): UUID 主键
        run_account_id (str): 关联的 RunAccount ID
        project_id (str | None): 关联的 Project ID（可选）
        task_title (str): 任务标题
        lifecycle_status (TaskLifecycleStatus): 任务生命周期状态（向后兼容）
        workflow_stage (WorkflowStage): 工作流精确阶段，作为 UI 阶段展示的唯一数据源
        worktree_path (str | None): codex 执行时创建的 git worktree 绝对路径
        created_at (datetime): 创建时间
        closed_at (datetime | None): 关闭时间
    """

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    run_account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("run_accounts.id", ondelete="CASCADE"),
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    task_title: Mapped[str] = mapped_column(String(200))
    lifecycle_status: Mapped[TaskLifecycleStatus] = mapped_column(
        Enum(TaskLifecycleStatus),
        default=TaskLifecycleStatus.OPEN,
    )
    workflow_stage: Mapped[WorkflowStage] = mapped_column(
        Enum(WorkflowStage, values_callable=lambda obj: [e.value for e in obj]),
        default=WorkflowStage.BACKLOG,
        server_default=WorkflowStage.BACKLOG.value,
    )
    worktree_path: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    requirement_brief: Mapped[str | None] = mapped_column(
        String(5000),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    # Relationships
    run_account: Mapped["RunAccount"] = relationship(
        "RunAccount",
        back_populates="tasks",
    )
    project: Mapped["Project | None"] = relationship(
        "Project",
        back_populates="tasks",
    )
    dev_logs: Mapped[list["DevLog"]] = relationship(
        "DevLog",
        back_populates="task",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        """返回模型的字符串表示.

        Returns:
            str: 格式化的字符串表示.
        """
        return (
            f"<Task("
            f"id={self.id[:8]}..., "
            f"title={self.task_title[:30]}, "
            f"stage={self.workflow_stage.value}"
            f")>"
        )
