"""Task Pydantic 模式定义.

定义 Task 的创建、更新和响应模式.
"""

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from dsl.models.enums import TaskLifecycleStatus


class TaskCreateSchema(BaseModel):
    """创建 Task 的请求模式.

    Attributes:
        task_title: 任务标题
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    task_title: str = Field(
        ..., min_length=1, max_length=200, description="任务标题"
    )


class TaskStatusUpdateSchema(BaseModel):
    """更新 Task 状态的请求模式.

    Attributes:
        lifecycle_status: 新的生命周期状态
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    lifecycle_status: TaskLifecycleStatus = Field(
        ..., description="任务生命周期状态"
    )


class TaskResponseSchema(BaseModel):
    """Task 响应模式.

    Attributes:
        id: UUID 主键
        run_account_id: 关联的 RunAccount ID
        task_title: 任务标题
        lifecycle_status: 任务生命周期状态
        created_at: 创建时间
        closed_at: 关闭时间
        log_count: 日志条目数量（计算字段）
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: str = Field(..., description="UUID 主键")
    run_account_id: str = Field(..., description="关联的 RunAccount ID")
    task_title: str = Field(..., description="任务标题")
    lifecycle_status: TaskLifecycleStatus = Field(..., description="任务生命周期状态")
    created_at: datetime = Field(..., description="创建时间")
    closed_at: datetime | None = Field(None, description="关闭时间")
    log_count: int = Field(default=0, description="日志条目数量")
