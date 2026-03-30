"""DevLog 模型定义.

定义开发日志的 ORM 模型，用于记录开发过程中的文本、图片和 AI 解析结果.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from utils.database import Base
from utils.helpers import utc_now_naive

from dsl.models.enums import AIProcessingStatus, DevLogStateTag

if TYPE_CHECKING:
    from dsl.models.run_account import RunAccount
    from dsl.models.task import Task


class DevLog(Base):
    """开发日志模型.

    表示一条开发日志记录，可以是文本、图片或两者的组合。
    支持 AI 异步解析图片内容。

    Attributes:
        id (str): UUID 主键
        task_id (str): 关联的 Task ID
        run_account_id (str): 关联的 RunAccount ID
        created_at (datetime): 创建时间
        text_content (str): 用户输入的 Markdown 文本
        state_tag (DevLogStateTag): 状态标记
        media_original_image_path (str | None): 图片本地存储路径
        media_thumbnail_path (str | None): 缩略图路径
        ai_processing_status (AIProcessingStatus | None): AI 处理状态
        ai_generated_title (str | None): AI 生成的标题
        ai_analysis_text (str | None): AI 分析文本
        ai_extracted_code (str | None): AI 提取的代码块
        ai_confidence_score (float | None): AI 置信度分数
        automation_session_id (str | None): 自动化连续 transcript 会话 ID
        automation_sequence_index (int | None): 自动化 transcript 内的 chunk 顺序
        automation_phase_label (str | None): 自动化输出所属 phase 标签
        automation_runner_kind (str | None): 自动化输出所属 runner 类型
    """

    __tablename__ = "dev_logs"

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
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
    )
    text_content: Mapped[str] = mapped_column(Text, default="")
    state_tag: Mapped[DevLogStateTag] = mapped_column(
        Enum(DevLogStateTag),
        default=DevLogStateTag.NONE,
    )

    # Media fields (flattened from nested media object)
    media_original_image_path: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    media_thumbnail_path: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # AI processing fields (Phase 2)
    ai_processing_status: Mapped[AIProcessingStatus | None] = mapped_column(
        Enum(AIProcessingStatus),
        nullable=True,
    )
    ai_generated_title: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    ai_analysis_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    ai_extracted_code: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    ai_confidence_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    automation_session_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    automation_sequence_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    automation_phase_label: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    automation_runner_kind: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )

    # Relationships
    task: Mapped["Task"] = relationship(
        "Task",
        back_populates="dev_logs",
    )
    run_account: Mapped["RunAccount"] = relationship(
        "RunAccount",
        back_populates="dev_logs",
    )

    def __repr__(self) -> str:
        """返回模型的字符串表示.

        Returns:
            str: 格式化的字符串表示.
        """
        return (
            f"<DevLog("
            f"id={self.id[:8]}..., "
            f"task_id={self.task_id[:8]}..., "
            f"state={self.state_tag.value}, "
            f"has_media={self.media_original_image_path is not None}"
            f")>"
        )
