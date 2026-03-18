"""Task Pydantic 模式定义.

定义 Task 的创建、更新和响应模式，包含工作流阶段字段.
"""

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from dsl.models.enums import TaskLifecycleStatus, WorkflowStage
from dsl.schemas.base import DSLResponseSchema


class TaskCreateSchema(BaseModel):
    """创建 Task 的请求模式.

    Attributes:
        task_title: 任务标题
        project_id: 关联的 Project ID（可选）
        requirement_brief: 需求描述文本（可选）
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    task_title: str = Field(
        ..., min_length=1, max_length=200, description="任务标题"
    )
    project_id: str | None = Field(None, description="关联的 Project ID")
    requirement_brief: str | None = Field(None, description="需求描述文本")


class TaskStatusUpdateSchema(BaseModel):
    """更新 Task 生命周期状态的请求模式.

    Attributes:
        lifecycle_status: 新的生命周期状态
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    lifecycle_status: TaskLifecycleStatus = Field(
        ..., description="任务生命周期状态"
    )


class TaskStageUpdateSchema(BaseModel):
    """更新 Task 工作流阶段的请求模式.

    Attributes:
        workflow_stage: 新的工作流阶段
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    workflow_stage: WorkflowStage = Field(
        ..., description="工作流阶段"
    )


class TaskUpdateSchema(BaseModel):
    """更新 Task 内容的请求模式.

    Attributes:
        task_title: 更新后的任务标题
        requirement_brief: 更新后的需求描述文本（可选）
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    task_title: str = Field(
        ..., min_length=1, max_length=200, description="更新后的任务标题"
    )
    requirement_brief: str | None = Field(None, description="更新后的需求描述文本")


class TaskResponseSchema(DSLResponseSchema):
    """Task 响应模式.

    Attributes:
        id: UUID 主键
        run_account_id: 关联的 RunAccount ID
        task_title: 任务标题
        lifecycle_status: 任务生命周期状态（向后兼容）
        workflow_stage: 工作流精确阶段（UI 阶段展示的唯一数据源）
        created_at: 创建时间
        closed_at: 关闭时间
        log_count: 日志条目数量（计算字段）
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: str = Field(..., description="UUID 主键")
    run_account_id: str = Field(..., description="关联的 RunAccount ID")
    project_id: str | None = Field(None, description="关联的 Project ID")
    task_title: str = Field(..., description="任务标题")
    lifecycle_status: TaskLifecycleStatus = Field(..., description="任务生命周期状态")
    workflow_stage: WorkflowStage = Field(
        default=WorkflowStage.BACKLOG, description="工作流阶段"
    )
    worktree_path: str | None = Field(None, description="git worktree 绝对路径")
    requirement_brief: str | None = Field(None, description="需求描述文本")
    created_at: datetime = Field(..., description="创建时间")
    closed_at: datetime | None = Field(None, description="关闭时间")
    log_count: int = Field(default=0, description="日志条目数量")
