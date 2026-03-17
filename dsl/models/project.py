"""Project 模型定义.

定义目标代码仓库项目的 ORM 模型.
每个 Project 对应用户本地的一个 Git 仓库，需求任务在其 worktree 中执行.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from utils.database import Base

if TYPE_CHECKING:
    from dsl.models.task import Task


class Project(Base):
    """目标代码仓库项目模型.

    Attributes:
        id (str): UUID 主键
        display_name (str): 项目展示名称，如 "My App"
        repo_path (str): 本地 Git 仓库绝对路径，如 "/Users/zata/code/my-app"
        description (str | None): 项目描述（可选）
        created_at (datetime): 创建时间
    """

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    display_name: Mapped[str] = mapped_column(String(100))
    repo_path: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        """返回模型的字符串表示.

        Returns:
            str: 格式化的字符串表示.
        """
        return f"<Project(id={self.id[:8]}..., name={self.display_name}, path={self.repo_path})>"
