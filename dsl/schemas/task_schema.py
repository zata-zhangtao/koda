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

    task_title: str = Field(..., min_length=1, max_length=200, description="任务标题")
    project_id: str | None = Field(None, description="关联的 Project ID")
    requirement_brief: str | None = Field(None, description="需求描述文本")


class TaskStatusUpdateSchema(BaseModel):
    """更新 Task 生命周期状态的请求模式.

    Attributes:
        lifecycle_status: 新的生命周期状态
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    lifecycle_status: TaskLifecycleStatus = Field(..., description="任务生命周期状态")


class TaskStageUpdateSchema(BaseModel):
    """更新 Task 工作流阶段的请求模式.

    Attributes:
        workflow_stage: 新的工作流阶段
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    workflow_stage: WorkflowStage = Field(..., description="工作流阶段")


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
        workflow_stage: 工作流业务阶段；后台运行态由 is_codex_task_running 补充
        last_ai_activity_at: 最近一次 Codex 自动化输出写入时间
        created_at: 创建时间
        closed_at: 关闭时间
        log_count: 日志条目数量（计算字段）
        is_codex_task_running: 后台自动化是否仍在运行
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: str = Field(..., description="UUID 主键")
    run_account_id: str = Field(..., description="关联的 RunAccount ID")
    project_id: str | None = Field(None, description="关联的 Project ID")
    task_title: str = Field(..., description="任务标题")
    lifecycle_status: TaskLifecycleStatus = Field(..., description="任务生命周期状态")
    workflow_stage: WorkflowStage = Field(
        default=WorkflowStage.BACKLOG,
        description="工作流业务阶段",
    )
    last_ai_activity_at: datetime | None = Field(
        None,
        description="最近一次 Codex 自动化输出写入时间",
    )
    worktree_path: str | None = Field(None, description="git worktree 绝对路径")
    requirement_brief: str | None = Field(None, description="需求描述文本")
    created_at: datetime = Field(..., description="创建时间")
    closed_at: datetime | None = Field(None, description="关闭时间")
    log_count: int = Field(default=0, description="日志条目数量")
    is_codex_task_running: bool = Field(
        default=False,
        description="该任务的后台自动化是否仍在运行",
    )


class TaskCardMetadataSchema(DSLResponseSchema):
    """Task 卡片与详情头部共用的展示元数据.

    该 Schema 只描述 UI 展示态，不会改变 `Task.workflow_stage`
    这一真实工作流阶段字段。

    Attributes:
        task_id: 对应任务 ID
        display_stage_key: 展示态 key；可能为 `waiting_user` 或真实 workflow_stage 值
        display_stage_label: 直接给前端 badge 使用的文案
        is_waiting_for_user: 当前是否处于“等待用户”展示态
        last_ai_activity_at: 最近一次 Codex 自动化输出写入时间
    """

    task_id: str = Field(..., description="对应任务 ID")
    display_stage_key: str = Field(
        ...,
        description="展示态 key；可能为 waiting_user 或真实 workflow_stage 值",
    )
    display_stage_label: str = Field(..., description="展示态文案")
    is_waiting_for_user: bool = Field(
        ...,
        description="当前是否处于等待用户展示态",
    )
    last_ai_activity_at: datetime | None = Field(
        None,
        description="最近一次 Codex 自动化输出写入时间",
    )
