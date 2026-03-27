"""Task-sidecar Q&A message model definitions.

Defines the ORM model used by task-scoped independent Q&A messages so sidecar
questions do not pollute `DevLog` or the main automation prompt history.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DDL, DateTime, Enum, ForeignKey, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dsl.models.enums import (
    TaskQaContextScope,
    TaskQaGenerationStatus,
    TaskQaMessageRole,
)
from utils.database import Base
from utils.helpers import utc_now_naive

if TYPE_CHECKING:
    from dsl.models.run_account import RunAccount
    from dsl.models.task import Task


class TaskQaMessage(Base):
    """Task-scoped sidecar Q&A message record.

    Attributes:
        id (str): UUID primary key.
        task_id (str): Owning task ID.
        run_account_id (str): Owning run account ID.
        role (TaskQaMessageRole): Message role (`user` or `assistant`).
        context_scope (TaskQaContextScope): Context scope used for the question.
        generation_status (TaskQaGenerationStatus): Message generation status.
        reply_to_message_id (str | None): Linked user-question message ID for AI replies.
        model_name (str | None): Model name used to generate the assistant reply.
        content_markdown (str): Markdown content for the message.
        error_text (str | None): Visible error text when generation fails.
        created_at (datetime): Creation timestamp.
        updated_at (datetime): Last update timestamp.
    """

    __tablename__ = "task_qa_messages"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tasks.id", ondelete="CASCADE"),
    )
    run_account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("run_accounts.id", ondelete="CASCADE"),
    )
    role: Mapped[TaskQaMessageRole] = mapped_column(
        Enum(
            TaskQaMessageRole,
            values_callable=lambda enum_cls: [
                enum_item.value for enum_item in enum_cls
            ],
        ),
    )
    context_scope: Mapped[TaskQaContextScope] = mapped_column(
        Enum(
            TaskQaContextScope,
            values_callable=lambda enum_cls: [
                enum_item.value for enum_item in enum_cls
            ],
        ),
    )
    generation_status: Mapped[TaskQaGenerationStatus] = mapped_column(
        Enum(
            TaskQaGenerationStatus,
            values_callable=lambda enum_cls: [
                enum_item.value for enum_item in enum_cls
            ],
        ),
        default=TaskQaGenerationStatus.COMPLETED,
        server_default=TaskQaGenerationStatus.COMPLETED.value,
    )
    reply_to_message_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("task_qa_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    content_markdown: Mapped[str] = mapped_column(Text, default="")
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        onupdate=utc_now_naive,
    )

    task: Mapped["Task"] = relationship(
        "Task",
        back_populates="task_qa_messages",
    )
    run_account: Mapped["RunAccount"] = relationship(
        "RunAccount",
        back_populates="task_qa_messages",
    )
    replied_user_message: Mapped["TaskQaMessage | None"] = relationship(
        "TaskQaMessage",
        remote_side="TaskQaMessage.id",
        foreign_keys=[reply_to_message_id],
    )

    def __repr__(self) -> str:
        """Return a compact debug representation.

        Returns:
            str: Formatted model debug string.
        """
        return (
            f"<TaskQaMessage("
            f"id={self.id[:8]}..., "
            f"task_id={self.task_id[:8]}..., "
            f"role={self.role.value}, "
            f"status={self.generation_status.value}"
            f")>"
        )


event.listen(
    TaskQaMessage.__table__,
    "after_create",
    DDL(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_task_qa_messages_single_pending_assistant "
        "ON task_qa_messages (task_id) "
        "WHERE role = 'assistant' AND generation_status = 'pending'"
    ).execute_if(dialect="sqlite"),
)
