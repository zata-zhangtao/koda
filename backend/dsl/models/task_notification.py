"""任务通知审计模型.

用于持久化记录任务通知事件的去重键、发送结果与接收人快照.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.dsl.models.enums import TaskNotificationEventType
from utils.database import Base
from utils.helpers import utc_now_naive

if TYPE_CHECKING:
    from backend.dsl.models.task import Task


class TaskNotification(Base):
    """任务通知审计记录.

    Attributes:
        id (str): UUID 主键
        task_id (str): 关联任务 ID
        event_type (TaskNotificationEventType): 通知事件类型
        workflow_stage_snapshot (str): 发送时的阶段快照
        dedup_key (str): 幂等/去重键
        receiver_email_snapshot (str | None): 发送时的收件人快照
        send_success (bool): 实际发送是否成功
        failure_message (str | None): 失败原因或跳过原因
        created_at (datetime): 审计记录创建时间
    """

    __tablename__ = "task_notifications"

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
    event_type: Mapped[TaskNotificationEventType] = mapped_column(
        Enum(
            TaskNotificationEventType,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    workflow_stage_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    receiver_email_snapshot: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    send_success: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    failure_message: Mapped[str | None] = mapped_column(
        String(2000),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)

    task: Mapped["Task"] = relationship(
        "Task",
        back_populates="task_notifications",
    )
