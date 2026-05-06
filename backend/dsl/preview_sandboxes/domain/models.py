"""Pure domain models for managed preview sandboxes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class PreviewApplicability(str, Enum):
    """Whether a task worktree should get an automatic preview."""

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNCERTAIN = "uncertain"


class PreviewRuntimeKind(str, Enum):
    """Runtime family selected for the preview command."""

    NODE = "node"
    PYTHON = "python"
    STATIC = "static"
    UNKNOWN = "unknown"


class PreviewStatus(str, Enum):
    """Task-scoped preview status exposed to the UI."""

    DISABLED = "disabled"
    NOT_STARTED = "not_started"
    GENERATING_PROFILE = "generating_profile"
    NOT_APPLICABLE = "not_applicable"
    UNCERTAIN = "uncertain"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"
    NEEDS_HUMAN_ACTION = "needs_human_action"
    STOPPED = "stopped"
    RUNTIME_STATE_LOST = "runtime_state_lost"


class PreviewFailureKind(str, Enum):
    """Failure category for failed preview startup."""

    CODE_ERROR = "code_error"
    DEPENDENCY_ERROR = "dependency_error"
    ENVIRONMENT_ERROR = "environment_error"
    SANDBOX_ERROR = "sandbox_error"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PreviewProfileFingerprint:
    """Revision fingerprint that scopes a preview profile to task content."""

    git_head: str | None = None
    dirty_diff_hash: str | None = None


@dataclass(frozen=True, slots=True)
class PreviewProfile:
    """Validated startup contract generated for a task worktree."""

    schema_version: int
    applicability: PreviewApplicability
    applicability_reason: str
    runtime_kind: PreviewRuntimeKind
    working_directory: str | None
    dependency_commands: tuple[str, ...]
    start_command: str | None
    internal_port: int | None
    healthcheck_path: str | None
    preview_path: str | None
    readiness_timeout_seconds: int
    notes: str | None = None
    profile_fingerprint: PreviewProfileFingerprint = field(
        default_factory=PreviewProfileFingerprint,
    )


@dataclass(frozen=True, slots=True)
class PreviewRuntimeHandle:
    """Machine-local preview runtime handle."""

    task_id: str
    container_id: str | None
    host_port: int | None
    internal_port: int | None
    preview_url: str | None
    log_tail: str | None = None


@dataclass(frozen=True, slots=True)
class PreviewStatusSnapshot:
    """Current task-scoped preview state returned by use cases and APIs."""

    task_id: str
    status: PreviewStatus
    applicability: PreviewApplicability | None = None
    preview_url: str | None = None
    profile_summary: str | None = None
    failure_kind: PreviewFailureKind | None = None
    failure_summary: str | None = None
    bypass_confirmed: bool = False
    log_tail: str | None = None
    container_id: str | None = None
    host_port: int | None = None
    internal_port: int | None = None
    started_at: datetime | None = None
