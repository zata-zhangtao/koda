"""DevLog Pydantic 模式定义.

定义 DevLog 的创建、更新和响应模式，包含 AI 解析结果.
"""

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from dsl.models.enums import AIProcessingStatus, DevLogStateTag
from dsl.schemas.base import DSLResponseSchema


class DevLogCreateSchema(BaseModel):
    """创建 DevLog 的请求模式.

    Attributes:
        text_content: Markdown 文本内容
        state_tag: 状态标记
        media_original_image_path: 原图路径（可选）
        media_thumbnail_path: 缩略图路径（可选）
        task_id: 关联的 Task ID（可选，默认使用当前活跃任务）
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    text_content: str = Field(default="", description="Markdown 文本内容")
    state_tag: DevLogStateTag = Field(
        default=DevLogStateTag.NONE, description="状态标记"
    )
    media_original_image_path: str | None = Field(
        default=None, description="原图存储路径"
    )
    media_thumbnail_path: str | None = Field(
        default=None, description="缩略图存储路径"
    )
    task_id: str | None = Field(
        default=None, description="关联的 Task ID（可选）"
    )


class DevLogResponseSchema(DSLResponseSchema):
    """DevLog 响应模式.

    Attributes:
        id: UUID 主键
        task_id: 关联的 Task ID
        run_account_id: 关联的 RunAccount ID
        created_at: 创建时间
        text_content: Markdown 文本内容
        state_tag: 状态标记
        media_original_image_path: 原图路径
        media_thumbnail_path: 缩略图路径
        task_title: 任务标题（关联查询）
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: str = Field(..., description="UUID 主键")
    task_id: str = Field(..., description="关联的 Task ID")
    run_account_id: str = Field(..., description="关联的 RunAccount ID")
    created_at: datetime = Field(..., description="创建时间")
    text_content: str = Field(..., description="Markdown 文本内容")
    state_tag: DevLogStateTag = Field(..., description="状态标记")
    media_original_image_path: str | None = Field(None, description="原图路径")
    media_thumbnail_path: str | None = Field(None, description="缩略图路径")
    task_title: str = Field(default="", description="任务标题")


class DevLogWithAIRSchema(DevLogResponseSchema):
    """包含 AI 解析结果的 DevLog 响应模式.

    Attributes:
        ai_processing_status: AI 处理状态
        ai_generated_title: AI 生成的标题
        ai_analysis_text: AI 分析文本
        ai_extracted_code: AI 提取的代码块
        ai_confidence_score: AI 置信度分数
    """

    ai_processing_status: AIProcessingStatus | None = Field(
        None, description="AI 处理状态"
    )
    ai_generated_title: str | None = Field(None, description="AI 生成的标题")
    ai_analysis_text: str | None = Field(None, description="AI 分析文本")
    ai_extracted_code: str | None = Field(None, description="AI 提取的代码块")
    ai_confidence_score: float | None = Field(None, description="AI 置信度分数")


class CommandParseResultSchema(BaseModel):
    """命令解析结果模式.

    用于解析用户输入的命令（如 /bug, /fix, /task 等）.

    Attributes:
        is_command: 是否为命令
        command_type: 命令类型 (bug, fix, opt, transfer, task)
        state_tag: 解析后的状态标记
        content: 去除命令后的内容
        task_title: 任务标题（仅用于 task 命令）
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    is_command: bool = Field(..., description="是否为命令")
    command_type: str | None = Field(None, description="命令类型")
    state_tag: DevLogStateTag = Field(
        default=DevLogStateTag.NONE, description="解析后的状态标记"
    )
    content: str = Field(..., description="去除命令后的内容")
    task_title: str | None = Field(None, description="任务标题（task 命令）")


class AIReviewUpdateSchema(BaseModel):
    """AI 结果校正请求模式.

    Attributes:
        action: 操作类型 (accept, edit, retry)
        ai_generated_title: 编辑后的标题（edit 操作）
        ai_analysis_text: 编辑后的分析文本（edit 操作）
        ai_extracted_code: 编辑后的代码块（edit 操作）
        retry_provider: 重试的提供商（retry 操作）
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    action: str = Field(..., pattern=r"^(accept|edit|retry)$", description="操作类型")
    ai_generated_title: str | None = Field(None, description="编辑后的标题")
    ai_analysis_text: str | None = Field(None, description="编辑后的分析文本")
    ai_extracted_code: str | None = Field(None, description="编辑后的代码块")
    retry_provider: str | None = Field(None, description="重试的提供商")
