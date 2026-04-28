"""Project Pydantic 模式定义.

定义 Project 的创建、更新和响应模式.
"""

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.dsl.schemas.base import DSLResponseSchema
from backend.dsl.worktree_resources.schemas import (
    ProjectWorktreeResourcePolicySchema,
    WorktreeResourcePolicyConfirmation,
)


class ProjectCreateSchema(BaseModel):
    """创建 Project 的请求模式.

    Attributes:
        display_name: 项目展示名称
        project_category: 项目类别（可选）
        repo_path: 本地 Git 仓库绝对路径
        remote_requirement_management_enabled: 是否启用 GitHub-backed 远程需求协作
        remote_requirement_branch_prefix: 远程需求分支前缀
        remote_requirement_remote_name: 远程需求同步使用的 Git remote 名称（可选）
        github_pr_creation_enabled: Complete 时是否创建 GitHub PR
        github_repository_full_name: GitHub 仓库全名，例如 owner/repo（可选）
        remote_requirement_delete_branch_after_pr_merge: PR 合并后是否允许删除远程任务分支
        description: 项目描述（可选）
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    display_name: str = Field(
        ..., min_length=1, max_length=100, description="项目展示名称"
    )
    project_category: str | None = Field(
        None,
        max_length=100,
        description="项目类别（可选）",
    )
    repo_path: str = Field(
        ..., min_length=1, max_length=500, description="本地 Git 仓库绝对路径"
    )
    remote_requirement_management_enabled: bool = Field(
        default=False,
        description="是否启用 GitHub-backed 远程需求协作",
    )
    remote_requirement_branch_prefix: str = Field(
        default="task",
        min_length=1,
        max_length=80,
        description="远程需求分支前缀",
    )
    remote_requirement_remote_name: str | None = Field(
        None,
        max_length=120,
        description="远程需求同步使用的 Git remote 名称（可选）",
    )
    github_pr_creation_enabled: bool = Field(
        default=True,
        description="Complete 时是否创建 GitHub PR",
    )
    github_repository_full_name: str | None = Field(
        None,
        max_length=255,
        description="GitHub 仓库全名，例如 owner/repo（可选）",
    )
    remote_requirement_delete_branch_after_pr_merge: bool = Field(
        default=False,
        description="PR 合并后是否允许删除远程任务分支",
    )
    description: str | None = Field(None, description="项目描述")
    worktree_resource_policy_confirmation: WorktreeResourcePolicyConfirmation = Field(
        default=WorktreeResourcePolicyConfirmation.ACCEPTED_DEFAULT,
        description="工作树本地资源策略确认状态",
    )
    worktree_resource_policy: ProjectWorktreeResourcePolicySchema | None = Field(
        None,
        description="工作树本地资源策略（可选）",
    )

    @field_validator("remote_requirement_branch_prefix")
    @classmethod
    def normalize_remote_branch_prefix(cls, value_str: str) -> str:
        """Normalize the remote requirement branch prefix.

        Args:
            value_str: Raw submitted prefix.

        Returns:
            str: Trimmed branch prefix without leading or trailing slashes.
        """
        normalized_prefix_str = value_str.strip().strip("/")
        return normalized_prefix_str or "task"

    @field_validator("remote_requirement_remote_name", "github_repository_full_name")
    @classmethod
    def normalize_optional_remote_text(cls, value_str: str | None) -> str | None:
        """Normalize remote collaboration text fields.

        Args:
            value_str: Raw submitted text value.

        Returns:
            str | None: Trimmed text, or None when optional text is blank.
        """
        if value_str is None:
            return None
        normalized_value_str = value_str.strip().strip("/")
        return normalized_value_str or None


class ProjectUpdateSchema(BaseModel):
    """更新 Project 的请求模式.

    Attributes:
        display_name: 项目展示名称
        project_category: 项目类别（可选）
        repo_path: 当前机器上的本地 Git 仓库绝对路径
        remote_requirement_management_enabled: 是否启用 GitHub-backed 远程需求协作
        remote_requirement_branch_prefix: 远程需求分支前缀
        remote_requirement_remote_name: 远程需求同步使用的 Git remote 名称（可选）
        github_pr_creation_enabled: Complete 时是否创建 GitHub PR
        github_repository_full_name: GitHub 仓库全名，例如 owner/repo（可选）
        remote_requirement_delete_branch_after_pr_merge: PR 合并后是否允许删除远程任务分支
        description: 项目描述（可选）
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    display_name: str = Field(
        ..., min_length=1, max_length=100, description="项目展示名称"
    )
    project_category: str | None = Field(
        None,
        max_length=100,
        description="项目类别（可选）",
    )
    repo_path: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="当前机器上的本地 Git 仓库绝对路径",
    )
    remote_requirement_management_enabled: bool = Field(
        default=False,
        description="是否启用 GitHub-backed 远程需求协作",
    )
    remote_requirement_branch_prefix: str = Field(
        default="task",
        min_length=1,
        max_length=80,
        description="远程需求分支前缀",
    )
    remote_requirement_remote_name: str | None = Field(
        None,
        max_length=120,
        description="远程需求同步使用的 Git remote 名称（可选）",
    )
    github_pr_creation_enabled: bool = Field(
        default=True,
        description="Complete 时是否创建 GitHub PR",
    )
    github_repository_full_name: str | None = Field(
        None,
        max_length=255,
        description="GitHub 仓库全名，例如 owner/repo（可选）",
    )
    remote_requirement_delete_branch_after_pr_merge: bool = Field(
        default=False,
        description="PR 合并后是否允许删除远程任务分支",
    )
    description: str | None = Field(None, description="项目描述")
    worktree_resource_policy_confirmation: WorktreeResourcePolicyConfirmation = Field(
        default=WorktreeResourcePolicyConfirmation.ACCEPTED_DEFAULT,
        description="工作树本地资源策略确认状态",
    )
    worktree_resource_policy: ProjectWorktreeResourcePolicySchema | None = Field(
        None,
        description="工作树本地资源策略（可选）",
    )

    @field_validator("remote_requirement_branch_prefix")
    @classmethod
    def normalize_remote_branch_prefix(cls, value_str: str) -> str:
        """Normalize the remote requirement branch prefix.

        Args:
            value_str: Raw submitted prefix.

        Returns:
            str: Trimmed branch prefix without leading or trailing slashes.
        """
        normalized_prefix_str = value_str.strip().strip("/")
        return normalized_prefix_str or "task"

    @field_validator("remote_requirement_remote_name", "github_repository_full_name")
    @classmethod
    def normalize_optional_remote_text(cls, value_str: str | None) -> str | None:
        """Normalize remote collaboration text fields.

        Args:
            value_str: Raw submitted text value.

        Returns:
            str | None: Trimmed text, or None when optional text is blank.
        """
        if value_str is None:
            return None
        normalized_value_str = value_str.strip().strip("/")
        return normalized_value_str or None


