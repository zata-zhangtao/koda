"""Project 模型定义.

定义目标代码仓库项目的 ORM 模型.
每个 Project 对应用户本地的一个 Git 仓库，需求任务在其 worktree 中执行.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from utils.database import Base
from utils.helpers import utc_now_naive

if TYPE_CHECKING:
    from backend.dsl.models.task import Task


class Project(Base):
    """目标代码仓库项目模型.

    Attributes:
        id (str): UUID 主键
        display_name (str): 项目展示名称，如 "My App"
        project_category (str | None): 项目类别，如 "frontend" 或 "agent"（可选）
        repo_path (str): 本地 Git 仓库绝对路径，如 "/Users/zata/code/my-app"
        repo_remote_url (str | None): 项目仓库的归一化 origin remote URL
        repo_head_commit_hash (str | None): 项目仓库在最近一次同步时记录的 HEAD commit 哈希
        worktree_resource_policy_json (str | None): JSON-encoded local resource policy
        remote_requirement_management_enabled (bool): 是否启用远程需求分支协作
        remote_requirement_branch_prefix (str): 远程需求分支前缀
        remote_requirement_remote_name (str | None): 远程需求同步使用的 Git remote 名称
        github_pr_creation_enabled (bool): Complete 时是否创建 GitHub PR
        github_repository_full_name (str | None): GitHub 仓库全名，例如 owner/repo
        remote_requirement_delete_branch_after_pr_merge (bool): PR 合并后是否允许删除远程任务分支
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
    project_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    repo_path: Mapped[str] = mapped_column(String(500))
    repo_remote_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    repo_head_commit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    worktree_resource_policy_json: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    remote_requirement_management_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        nullable=False,
    )
    remote_requirement_branch_prefix: Mapped[str] = mapped_column(
        String(80),
        default="task",
        server_default="task",
        nullable=False,
    )
    remote_requirement_remote_name: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    github_pr_creation_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="1",
        nullable=False,
    )
    github_repository_full_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    remote_requirement_delete_branch_after_pr_merge: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
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
