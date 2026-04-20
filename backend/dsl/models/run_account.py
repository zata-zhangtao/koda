"""RunAccount 模型定义.

定义运行账户的 ORM 模型，用于标识不同的开发环境和用户上下文.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from utils.database import Base
from utils.helpers import utc_now_naive

if TYPE_CHECKING:
    from backend.dsl.models.dev_log import DevLog
    from backend.dsl.models.task import Task
    from backend.dsl.models.task_qa_message import TaskQaMessage


class RunAccount(Base):
    """运行账户模型.

    表示一个特定的开发运行环境，包含用户、操作系统和 Git 分支信息.

    Attributes:
        id (str): UUID 主键
        account_display_name (str): 显示名称，如 "Zata @ MacOS-Pro"
        user_name (str): 用户名
        environment_os (str): 操作系统
        git_branch_name (str | None): 当前 Git 分支
        created_at (datetime): 创建时间
        is_active (bool): 是否为当前活跃账户
    """

    __tablename__ = "run_accounts"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    account_display_name: Mapped[str] = mapped_column(String(100))
    user_name: Mapped[str] = mapped_column(String(50))
    environment_os: Mapped[str] = mapped_column(String(50))
    git_branch_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )

    # Relationships
    tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="run_account",
        cascade="all, delete-orphan",
    )
    dev_logs: Mapped[list["DevLog"]] = relationship(
        "DevLog",
        back_populates="run_account",
        cascade="all, delete-orphan",
    )
    task_qa_messages: Mapped[list["TaskQaMessage"]] = relationship(
        "TaskQaMessage",
        back_populates="run_account",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        """返回模型的字符串表示.

        Returns:
            str: 格式化的字符串表示.
        """
        return (
            f"<RunAccount("
            f"id={self.id[:8]}..., "
            f"display_name={self.account_display_name}, "
            f"is_active={self.is_active}"
            f")>"
        )
