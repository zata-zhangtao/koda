"""TaskArtifact 模型定义.

定义任务级工件快照，用于持久化 PRD 与 Planning with files 历史.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from utils.database import Base
from utils.helpers import utc_now_naive

from backend.dsl.models.enums import TaskArtifactType

if TYPE_CHECKING:
    from backend.dsl.models.task import Task


class TaskArtifact(Base):
    """任务工件快照模型.

    Attributes:
        id (str): UUID 主键
        task_id (str): 关联任务 ID
        artifact_type (TaskArtifactType): 工件类型
        source_path (str | None): 快照来源路径（文件路径或逻辑来源）
        content_markdown (str): 工件正文内容
        file_manifest_json (str | None): 关联文件清单（JSON 字符串）
        captured_at (datetime): 快照采集时间
    """

    __tablename__ = "task_artifacts"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
    )
    artifact_type: Mapped[TaskArtifactType] = mapped_column(
        Enum(TaskArtifactType),
        index=True,
    )
    source_path: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    content_markdown: Mapped[str] = mapped_column(Text, default="")
    file_manifest_json: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        index=True,
    )

    task: Mapped["Task"] = relationship(
        "Task",
        back_populates="task_artifacts",
    )

    def __repr__(self) -> str:
        """返回模型的字符串表示.

        Returns:
            str: 格式化的字符串表示.
        """
        return (
            f"<TaskArtifact(id={self.id[:8]}..., "
            f"task_id={self.task_id[:8]}..., "
            f"type={self.artifact_type.value})>"
        )
