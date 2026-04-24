"""Application use cases for PRD source selection and import."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.dsl.prd_sources.application.ports import (
    PrdSourceRepositoryPort,
    TaskWorkflowPort,
)
from backend.dsl.prd_sources.domain.errors import InvalidPrdContentError
from backend.dsl.prd_sources.domain.models import (
    PendingPrdCandidate,
    PrdSourceType,
    PrdStagingOutcome,
)
from backend.dsl.prd_sources.domain.policies import (
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
        task_context = self.task_workflow_port.resolve_task_context(task_id_str)
        return self.prd_source_repository.list_pending_prd_candidates(
            task_context.workspace_dir_path,
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
        task_context = self.task_workflow_port.prepare_prd_workspace(task_id_str)
        pending_prd_markdown_text = (
            self.prd_source_repository.read_pending_prd_markdown(
                task_context.workspace_dir_path,
                normalized_pending_relative_path_str,
            )
        )
        validate_prd_markdown_text(pending_prd_markdown_text)
        target_prd_file_name_str = build_task_prd_file_name(
            task_id_str=task_context.task_id_str,
            task_title_str=task_context.task_title_str,
            prd_markdown_text=pending_prd_markdown_text,
            reference_datetime=reference_datetime,
        )

        self.prd_source_repository.ensure_task_prd_absent(
            task_context.workspace_dir_path,
            task_context.task_id_str,
        )
        staged_prd_document = self.prd_source_repository.move_pending_prd_to_tasks_root(
            task_context.workspace_dir_path,
            normalized_pending_relative_path_str,
            target_prd_file_name_str,
        )
        auto_started_implementation_bool = self.task_workflow_port.mark_prd_ready(
            task_context,
            staged_prd_document,
        )
        return PrdStagingOutcome(
            task_id_str=task_context.task_id_str,
            source_type=PrdSourceType.PENDING,
            staged_relative_path_str=staged_prd_document.relative_path_str,
            auto_started_implementation_bool=auto_started_implementation_bool,
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
