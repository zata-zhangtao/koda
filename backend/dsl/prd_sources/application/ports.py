"""Application ports for PRD source use cases."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from backend.dsl.prd_sources.domain.models import (
    PendingPrdCandidate,
    PrdTaskContext,
    StagedPrdDocument,
)


class PrdSourceRepositoryPort(Protocol):
    """Port for listing, reading, moving, and importing PRD files."""

    def list_pending_prd_candidates(
        self,
        workspace_dir_path: Path,
    ) -> list[PendingPrdCandidate]:
        """List pending Markdown PRDs in a workspace."""

    def read_pending_prd_markdown(
        self,
        workspace_dir_path: Path,
        pending_relative_path_str: str,
    ) -> str:
        """Read a pending PRD as UTF-8 Markdown."""

    def ensure_task_prd_absent(
        self,
        workspace_dir_path: Path,
        task_id_str: str,
    ) -> None:
        """Raise when the task already has a staged PRD."""

    def move_pending_prd_to_tasks_root(
        self,
        workspace_dir_path: Path,
        pending_relative_path_str: str,
        target_file_name_str: str,
    ) -> StagedPrdDocument:
        """Move a pending PRD into the workspace `tasks/` root."""

    def stage_pending_prd_to_tasks_root(
        self,
        source_workspace_dir_path: Path,
        target_workspace_dir_path: Path,
        pending_relative_path_str: str,
        target_file_name_str: str,
        pending_prd_markdown_text: str,
    ) -> StagedPrdDocument:
        """Stage a pending PRD from one workspace into another workspace root."""

    def import_prd_to_tasks_root(
        self,
        workspace_dir_path: Path,
        target_file_name_str: str,
        prd_markdown_text: str,
    ) -> StagedPrdDocument:
        """Write imported PRD Markdown into the workspace `tasks/` root."""


class TaskWorkflowPort(Protocol):
    """Port for task workspace and workflow transitions."""

    def resolve_task_context(self, task_id_str: str) -> PrdTaskContext:
        """Resolve task metadata and its effective workspace."""

    def resolve_pending_source_context(self, task_id_str: str) -> PrdTaskContext:
        """Resolve task metadata and the workspace that lists pending templates."""

    def prepare_prd_workspace(self, task_id_str: str) -> PrdTaskContext:
        """Prepare the workspace needed for staging a PRD."""

    def mark_prd_ready(
        self,
        task_context: PrdTaskContext,
        staged_prd_document: StagedPrdDocument,
    ) -> bool:
        """Mark a staged PRD ready and return whether implementation started."""
