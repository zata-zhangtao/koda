"""Application use cases for PRD source selection and import."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.dsl.prd_sources.application.ports import (
    PrdTaskDraftSuggestionPort,
    PrdSourceRepositoryPort,
    TaskWorkflowPort,
)
from backend.dsl.prd_sources.domain.errors import (
    InvalidTaskDraftError,
    InvalidPrdContentError,
    PendingPrdNotFoundError,
    StalePendingPrdError,
)
from backend.dsl.prd_sources.domain.models import (
    PendingPrdCandidate,
    PrdTaskDraftSuggestion,
    PrdTaskDraftTextSuggestion,
    PrdSourceType,
    PrdStagingOutcome,
)
from backend.dsl.prd_sources.domain.policies import (
    build_task_draft_requirement_brief_from_prd,
    build_task_draft_title_from_prd,
    build_task_prd_file_name,
    validate_imported_prd_file,
    validate_pending_prd_relative_path,
    validate_prd_markdown_text,
)


@dataclass(frozen=True, slots=True)
class ListPendingPrdFilesUseCase:
    """List selectable PRDs from a task workspace."""

    task_workflow_port: TaskWorkflowPort
    prd_source_repository: PrdSourceRepositoryPort

    def execute(self, task_id_str: str) -> list[PendingPrdCandidate]:
        """List pending PRD candidates for a task.

        Args:
            task_id_str: Task UUID string.

        Returns:
            list[PendingPrdCandidate]: Pending PRD files.
        """
        task_context = self.task_workflow_port.resolve_pending_source_context(
            task_id_str
        )
        return self.prd_source_repository.list_pending_prd_candidates(
            task_context.workspace_dir_path,
        )


@dataclass(frozen=True, slots=True)
class ListTasklessPendingPrdFilesUseCase:
    """List selectable PRDs before a task has been created."""

    task_workflow_port: TaskWorkflowPort
    prd_source_repository: PrdSourceRepositoryPort

    def execute(self, project_id_str: str | None) -> list[PendingPrdCandidate]:
        """List pending PRD candidates for a project/default workspace.

        Args:
            project_id_str: Optional project UUID string.

        Returns:
            list[PendingPrdCandidate]: Pending PRD files.
        """
        source_context = (
            self.task_workflow_port.resolve_taskless_pending_source_context(
                project_id_str
            )
        )
        return self.prd_source_repository.list_pending_prd_candidates(
            source_context.workspace_dir_path,
        )


@dataclass(frozen=True, slots=True)
class BuildPrdTaskDraftUseCase:
    """Build a task draft from selected or imported PRD Markdown."""

    task_workflow_port: TaskWorkflowPort
    prd_source_repository: PrdSourceRepositoryPort
    task_draft_suggestion_port: PrdTaskDraftSuggestionPort | None = None

    def execute_pending(
        self,
        *,
        project_id_str: str | None,
        pending_relative_path_str: str,
    ) -> PrdTaskDraftSuggestion:
        """Build a task draft from a pending PRD.

        Args:
            project_id_str: Optional project UUID string.
            pending_relative_path_str: Workspace-relative pending PRD path.

        Returns:
            PrdTaskDraftSuggestion: Suggested task fields and source metadata.
        """
        normalized_pending_relative_path_str = validate_pending_prd_relative_path(
            pending_relative_path_str
        )
        source_context = (
            self.task_workflow_port.resolve_taskless_pending_source_context(
                project_id_str
            )
        )
        pending_prd_candidate = _find_pending_prd_candidate(
            self.prd_source_repository.list_pending_prd_candidates(
                source_context.workspace_dir_path,
            ),
            normalized_pending_relative_path_str,
        )
        pending_prd_markdown_text = (
            self.prd_source_repository.read_pending_prd_markdown(
                source_context.workspace_dir_path,
                normalized_pending_relative_path_str,
            )
        )
        text_suggestion = self._build_text_suggestion(
            prd_markdown_text=pending_prd_markdown_text,
            source_file_name_str=pending_prd_candidate.file_name_str,
        )
        return PrdTaskDraftSuggestion(
            source_type=PrdSourceType.PENDING,
            suggested_task_title_str=text_suggestion.task_title_str,
            suggested_requirement_brief_str=text_suggestion.requirement_brief_str,
            source_file_name_str=pending_prd_candidate.file_name_str,
            source_relative_path_str=pending_prd_candidate.relative_path_str,
            source_updated_at=pending_prd_candidate.updated_at,
        )

    def execute_imported_file(
        self,
        *,
        original_file_name_str: str,
        raw_prd_file_bytes: bytes,
    ) -> PrdTaskDraftSuggestion:
        """Build a task draft from an uploaded PRD file.

        Args:
            original_file_name_str: Browser-provided filename.
            raw_prd_file_bytes: Uploaded file bytes.

        Returns:
            PrdTaskDraftSuggestion: Suggested task fields.
        """
        prd_markdown_text = _decode_imported_prd_markdown(
            original_file_name_str=original_file_name_str,
            raw_prd_file_bytes=raw_prd_file_bytes,
        )
        text_suggestion = self._build_text_suggestion(
            prd_markdown_text=prd_markdown_text,
            source_file_name_str=original_file_name_str,
        )
        return PrdTaskDraftSuggestion(
            source_type=PrdSourceType.MANUAL_IMPORT,
            suggested_task_title_str=text_suggestion.task_title_str,
            suggested_requirement_brief_str=text_suggestion.requirement_brief_str,
            source_file_name_str=original_file_name_str,
        )

    def execute_pasted_markdown(
        self,
        *,
        original_file_name_str: str,
        prd_markdown_text: str,
    ) -> PrdTaskDraftSuggestion:
        """Build a task draft from pasted PRD Markdown.

        Args:
            original_file_name_str: Logical source filename.
            prd_markdown_text: Pasted PRD Markdown.

        Returns:
            PrdTaskDraftSuggestion: Suggested task fields.
        """
        raw_prd_markdown_bytes = prd_markdown_text.encode("utf-8")
        validate_imported_prd_file(
            original_file_name_str=original_file_name_str,
            raw_file_size_int=len(raw_prd_markdown_bytes),
        )
        validate_prd_markdown_text(prd_markdown_text)
        text_suggestion = self._build_text_suggestion(
            prd_markdown_text=prd_markdown_text,
            source_file_name_str=original_file_name_str,
        )
        return PrdTaskDraftSuggestion(
            source_type=PrdSourceType.MANUAL_IMPORT,
            suggested_task_title_str=text_suggestion.task_title_str,
            suggested_requirement_brief_str=text_suggestion.requirement_brief_str,
            source_file_name_str=original_file_name_str,
        )

    def _build_text_suggestion(
        self,
        *,
        prd_markdown_text: str,
        source_file_name_str: str | None,
    ) -> PrdTaskDraftTextSuggestion:
        """Build AI-provided or deterministic fallback task fields."""
        if self.task_draft_suggestion_port is not None:
            ai_text_suggestion = self.task_draft_suggestion_port.suggest_task_draft(
                prd_markdown_text=prd_markdown_text,
                source_file_name_str=source_file_name_str,
            )
            if _is_valid_text_suggestion(ai_text_suggestion):
                return ai_text_suggestion

        fallback_task_title_str = build_task_draft_title_from_prd(
            prd_markdown_text,
            source_file_name_str=source_file_name_str,
        )
        fallback_requirement_brief_str = build_task_draft_requirement_brief_from_prd(
            prd_markdown_text,
            fallback_title_str=fallback_task_title_str,
        )
        return PrdTaskDraftTextSuggestion(
            task_title_str=fallback_task_title_str,
            requirement_brief_str=fallback_requirement_brief_str,
        )


@dataclass(frozen=True, slots=True)
class SelectPendingPrdUseCase:
    """Move a selected pending PRD into the task PRD root."""

    task_workflow_port: TaskWorkflowPort
    prd_source_repository: PrdSourceRepositoryPort

    def execute(
        self,
        task_id_str: str,
        pending_relative_path_str: str,
        reference_datetime: datetime | None = None,
    ) -> PrdStagingOutcome:
        """Select and stage a pending PRD for a task.

        Args:
            task_id_str: Task UUID string.
            pending_relative_path_str: Workspace-relative pending PRD path.
            reference_datetime: Optional timestamp reference for the staged file.

        Returns:
            PrdStagingOutcome: Staging and workflow transition result.
        """
        normalized_pending_relative_path_str = validate_pending_prd_relative_path(
            pending_relative_path_str
        )
        source_task_context = self.task_workflow_port.resolve_pending_source_context(
            task_id_str
        )
        target_task_context = self.task_workflow_port.prepare_prd_workspace(task_id_str)
        try:
            pending_prd_markdown_text = (
                self.prd_source_repository.read_pending_prd_markdown(
                    target_task_context.workspace_dir_path,
                    normalized_pending_relative_path_str,
                )
            )
        except PendingPrdNotFoundError:
            pending_prd_markdown_text = (
                self.prd_source_repository.read_pending_prd_markdown(
                    source_task_context.workspace_dir_path,
                    normalized_pending_relative_path_str,
                )
            )
        validate_prd_markdown_text(pending_prd_markdown_text)
        target_prd_file_name_str = build_task_prd_file_name(
            task_id_str=target_task_context.task_id_str,
            task_title_str=target_task_context.task_title_str,
            prd_markdown_text=pending_prd_markdown_text,
            reference_datetime=reference_datetime,
        )

        self.prd_source_repository.ensure_task_prd_absent(
            target_task_context.workspace_dir_path,
            target_task_context.task_id_str,
        )
        staged_prd_document = (
            self.prd_source_repository.stage_pending_prd_to_tasks_root(
                source_workspace_dir_path=source_task_context.workspace_dir_path,
                target_workspace_dir_path=target_task_context.workspace_dir_path,
                pending_relative_path_str=normalized_pending_relative_path_str,
                target_file_name_str=target_prd_file_name_str,
                pending_prd_markdown_text=pending_prd_markdown_text,
            )
        )
        auto_started_implementation_bool = self.task_workflow_port.mark_prd_ready(
            target_task_context,
            staged_prd_document,
        )
        return PrdStagingOutcome(
            task_id_str=target_task_context.task_id_str,
            source_type=PrdSourceType.PENDING,
            staged_relative_path_str=staged_prd_document.relative_path_str,
            auto_started_implementation_bool=auto_started_implementation_bool,
        )


@dataclass(frozen=True, slots=True)
class CreateTaskFromPendingPrdUseCase:
    """Create a confirmed task draft and stage a selected pending PRD."""

    task_workflow_port: TaskWorkflowPort
    prd_source_repository: PrdSourceRepositoryPort

    def execute(
        self,
        *,
        task_title_str: str,
        project_id_str: str | None,
        worktree_base_branch_name_str: str,
        requirement_brief_str: str,
        auto_confirm_prd_and_execute_bool: bool,
        pending_relative_path_str: str,
        expected_source_updated_at: datetime,
    ) -> PrdStagingOutcome:
        """Create a task from a pending PRD source.

        Args:
            task_title_str: Confirmed task title.
            project_id_str: Optional project UUID string.
            worktree_base_branch_name_str: Selected worktree base branch.
            requirement_brief_str: Confirmed task description.
            auto_confirm_prd_and_execute_bool: Whether to execute after PRD ready.
            pending_relative_path_str: Workspace-relative pending PRD path.
            expected_source_updated_at: Timestamp captured when the draft was built.

        Returns:
            PrdStagingOutcome: Staging and workflow transition result.
        """
        _validate_confirmed_task_draft(
            task_title_str=task_title_str,
            requirement_brief_str=requirement_brief_str,
        )
        normalized_pending_relative_path_str = validate_pending_prd_relative_path(
            pending_relative_path_str
        )
        source_context = (
            self.task_workflow_port.resolve_taskless_pending_source_context(
                project_id_str
            )
        )
        pending_prd_candidate = _find_pending_prd_candidate(
            self.prd_source_repository.list_pending_prd_candidates(
                source_context.workspace_dir_path,
            ),
            normalized_pending_relative_path_str,
        )
        if pending_prd_candidate.updated_at != expected_source_updated_at:
            raise StalePendingPrdError(
                "Pending PRD changed after the task draft was generated. Refresh the draft and try again."
            )

        created_task_id_str = self.task_workflow_port.create_task_from_prd_draft(
            task_title_str=task_title_str,
            project_id_str=project_id_str,
            worktree_base_branch_name_str=worktree_base_branch_name_str,
            requirement_brief_str=requirement_brief_str,
            auto_confirm_prd_and_execute_bool=auto_confirm_prd_and_execute_bool,
        )
        select_pending_use_case = SelectPendingPrdUseCase(
            task_workflow_port=self.task_workflow_port,
            prd_source_repository=self.prd_source_repository,
        )
        return select_pending_use_case.execute(
            created_task_id_str,
            normalized_pending_relative_path_str,
        )


@dataclass(frozen=True, slots=True)
class ImportPrdUseCase:
    """Import uploaded PRD Markdown into the task PRD root."""

    task_workflow_port: TaskWorkflowPort
    prd_source_repository: PrdSourceRepositoryPort

    def execute(
        self,
        task_id_str: str,
        original_file_name_str: str,
        raw_prd_file_bytes: bytes,
        reference_datetime: datetime | None = None,
    ) -> PrdStagingOutcome:
        """Import and stage an uploaded PRD for a task.

        Args:
            task_id_str: Task UUID string.
            original_file_name_str: Browser-provided filename.
            raw_prd_file_bytes: Uploaded file bytes.
            reference_datetime: Optional timestamp reference for the staged file.

        Returns:
            PrdStagingOutcome: Staging and workflow transition result.

        Raises:
            InvalidPrdContentError: If the file cannot be decoded as UTF-8.
        """
        validate_imported_prd_file(
            original_file_name_str=original_file_name_str,
            raw_file_size_int=len(raw_prd_file_bytes),
        )
        try:
            prd_markdown_text = raw_prd_file_bytes.decode("utf-8")
        except UnicodeDecodeError as unicode_decode_error:
            raise InvalidPrdContentError(
                "PRD file must be encoded as UTF-8 Markdown."
            ) from unicode_decode_error

        return self._stage_imported_prd_markdown(
            task_id_str=task_id_str,
            prd_markdown_text=prd_markdown_text,
            reference_datetime=reference_datetime,
        )

    def execute_pasted_markdown(
        self,
        task_id_str: str,
        original_file_name_str: str,
        prd_markdown_text: str,
        reference_datetime: datetime | None = None,
    ) -> PrdStagingOutcome:
        """Import pasted PRD Markdown into the task PRD root.

        Args:
            task_id_str: Task UUID string.
            original_file_name_str: Logical source filename for validation.
            prd_markdown_text: Markdown content pasted by the user.
            reference_datetime: Optional timestamp reference for the staged file.

        Returns:
            PrdStagingOutcome: Staging and workflow transition result.
        """
        raw_prd_markdown_bytes = prd_markdown_text.encode("utf-8")
        validate_imported_prd_file(
            original_file_name_str=original_file_name_str,
            raw_file_size_int=len(raw_prd_markdown_bytes),
        )
        return self._stage_imported_prd_markdown(
            task_id_str=task_id_str,
            prd_markdown_text=prd_markdown_text,
            reference_datetime=reference_datetime,
        )

    def _stage_imported_prd_markdown(
        self,
        *,
        task_id_str: str,
        prd_markdown_text: str,
        reference_datetime: datetime | None = None,
    ) -> PrdStagingOutcome:
        """Stage validated manual PRD Markdown and advance the workflow."""
        validate_prd_markdown_text(prd_markdown_text)
        task_context = self.task_workflow_port.prepare_prd_workspace(task_id_str)
        target_prd_file_name_str = build_task_prd_file_name(
            task_id_str=task_context.task_id_str,
            task_title_str=task_context.task_title_str,
            prd_markdown_text=prd_markdown_text,
            reference_datetime=reference_datetime,
        )

        self.prd_source_repository.ensure_task_prd_absent(
            task_context.workspace_dir_path,
            task_context.task_id_str,
        )
        staged_prd_document = self.prd_source_repository.import_prd_to_tasks_root(
            task_context.workspace_dir_path,
            target_prd_file_name_str,
            prd_markdown_text,
        )
        auto_started_implementation_bool = self.task_workflow_port.mark_prd_ready(
            task_context,
            staged_prd_document,
        )
        return PrdStagingOutcome(
            task_id_str=task_context.task_id_str,
            source_type=PrdSourceType.MANUAL_IMPORT,
            staged_relative_path_str=staged_prd_document.relative_path_str,
            auto_started_implementation_bool=auto_started_implementation_bool,
        )


@dataclass(frozen=True, slots=True)
class CreateTaskFromImportedPrdUseCase:
    """Create a confirmed task draft and stage imported PRD Markdown."""

    task_workflow_port: TaskWorkflowPort
    prd_source_repository: PrdSourceRepositoryPort

    def execute_uploaded_file(
        self,
        *,
        task_title_str: str,
        project_id_str: str | None,
        worktree_base_branch_name_str: str,
        requirement_brief_str: str,
        auto_confirm_prd_and_execute_bool: bool,
        original_file_name_str: str,
        raw_prd_file_bytes: bytes,
    ) -> PrdStagingOutcome:
        """Create a task and import an uploaded PRD file.

        Args:
            task_title_str: Confirmed task title.
            project_id_str: Optional project UUID string.
            worktree_base_branch_name_str: Selected worktree base branch.
            requirement_brief_str: Confirmed task description.
            auto_confirm_prd_and_execute_bool: Whether to execute after PRD ready.
            original_file_name_str: Uploaded filename.
            raw_prd_file_bytes: Uploaded file bytes.

        Returns:
            PrdStagingOutcome: Staging and workflow transition result.
        """
        _validate_confirmed_task_draft(
            task_title_str=task_title_str,
            requirement_brief_str=requirement_brief_str,
        )
        _decode_imported_prd_markdown(
            original_file_name_str=original_file_name_str,
            raw_prd_file_bytes=raw_prd_file_bytes,
        )
        created_task_id_str = self.task_workflow_port.create_task_from_prd_draft(
            task_title_str=task_title_str,
            project_id_str=project_id_str,
            worktree_base_branch_name_str=worktree_base_branch_name_str,
            requirement_brief_str=requirement_brief_str,
            auto_confirm_prd_and_execute_bool=auto_confirm_prd_and_execute_bool,
        )
        import_prd_use_case = ImportPrdUseCase(
            task_workflow_port=self.task_workflow_port,
            prd_source_repository=self.prd_source_repository,
        )
        return import_prd_use_case.execute(
            task_id_str=created_task_id_str,
            original_file_name_str=original_file_name_str,
            raw_prd_file_bytes=raw_prd_file_bytes,
        )

    def execute_pasted_markdown(
        self,
        *,
        task_title_str: str,
        project_id_str: str | None,
        worktree_base_branch_name_str: str,
        requirement_brief_str: str,
        auto_confirm_prd_and_execute_bool: bool,
        original_file_name_str: str,
        prd_markdown_text: str,
    ) -> PrdStagingOutcome:
        """Create a task and import pasted PRD Markdown.

        Args:
            task_title_str: Confirmed task title.
            project_id_str: Optional project UUID string.
            worktree_base_branch_name_str: Selected worktree base branch.
            requirement_brief_str: Confirmed task description.
            auto_confirm_prd_and_execute_bool: Whether to execute after PRD ready.
            original_file_name_str: Logical source filename.
            prd_markdown_text: Pasted PRD Markdown.

        Returns:
            PrdStagingOutcome: Staging and workflow transition result.
        """
        _validate_confirmed_task_draft(
            task_title_str=task_title_str,
            requirement_brief_str=requirement_brief_str,
        )
        raw_prd_markdown_bytes = prd_markdown_text.encode("utf-8")
        validate_imported_prd_file(
            original_file_name_str=original_file_name_str,
            raw_file_size_int=len(raw_prd_markdown_bytes),
        )
        validate_prd_markdown_text(prd_markdown_text)
        created_task_id_str = self.task_workflow_port.create_task_from_prd_draft(
            task_title_str=task_title_str,
            project_id_str=project_id_str,
            worktree_base_branch_name_str=worktree_base_branch_name_str,
            requirement_brief_str=requirement_brief_str,
            auto_confirm_prd_and_execute_bool=auto_confirm_prd_and_execute_bool,
        )
        import_prd_use_case = ImportPrdUseCase(
            task_workflow_port=self.task_workflow_port,
            prd_source_repository=self.prd_source_repository,
        )
        return import_prd_use_case.execute_pasted_markdown(
            task_id_str=created_task_id_str,
            original_file_name_str=original_file_name_str,
            prd_markdown_text=prd_markdown_text,
        )


def _find_pending_prd_candidate(
    pending_prd_candidate_list: list[PendingPrdCandidate],
    pending_relative_path_str: str,
) -> PendingPrdCandidate:
    """Find a pending candidate by relative path or raise."""
    for pending_prd_candidate in pending_prd_candidate_list:
        if pending_prd_candidate.relative_path_str == pending_relative_path_str:
            return pending_prd_candidate
    raise PendingPrdNotFoundError("Pending PRD file was not found.")


def _decode_imported_prd_markdown(
    *,
    original_file_name_str: str,
    raw_prd_file_bytes: bytes,
) -> str:
    """Validate and decode uploaded PRD Markdown."""
    validate_imported_prd_file(
        original_file_name_str=original_file_name_str,
        raw_file_size_int=len(raw_prd_file_bytes),
    )
    try:
        prd_markdown_text = raw_prd_file_bytes.decode("utf-8")
    except UnicodeDecodeError as unicode_decode_error:
        raise InvalidPrdContentError(
            "PRD file must be encoded as UTF-8 Markdown."
        ) from unicode_decode_error
    validate_prd_markdown_text(prd_markdown_text)
    return prd_markdown_text


def _validate_confirmed_task_draft(
    *,
    task_title_str: str,
    requirement_brief_str: str,
) -> None:
    """Validate task fields that must be confirmed before creation."""
    if not task_title_str.strip():
        raise InvalidTaskDraftError("Task title is required.")
    if not requirement_brief_str.strip():
        raise InvalidTaskDraftError("Task description is required.")


def _is_valid_text_suggestion(
    text_suggestion: PrdTaskDraftTextSuggestion | None,
) -> bool:
    """Return whether an AI suggestion contains the required fields."""
    if text_suggestion is None:
        return False
    return bool(
        text_suggestion.task_title_str.strip()
        and text_suggestion.requirement_brief_str.strip()
    )
