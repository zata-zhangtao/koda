"""Chronicle 相关 Pydantic 模式定义."""

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.dsl.models.enums import (
    TaskLifecycleStatus,
    TaskArtifactType,
    WorkflowStage,
)
from backend.dsl.schemas.base import DSLResponseSchema


class TaskArtifactSnapshotSchema(DSLResponseSchema):
    """任务工件快照响应模式.

    Attributes:
        artifact_type: 工件类型
        source_path: 快照来源路径
        content_markdown: 工件正文内容
        file_manifest: 关联文件清单
        captured_at: 快照采集时间
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    artifact_type: TaskArtifactType = Field(..., description="工件类型")
    source_path: str | None = Field(None, description="快照来源路径")
    content_markdown: str = Field(..., description="工件正文内容")
    file_manifest: list[str] = Field(
        default_factory=list,
        description="关联文件清单",
    )
    captured_at: datetime = Field(..., description="快照采集时间")


class ProjectTimelineEntrySchema(DSLResponseSchema):
    """项目时间线条目响应模式.

    Attributes:
        task_id: 任务 ID
        project_id: 所属项目 ID
        project_display_name: 所属项目名称
        project_category: 所属项目类别
        task_title: 任务标题
        lifecycle_status: 生命周期状态
        workflow_stage: 工作流阶段
        created_at: 创建时间
        closed_at: 关闭时间
        last_activity_at: 最近活动时间
        total_logs: 日志总数
        bug_count: BUG 日志数量
        fix_count: FIX 日志数量
        has_prd_artifact: 是否存在 PRD 快照
        has_planning_artifact: 是否存在 planning with files 快照
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    task_id: str = Field(..., description="任务 ID")
    project_id: str = Field(..., description="所属项目 ID")
    project_display_name: str | None = Field(None, description="所属项目名称")
    project_category: str | None = Field(None, description="所属项目类别")
    task_title: str = Field(..., description="任务标题")
    lifecycle_status: TaskLifecycleStatus = Field(..., description="生命周期状态")
    workflow_stage: WorkflowStage = Field(..., description="工作流阶段")
    created_at: datetime = Field(..., description="创建时间")
    closed_at: datetime | None = Field(None, description="关闭时间")
    last_activity_at: datetime = Field(..., description="最近活动时间")
    total_logs: int = Field(default=0, description="日志总数")
    bug_count: int = Field(default=0, description="BUG 日志数量")
    fix_count: int = Field(default=0, description="FIX 日志数量")
    has_prd_artifact: bool = Field(default=False, description="是否存在 PRD 快照")
    has_planning_artifact: bool = Field(
        default=False,
        description="是否存在 planning with files 快照",
    )


class ProjectTimelineTaskDetailSchema(DSLResponseSchema):
    """项目时间线任务详情响应模式.

    Attributes:
        task: 任务基本信息
        requirement_snapshot: 任务需求快照
        prd_snapshot: PRD 快照
        planning_snapshot: planning with files 快照
        logs: 时间线日志（按时间升序）
        stats: 统计信息
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    task: dict = Field(..., description="任务基本信息")
    requirement_snapshot: str | None = Field(None, description="任务需求快照")
    prd_snapshot: TaskArtifactSnapshotSchema | None = Field(
        None,
        description="PRD 快照",
    )
    planning_snapshot: TaskArtifactSnapshotSchema | None = Field(
        None,
        description="planning with files 快照",
    )
    logs: list[dict] = Field(default_factory=list, description="时间线日志")
    stats: dict = Field(default_factory=dict, description="统计信息")


class ProjectTimelineSummaryRequestSchema(BaseModel):
    """项目时间线总结请求模式.

    Attributes:
        project_id: 项目 ID
        project_category: 项目类别（可选）
        lifecycle_status_list: 生命周期筛选列表（可选）
        start_date: 起始时间（可选）
        end_date: 结束时间（可选）
        summary_focus: 总结关注点
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    project_id: str | None = Field(default=None, description="项目 ID")
    project_category: str | None = Field(
        default=None,
        description="项目类别（可选）",
    )
    lifecycle_status_list: list[TaskLifecycleStatus] | None = Field(
        default=None,
        description="生命周期筛选列表",
    )
    start_date: datetime | None = Field(default=None, description="起始时间")
    end_date: datetime | None = Field(default=None, description="结束时间")
    summary_focus: Literal["progress", "risk", "decision"] = Field(
        default="progress",
        description="总结关注点",
    )


class ProjectTimelineSummaryResponseSchema(DSLResponseSchema):
    """项目时间线总结响应模式.

    Attributes:
        summary_text: 摘要正文
        milestones: 里程碑列表
        risks: 风险列表
        next_actions: 下一步建议列表
        source_task_ids: 证据任务 ID 列表
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    summary_text: str = Field(..., description="摘要正文")
    milestones: list[str] = Field(default_factory=list, description="里程碑列表")
    risks: list[str] = Field(default_factory=list, description="风险列表")
    next_actions: list[str] = Field(default_factory=list, description="下一步建议列表")
    source_task_ids: list[str] = Field(
        default_factory=list,
        description="证据任务 ID 列表",
    )