class ProjectResponseSchema(DSLResponseSchema):
    """Project 响应模式.

    Attributes:
        id: UUID 主键
        display_name: 项目展示名称
        project_category: 项目类别
        repo_path: 本地 Git 仓库绝对路径
        description: 项目描述
        repo_remote_url: 项目记录中保存的归一化 origin remote URL
        repo_head_commit_hash: 项目记录中保存的 HEAD commit 哈希
        worktree_resource_policy_confirmation: 工作树本地资源策略确认状态
        worktree_resource_policy: 解析后的工作树本地资源策略
        remote_requirement_management_enabled: 是否启用 GitHub-backed 远程需求协作
        remote_requirement_branch_prefix: 远程需求分支前缀
        remote_requirement_remote_name: 远程需求同步使用的 Git remote 名称
        github_pr_creation_enabled: Complete 时是否创建 GitHub PR
        github_repository_full_name: GitHub 仓库全名
        remote_requirement_delete_branch_after_pr_merge: PR 合并后是否允许删除远程任务分支
        current_repo_remote_url: 当前本机仓库解析出的归一化 origin remote URL
        current_repo_head_commit_hash: 当前本机仓库解析出的 HEAD commit 哈希
        is_repo_path_valid: 当前机器上该路径是否仍然有效
        is_repo_remote_consistent: 当前仓库 remote 是否与已保存指纹一致
        is_repo_head_consistent: 当前仓库 HEAD 是否与已保存指纹一致
        repo_consistency_note: 当前仓库一致性说明
        created_at: 创建时间
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: str = Field(..., description="UUID 主键")
    display_name: str = Field(..., description="项目展示名称")
    project_category: str | None = Field(None, description="项目类别")
    repo_path: str = Field(..., description="本地 Git 仓库绝对路径")
    repo_remote_url: str | None = Field(
        None, description="项目记录中保存的归一化 origin remote URL"
    )
    repo_head_commit_hash: str | None = Field(
        None, description="项目记录中保存的 HEAD commit 哈希"
    )
    worktree_resource_policy_confirmation: WorktreeResourcePolicyConfirmation = Field(
        default=WorktreeResourcePolicyConfirmation.DEFERRED,
        description="工作树本地资源策略确认状态",
    )
    worktree_resource_policy: ProjectWorktreeResourcePolicySchema | None = Field(
        None,
        description="解析后的工作树本地资源策略",
    )
    remote_requirement_management_enabled: bool = Field(
        default=False,
        description="是否启用 GitHub-backed 远程需求协作",
    )
    remote_requirement_branch_prefix: str = Field(
        default="task",
        description="远程需求分支前缀",
    )
    remote_requirement_remote_name: str | None = Field(
        None,
        description="远程需求同步使用的 Git remote 名称",
    )
    github_pr_creation_enabled: bool = Field(
        default=True,
        description="Complete 时是否创建 GitHub PR",
    )
    github_repository_full_name: str | None = Field(
        None,
        description="GitHub 仓库全名",
    )
    remote_requirement_delete_branch_after_pr_merge: bool = Field(
        default=False,
        description="PR 合并后是否允许删除远程任务分支",
    )
    current_repo_remote_url: str | None = Field(
        None, description="当前本机仓库解析出的归一化 origin remote URL"
    )
    current_repo_head_commit_hash: str | None = Field(
        None, description="当前本机仓库解析出的 HEAD commit 哈希"
    )
    description: str | None = Field(None, description="项目描述")
    is_repo_path_valid: bool = Field(..., description="当前机器上该仓库路径是否有效")
    is_repo_remote_consistent: bool | None = Field(
        None, description="当前仓库 remote 是否与已保存指纹一致"
    )
    is_repo_head_consistent: bool | None = Field(
        None, description="当前仓库 HEAD 是否与已保存指纹一致"
    )
    repo_consistency_note: str | None = Field(None, description="当前仓库一致性说明")
    is_worktree_resource_policy_ready: bool = Field(
        ...,
        description="当前项目是否拥有可用于 task start 的已确认资源策略",
    )
    worktree_resource_policy_note: str | None = Field(
        None,
        description="资源策略状态说明",
    )
    created_at: datetime = Field(..., description="创建时间")


class ProjectBranchListSchema(DSLResponseSchema):
    """本地 Project 分支列表响应.

    Attributes:
        branches: 当前本机仓库中的本地分支名称列表
        current_branch_name: 当前工作区检出的分支；detached HEAD 时为 None
    """

    branches: list[str] = Field(..., description="当前本机仓库中的本地分支名称列表")
    current_branch_name: str | None = Field(
        None,
        description="当前工作区检出的分支；detached HEAD 时为 None",
    )


class RemoteRequirementSyncResponseSchema(DSLResponseSchema):
    """远程需求分支同步响应.

    Attributes:
        project_id: 项目 ID
        imported_count: 新导入到本地数据库的任务数量
        updated_count: 已存在任务的更新数量
        skipped_count: 因校验或冲突跳过的 manifest 数量
        message: 面向 UI 的同步摘要
    """

    project_id: str = Field(..., description="项目 ID")
    imported_count: int = Field(..., description="新导入到本地数据库的任务数量")
    updated_count: int = Field(..., description="已存在任务的更新数量")
    skipped_count: int = Field(..., description="跳过的 manifest 数量")
    message: str = Field(..., description="面向 UI 的同步摘要")
