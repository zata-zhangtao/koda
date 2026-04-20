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
