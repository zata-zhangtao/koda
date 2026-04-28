"""Schemas for worktree local resource policies.

The policy model is intentionally project-scoped and JSON serializable so it can
be stored in the Project table, previewed before creation, and reused when a
task worktree is materialized.
"""

from __future__ import annotations

from enum import Enum
from pathlib import PurePosixPath
import re
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

_WINDOWS_DRIVE_PREFIX_PATTERN = re.compile(r"^[A-Za-z]:")


def _normalize_safe_repo_relative_path(raw_relative_path_str: str) -> str:
    """Normalize and validate a repo-relative POSIX path.

    Args:
        raw_relative_path_str: User-supplied repo-relative path.

    Returns:
        str: Normalized POSIX relative path.

    Raises:
        ValueError: Raised when the path can escape the repository or worktree.
    """

    if "\x00" in raw_relative_path_str:
        raise ValueError("relative_path must not contain null bytes")

    normalized_relative_path_str = raw_relative_path_str.strip().replace("\\", "/")
    if _WINDOWS_DRIVE_PREFIX_PATTERN.match(normalized_relative_path_str):
        raise ValueError("relative_path must not use a Windows drive prefix")

    normalized_path = PurePosixPath(normalized_relative_path_str)
    if normalized_path.is_absolute():
        raise ValueError("relative_path must be repo-relative")

    normalized_posix_path_str = normalized_path.as_posix().lstrip("/")
    if not normalized_posix_path_str or normalized_posix_path_str in {".", ".."}:
        raise ValueError("relative_path must not be empty or a traversal path")
    if any(path_part in {"", ".", ".."} for path_part in normalized_path.parts):
        raise ValueError("relative_path must not contain traversal segments")
    if normalized_posix_path_str == ".git" or normalized_posix_path_str.startswith(
        ".git/"
    ):
        raise ValueError("relative_path must not reference .git")

    return normalized_posix_path_str


class WorktreeResourceMaterialization(str, Enum):
    """Materialization action for one worktree resource candidate."""

    GIT_MANAGED_COPY = "git-managed-copy"
    LINK = "link"
    COPY = "copy"
    SKIP = "skip"


class WorktreeResourceGitState(str, Enum):
    """Git state for a discovered candidate."""

    TRACKED = "tracked"
    UNTRACKED = "untracked"
    IGNORED = "ignored"


class WorktreeResourcePolicyConfirmation(str, Enum):
    """Confirmation state for a project's worktree resource policy."""

    ACCEPTED_DEFAULT = "accepted_default"
    CUSTOMIZED = "customized"
    DEFERRED = "deferred"


class ProjectWorktreeResourceRuleSchema(BaseModel):
    """One policy rule for a repo-relative worktree resource."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    relative_path: str = Field(..., min_length=1, description="Repo-relative path")
    include: bool = Field(default=True, description="Whether this rule is active")
    materialization: WorktreeResourceMaterialization = Field(
        ...,
        description="How the resource should be materialized",
    )
    resource_kind: str = Field(..., min_length=1, description="Kind of resource")
    git_state: WorktreeResourceGitState = Field(..., description="Git state")
    required: bool = Field(
        default=False, description="Whether the resource is required"
    )
    is_directory: bool = Field(
        default=False, description="Whether the rule targets a directory"
    )
    note: str | None = Field(None, description="Human-readable note")

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, raw_relative_path_str: str) -> str:
        """Validate and normalize one policy rule path.

        Args:
            raw_relative_path_str: Raw repo-relative path value.

        Returns:
            str: Normalized POSIX repo-relative path.

        Raises:
            ValueError: Raised when the path is unsafe.
        """

        return _normalize_safe_repo_relative_path(raw_relative_path_str)


class ProjectWorktreeResourcePolicySchema(BaseModel):
    """JSON-serializable worktree resource policy for one Project."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    confirmation_status: WorktreeResourcePolicyConfirmation = Field(
        ...,
        description="Project policy confirmation state",
    )
    rules: list[ProjectWorktreeResourceRuleSchema] = Field(
        default_factory=list,
        description="Ordered policy rules",
    )


class WorktreeResourceCandidateSchema(BaseModel):
    """Discovered local resource candidate for preview/editing."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    relative_path: str = Field(..., min_length=1, description="Repo-relative path")
    git_state: WorktreeResourceGitState = Field(..., description="Git state")
    resource_kind: str = Field(..., min_length=1, description="Resource kind")
    materialization: WorktreeResourceMaterialization = Field(
        ...,
        description="Default or selected materialization",
    )
    warning_codes: list[str] = Field(
        default_factory=list,
        description="Machine-readable warning identifiers",
    )
    warning_text: str | None = Field(None, description="Human-readable warning")
    is_directory: bool = Field(
        default=False, description="Whether the candidate is a directory"
    )

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, raw_relative_path_str: str) -> str:
        """Validate and normalize one preview candidate path.

        Args:
            raw_relative_path_str: Raw repo-relative path value.

        Returns:
            str: Normalized POSIX repo-relative path.

        Raises:
            ValueError: Raised when the path is unsafe.
        """

        return _normalize_safe_repo_relative_path(raw_relative_path_str)


class WorktreeResourceCandidateListSchema(BaseModel):
    """Preview response containing resource candidates for one repo."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    repo_path: str = Field(..., description="Absolute repository path")
    is_policy_ready: bool = Field(
        ...,
        description="Whether the saved policy is ready for task start",
    )
    policy_note: str | None = Field(None, description="Policy status note")
    candidates: list[WorktreeResourceCandidateSchema] = Field(
        default_factory=list,
        description="Candidate list",
    )


class WorktreeResourcePreviewRequestSchema(BaseModel):
    """Request schema for repo preview scans."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    repo_path: str = Field(..., min_length=1, description="Absolute repository path")
    draft_policy: ProjectWorktreeResourcePolicySchema | None = Field(
        None,
        description="Optional draft policy to overlay during preview",
    )
