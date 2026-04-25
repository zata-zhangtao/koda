"""Task Pydantic 模式定义.

定义 Task 的创建、更新和响应模式，包含工作流阶段字段.
"""

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.dsl.models.enums import TaskLifecycleStatus, WorkflowStage
from backend.dsl.schemas.base import DSLResponseSchema


class TaskCreateSchema(BaseModel):
    """创建 Task 的请求模式.

    Attributes:
        task_title: 任务标题
        project_id: 关联的 Project ID（可选）
        worktree_base_branch_name: 创建任务 worktree 与完成合并时使用的基底分支
        requirement_brief: 需求描述文本（可选）
        auto_confirm_prd_and_execute: PRD 生成后是否自动确认并直接进入执行
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    task_title: str = Field(..., min_length=1, max_length=200, description="任务标题")
    project_id: str | None = Field(None, description="关联的 Project ID")
    worktree_base_branch_name: str = Field(
        default="main",
        min_length=1,
        max_length=255,
        description="创建任务 worktree 与完成合并时使用的基底分支",
    )
    requirement_brief: str | None = Field(None, description="需求描述文本")
    auto_confirm_prd_and_execute: bool = Field(
        default=False,
        description="PRD 生成后是否自动确认并直接进入执行",
    )

    @field_validator("worktree_base_branch_name")
    @classmethod
    def validate_worktree_base_branch_name(cls, branch_name_str: str) -> str:
        """Normalize the task worktree base branch name.

        Args:
            branch_name_str: Raw branch name from the API request.

        Returns:
            str: Trimmed branch name.

        Raises:
            ValueError: Raised when the branch name is empty.
        """
        normalized_branch_name_str = branch_name_str.strip()
        if not normalized_branch_name_str:
            raise ValueError("worktree_base_branch_name cannot be empty")
        return normalized_branch_name_str


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
        project_id: 更新后的关联项目 ID；仅 backlog 阶段允许改绑
        worktree_base_branch_name: 更新后的任务 worktree 基底分支；仅 worktree 创建前允许修改
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    task_title: str = Field(
        ..., min_length=1, max_length=200, description="更新后的任务标题"
    )
    requirement_brief: str | None = Field(None, description="更新后的需求描述文本")
    project_id: str | None = Field(
        None,
        description="更新后的关联项目 ID；传 null 表示取消项目绑定",
    )
    worktree_base_branch_name: str | None = Field(
        None,
        min_length=1,
        max_length=255,
        description="更新后的任务 worktree 基底分支；仅 worktree 创建前允许修改",
    )

    @field_validator("worktree_base_branch_name")
    @classmethod
    def validate_updated_worktree_base_branch_name(
        cls,
        branch_name_str: str | None,
    ) -> str | None:
        """Normalize an updated task worktree base branch name.

        Args:
            branch_name_str: Raw branch name from the API request.

        Returns:
            str | None: Trimmed branch name, or None when not provided.

        Raises:
            ValueError: Raised when the branch name is empty.
        """
        if branch_name_str is None:
            return None
        normalized_branch_name_str = branch_name_str.strip()
        if not normalized_branch_name_str:
            raise ValueError("worktree_base_branch_name cannot be empty")
        return normalized_branch_name_str


class TaskDestroySchema(BaseModel):
    """销毁已启动任务的请求模式.

    Attributes:
        destroy_reason: 销毁原因；必填，提交后会持久化到 Task
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    destroy_reason: str = Field(
        ...,
        min_length=5,
        max_length=200,
        description="销毁原因；去除首尾空白后至少 5 个字符",
    )

    @field_validator("destroy_reason")
    @classmethod
    def validate_destroy_reason(cls, destroy_reason_str: str) -> str:
        """规范化并校验销毁原因.

        Args:
            destroy_reason_str: 原始销毁原因输入

        Returns:
            str: 去除首尾空白后的销毁原因

        Raises:
            ValueError: 当原因为空白或长度不足时抛出
        """
        normalized_destroy_reason = destroy_reason_str.strip()
        if len(normalized_destroy_reason) < 5:
            raise ValueError(
                "destroy_reason must contain at least 5 non-space characters"
            )
        return normalized_destroy_reason


class TaskBranchHealthSchema(DSLResponseSchema):
    """Task 关联 Git 分支的派生健康状态.

    Attributes:
        expected_branch_name: 基于任务 ID 推导出的任务分支名；若探测到语义分支，
            则返回匹配到的真实本地分支名
        branch_exists: 本地仓库中是否仍存在该 branch；无法确认时为 None
        worktree_exists: 当前记录的 worktree 目录是否仍存在
        manual_completion_candidate: 当前是否满足“缺失分支待人工确认完成”条件
        status_message: 面向 UI 的状态说明文案
    """

    expected_branch_name: str = Field(
        ...,
        description=(
            "基于任务 ID 推导出的任务分支名；若探测到语义分支，"
            "则返回匹配到的真实本地分支名"
        ),
    )
    branch_exists: bool | None = Field(
        None,
        description="本地仓库中是否仍存在该 branch；无法确认时为 None",
    )
    worktree_exists: bool = Field(..., description="当前记录的 worktree 目录是否仍存在")
    manual_completion_candidate: bool = Field(
        ...,
        description="当前是否满足缺失分支后的人工确认完成条件",
    )
    status_message: str | None = Field(None, description="面向 UI 的状态说明文案")


