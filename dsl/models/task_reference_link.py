"""TaskReferenceLink 模型定义.

定义任务之间的持久化引用关系，用于审计与去重.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from utils.database import Base
from utils.helpers import utc_now_naive

if TYPE_CHECKING:
    from dsl.models.dev_log import DevLog
    from dsl.models.run_account import RunAccount
    from dsl.models.task import Task


class TaskReferenceLink(Base):
    """任务引用关系模型.

    Attributes:
        id (str): UUID 主键
        run_account_id (str): 创建该引用关系的运行账户 ID
        source_task_id (str): 被引用的来源任务 ID
        target_task_id (str): 接收引用的目标任务 ID
        reference_log_id (str | None): 对应的结构化引用 DevLog ID
        requirement_brief_appended (bool): 是否已把来源摘要追加到目标任务需求描述
        created_at (datetime): 引用关系创建时间
    """

    __tablename__ = "task_reference_links"
    __table_args__ = (
        UniqueConstraint(
            "source_task_id",
            "target_task_id",
            name="uq_task_reference_links_source_target",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    run_account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("run_accounts.id", ondelete="CASCADE"),
        index=True,
    )
    source_task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
    )
    target_task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
    )
    reference_log_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("dev_logs.id", ondelete="SET NULL"),
        nullable=True,
    )
    requirement_brief_appended: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        index=True,
    )

    run_account: Mapped["RunAccount"] = relationship("RunAccount")
    source_task: Mapped["Task"] = relationship("Task", foreign_keys=[source_task_id])
    target_task: Mapped["Task"] = relationship("Task", foreign_keys=[target_task_id])
    reference_log: Mapped["DevLog | None"] = relationship(
        "DevLog",
        foreign_keys=[reference_log_id],
    )

    def __repr__(self) -> str:
        """返回模型的字符串表示.

        Returns:
            str: 格式化的字符串表示.
        """
        return (
            f"<TaskReferenceLink(id={self.id[:8]}..., "
            f"source={self.source_task_id[:8]}..., "
            f"target={self.target_task_id[:8]}...)>"
        )
