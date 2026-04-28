"""Application service for remote branch and PR-backed requirements."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from backend.dsl.models.enums import TaskLifecycleStatus, WorkflowStage
from backend.dsl.models.project import Project
from backend.dsl.models.task import Task
from backend.dsl.remote_requirements.domain import (
    REMOTE_REQUIREMENT_MANIFEST_ROOT,
    REMOTE_REQUIREMENT_SYNC_STATUS_CONFLICT,
    REMOTE_REQUIREMENT_SYNC_STATUS_CREATED,
    REMOTE_REQUIREMENT_SYNC_STATUS_FAILED,
    REMOTE_REQUIREMENT_SYNC_STATUS_IMPORTED,
    REMOTE_REQUIREMENT_SYNC_STATUS_PR_MERGED,
    REMOTE_REQUIREMENT_SYNC_STATUS_PR_OPEN,
    REMOTE_REQUIREMENT_SYNC_STATUS_PUSHED,
    PullRequestMetadata,
    RemoteRequirementConflictError,
    RemoteRequirementError,
    RemoteRequirementManifest,
    RemoteRequirementSyncOutcome,
)
from backend.dsl.remote_requirements.infrastructure.git_remote_requirement_repository import (
    GitRemoteRequirementRepository,
)
from backend.dsl.remote_requirements.infrastructure.github_pull_request_adapter import (
    GitHubPullRequestAdapter,
)
from backend.dsl.services.git_worktree_service import GitWorktreeService
from backend.dsl.services.project_service import ProjectService
from backend.dsl.services.worktree_branch_naming_service import (
    WorktreeBranchNamingService,
)
from utils.helpers import utc_now_naive


class RemoteRequirementService:
    """Use cases for remote requirement branch collaboration."""

    def __init__(
        self,
        *,
        git_repository: GitRemoteRequirementRepository | None = None,
        github_adapter: GitHubPullRequestAdapter | None = None,
    ) -> None:
        """Initialize the service.

        Args:
            git_repository: Optional Git infrastructure adapter.
            github_adapter: Optional GitHub PR provider adapter.
        """
        self._git_repository = git_repository or GitRemoteRequirementRepository()
        self._github_adapter = github_adapter or GitHubPullRequestAdapter()

    @staticmethod
    def is_project_remote_requirement_enabled(project_obj: Project | None) -> bool:
        """Return whether a project has remote requirement collaboration enabled.

        Args:
            project_obj: Project object or None.

        Returns:
            bool: Whether remote-backed collaboration is enabled.
        """
        return bool(
            project_obj is not None
            and project_obj.remote_requirement_management_enabled
        )

    @staticmethod
    def should_use_pull_request_completion(
        project_obj: Project | None,
        task_obj: Task | None,
    ) -> bool:
        """Return whether Complete should create/update a PR for this task.

        Args:
            project_obj: Linked project object.
            task_obj: Task object.

        Returns:
            bool: Whether the task should use PR-backed completion.
        """
        return bool(
            task_obj is not None
            and task_obj.task_branch_name
            and RemoteRequirementService.is_project_remote_requirement_enabled(
                project_obj
            )
            and project_obj is not None
            and project_obj.github_pr_creation_enabled
        )

    @staticmethod
    def build_manifest_relative_path(task_id_str: str) -> str:
        """Build the repository-relative manifest path for a task.

        Args:
            task_id_str: Task UUID.

        Returns:
            str: Manifest path inside the repository.
        """
        return f"{REMOTE_REQUIREMENT_MANIFEST_ROOT}/{task_id_str}.json"

    @staticmethod
    def _normalize_branch_prefix(raw_branch_prefix_str: str | None) -> str:
        """Normalize a configured task branch prefix.

        Args:
            raw_branch_prefix_str: Raw branch prefix.

        Returns:
            str: Normalized prefix without surrounding slashes.
        """
        normalized_branch_prefix_str = (
            (raw_branch_prefix_str or "task").strip().strip("/")
        )
        return normalized_branch_prefix_str or "task"

    @staticmethod
    def _serialize_manifest(manifest: RemoteRequirementManifest) -> str:
        """Serialize a manifest as stable UTF-8 JSON text.

        Args:
            manifest: Manifest model.

        Returns:
            str: Pretty JSON text.
        """
        manifest_payload = manifest.model_dump(mode="json", exclude_none=False)
        return (
            json.dumps(
                manifest_payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    @staticmethod
    def _to_naive_datetime(
        incoming_datetime: datetime | None,
    ) -> datetime | None:
        """Convert a datetime into a DB-friendly naive UTC datetime.

        Args:
            incoming_datetime: Optional datetime.

        Returns:
            datetime | None: Naive UTC datetime or None.
        """
        if incoming_datetime is None:
            return None
        if incoming_datetime.tzinfo is None:
            return incoming_datetime
        return incoming_datetime.astimezone(timezone.utc).replace(tzinfo=None)

    def _resolve_remote_name(
        self,
        project_obj: Project,
        base_branch_name_str: str,
    ) -> str:
        """Resolve the remote name used for requirement branch sync.

        Args:
            project_obj: Linked project.
            base_branch_name_str: Base branch name.

        Returns:
            str: Git remote name.

        Raises:
            RemoteRequirementError: Raised when no safe remote is available.
        """
        configured_remote_name_str = (
            project_obj.remote_requirement_remote_name or ""
        ).strip()
        if configured_remote_name_str:
            return configured_remote_name_str

        repo_root_path = Path(project_obj.repo_path).expanduser().resolve()
        resolved_remote_name_str = GitWorktreeService.resolve_preferred_remote_name(
            repo_root_path=repo_root_path,
            branch_name_str=base_branch_name_str,
        )
        if not resolved_remote_name_str:
            raise RemoteRequirementError(
                "Remote requirement collaboration requires a resolvable Git remote."
            )
        return resolved_remote_name_str

    @staticmethod
    def _resolve_github_repository_full_name(project_obj: Project) -> str:
        """Resolve the GitHub ``owner/repo`` name for PR operations.

        Args:
            project_obj: Linked project.

        Returns:
            str: GitHub repository full name.

        Raises:
            RemoteRequirementError: Raised when the project does not point at GitHub.
        """
        configured_full_name_str = (
            (project_obj.github_repository_full_name or "")
            .strip()
            .removeprefix("github.com/")
        )
        if configured_full_name_str and configured_full_name_str.count("/") == 1:
            return configured_full_name_str

        normalized_remote_url_str = (project_obj.repo_remote_url or "").strip()
        github_prefix_str = "github.com/"
        if normalized_remote_url_str.startswith(github_prefix_str):
            inferred_full_name_str = normalized_remote_url_str.removeprefix(
                github_prefix_str
            )
            if inferred_full_name_str.count("/") == 1:
                return inferred_full_name_str

        raise RemoteRequirementError(
            "GitHub PR creation requires github_repository_full_name or a GitHub remote URL."
        )

    def _ensure_github_pr_creation_is_configured(self, project_obj: Project) -> None:
        """Validate GitHub PR handoff settings before remote branch creation.

        Args:
            project_obj: Linked project with remote collaboration enabled.

        Raises:
            RemoteRequirementError: Raised when PR handoff is enabled without
                enough GitHub repository metadata to create a pull request later.
        """
        if not project_obj.github_pr_creation_enabled:
            return
        self._resolve_github_repository_full_name(project_obj)

    @staticmethod
    def _build_task_branch_name(task_obj: Task, project_obj: Project) -> str:
        """Build a semantic task branch name using the configured prefix.

        Args:
            task_obj: Task requiring a remote branch.
            project_obj: Linked project.

        Returns:
            str: Valid task branch name.

        Raises:
            RemoteRequirementError: Raised when Git rejects the branch name.
        """
        branch_naming_result = (
            WorktreeBranchNamingService.build_task_branch_naming_result(
                task_id_str=task_obj.id,
                task_title_str=task_obj.task_title,
                requirement_brief_str=task_obj.requirement_brief,
                recent_context_text_list=[],
            )
        )
        branch_prefix_str = RemoteRequirementService._normalize_branch_prefix(
            project_obj.remote_requirement_branch_prefix
        )
        default_branch_name_str = branch_naming_result.branch_name_str
        if branch_prefix_str != "task" and default_branch_name_str.startswith("task/"):
            task_branch_name_str = (
                f"{branch_prefix_str}/{default_branch_name_str.removeprefix('task/')}"
            )
        else:
            task_branch_name_str = default_branch_name_str

        if not GitWorktreeService.is_valid_branch_name(task_branch_name_str):
            raise RemoteRequirementError(
                f"Invalid remote requirement branch name: {task_branch_name_str}"
            )
        return task_branch_name_str

    def _build_manifest(
        self,
        task_obj: Task,
        project_obj: Project,
        *,
        prd_relative_path_str: str | None = None,
        updated_at: datetime | None = None,
    ) -> RemoteRequirementManifest:
        """Build the current remote requirement manifest for a task.

        Args:
            task_obj: Task object.
            project_obj: Linked project.
            prd_relative_path_str: Optional workspace-relative PRD path override.
            updated_at: Optional manifest updated timestamp.

        Returns:
            RemoteRequirementManifest: Manifest snapshot.

        Raises:
            RemoteRequirementError: Raised when the task has no branch name.
        """
        if not task_obj.task_branch_name:
            raise RemoteRequirementError("Task has no task_branch_name to manifest.")

        manifest_path_str = task_obj.remote_requirement_manifest_path or (
            self.build_manifest_relative_path(task_obj.id)
        )
        task_obj.remote_requirement_manifest_path = manifest_path_str
        resolved_updated_at = updated_at or utc_now_naive()
        return RemoteRequirementManifest(
            task_id=task_obj.id,
            task_title=task_obj.task_title,
            requirement_brief=task_obj.requirement_brief,
            workflow_stage=task_obj.workflow_stage.value,
            lifecycle_status=task_obj.lifecycle_status.value,
            task_branch_name=task_obj.task_branch_name,
            worktree_base_branch_name=(task_obj.worktree_base_branch_name or "main"),
            repo_remote_url=project_obj.repo_remote_url,
            prd_relative_path=prd_relative_path_str,
            github_pr_url=task_obj.github_pr_url,
            github_pr_number=task_obj.github_pr_number,
            github_pr_state=task_obj.github_pr_state,
            last_progress_pushed_at=task_obj.last_progress_pushed_at,
            created_at=task_obj.created_at,
            updated_at=resolved_updated_at,
            closed_at=task_obj.closed_at,
        )

    def _read_existing_manifest_for_task(
        self,
        *,
        task_obj: Task,
        manifest_relative_path_str: str,
        repo_root_path: Path | None = None,
        remote_name_str: str | None = None,
        worktree_path: Path | None = None,
    ) -> RemoteRequirementManifest | None:
        """Read an existing task manifest from the safest available source.

        Args:
            task_obj: Task whose manifest should be read.
            manifest_relative_path_str: Manifest path in the repository.
            repo_root_path: Optional project repository root.
            remote_name_str: Optional remote name for remote-tracking refs.
            worktree_path: Optional task worktree path.

        Returns:
            RemoteRequirementManifest | None: Existing manifest when available.
        """
        if worktree_path is not None and worktree_path.exists():
            worktree_manifest = self._git_repository.read_manifest_from_worktree(
                worktree_path,
                manifest_relative_path_str,
            )
            if worktree_manifest is not None:
                return worktree_manifest

        if repo_root_path is None or not task_obj.task_branch_name:
            return None

        git_ref_candidate_list: list[str] = []
        if remote_name_str:
            git_ref_candidate_list.append(
                f"refs/remotes/{remote_name_str}/{task_obj.task_branch_name}"
            )
        git_ref_candidate_list.append(f"refs/heads/{task_obj.task_branch_name}")

        for git_ref_candidate_str in git_ref_candidate_list:
            git_ref_manifest = self._git_repository.read_manifest_from_git_ref(
                repo_root_path,
                git_ref_candidate_str,
                manifest_relative_path_str,
            )
            if git_ref_manifest is not None:
                return git_ref_manifest
        return None

    def _resolve_manifest_prd_relative_path(
        self,
        *,
        task_obj: Task,
        explicit_prd_relative_path_str: str | None,
        manifest_relative_path_str: str,
        repo_root_path: Path | None = None,
        remote_name_str: str | None = None,
        worktree_path: Path | None = None,
    ) -> str | None:
        """Resolve the PRD path that should be written into a manifest.

        Args:
            task_obj: Task being serialized.
            explicit_prd_relative_path_str: New PRD path supplied by the caller.
            manifest_relative_path_str: Manifest path in the repository.
            repo_root_path: Optional project repository root.
            remote_name_str: Optional remote name for remote-tracking refs.
            worktree_path: Optional task worktree path.

        Returns:
            str | None: Explicit or preserved PRD path.
        """
        if explicit_prd_relative_path_str is not None:
            return explicit_prd_relative_path_str

        existing_manifest = self._read_existing_manifest_for_task(
            task_obj=task_obj,
            manifest_relative_path_str=manifest_relative_path_str,
            repo_root_path=repo_root_path,
            remote_name_str=remote_name_str,
            worktree_path=worktree_path,
        )
        if existing_manifest is None:
            return None
        return existing_manifest.prd_relative_path

    @staticmethod
    def _mark_remote_sync_failure(task_obj: Task, failure_reason_text: str) -> None:
        """Record a remote sync failure on the task.

        Args:
            task_obj: Task object to mark.
            failure_reason_text: Human-readable failure reason.
        """
        task_obj.remote_requirement_sync_status = REMOTE_REQUIREMENT_SYNC_STATUS_FAILED
        task_obj.remote_requirement_last_error = failure_reason_text

    def create_remote_branch_for_task(
        self,
        db_session: Session,
        task_obj: Task,
        project_obj: Project,
    ) -> Task:
        """Create and push the initial remote requirement branch for a task.

        Args:
            db_session: Database session.
            task_obj: Newly created task.
            project_obj: Linked project with remote collaboration enabled.

        Returns:
            Task: Updated task.

        Raises:
            RemoteRequirementError: Raised when remote branch creation fails.
        """
        if not self.is_project_remote_requirement_enabled(project_obj):
            return task_obj

        try:
            consistency_snapshot = ProjectService.build_project_consistency_snapshot(
                project_obj
            )
            if consistency_snapshot.is_repo_remote_consistent is False:
                raise RemoteRequirementError(
                    "Project repo_path points to a different Git remote than the stored fingerprint."
                )

            repo_root_path = Path(project_obj.repo_path).expanduser().resolve()
            remote_name_str = self._resolve_remote_name(
                project_obj,
                task_obj.worktree_base_branch_name or "main",
            )
            self._ensure_github_pr_creation_is_configured(project_obj)
            task_branch_name_str = self._build_task_branch_name(task_obj, project_obj)
            manifest_relative_path_str = self.build_manifest_relative_path(task_obj.id)
            task_obj.task_branch_name = task_branch_name_str
            task_obj.remote_requirement_manifest_path = manifest_relative_path_str

            manifest = self._build_manifest(task_obj, project_obj)
            manifest_json_text = self._serialize_manifest(manifest)
            synced_commit_hash_str = self._git_repository.create_manifest_branch(
                repo_root_path=repo_root_path,
                remote_name_str=remote_name_str,
                branch_name_str=task_branch_name_str,
                base_branch_name_str=task_obj.worktree_base_branch_name or "main",
                manifest_relative_path_str=manifest_relative_path_str,
                manifest_json_text=manifest_json_text,
                commit_message_text=(
                    f"chore(koda): create requirement {task_obj.id[:8]} manifest"
                ),
            )
        except RemoteRequirementError as remote_error:
            self._mark_remote_sync_failure(task_obj, str(remote_error))
            db_session.commit()
            raise

        task_obj.remote_requirement_sync_status = REMOTE_REQUIREMENT_SYNC_STATUS_CREATED
        task_obj.remote_requirement_synced_commit_hash = synced_commit_hash_str
        task_obj.remote_requirement_last_synced_at = utc_now_naive()
        task_obj.remote_requirement_last_error = None
        db_session.commit()
        db_session.refresh(task_obj)
        return task_obj

    def _load_project_for_task_or_raise(
        self,
        db_session: Session,
        task_obj: Task,
    ) -> Project:
        """Load the linked project for a remote-backed task.

        Args:
            db_session: Database session.
            task_obj: Task object.

        Returns:
            Project: Linked project.

        Raises:
            RemoteRequirementError: Raised when the task is not remote-backed.
        """
        if not task_obj.project_id:
            raise RemoteRequirementError("Task is not linked to a project.")
        project_obj = (
            db_session.query(Project).filter(Project.id == task_obj.project_id).first()
        )
        if project_obj is None:
            raise RemoteRequirementError("Task project no longer exists.")
        if not self.is_project_remote_requirement_enabled(project_obj):
            raise RemoteRequirementError(
                "Remote requirement collaboration is not enabled for this project."
            )
        return project_obj

    def _assert_remote_cursor_is_fresh(
        self,
        *,
        repo_root_path: Path,
        remote_name_str: str,
        task_obj: Task,
    ) -> None:
        """Raise when the remote branch advanced beyond the local sync cursor.

        Args:
            repo_root_path: Project repository root.
            remote_name_str: Git remote name.
            task_obj: Task being pushed.

        Raises:
            RemoteRequirementConflictError: Raised when remote branch is stale.
        """
        if not task_obj.task_branch_name:
            raise RemoteRequirementError("Task has no task_branch_name.")
        self._git_repository.fetch_remote(repo_root_path, remote_name_str)
        remote_commit_hash_str = self._git_repository.get_remote_branch_commit_hash(
            repo_root_path,
            remote_name_str,
            task_obj.task_branch_name,
        )
        if (
            remote_commit_hash_str
            and task_obj.remote_requirement_synced_commit_hash
            and remote_commit_hash_str != task_obj.remote_requirement_synced_commit_hash
        ):
            task_obj.remote_requirement_sync_status = (
                REMOTE_REQUIREMENT_SYNC_STATUS_CONFLICT
            )
            task_obj.remote_requirement_last_error = (
                "Remote task branch advanced since the last local sync."
            )
            raise RemoteRequirementConflictError(
                "Remote task branch advanced since the last local sync. Run remote sync before pushing."
            )

    def push_progress(
        self,
        db_session: Session,
        task_id_str: str,
        *,
        prd_relative_path_str: str | None = None,
        commit_message_text: str | None = None,
    ) -> Task | None:
        """Commit and push current task branch progress without creating a PR.

        Args:
            db_session: Database session.
            task_id_str: Task UUID.
            prd_relative_path_str: Optional PRD path to record in the manifest.
            commit_message_text: Optional commit message override.

        Returns:
            Task | None: Updated task or None when missing.

        Raises:
            RemoteRequirementError: Raised when the task cannot be pushed.
        """
        task_obj = db_session.query(Task).filter(Task.id == task_id_str).first()
        if task_obj is None:
            return None
        project_obj = self._load_project_for_task_or_raise(db_session, task_obj)
        if not task_obj.task_branch_name:
            raise RemoteRequirementError("Task has no remote task branch.")
        if task_obj.lifecycle_status in {
            TaskLifecycleStatus.CLOSED,
            TaskLifecycleStatus.DELETED,
            TaskLifecycleStatus.ABANDONED,
        }:
            raise RemoteRequirementError(
                "Push Progress is only available for open or pending tasks."
            )
        if not task_obj.worktree_path:
            raise RemoteRequirementError(
                "Push Progress requires an existing task worktree."
            )
        worktree_path = Path(task_obj.worktree_path).expanduser()
        if not worktree_path.exists():
            raise RemoteRequirementError(
                f"Task worktree does not exist: {worktree_path}"
            )

        try:
            remote_name_str = self._resolve_remote_name(
                project_obj,
                task_obj.worktree_base_branch_name or "main",
            )
            repo_root_path = Path(project_obj.repo_path).expanduser().resolve()
        except RemoteRequirementError as remote_error:
            self._refresh_after_manifest_failure(
                db_session,
                task_obj,
                str(remote_error),
                conflict_bool=False,
            )
            raise
        try:
            self._assert_remote_cursor_is_fresh(
                repo_root_path=repo_root_path,
                remote_name_str=remote_name_str,
                task_obj=task_obj,
            )
        except RemoteRequirementConflictError:
            db_session.commit()
            raise
        except RemoteRequirementError as remote_error:
            self._refresh_after_manifest_failure(
                db_session,
                task_obj,
                str(remote_error),
                conflict_bool=False,
            )
            raise

        now_datetime = utc_now_naive()
        previous_last_progress_pushed_at = task_obj.last_progress_pushed_at
        task_obj.last_progress_pushed_at = now_datetime
        manifest_path_str = task_obj.remote_requirement_manifest_path or (
            self.build_manifest_relative_path(task_obj.id)
        )
        resolved_prd_relative_path_str = self._resolve_manifest_prd_relative_path(
            task_obj=task_obj,
            explicit_prd_relative_path_str=prd_relative_path_str,
            manifest_relative_path_str=manifest_path_str,
            repo_root_path=repo_root_path,
            remote_name_str=remote_name_str,
            worktree_path=worktree_path,
        )
        manifest = self._build_manifest(
            task_obj,
            project_obj,
            prd_relative_path_str=resolved_prd_relative_path_str,
            updated_at=now_datetime,
        )
        try:
            self._git_repository.write_manifest_to_worktree(
                worktree_path,
                manifest_path_str,
                self._serialize_manifest(manifest),
            )
            self._git_repository.commit_all_changes_if_needed(
                worktree_path,
                commit_message_text
                or f"chore(koda): sync requirement {task_obj.id[:8]} progress",
            )
            synced_commit_hash_str = self._git_repository.push_branch(
                worktree_path,
                remote_name_str,
                task_obj.task_branch_name,
            )
        except RemoteRequirementError as remote_error:
            task_obj.last_progress_pushed_at = previous_last_progress_pushed_at
            self._refresh_after_manifest_failure(
                db_session,
                task_obj,
                str(remote_error),
                conflict_bool=False,
            )
            raise
        task_obj.remote_requirement_sync_status = REMOTE_REQUIREMENT_SYNC_STATUS_PUSHED
        task_obj.remote_requirement_synced_commit_hash = synced_commit_hash_str
        task_obj.remote_requirement_last_synced_at = now_datetime
        task_obj.remote_requirement_last_error = None
        db_session.commit()
        db_session.refresh(task_obj)
        return task_obj

    def update_manifest_after_prd_staging(
        self,
        db_session: Session,
        task_id_str: str,
        prd_relative_path_str: str,
    ) -> None:
        """Update and push the manifest after a PRD is staged.

        Args:
            db_session: Database session.
            task_id_str: Task UUID.
            prd_relative_path_str: Workspace-relative PRD path.
        """
        task_obj = db_session.query(Task).filter(Task.id == task_id_str).first()
        if task_obj is None or not task_obj.task_branch_name:
            return
        try:
            self._load_project_for_task_or_raise(db_session, task_obj)
        except RemoteRequirementError:
            return

        try:
            self.push_progress(
                db_session,
                task_id_str,
                prd_relative_path_str=prd_relative_path_str,
                commit_message_text=(
                    f"chore(koda): stage requirement {task_id_str[:8]} PRD"
                ),
            )
        except RemoteRequirementError as remote_error:
            self._mark_remote_sync_failure(
                task_obj,
                (f"Failed to update remote manifest after PRD staging: {remote_error}"),
            )
            db_session.commit()

    def update_manifest_after_task_state_change(
        self,
        db_session: Session,
        task_id_str: str,
        commit_message_text: str | None = None,
        sync_status_str: str = REMOTE_REQUIREMENT_SYNC_STATUS_PUSHED,
    ) -> Task | None:
        """Update and push a remote manifest after a local task mutation.

        This helper is intentionally best-effort for shared task mutations: local
        state is preserved, while remote conflicts/failures are recorded on the
        task so project sync does not silently overwrite newer local changes.

        Args:
            db_session: Database session.
            task_id_str: Task UUID.
            commit_message_text: Optional commit message override.
            sync_status_str: Sync status to persist after a successful push.

        Returns:
            Task | None: Refreshed task when present.
        """
        task_obj = db_session.query(Task).filter(Task.id == task_id_str).first()
        if task_obj is None:
            return None
        if not task_obj.task_branch_name:
            return task_obj

        try:
            project_obj = self._load_project_for_task_or_raise(db_session, task_obj)
        except RemoteRequirementError:
            return task_obj

        remote_name_str = self._resolve_remote_name(
            project_obj,
            task_obj.worktree_base_branch_name or "main",
        )
        repo_root_path = Path(project_obj.repo_path).expanduser().resolve()
        try:
            self._assert_remote_cursor_is_fresh(
                repo_root_path=repo_root_path,
                remote_name_str=remote_name_str,
                task_obj=task_obj,
            )
        except RemoteRequirementConflictError as remote_conflict_error:
            db_session.commit()
            return self._refresh_after_manifest_failure(
                db_session,
                task_obj,
                str(remote_conflict_error),
                conflict_bool=True,
            )

        manifest_path_str = task_obj.remote_requirement_manifest_path or (
            self.build_manifest_relative_path(task_obj.id)
        )
        worktree_path = (
            Path(task_obj.worktree_path).expanduser()
            if task_obj.worktree_path
            else None
        )
        resolved_prd_relative_path_str = self._resolve_manifest_prd_relative_path(
            task_obj=task_obj,
            explicit_prd_relative_path_str=None,
            manifest_relative_path_str=manifest_path_str,
            repo_root_path=repo_root_path,
            remote_name_str=remote_name_str,
            worktree_path=worktree_path,
        )
        manifest = self._build_manifest(
            task_obj,
            project_obj,
            prd_relative_path_str=resolved_prd_relative_path_str,
        )
        manifest_json_text = self._serialize_manifest(manifest)
        resolved_commit_message_text = commit_message_text or (
            f"chore(koda): sync requirement {task_obj.id[:8]} state"
        )

        try:
            if worktree_path is not None and worktree_path.exists():
                self._git_repository.write_manifest_to_worktree(
                    worktree_path,
                    manifest_path_str,
                    manifest_json_text,
                )
                self._git_repository.commit_all_changes_if_needed(
                    worktree_path,
                    resolved_commit_message_text,
                )
                synced_commit_hash_str = self._git_repository.push_branch(
                    worktree_path,
                    remote_name_str,
                    task_obj.task_branch_name,
                )
            else:
                synced_commit_hash_str = self._git_repository.write_manifest_to_branch(
                    repo_root_path=repo_root_path,
                    remote_name_str=remote_name_str,
                    branch_name_str=task_obj.task_branch_name,
                    manifest_relative_path_str=manifest_path_str,
                    manifest_json_text=manifest_json_text,
                    commit_message_text=resolved_commit_message_text,
                )
        except RemoteRequirementError as remote_error:
            return self._refresh_after_manifest_failure(
                db_session,
                task_obj,
                str(remote_error),
                conflict_bool=False,
            )

        task_obj.remote_requirement_sync_status = sync_status_str
        task_obj.remote_requirement_synced_commit_hash = synced_commit_hash_str
        task_obj.remote_requirement_last_synced_at = utc_now_naive()
        task_obj.remote_requirement_last_error = None
        db_session.commit()
        db_session.refresh(task_obj)
        return task_obj

    def _refresh_after_manifest_failure(
        self,
        db_session: Session,
        task_obj: Task,
        failure_reason_text: str,
        *,
        conflict_bool: bool,
    ) -> Task:
        """Persist a manifest sync failure and refresh the task.

        Args:
            db_session: Database session.
            task_obj: Task object.
            failure_reason_text: Human-readable failure reason.
            conflict_bool: Whether the failure was a stale remote conflict.

        Returns:
            Task: Refreshed task.
        """
        if conflict_bool:
            task_obj.remote_requirement_sync_status = (
                REMOTE_REQUIREMENT_SYNC_STATUS_CONFLICT
            )
            task_obj.remote_requirement_last_error = failure_reason_text
        else:
            self._mark_remote_sync_failure(task_obj, failure_reason_text)
        db_session.commit()
        db_session.refresh(task_obj)
        return task_obj

    def _should_skip_existing_task_during_remote_sync(
        self,
        task_obj: Task,
        remote_manifest_updated_at: datetime,
        remote_commit_hash_str: str,
    ) -> bool:
        """Return whether project sync must preserve a local task projection.

        Args:
            task_obj: Existing local task row.
            remote_manifest_updated_at: Manifest update timestamp from the remote ref.
            remote_commit_hash_str: Remote branch commit hash for the manifest.

        Returns:
            bool: Whether remote sync should skip this local task.
        """
        if task_obj.remote_requirement_sync_status in {
            REMOTE_REQUIREMENT_SYNC_STATUS_CONFLICT,
            REMOTE_REQUIREMENT_SYNC_STATUS_FAILED,
        }:
            return True

        if (
            task_obj.task_branch_name
            and not task_obj.remote_requirement_synced_commit_hash
        ):
            return True

        if (
            task_obj.task_branch_name
            and task_obj.remote_requirement_sync_status is None
        ):
            return True

        if task_obj.remote_requirement_synced_commit_hash == remote_commit_hash_str:
            return False

        local_last_synced_at = task_obj.remote_requirement_last_synced_at
        if local_last_synced_at is None:
            return False

        remote_updated_at = self._to_naive_datetime(remote_manifest_updated_at)
        if remote_updated_at is None:
            return True

        return remote_updated_at <= local_last_synced_at

    def _build_pull_request_body(self, task_obj: Task) -> str:
        """Build the PR body for a remote-backed task.

        Args:
            task_obj: Task being completed.

        Returns:
            str: Markdown PR body.
        """
        manifest_path_str = task_obj.remote_requirement_manifest_path or (
            self.build_manifest_relative_path(task_obj.id)
        )
        body_part_list = [
            f"Koda requirement task: `{task_obj.id}`",
            f"Manifest: `{manifest_path_str}`",
        ]
        if task_obj.requirement_brief:
            body_part_list.extend(
                ["", "Requirement brief:", task_obj.requirement_brief]
            )
        return "\n".join(body_part_list)

    def complete_as_pull_request(
        self,
        db_session: Session,
        task_id_str: str,
        *,
        allow_complete_from_changes_requested_bool: bool = False,
    ) -> Task | None:
        """Push final branch state and create/update a GitHub pull request.

        Args:
            db_session: Database session.
            task_id_str: Task UUID.
            allow_complete_from_changes_requested_bool: Whether completion is allowed
                from ``changes_requested`` after manual repair.

        Returns:
            Task | None: Updated task or None when missing.

        Raises:
            RemoteRequirementError: Raised when PR handoff cannot complete.
        """
        from backend.dsl.services.task_service import TaskService

        completion_task = TaskService.prepare_task_completion(
            db_session,
            task_id_str,
            allow_complete_from_changes_requested_bool=(
                allow_complete_from_changes_requested_bool
            ),
        )
        if completion_task is None:
            return None
        project_obj = self._load_project_for_task_or_raise(db_session, completion_task)
        if not completion_task.task_branch_name:
            raise RemoteRequirementError("Task has no remote task branch.")
        if not completion_task.worktree_path:
            raise RemoteRequirementError("Task has no worktree_path.")
        worktree_path = Path(completion_task.worktree_path).expanduser()
        if not worktree_path.exists():
            raise RemoteRequirementError(
                f"Task worktree does not exist: {worktree_path}"
            )

        remote_name_str = self._resolve_remote_name(
            project_obj,
            completion_task.worktree_base_branch_name or "main",
        )
        repo_root_path = Path(project_obj.repo_path).expanduser().resolve()
        try:
            self._assert_remote_cursor_is_fresh(
                repo_root_path=repo_root_path,
                remote_name_str=remote_name_str,
                task_obj=completion_task,
            )

            now_datetime = utc_now_naive()
            manifest_path_str = completion_task.remote_requirement_manifest_path or (
                self.build_manifest_relative_path(completion_task.id)
            )
            resolved_prd_relative_path_str = self._resolve_manifest_prd_relative_path(
                task_obj=completion_task,
                explicit_prd_relative_path_str=None,
                manifest_relative_path_str=manifest_path_str,
                repo_root_path=repo_root_path,
                remote_name_str=remote_name_str,
                worktree_path=worktree_path,
            )
            manifest = self._build_manifest(
                completion_task,
                project_obj,
                prd_relative_path_str=resolved_prd_relative_path_str,
                updated_at=now_datetime,
            )
            self._git_repository.write_manifest_to_worktree(
                worktree_path,
                manifest_path_str,
                self._serialize_manifest(manifest),
            )
            self._git_repository.commit_all_changes_if_needed(
                worktree_path,
                f"chore(koda): prepare requirement {completion_task.id[:8]} PR",
            )
            self._git_repository.rebase_onto_base_branch(
                worktree_path,
                completion_task.worktree_base_branch_name or "main",
            )
            pushed_commit_hash_str = self._git_repository.push_branch(
                worktree_path,
                remote_name_str,
                completion_task.task_branch_name,
            )

            repository_full_name_str = self._resolve_github_repository_full_name(
                project_obj
            )
            head_owner_login_str = repository_full_name_str.split("/", 1)[0]
            pull_request_metadata = self._github_adapter.create_or_get_pull_request(
                repository_full_name_str=repository_full_name_str,
                head_owner_login_str=head_owner_login_str,
                branch_name_str=completion_task.task_branch_name,
                base_branch_name_str=completion_task.worktree_base_branch_name
                or "main",
                title_str=completion_task.task_title,
                body_str=self._build_pull_request_body(completion_task),
            )
        except RemoteRequirementConflictError:
            db_session.commit()
            raise
        except RemoteRequirementError as remote_error:
            self._mark_remote_sync_failure(completion_task, str(remote_error))
            TaskService._apply_workflow_stage_transition(
                completion_task,
                WorkflowStage.CHANGES_REQUESTED,
            )
            completion_task.lifecycle_status = TaskLifecycleStatus.OPEN
            db_session.commit()
            raise
        self._apply_pull_request_metadata(completion_task, pull_request_metadata)
        TaskService._apply_workflow_stage_transition(
            completion_task,
            WorkflowStage.ACCEPTANCE_IN_PROGRESS,
        )
        completion_task.lifecycle_status = TaskLifecycleStatus.OPEN
        completion_task.remote_requirement_sync_status = (
            REMOTE_REQUIREMENT_SYNC_STATUS_PR_OPEN
        )
        completion_task.remote_requirement_synced_commit_hash = pushed_commit_hash_str
        completion_task.remote_requirement_last_synced_at = utc_now_naive()
        completion_task.remote_requirement_last_error = None
        db_session.commit()
        db_session.refresh(completion_task)

        pr_metadata_prd_relative_path_str = self._resolve_manifest_prd_relative_path(
            task_obj=completion_task,
            explicit_prd_relative_path_str=None,
            manifest_relative_path_str=manifest_path_str,
            repo_root_path=repo_root_path,
            remote_name_str=remote_name_str,
            worktree_path=worktree_path,
        )
        pr_manifest = self._build_manifest(
            completion_task,
            project_obj,
            prd_relative_path_str=pr_metadata_prd_relative_path_str,
        )
        self._git_repository.write_manifest_to_worktree(
            worktree_path,
            manifest_path_str,
            self._serialize_manifest(pr_manifest),
        )
        pr_metadata_commit_hash_str = self._git_repository.commit_all_changes_if_needed(
            worktree_path,
            f"chore(koda): record requirement {completion_task.id[:8]} PR metadata",
        )
        pr_metadata_commit_hash_str = self._git_repository.push_branch(
            worktree_path,
            remote_name_str,
            completion_task.task_branch_name,
        )
        completion_task.remote_requirement_synced_commit_hash = (
            pr_metadata_commit_hash_str
        )
        completion_task.remote_requirement_last_synced_at = utc_now_naive()
        db_session.commit()
        db_session.refresh(completion_task)
        return completion_task

    @staticmethod
    def _apply_pull_request_metadata(
        task_obj: Task,
        pull_request_metadata: PullRequestMetadata,
    ) -> None:
        """Persist PR metadata on a task.

        Args:
            task_obj: Task object.
            pull_request_metadata: Provider PR metadata.
        """
        task_obj.github_pr_url = pull_request_metadata.url
        task_obj.github_pr_number = pull_request_metadata.number
        task_obj.github_pr_state = pull_request_metadata.state

    def sync_pull_request_status(
        self,
        db_session: Session,
        task_id_str: str,
    ) -> Task | None:
        """Sync a task's GitHub PR status and close it when merged.

        Args:
            db_session: Database session.
            task_id_str: Task UUID.

        Returns:
            Task | None: Updated task or None when missing.

        Raises:
            RemoteRequirementError: Raised when the task lacks PR metadata.
        """
        from backend.dsl.services.task_service import TaskService

        task_obj = db_session.query(Task).filter(Task.id == task_id_str).first()
        if task_obj is None:
            return None
        project_obj = self._load_project_for_task_or_raise(db_session, task_obj)
        if task_obj.github_pr_number is None:
            raise RemoteRequirementError("Task has no GitHub PR number to sync.")
        repository_full_name_str = self._resolve_github_repository_full_name(
            project_obj
        )
        pull_request_metadata = self._github_adapter.get_pull_request(
            repository_full_name_str=repository_full_name_str,
            pull_request_number_int=task_obj.github_pr_number,
        )
        self._apply_pull_request_metadata(task_obj, pull_request_metadata)
        if pull_request_metadata.merged:
            TaskService._apply_workflow_stage_transition(task_obj, WorkflowStage.DONE)
            task_obj.lifecycle_status = TaskLifecycleStatus.CLOSED
            task_obj.closed_at = utc_now_naive()
            task_obj.remote_requirement_sync_status = (
                REMOTE_REQUIREMENT_SYNC_STATUS_PR_MERGED
            )
        else:
            task_obj.remote_requirement_sync_status = (
                REMOTE_REQUIREMENT_SYNC_STATUS_PR_OPEN
            )

        synced_task = self.update_manifest_after_task_state_change(
            db_session,
            task_obj.id,
            commit_message_text=(
                f"chore(koda): sync requirement {task_obj.id[:8]} PR status"
            ),
            sync_status_str=task_obj.remote_requirement_sync_status
            or REMOTE_REQUIREMENT_SYNC_STATUS_PUSHED,
        )
        if synced_task is not None:
            if (
                pull_request_metadata.merged
                and synced_task.remote_requirement_sync_status
                != REMOTE_REQUIREMENT_SYNC_STATUS_PR_MERGED
            ):
                synced_task.remote_requirement_sync_status = (
                    REMOTE_REQUIREMENT_SYNC_STATUS_PR_MERGED
                )
                synced_task.remote_requirement_last_error = (
                    "PR is merged; remote manifest update still needs retry. "
                    f"{synced_task.remote_requirement_last_error or ''}"
                ).strip()
                db_session.commit()
                db_session.refresh(synced_task)
            return synced_task
        db_session.commit()
        db_session.refresh(task_obj)
        return task_obj

    def sync_project_remote_requirements(
        self,
        db_session: Session,
        project_obj: Project,
        run_account_id_str: str,
    ) -> RemoteRequirementSyncOutcome:
        """Materialize local tasks from remote branch manifests.

        Args:
            db_session: Database session.
            project_obj: Project with remote collaboration enabled.
            run_account_id_str: Local run account that owns imported cards.

        Returns:
            RemoteRequirementSyncOutcome: Import/update counts.

        Raises:
            RemoteRequirementError: Raised when the project is not remote-enabled.
        """
        if not self.is_project_remote_requirement_enabled(project_obj):
            raise RemoteRequirementError(
                "Remote requirement collaboration is not enabled for this project."
            )
        repo_root_path = Path(project_obj.repo_path).expanduser().resolve()
        remote_name_str = self._resolve_remote_name(project_obj, "main")
        branch_prefix_str = self._normalize_branch_prefix(
            project_obj.remote_requirement_branch_prefix
        )
        remote_branch_manifest_list = self._git_repository.list_remote_branch_manifests(
            repo_root_path,
            remote_name_str,
            branch_prefix_str,
        )

        imported_count_int = 0
        updated_count_int = 0
        skipped_count_int = 0
        for remote_branch_manifest in remote_branch_manifest_list:
            manifest = remote_branch_manifest.manifest
            if manifest.task_branch_name != remote_branch_manifest.branch_name_str:
                skipped_count_int += 1
                continue

            resolved_lifecycle_status = self._parse_lifecycle_status(
                manifest.lifecycle_status
            )
            resolved_workflow_stage = self._parse_workflow_stage(
                manifest.workflow_stage
            )
            resolved_closed_at = self._to_naive_datetime(manifest.closed_at)
            resolved_github_pr_url = manifest.github_pr_url
            resolved_github_pr_number = manifest.github_pr_number
            resolved_github_pr_state = manifest.github_pr_state
            if manifest.github_pr_number is not None:
                try:
                    pull_request_metadata = self._github_adapter.get_pull_request(
                        repository_full_name_str=(
                            self._resolve_github_repository_full_name(project_obj)
                        ),
                        pull_request_number_int=manifest.github_pr_number,
                    )
                except RemoteRequirementError:
                    pull_request_metadata = None
                if pull_request_metadata is not None:
                    resolved_github_pr_url = pull_request_metadata.url
                    resolved_github_pr_number = pull_request_metadata.number
                    resolved_github_pr_state = pull_request_metadata.state
                    if pull_request_metadata.merged:
                        resolved_lifecycle_status = TaskLifecycleStatus.CLOSED
                        resolved_workflow_stage = WorkflowStage.DONE
                        resolved_closed_at = utc_now_naive()

            task_obj = (
                db_session.query(Task).filter(Task.id == manifest.task_id).first()
            )
            if task_obj is None:
                task_obj = Task(
                    id=manifest.task_id,
                    run_account_id=run_account_id_str,
                    project_id=project_obj.id,
                    task_title=manifest.task_title,
                    lifecycle_status=resolved_lifecycle_status,
                    workflow_stage=resolved_workflow_stage,
                    stage_updated_at=utc_now_naive(),
                    worktree_base_branch_name=manifest.worktree_base_branch_name,
                    requirement_brief=manifest.requirement_brief,
                    created_at=self._to_naive_datetime(manifest.created_at)
                    or utc_now_naive(),
                    closed_at=resolved_closed_at,
                )
                db_session.add(task_obj)
                imported_count_int += 1
            else:
                if task_obj.project_id and task_obj.project_id != project_obj.id:
                    skipped_count_int += 1
                    continue
                if task_obj.remote_requirement_sync_status == (
                    REMOTE_REQUIREMENT_SYNC_STATUS_CONFLICT
                ):
                    skipped_count_int += 1
                    continue
                if self._should_skip_existing_task_during_remote_sync(
                    task_obj,
                    manifest.updated_at,
                    remote_branch_manifest.commit_hash_str,
                ):
                    skipped_count_int += 1
                    continue
                if (
                    task_obj.lifecycle_status == TaskLifecycleStatus.CLOSED
                    and resolved_lifecycle_status != TaskLifecycleStatus.CLOSED
                ):
                    skipped_count_int += 1
                    continue
                from backend.dsl.services.automation_runner import (
                    is_task_automation_running,
                )

                if is_task_automation_running(task_obj.id):
                    skipped_count_int += 1
                    continue
                task_obj.project_id = project_obj.id
                task_obj.task_title = manifest.task_title
                task_obj.requirement_brief = manifest.requirement_brief
                task_obj.lifecycle_status = resolved_lifecycle_status
                task_obj.workflow_stage = resolved_workflow_stage
                task_obj.closed_at = resolved_closed_at
                updated_count_int += 1

            task_obj.task_branch_name = manifest.task_branch_name
            task_obj.worktree_base_branch_name = manifest.worktree_base_branch_name
            task_obj.remote_requirement_manifest_path = (
                remote_branch_manifest.manifest_relative_path_str
            )
            task_obj.remote_requirement_synced_commit_hash = (
                remote_branch_manifest.commit_hash_str
            )
            task_obj.remote_requirement_sync_status = (
                REMOTE_REQUIREMENT_SYNC_STATUS_PR_MERGED
                if (
                    resolved_lifecycle_status == TaskLifecycleStatus.CLOSED
                    and resolved_github_pr_state == "merged"
                )
                else REMOTE_REQUIREMENT_SYNC_STATUS_IMPORTED
            )
            task_obj.remote_requirement_last_synced_at = utc_now_naive()
            task_obj.remote_requirement_last_error = None
            task_obj.github_pr_url = resolved_github_pr_url
            task_obj.github_pr_number = resolved_github_pr_number
            task_obj.github_pr_state = resolved_github_pr_state
            task_obj.last_progress_pushed_at = self._to_naive_datetime(
                manifest.last_progress_pushed_at
            )

        db_session.commit()
        return RemoteRequirementSyncOutcome(
            imported_count=imported_count_int,
            updated_count=updated_count_int,
            skipped_count=skipped_count_int,
        )

    @staticmethod
    def _parse_lifecycle_status(raw_lifecycle_status_str: str) -> TaskLifecycleStatus:
        """Parse a manifest lifecycle value.

        Args:
            raw_lifecycle_status_str: Raw lifecycle status value.

        Returns:
            TaskLifecycleStatus: Parsed lifecycle status.
        """
        try:
            return TaskLifecycleStatus(raw_lifecycle_status_str)
        except ValueError:
            return TaskLifecycleStatus.PENDING

    @staticmethod
    def _parse_workflow_stage(raw_workflow_stage_str: str) -> WorkflowStage:
        """Parse a manifest workflow stage value.

        Args:
            raw_workflow_stage_str: Raw workflow stage value.

        Returns:
            WorkflowStage: Parsed workflow stage.
        """
        try:
            return WorkflowStage(raw_workflow_stage_str)
        except ValueError:
            return WorkflowStage.BACKLOG