class TaskResponseSchema(DSLResponseSchema):
    """Task 响应模式.

    Attributes:
        id: UUID 主键
        run_account_id: 关联的 RunAccount ID
        task_title: 任务标题
        lifecycle_status: 任务生命周期状态（向后兼容）
        workflow_stage: 工作流业务阶段；后台运行态由 is_codex_task_running 补充
        stage_updated_at: 最近一次进入当前工作流阶段的时间
        last_ai_activity_at: 最近一次 Codex 自动化输出写入时间
        worktree_base_branch_name: 创建任务 worktree 与完成合并时使用的基底分支
        auto_confirm_prd_and_execute: PRD 生成后是否自动确认并直接进入执行
        business_sync_original_workflow_stage: 最近一次业务同步恢复前的原始阶段快照
        business_sync_original_lifecycle_status: 最近一次业务同步恢复前的原始生命周期快照
        business_sync_restored_at: 最近一次从业务同步快照恢复到当前机器的时间
        business_sync_status_note: 面向 UI 的业务同步恢复说明
        created_at: 创建时间
        closed_at: 关闭时间
        destroy_reason: 已启动任务销毁原因（若存在）
        destroyed_at: 任务进入 deleted history 的时间（若存在）
        log_count: 日志条目数量（计算字段）
        is_codex_task_running: 后台自动化是否仍在运行
        branch_health: 任务关联 Git 分支的派生健康状态
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
    stage_updated_at: datetime = Field(
        ...,
        description="最近一次进入当前工作流阶段的时间",
    )
    last_ai_activity_at: datetime | None = Field(
        None,
        description="最近一次 Codex 自动化输出写入时间",
    )
    worktree_path: str | None = Field(None, description="git worktree 绝对路径")
    worktree_base_branch_name: str = Field(
        default="main",
        description="创建任务 worktree 与完成合并时使用的基底分支",
    )
    requirement_brief: str | None = Field(None, description="需求描述文本")
    auto_confirm_prd_and_execute: bool = Field(
        default=False,
        description="PRD 生成后是否自动确认并直接进入执行",
    )
    business_sync_original_workflow_stage: str | None = Field(
        None,
        description="最近一次业务同步恢复前的原始阶段快照",
    )
    business_sync_original_lifecycle_status: str | None = Field(
        None,
        description="最近一次业务同步恢复前的原始生命周期快照",
    )
    business_sync_restored_at: datetime | None = Field(
        None,
        description="最近一次从业务同步快照恢复到当前机器的时间",
    )
    business_sync_status_note: str | None = Field(
        None,
        description="面向 UI 的业务同步恢复说明",
    )
    destroy_reason: str | None = Field(None, description="已启动任务销毁原因")
    destroyed_at: datetime | None = Field(
        None,
        description="任务进入 deleted history 的时间",
    )
    created_at: datetime = Field(..., description="创建时间")
    closed_at: datetime | None = Field(None, description="关闭时间")
    log_count: int = Field(default=0, description="日志条目数量")
    is_codex_task_running: bool = Field(
        default=False,
        description="该任务的后台自动化是否仍在运行",
    )
    branch_health: TaskBranchHealthSchema | None = Field(
        None,
        description="任务关联 Git 分支的派生健康状态",
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
        requirement_change_kind: 最近一次需求变更日志类型；仅卡片分组/摘要使用
        requirement_summary: 最近一次需求变更摘要；为空时前端回退到 `Task.requirement_brief`
        business_sync_restored_at: 最近一次从业务同步快照恢复到当前机器的时间
        business_sync_status_note: 业务同步恢复说明
        branch_health: 任务关联 Git 分支的派生健康状态
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
    requirement_change_kind: str | None = Field(
        None,
        description="最近一次需求变更日志类型；可能为 update 或 delete",
    )
    requirement_summary: str | None = Field(
        None,
        description="最近一次需求变更摘要；为空时前端回退到 Task.requirement_brief",
    )
    business_sync_restored_at: datetime | None = Field(
        None,
        description="最近一次从业务同步快照恢复到当前机器的时间",
    )
    business_sync_status_note: str | None = Field(
        None,
        description="业务同步恢复说明",
    )
    branch_health: TaskBranchHealthSchema | None = Field(
        None,
        description="任务关联 Git 分支的派生健康状态",
    )


class TaskReferenceCreateSchema(BaseModel):
    """创建任务引用关系的请求模式.

    Attributes:
        source_task_id: 被引用的历史任务 ID
        append_to_requirement_brief: 是否把引用摘要追加到目标任务需求描述
        reference_note: 引用备注（可选）
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    source_task_id: str = Field(..., description="被引用的历史任务 ID")
    append_to_requirement_brief: bool = Field(
        default=False,
        description="是否把引用摘要追加到目标任务需求描述",
    )
    reference_note: str | None = Field(
        default=None,
        description="引用备注（可选）",
    )


class TaskReferenceResponseSchema(DSLResponseSchema):
    """任务引用创建响应模式.

    Attributes:
        target_task_id: 目标任务 ID
        source_task_id: 来源任务 ID
        reference_log_id: 首次创建或复用的引用日志 ID
        requirement_brief_appended: 目标任务 requirement_brief 当前是否已包含该引用摘要
    """

    target_task_id: str = Field(..., description="目标任务 ID")
    source_task_id: str = Field(..., description="来源任务 ID")
    reference_log_id: str = Field(..., description="记录引用行为的日志 ID")
    requirement_brief_appended: bool = Field(
        default=False,
        description="是否已追加到目标任务 requirement_brief",
    )
