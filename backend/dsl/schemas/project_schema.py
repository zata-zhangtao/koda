"""Project Pydantic 模式定义.

定义 Project 的创建、更新和响应模式.
"""

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from backend.dsl.schemas.base import DSLResponseSchema


class ProjectCreateSchema(BaseModel):
    """创建 Project 的请求模式.

    Attributes:
        display_name: 项目展示名称
        project_category: 项目类别（可选）
        repo_path: 本地 Git 仓库绝对路径
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
    description: str | None = Field(None, description="项目描述")


class ProjectUpdateSchema(BaseModel):
    """更新 Project 的请求模式.

    Attributes:
        display_name: 项目展示名称
        project_category: 项目类别（可选）
        repo_path: 当前机器上的本地 Git 仓库绝对路径
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
    description: str | None = Field(None, description="项目描述")


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
    created_at: datetime = Field(..., description="创建时间")
