"""Domain models for remote requirement collaboration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


REMOTE_REQUIREMENT_MANIFEST_SCHEMA_VERSION = 1
REMOTE_REQUIREMENT_MANIFEST_ROOT = ".koda/requirements"
REMOTE_REQUIREMENT_SYNC_STATUS_CREATED = "created"
REMOTE_REQUIREMENT_SYNC_STATUS_PUSHED = "pushed"
REMOTE_REQUIREMENT_SYNC_STATUS_IMPORTED = "imported"
REMOTE_REQUIREMENT_SYNC_STATUS_CONFLICT = "conflict"
REMOTE_REQUIREMENT_SYNC_STATUS_FAILED = "failed"
REMOTE_REQUIREMENT_SYNC_STATUS_PR_OPEN = "pr_open"
REMOTE_REQUIREMENT_SYNC_STATUS_PR_MERGED = "pr_merged"


class RemoteRequirementError(ValueError):
    """Base error for remote requirement collaboration failures."""


class RemoteRequirementConflictError(RemoteRequirementError):
    """Raised when a remote branch advanced beyond the local sync cursor."""


class RemoteRequirementManifest(BaseModel):
    """Stable JSON manifest stored on remote task branches.

    Attributes:
        schema_version: Manifest schema version.
        task_id: Koda task UUID.
        task_title: Requirement title.
        requirement_brief: Requirement brief text.
        workflow_stage: Current workflow stage value.
        lifecycle_status: Current lifecycle status value.
        task_branch_name: Branch that owns this requirement.
        worktree_base_branch_name: Base branch used for worktree and PR target.
        repo_remote_url: Normalized repository remote URL recorded by Koda.
        prd_relative_path: Workspace-relative PRD path when known.
        github_pr_url: Associated GitHub PR URL when created.
        github_pr_number: Associated GitHub PR number when created.
        github_pr_state: Associated GitHub PR state.
        last_progress_pushed_at: Last progress-push timestamp.
        created_at: Task creation timestamp.
        updated_at: Manifest update timestamp.
        closed_at: Task close timestamp.
    """

    model_config = ConfigDict(extra="ignore")

    schema_version: int = Field(default=REMOTE_REQUIREMENT_MANIFEST_SCHEMA_VERSION)
    task_id: str
    task_title: str
    requirement_brief: str | None = None
    workflow_stage: str
    lifecycle_status: str
    task_branch_name: str
    worktree_base_branch_name: str
    repo_remote_url: str | None = None
    prd_relative_path: str | None = None
    github_pr_url: str | None = None
    github_pr_number: int | None = None
    github_pr_state: str | None = None
    last_progress_pushed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RemoteRequirementBranchManifest:
    """A manifest read from one remote branch.

    Attributes:
        branch_name_str: Remote task branch name without the remote prefix.
        manifest_relative_path_str: Manifest path inside the repository.
        commit_hash_str: Remote branch commit hash used for this projection.
        manifest: Parsed remote requirement manifest.
    """

    branch_name_str: str
    manifest_relative_path_str: str
    commit_hash_str: str
    manifest: RemoteRequirementManifest


@dataclass(frozen=True, slots=True)
class RemoteRequirementSyncOutcome:
    """Summary of a project-level remote requirement sync.

    Attributes:
        imported_count: Number of local Task rows created from remote manifests.
        updated_count: Number of existing Task rows updated from remote manifests.
        skipped_count: Number of invalid or conflicting manifests skipped.
    """

    imported_count: int
    updated_count: int
    skipped_count: int


@dataclass(frozen=True, slots=True)
class PullRequestMetadata:
    """GitHub pull request metadata projected onto a task.

    Attributes:
        number: Pull request number.
        url: Browser URL for the pull request.
        state: Provider state such as ``open``, ``closed`` or ``merged``.
        merged: Whether the pull request has been merged.
    """

    number: int
    url: str
    state: str
    merged: bool = False
