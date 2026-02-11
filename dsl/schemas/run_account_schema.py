"""RunAccount Pydantic 模式定义.

定义 RunAccount 的创建、更新和响应模式.
"""

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class RunAccountCreateSchema(BaseModel):
    """创建 RunAccount 的请求模式.

    Attributes:
        user_name: 用户名
        environment_os: 操作系统
        git_branch_name: 当前 Git 分支（可选）
        account_display_name: 显示名称（可选，默认自动生成）
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    user_name: str = Field(..., min_length=1, max_length=50, description="用户名")
    environment_os: str = Field(..., min_length=1, max_length=50, description="操作系统")
    git_branch_name: str | None = Field(
        default=None, max_length=100, description="当前 Git 分支"
    )
    account_display_name: str | None = Field(
        default=None, max_length=100, description="显示名称"
    )


class RunAccountUpdateSchema(BaseModel):
    """更新 RunAccount 的请求模式.

    Attributes:
        account_display_name: 新的显示名称
        git_branch_name: 新的 Git 分支
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    account_display_name: str | None = Field(
        default=None, max_length=100, description="显示名称"
    )
    git_branch_name: str | None = Field(
        default=None, max_length=100, description="当前 Git 分支"
    )


class RunAccountResponseSchema(BaseModel):
    """RunAccount 响应模式.

    Attributes:
        id: UUID 主键
        account_display_name: 显示名称
        user_name: 用户名
        environment_os: 操作系统
        git_branch_name: Git 分支
        created_at: 创建时间
        is_active: 是否为活跃账户
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: str = Field(..., description="UUID 主键")
    account_display_name: str = Field(..., description="显示名称")
    user_name: str = Field(..., description="用户名")
    environment_os: str = Field(..., description="操作系统")
    git_branch_name: str | None = Field(None, description="当前 Git 分支")
    created_at: datetime = Field(..., description="创建时间")
    is_active: bool = Field(..., description="是否为当前活跃账户")
