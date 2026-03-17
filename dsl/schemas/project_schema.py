"""Project Pydantic 模式定义.

定义 Project 的创建、更新和响应模式.
"""

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreateSchema(BaseModel):
    """创建 Project 的请求模式.

    Attributes:
        display_name: 项目展示名称
        repo_path: 本地 Git 仓库绝对路径
        description: 项目描述（可选）
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    display_name: str = Field(..., min_length=1, max_length=100, description="项目展示名称")
    repo_path: str = Field(..., min_length=1, max_length=500, description="本地 Git 仓库绝对路径")
    description: str | None = Field(None, description="项目描述")


class ProjectResponseSchema(BaseModel):
    """Project 响应模式.

    Attributes:
        id: UUID 主键
        display_name: 项目展示名称
        repo_path: 本地 Git 仓库绝对路径
        description: 项目描述
        created_at: 创建时间
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: str = Field(..., description="UUID 主键")
    display_name: str = Field(..., description="项目展示名称")
    repo_path: str = Field(..., description="本地 Git 仓库绝对路径")
    description: str | None = Field(None, description="项目描述")
    created_at: datetime = Field(..., description="创建时间")
