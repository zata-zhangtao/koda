"""Pydantic schemas for preview sandbox APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PreviewApplicabilityLiteral = Literal["applicable", "not_applicable", "uncertain"]
PreviewStatusLiteral = Literal[
    "disabled",
    "not_started",
    "generating_profile",
    "not_applicable",
    "uncertain",
    "starting",
    "running",
    "failed",
    "needs_human_action",
    "stopped",
    "runtime_state_lost",
]
PreviewFailureKindLiteral = Literal[
    "code_error",
    "dependency_error",
    "environment_error",
    "sandbox_error",
    "unknown",
]
PreviewRuntimeKindLiteral = Literal["node", "python", "static", "unknown"]


class PreviewProfileFingerprintSchema(BaseModel):
    """Revision fingerprint for profile reuse decisions."""

    model_config = ConfigDict(from_attributes=True)

    git_head: str | None = Field(None, description="Git HEAD hash")
    dirty_diff_hash: str | None = Field(None, description="Dirty worktree diff hash")


class PreviewProfileSchema(BaseModel):
    """Strict JSON preview startup profile."""

    model_config = ConfigDict(from_attributes=True)

    schema_version: int = Field(..., ge=1, description="Preview profile schema version")
    applicability: PreviewApplicabilityLiteral = Field(
        ...,
        description="Whether the task should be previewed automatically",
    )
    applicability_reason: str = Field(..., min_length=1, description="Reason text")
    profile_fingerprint: PreviewProfileFingerprintSchema = Field(
        default_factory=PreviewProfileFingerprintSchema,
        description="Task revision fingerprint",
    )
    runtime_kind: PreviewRuntimeKindLiteral = Field(..., description="Runtime kind")
    working_directory: str | None = Field(None, description="Worktree-relative cwd")
    dependency_commands: list[str] = Field(
        default_factory=list,
        description="Container-only dependency preparation commands",
    )
    start_command: str | None = Field(None, description="Container start command")
    internal_port: int | None = Field(None, ge=1, le=65535)
    healthcheck_path: str | None = Field(None, description="HTTP health path")
    preview_path: str | None = Field(None, description="Preview URL path")
    readiness_timeout_seconds: int = Field(default=90, ge=1, le=600)
    notes: str | None = Field(None, description="Profile generation notes")


class PreviewSandboxStatusSchema(BaseModel):
    """Preview sandbox status returned to the task detail UI."""

    model_config = ConfigDict(from_attributes=True)

    task_id: str
    status: PreviewStatusLiteral
    applicability: PreviewApplicabilityLiteral | None = None
    preview_url: str | None = None
    profile_summary: str | None = None
    failure_kind: PreviewFailureKindLiteral | None = None
    failure_summary: str | None = None
    bypass_confirmed: bool = False
    log_tail: str | None = None
    container_id: str | None = None
    host_port: int | None = None
    internal_port: int | None = None
    started_at: datetime | None = None
