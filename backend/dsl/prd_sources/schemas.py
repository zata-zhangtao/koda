"""Pydantic schemas for PRD source APIs."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class PendingPrdFileSchema(BaseModel):
    """Pending PRD file list item.

    Attributes:
        file_name: Display filename.
        relative_path: Workspace-relative path.
        size_bytes: File size in bytes.
        updated_at: Last modification time.
        title_preview: Optional title or metadata preview.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    file_name: str = Field(..., description="Display filename")
    relative_path: str = Field(..., description="Workspace-relative pending PRD path")
    size_bytes: int = Field(..., description="File size in bytes")
    updated_at: datetime = Field(..., description="Last modification time")
    title_preview: str | None = Field(None, description="Optional title preview")


class PendingPrdFileListSchema(BaseModel):
    """Response schema for pending PRD file listing."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    files: list[PendingPrdFileSchema] = Field(default_factory=list)


class SelectPendingPrdRequestSchema(BaseModel):
    """Request schema for selecting a pending PRD.

    Attributes:
        relative_path: Workspace-relative path returned by the pending list API.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    relative_path: str = Field(
        ...,
        min_length=1,
        description="Workspace-relative path returned by the pending list API",
    )


class BuildPendingPrdTaskDraftRequestSchema(BaseModel):
    """Request schema for building a task draft from a pending PRD.

    Attributes:
        project_id: Optional project UUID string.
        relative_path: Workspace-relative pending PRD path.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    project_id: str | None = Field(None, description="Optional project ID")
    relative_path: str = Field(
        ...,
        min_length=1,
        description="Workspace-relative pending PRD path",
    )


class PrdTaskDraftSuggestionSchema(BaseModel):
    """Response schema for a PRD-first task draft suggestion.

    Attributes:
        source_type: Source kind used to build the draft.
        suggested_task_title: Suggested task title.
        suggested_requirement_brief: Suggested task description.
        source_file_name: Optional source filename.
        source_relative_path: Optional source relative path.
        source_updated_at: Optional source update timestamp.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    source_type: str = Field(..., description="PRD source type")
    suggested_task_title: str = Field(..., description="Suggested task title")
    suggested_requirement_brief: str = Field(
        ...,
        description="Suggested task description",
    )
    source_file_name: str | None = Field(None, description="Source filename")
    source_relative_path: str | None = Field(None, description="Source relative path")
    source_updated_at: datetime | None = Field(
        None,
        description="Source update timestamp",
    )


class CreateTaskFromPendingPrdRequestSchema(BaseModel):
    """Request schema for creating a task from a selected pending PRD.

    Attributes:
        task_title: Confirmed task title.
        project_id: Optional project UUID string.
        worktree_base_branch_name: Selected worktree base branch.
        requirement_brief: Confirmed task description.
        auto_confirm_prd_and_execute: Whether to execute after PRD ready.
        relative_path: Workspace-relative pending PRD path.
        source_updated_at: Pending PRD timestamp captured at draft time.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    task_title: str = Field(..., min_length=1, max_length=200)
    project_id: str | None = Field(None, description="Optional project ID")
    worktree_base_branch_name: str = Field(default="main", min_length=1, max_length=255)
    requirement_brief: str = Field(..., min_length=1)
    auto_confirm_prd_and_execute: bool = Field(default=False)
    relative_path: str = Field(..., min_length=1)
    source_updated_at: datetime = Field(
        ...,
        description="Pending PRD timestamp captured at draft time",
    )


class ImportPastedPrdRequestSchema(BaseModel):
    """Request schema for importing pasted PRD Markdown.

    Attributes:
        prd_markdown_text: Markdown content pasted by the user.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    prd_markdown_text: str = Field(
        ...,
        min_length=1,
        description="Markdown content pasted by the user",
    )


class BuildPastedPrdTaskDraftRequestSchema(ImportPastedPrdRequestSchema):
    """Request schema for building a task draft from pasted PRD Markdown."""

    original_file_name: str = Field(default="pasted-prd.md", min_length=1)


class CreateTaskFromPastedPrdRequestSchema(BaseModel):
    """Request schema for creating a task from pasted PRD Markdown.

    Attributes:
        task_title: Confirmed task title.
        project_id: Optional project UUID string.
        worktree_base_branch_name: Selected worktree base branch.
        requirement_brief: Confirmed task description.
        auto_confirm_prd_and_execute: Whether to execute after PRD ready.
        prd_markdown_text: Markdown content pasted by the user.
        original_file_name: Logical source filename.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    task_title: str = Field(..., min_length=1, max_length=200)
    project_id: str | None = Field(None, description="Optional project ID")
    worktree_base_branch_name: str = Field(default="main", min_length=1, max_length=255)
    requirement_brief: str = Field(..., min_length=1)
    auto_confirm_prd_and_execute: bool = Field(default=False)
    prd_markdown_text: str = Field(..., min_length=1)
    original_file_name: str = Field(default="pasted-prd.md", min_length=1)
