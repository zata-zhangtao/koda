"""Task workflow adapter for PRD source use cases."""

from __future__ import annotations

from pathlib import Path

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from backend.dsl.models.enums import TaskLifecycleStatus, WorkflowStage
from backend.dsl.models.project import Project
from backend.dsl.models.task import Task
from backend.dsl.prd_sources.domain.errors import (
    InvalidTaskStageError,
    TaskAutomationRunningError,
    TaskNotFoundError,
)
from backend.dsl.prd_sources.domain.models import PrdTaskContext, StagedPrdDocument
from backend.dsl.services.automation_runner import (
    is_task_automation_running,
    register_task_background_activity,
    run_task_implementation,
)
from backend.dsl.services.task_service import TaskService
from utils.settings import config

_ALLOWED_PRD_STAGING_STAGE_SET = {
    WorkflowStage.BACKLOG,
    WorkflowStage.PRD_GENERATING,
    WorkflowStage.PRD_WAITING_CONFIRMATION,
    WorkflowStage.CHANGES_REQUESTED,
}


class SqlAlchemyTaskWorkflowAdapter:
    """SQLAlchemy-backed task workflow adapter for PRD source use cases."""

    def __init__(
        self,
        db_session: Session,
        background_tasks: BackgroundTasks | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            db_session: SQLAlchemy database session.
            background_tasks: Optional FastAPI background task container.
        """
        self._db_session = db_session
        self._background_tasks = background_tasks

    def resolve_task_context(self, task_id_str: str) -> PrdTaskContext:
        """Resolve task metadata and its effective workspace.

        Args:
            task_id_str: Task UUID string.

        Returns:
            PrdTaskContext: Task context.
        """
        task_obj = self._get_task_or_raise(task_id_str)
        workspace_dir_path = self._resolve_effective_work_dir_path(task_obj)
        return self._build_context(task_obj, workspace_dir_path)

    def resolve_pending_source_context(self, task_id_str: str) -> PrdTaskContext:
        """Resolve the workspace that lists selectable pending PRD templates.

        Project-linked tasks list pending templates from the project repository,
        even after a task worktree exists. Staging still happens inside the
        task worktree.

        Args:
            task_id_str: Task UUID string.

        Returns:
            PrdTaskContext: Task context with pending template workspace.
        """
        task_obj = self._get_task_or_raise(task_id_str)
        workspace_dir_path = self._resolve_pending_source_work_dir_path(task_obj)
        return self._build_context(task_obj, workspace_dir_path)

    def prepare_prd_workspace(self, task_id_str: str) -> PrdTaskContext:
        """Prepare a task workspace without starting PRD generation.

        Args:
            task_id_str: Task UUID string.

        Returns:
            PrdTaskContext: Prepared task context.
        """
        if is_task_automation_running(task_id_str):
            raise TaskAutomationRunningError(
                "Task automation is already running for this task."
            )

        task_obj = self._get_task_or_raise(task_id_str)
        if task_obj.lifecycle_status in {
            TaskLifecycleStatus.DELETED,
            TaskLifecycleStatus.ABANDONED,
        }:
            raise InvalidTaskStageError("Deleted or abandoned tasks cannot stage PRDs.")
        if task_obj.workflow_stage not in _ALLOWED_PRD_STAGING_STAGE_SET:
            raise InvalidTaskStageError(
                f"Task {task_id_str[:8]}... cannot stage PRD from stage "
                f"'{task_obj.workflow_stage.value}'."
            )

        TaskService._ensure_task_worktree_if_needed(self._db_session, task_obj)
        task_obj.lifecycle_status = TaskLifecycleStatus.OPEN
        TaskService._clear_business_sync_restore_markers(task_obj)
        self._db_session.commit()
        self._db_session.refresh(task_obj)

        workspace_dir_path = self._resolve_effective_work_dir_path(task_obj)
        return self._build_context(task_obj, workspace_dir_path)

    def mark_prd_ready(
        self,
        task_context: PrdTaskContext,
        staged_prd_document: StagedPrdDocument,
    ) -> bool:
        """Mark a staged PRD ready and optionally schedule implementation.

        Args:
            task_context: Task context captured before staging.
            staged_prd_document: PRD staged by a repository.

        Returns:
            bool: Whether implementation was scheduled.
        """
        task_obj = self._get_task_or_raise(task_context.task_id_str)
        TaskService._apply_workflow_stage_transition(
            task_obj,
            WorkflowStage.PRD_WAITING_CONFIRMATION,
        )
        task_obj.lifecycle_status = TaskLifecycleStatus.OPEN
        TaskService._clear_business_sync_restore_markers(task_obj)
        self._db_session.commit()
        self._db_session.refresh(task_obj)

        if not bool(task_obj.auto_confirm_prd_and_execute):
            return False

        executed_task_obj = TaskService.execute_task(
            self._db_session,
            task_context.task_id_str,
        )
        if executed_task_obj is None:
            raise TaskNotFoundError(f"Task {task_context.task_id_str} was not found.")

        self._schedule_implementation(executed_task_obj)
        return True

    def get_task_for_response(self, task_id_str: str) -> Task:
        """Load a task object after use-case execution.

        Args:
            task_id_str: Task UUID string.

        Returns:
            Task: ORM task object.
        """
        return self._get_task_or_raise(task_id_str)

    def _get_task_or_raise(self, task_id_str: str) -> Task:
        """Return a task or raise a domain error."""
        task_obj = TaskService.get_task_by_id(self._db_session, task_id_str)
        if task_obj is None:
            raise TaskNotFoundError(f"Task with id {task_id_str} not found.")
        return task_obj

    def _resolve_effective_work_dir_path(self, task_obj: Task) -> Path:
        """Resolve the workspace used for PRD file operations."""
        if task_obj.worktree_path:
            worktree_dir_path = Path(task_obj.worktree_path)
            if worktree_dir_path.exists():
                return worktree_dir_path

        project_repo_path = self._resolve_project_repo_path(task_obj)
        if project_repo_path is not None:
            return project_repo_path

        return config.BASE_DIR

    def _resolve_pending_source_work_dir_path(self, task_obj: Task) -> Path:
        """Resolve the workspace that contains selectable pending PRDs."""
        project_repo_path = self._resolve_project_repo_path(task_obj)
        if project_repo_path is not None:
            return project_repo_path
        return self._resolve_effective_work_dir_path(task_obj)

    def _resolve_project_repo_path(self, task_obj: Task) -> Path | None:
        """Resolve a linked project's repository path when available."""
        if not task_obj.project_id:
            return None

        project_obj = (
            self._db_session.query(Project)
            .filter(Project.id == task_obj.project_id)
            .first()
        )
        if project_obj is None:
            return None

        project_repo_path = Path(project_obj.repo_path)
        if not project_repo_path.exists():
            return None
        return project_repo_path

    def _build_context(
        self, task_obj: Task, workspace_dir_path: Path
    ) -> PrdTaskContext:
        """Build a pure task context object from an ORM task."""
        return PrdTaskContext(
            task_id_str=task_obj.id,
            run_account_id_str=task_obj.run_account_id,
            task_title_str=task_obj.task_title,
            workspace_dir_path=workspace_dir_path,
            worktree_path_str=task_obj.worktree_path,
            auto_confirm_prd_and_execute_bool=bool(
                task_obj.auto_confirm_prd_and_execute
            ),
        )

    def _schedule_implementation(self, task_obj: Task) -> None:
        """Schedule implementation automation for an auto-confirm task."""
        register_task_background_activity(task_obj.id)
        if self._background_tasks is None:
            return

        self._background_tasks.add_task(
            run_task_implementation,
            task_id_str=task_obj.id,
            run_account_id_str=task_obj.run_account_id,
            task_title_str=task_obj.task_title,
            dev_log_text_list=self._build_task_context_snapshot_list(task_obj),
            work_dir_path=self._resolve_effective_work_dir_path(task_obj),
            worktree_path_str=task_obj.worktree_path,
        )

    def _build_task_context_snapshot_list(self, task_obj: Task) -> list[str]:
        """Build a lightweight task context snapshot for implementation prompts."""
        ordered_dev_log_list = sorted(
            task_obj.dev_logs,
            key=lambda dev_log_item: (dev_log_item.created_at, dev_log_item.id),
        )
        return [
            dev_log_item.text_content.strip()
            for dev_log_item in ordered_dev_log_list
            if dev_log_item.text_content.strip()
        ]
