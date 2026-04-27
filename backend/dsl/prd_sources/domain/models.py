"""Pure domain models for PRD source staging."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


class PrdSourceType(str, Enum):
    """Supported sources for making a task PRD ready."""

    AI_GENERATED = "ai_generated"
    PENDING = "pending"
    MANUAL_IMPORT = "manual_import"


@dataclass(frozen=True, slots=True)
class PendingPrdCandidate:
    """A pending Markdown PRD that can be selected for a task.

    Attributes:
        file_name_str: Display filename.
        relative_path_str: Workspace-relative path such as
            ``tasks/pending/example.md``.
        size_bytes_int: File size in bytes.
        updated_at: Last modification time.
        title_preview_text: Optional heading or metadata preview.
    """

    file_name_str: str
    relative_path_str: str
    size_bytes_int: int
    updated_at: datetime
    title_preview_text: str | None = None


@dataclass(frozen=True, slots=True)
class PrdTasklessSourceContext:
    """Workspace context used before a task exists.

    Attributes:
        run_account_id_str: Active run account UUID string.
        project_id_str: Optional project UUID string selected by the user.
        workspace_dir_path: Workspace that contains selectable PRDs.
    """

    run_account_id_str: str
    project_id_str: str | None
    workspace_dir_path: Path


@dataclass(frozen=True, slots=True)
class PrdTaskDraftTextSuggestion:
    """Suggested task fields extracted from a PRD.

    Attributes:
        task_title_str: Suggested task title.
        requirement_brief_str: Suggested requirement description.
    """

    task_title_str: str
    requirement_brief_str: str


@dataclass(frozen=True, slots=True)
class PrdTaskDraftSuggestion:
    """Task draft returned before creating a real task.

    Attributes:
        source_type: PRD source type used to build the draft.
        suggested_task_title_str: Suggested task title.
        suggested_requirement_brief_str: Suggested task description.
        source_file_name_str: Optional source filename.
        source_relative_path_str: Optional workspace-relative source path.
        source_updated_at: Optional source file update timestamp.
    """

    source_type: PrdSourceType
    suggested_task_title_str: str
    suggested_requirement_brief_str: str
    source_file_name_str: str | None = None
    source_relative_path_str: str | None = None
    source_updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StagedPrdDocument:
    """A PRD document staged into the task `tasks/` root.

    Attributes:
        file_name_str: Staged PRD filename.
        relative_path_str: Workspace-relative PRD path.
        absolute_path: Absolute path on disk.
        source_type: Source used to stage the PRD.
    """

    file_name_str: str
    relative_path_str: str
    absolute_path: Path
    source_type: PrdSourceType


@dataclass(frozen=True, slots=True)
class PrdTaskContext:
    """Task data needed by PRD source use cases.

    Attributes:
        task_id_str: Task UUID string.
        run_account_id_str: Run account UUID string.
        task_title_str: Task title.
        workspace_dir_path: Effective workspace directory.
        worktree_path_str: Optional task worktree path.
        auto_confirm_prd_and_execute_bool: Whether PRD-ready should start coding.
    """

    task_id_str: str
    run_account_id_str: str
    task_title_str: str
    workspace_dir_path: Path
    worktree_path_str: str | None
    auto_confirm_prd_and_execute_bool: bool


@dataclass(frozen=True, slots=True)
class PrdStagingOutcome:
    """Result of selecting or importing a PRD.

    Attributes:
        task_id_str: Task UUID string.
        source_type: Source used to stage the PRD.
        staged_relative_path_str: Workspace-relative staged PRD path.
        auto_started_implementation_bool: Whether implementation was scheduled.
    """

    task_id_str: str
    source_type: PrdSourceType
    staged_relative_path_str: str
    auto_started_implementation_bool: bool
