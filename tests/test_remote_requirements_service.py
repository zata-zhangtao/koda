"""Tests for remote branch and PR-backed requirement collaboration."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.dsl.models.enums import TaskLifecycleStatus, WorkflowStage
from backend.dsl.models.project import Project
from backend.dsl.models.run_account import RunAccount
from backend.dsl.models.task import Task
from backend.dsl.remote_requirements.domain import (
    PullRequestMetadata,
    RemoteRequirementConflictError,
    RemoteRequirementError,
)
from backend.dsl.remote_requirements.service import RemoteRequirementService
from backend.dsl.schemas.task_schema import TaskCreateSchema
from backend.dsl.services.task_service import TaskService
from utils.database import Base


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite session for remote requirement tests."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    test_session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )
    Base.metadata.create_all(bind=test_engine)

    session = test_session_factory()
    try:
        yield session
    finally:
        session.close()


class FakePullRequestAdapter:
    """In-memory pull request adapter for service tests."""

    def __init__(self) -> None:
        """Initialize fake adapter state."""
        self.created_request_list: list[dict[str, str]] = []

    def create_or_get_pull_request(
        self,
        *,
        repository_full_name_str: str,
        head_owner_login_str: str,
        branch_name_str: str,
        base_branch_name_str: str,
        title_str: str,
        body_str: str,
    ) -> PullRequestMetadata:
        """Return deterministic pull request metadata.

        Args:
            repository_full_name_str: GitHub repository full name.
            head_owner_login_str: Head owner login.
            branch_name_str: Task branch name.
            base_branch_name_str: Base branch name.
            title_str: Pull request title.
            body_str: Pull request body.

        Returns:
            PullRequestMetadata: Fake PR metadata.
        """
        self.created_request_list.append(
            {
                "repository": repository_full_name_str,
                "head_owner": head_owner_login_str,
                "branch": branch_name_str,
                "base": base_branch_name_str,
                "title": title_str,
                "body": body_str,
            }
        )
        return PullRequestMetadata(
            number=128,
            url="https://github.com/example/demo-repo/pull/128",
            state="open",
        )

    def get_pull_request(
        self,
        *,
        repository_full_name_str: str,
        pull_request_number_int: int,
    ) -> PullRequestMetadata:
        """Return merged fake PR metadata.

        Args:
            repository_full_name_str: GitHub repository full name.
            pull_request_number_int: Pull request number.

        Returns:
            PullRequestMetadata: Fake merged PR metadata.
        """
        return PullRequestMetadata(
            number=pull_request_number_int,
            url=f"https://github.com/{repository_full_name_str}/pull/{pull_request_number_int}",
            state="merged",
            merged=True,
        )


class FailingPullRequestAdapter:
    """Pull request adapter that simulates provider failure."""

    def create_or_get_pull_request(
        self,
        *,
        repository_full_name_str: str,
        head_owner_login_str: str,
        branch_name_str: str,
        base_branch_name_str: str,
        title_str: str,
        body_str: str,
    ) -> PullRequestMetadata:
        """Raise a deterministic remote requirement error.

        Args:
            repository_full_name_str: GitHub repository full name.
            head_owner_login_str: Head owner login.
            branch_name_str: Task branch name.
            base_branch_name_str: Base branch name.
            title_str: Pull request title.
            body_str: Pull request body.

        Raises:
            RemoteRequirementError: Always raised for this fake adapter.
        """
        raise RemoteRequirementError("GitHub token missing")


def _run_git_command(repo_root_path: Path, git_argument_list: list[str]) -> str:
    """Run a Git command and return stdout.

    Args:
        repo_root_path: Repository path.
        git_argument_list: Git arguments without ``git -C``.

    Returns:
        str: Trimmed stdout.
    """
    completed_process = subprocess.run(
        ["git", "-C", str(repo_root_path), *git_argument_list],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed_process.stdout.strip()


def _create_repo_with_bare_remote(tmp_path: Path) -> tuple[Path, Path]:
    """Create a Git repository with an origin bare remote.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        tuple[Path, Path]: Working repo path and bare remote path.
    """
    repo_root_path = tmp_path / "demo-repo"
    bare_remote_path = tmp_path / "demo-remote.git"
    subprocess.run(
        ["git", "init", "-b", "main", str(repo_root_path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "init", "--bare", str(bare_remote_path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    _run_git_command(repo_root_path, ["config", "user.email", "tester@example.com"])
    _run_git_command(repo_root_path, ["config", "user.name", "Tester"])
    (repo_root_path / "README.md").write_text("hello\n", encoding="utf-8")
    _run_git_command(repo_root_path, ["add", "README.md"])
    _run_git_command(repo_root_path, ["commit", "-m", "init"])
    _run_git_command(repo_root_path, ["remote", "add", "origin", str(bare_remote_path)])
    _run_git_command(repo_root_path, ["push", "-u", "origin", "main"])
    return repo_root_path, bare_remote_path


def _clone_repo_from_bare_remote(
    bare_remote_path: Path,
    clone_parent_path: Path,
    clone_name_str: str,
) -> Path:
    """Clone a bare remote into a second local working repository.

    Args:
        bare_remote_path: Bare remote path to clone.
        clone_parent_path: Directory that will contain the clone.
        clone_name_str: Clone directory name.

    Returns:
        Path: Cloned repository root path.
    """
    clone_repo_path = clone_parent_path / clone_name_str
    subprocess.run(
        [
            "git",
            "clone",
            "--branch",
            "main",
            str(bare_remote_path),
            str(clone_repo_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    _run_git_command(clone_repo_path, ["config", "user.email", "tester@example.com"])
    _run_git_command(clone_repo_path, ["config", "user.name", "Tester"])
    return clone_repo_path


def _read_remote_manifest(
    bare_remote_path: Path,
    branch_name_str: str,
    task_id_str: str,
) -> dict[str, object]:
    """Read a manifest directly from the bare remote.

    Args:
        bare_remote_path: Bare remote path.
        branch_name_str: Task branch name.
        task_id_str: Task UUID.

    Returns:
        dict[str, object]: Parsed manifest payload.
    """
    manifest_json_text = _run_git_command(
        bare_remote_path,
        ["show", f"{branch_name_str}:.koda/requirements/{task_id_str}.json"],
    )
    return json.loads(manifest_json_text)


def _create_remote_enabled_project(
    db_session: Session,
    repo_root_path: Path,
    *,
    github_pr_creation_enabled: bool = True,
) -> tuple[RunAccount, Project]:
    """Create a run account and remote-enabled project row.

    Args:
        db_session: Database session.
        repo_root_path: Project repository root.
        github_pr_creation_enabled: Whether project Complete should create a PR.

    Returns:
        tuple[RunAccount, Project]: Created account and project.
    """
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    project_obj = Project(
        display_name="demo-repo",
        repo_path=str(repo_root_path),
        repo_remote_url=None,
        repo_head_commit_hash=None,
        worktree_resource_policy_json=json.dumps(
            {"confirmation_status": "accepted_default", "rules": []}
        ),
        remote_requirement_management_enabled=True,
        remote_requirement_branch_prefix="task",
        remote_requirement_remote_name="origin",
        github_pr_creation_enabled=github_pr_creation_enabled,
        github_repository_full_name="example/demo-repo",
        description=None,
    )
    db_session.add_all([run_account_obj, project_obj])
    db_session.commit()
    return run_account_obj, project_obj


def test_remote_enabled_task_creation_pushes_manifest_branch(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Creating a task in remote mode should push one manifest branch."""
    repo_root_path, bare_remote_path = _create_repo_with_bare_remote(tmp_path)
    run_account_obj, project_obj = _create_remote_enabled_project(
        db_session,
        repo_root_path,
    )

    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=TaskCreateSchema(
            task_title="Remote branch collaboration",
            project_id=project_obj.id,
            requirement_brief="Create a remote branch and manifest.",
        ),
        run_account_id=run_account_obj.id,
    )

    assert created_task.task_branch_name is not None
    assert created_task.task_branch_name.startswith(f"task/{created_task.id[:8]}")
    assert created_task.remote_requirement_manifest_path == (
        f".koda/requirements/{created_task.id}.json"
    )
    assert created_task.remote_requirement_sync_status == "created"
    manifest_payload = _read_remote_manifest(
        bare_remote_path,
        created_task.task_branch_name,
        created_task.id,
    )
    assert manifest_payload["task_id"] == created_task.id
    assert manifest_payload["task_title"] == "Remote branch collaboration"
    assert manifest_payload["task_branch_name"] == created_task.task_branch_name


def test_remote_enabled_task_creation_failure_marks_local_projection_failed(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Remote creation setup failures should leave retryable failure metadata."""
    repo_root_path, _bare_remote_path = _create_repo_with_bare_remote(tmp_path)
    run_account_obj, project_obj = _create_remote_enabled_project(
        db_session,
        repo_root_path,
    )
    project_obj.github_repository_full_name = None
    project_obj.repo_remote_url = None
    db_session.commit()

    with pytest.raises(RemoteRequirementError):
        TaskService.create_task(
            db_session=db_session,
            task_create_schema=TaskCreateSchema(
                task_title="Missing GitHub repository metadata",
                project_id=project_obj.id,
            ),
            run_account_id=run_account_obj.id,
        )

    failed_task_obj = db_session.query(Task).one()
    assert failed_task_obj.remote_requirement_sync_status == "failed"
    assert "GitHub PR creation requires" in (
        failed_task_obj.remote_requirement_last_error or ""
    )


def test_remote_backed_start_reuses_persisted_task_branch(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Starting a remote-backed task should create its worktree from persisted branch."""
    repo_root_path, _bare_remote_path = _create_repo_with_bare_remote(tmp_path)
    run_account_obj, project_obj = _create_remote_enabled_project(
        db_session,
        repo_root_path,
    )
    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=TaskCreateSchema(
            task_title="Reuse remote branch",
            project_id=project_obj.id,
        ),
        run_account_id=run_account_obj.id,
    )

    started_task = TaskService.start_task(db_session, created_task.id)

    assert started_task is not None
    assert started_task.worktree_path is not None
    checked_out_branch_name = _run_git_command(
        Path(started_task.worktree_path),
        ["branch", "--show-current"],
    )
    assert checked_out_branch_name == created_task.task_branch_name


def test_push_progress_commits_and_pushes_without_creating_pr(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Push Progress should push branch changes and leave PR metadata empty."""
    repo_root_path, bare_remote_path = _create_repo_with_bare_remote(tmp_path)
    run_account_obj, project_obj = _create_remote_enabled_project(
        db_session,
        repo_root_path,
    )
    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=TaskCreateSchema(
            task_title="Push progress",
            project_id=project_obj.id,
        ),
        run_account_id=run_account_obj.id,
    )
    started_task = TaskService.start_task(db_session, created_task.id)
    assert started_task is not None
    assert started_task.worktree_path is not None
    worktree_path = Path(started_task.worktree_path)
    (worktree_path / "progress.txt").write_text("draft\n", encoding="utf-8")

    pushed_task = RemoteRequirementService().push_progress(
        db_session,
        started_task.id,
    )

    assert pushed_task is not None
    assert pushed_task.remote_requirement_sync_status == "pushed"
    assert pushed_task.github_pr_url is None
    remote_branch_head_hash = _run_git_command(
        bare_remote_path,
        ["rev-parse", pushed_task.task_branch_name or ""],
    )
    assert remote_branch_head_hash == pushed_task.remote_requirement_synced_commit_hash


def test_push_progress_persists_conflict_status_when_remote_advanced(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Stale Push Progress should persist conflict state before raising."""
    repo_root_path, bare_remote_path = _create_repo_with_bare_remote(tmp_path)
    run_account_obj, project_obj = _create_remote_enabled_project(
        db_session,
        repo_root_path,
    )
    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=TaskCreateSchema(
            task_title="Detect stale branch",
            project_id=project_obj.id,
        ),
        run_account_id=run_account_obj.id,
    )
    started_task = TaskService.start_task(db_session, created_task.id)
    assert started_task is not None
    assert started_task.worktree_path is not None

    other_clone_path = tmp_path / "other-clone"
    subprocess.run(
        ["git", "clone", str(bare_remote_path), str(other_clone_path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    _run_git_command(other_clone_path, ["config", "user.email", "tester@example.com"])
    _run_git_command(other_clone_path, ["config", "user.name", "Tester"])
    _run_git_command(
        other_clone_path, ["checkout", created_task.task_branch_name or ""]
    )
    (other_clone_path / "remote-change.txt").write_text(
        "advanced remotely\n",
        encoding="utf-8",
    )
    _run_git_command(other_clone_path, ["add", "remote-change.txt"])
    _run_git_command(other_clone_path, ["commit", "-m", "remote advance"])
    _run_git_command(
        other_clone_path, ["push", "origin", created_task.task_branch_name or ""]
    )

    with pytest.raises(RemoteRequirementConflictError):
        RemoteRequirementService().push_progress(db_session, started_task.id)

    db_session.refresh(started_task)
    assert started_task.remote_requirement_sync_status == "conflict"
    assert "advanced since the last local sync" in (
        started_task.remote_requirement_last_error or ""
    )


def test_push_progress_remote_unavailable_raises_and_marks_failed(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Push Progress should not report success when the configured remote fails."""
    repo_root_path, _bare_remote_path = _create_repo_with_bare_remote(tmp_path)
    run_account_obj, project_obj = _create_remote_enabled_project(
        db_session,
        repo_root_path,
    )
    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=TaskCreateSchema(
            task_title="Remote unavailable",
            project_id=project_obj.id,
        ),
        run_account_id=run_account_obj.id,
    )
    started_task = TaskService.start_task(db_session, created_task.id)
    assert started_task is not None
    assert started_task.worktree_path is not None

    project_obj.remote_requirement_remote_name = "missing-remote"
    db_session.commit()

    with pytest.raises(RemoteRequirementError):
        RemoteRequirementService().push_progress(db_session, started_task.id)

    db_session.refresh(started_task)
    assert started_task.remote_requirement_sync_status == "failed"
    assert "Git command failed" in (started_task.remote_requirement_last_error or "")


def test_manifest_state_update_preserves_existing_prd_relative_path(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Later manifest writes should keep the staged PRD path."""
    repo_root_path, bare_remote_path = _create_repo_with_bare_remote(tmp_path)
    run_account_obj, project_obj = _create_remote_enabled_project(
        db_session,
        repo_root_path,
    )
    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=TaskCreateSchema(
            task_title="Preserve PRD path",
            project_id=project_obj.id,
        ),
        run_account_id=run_account_obj.id,
    )
    started_task = TaskService.start_task(db_session, created_task.id)
    assert started_task is not None
    assert started_task.worktree_path is not None

    RemoteRequirementService().update_manifest_after_prd_staging(
        db_session,
        started_task.id,
        "tasks/20260428-123000-prd-preserve-path.md",
    )
    db_session.refresh(started_task)
    started_task.task_title = "Renamed after PRD"
    db_session.commit()

    synced_task = RemoteRequirementService().update_manifest_after_task_state_change(
        db_session,
        started_task.id,
        commit_message_text="chore(koda): sync renamed requirement",
    )

    assert synced_task is not None
    manifest_payload = _read_remote_manifest(
        bare_remote_path,
        synced_task.task_branch_name or "",
        synced_task.id,
    )
    assert manifest_payload["task_title"] == "Renamed after PRD"
    assert (
        manifest_payload["prd_relative_path"]
        == "tasks/20260428-123000-prd-preserve-path.md"
    )


def test_project_remote_sync_imports_manifest_backed_cards(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Remote sync should materialize a missing local Task from branch manifest."""
    repo_root_path, _bare_remote_path = _create_repo_with_bare_remote(tmp_path)
    run_account_obj, project_obj = _create_remote_enabled_project(
        db_session,
        repo_root_path,
    )
    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=TaskCreateSchema(
            task_title="Sync me back",
            project_id=project_obj.id,
        ),
        run_account_id=run_account_obj.id,
    )
    db_session.delete(created_task)
    db_session.commit()

    sync_outcome = RemoteRequirementService().sync_project_remote_requirements(
        db_session,
        project_obj,
        run_account_obj.id,
    )

    imported_task = db_session.get(Task, created_task.id)
    assert sync_outcome.imported_count == 1
    assert imported_task is not None
    assert imported_task.task_title == "Sync me back"
    assert imported_task.task_branch_name == created_task.task_branch_name
    assert imported_task.remote_requirement_sync_status == "imported"


def test_project_remote_sync_skips_failed_local_projection(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Remote sync should not overwrite locally failed unsynced task edits."""
    repo_root_path, _bare_remote_path = _create_repo_with_bare_remote(tmp_path)
    run_account_obj, project_obj = _create_remote_enabled_project(
        db_session,
        repo_root_path,
    )
    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=TaskCreateSchema(
            task_title="Remote version",
            requirement_brief="Remote brief",
            project_id=project_obj.id,
        ),
        run_account_id=run_account_obj.id,
    )
    created_task.task_title = "Local failed title"
    created_task.requirement_brief = "Local failed brief"
    created_task.remote_requirement_sync_status = "failed"
    created_task.remote_requirement_last_error = "push failed before sync"
    db_session.commit()

    sync_outcome = RemoteRequirementService().sync_project_remote_requirements(
        db_session,
        project_obj,
        run_account_obj.id,
    )

    db_session.refresh(created_task)
    assert sync_outcome.imported_count == 0
    assert sync_outcome.updated_count == 0
    assert sync_outcome.skipped_count == 1
    assert created_task.task_title == "Local failed title"
    assert created_task.requirement_brief == "Local failed brief"
    assert created_task.remote_requirement_sync_status == "failed"
    assert created_task.remote_requirement_last_error == "push failed before sync"


def test_imported_remote_task_start_uses_remote_tracking_branch(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Starting an imported task should preserve the remote manifest branch."""
    source_repo_path, bare_remote_path = _create_repo_with_bare_remote(tmp_path)
    source_run_account_obj, source_project_obj = _create_remote_enabled_project(
        db_session,
        source_repo_path,
    )
    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=TaskCreateSchema(
            task_title="Resume on second machine",
            requirement_brief="Import and start the persisted remote task branch.",
            project_id=source_project_obj.id,
        ),
        run_account_id=source_run_account_obj.id,
    )
    created_task_id_str = created_task.id
    created_task_branch_name_str = created_task.task_branch_name or ""
    db_session.delete(created_task)
    db_session.commit()

    clone_repo_path = _clone_repo_from_bare_remote(
        bare_remote_path,
        tmp_path,
        "second-demo-repo",
    )
    second_run_account_obj, second_project_obj = _create_remote_enabled_project(
        db_session,
        clone_repo_path,
    )

    sync_outcome = RemoteRequirementService().sync_project_remote_requirements(
        db_session,
        second_project_obj,
        second_run_account_obj.id,
    )
    assert sync_outcome.imported_count == 1

    started_task = TaskService.start_task(db_session, created_task_id_str)
    assert started_task is not None
    assert started_task.task_branch_name == created_task_branch_name_str
    assert started_task.worktree_path is not None

    worktree_path = Path(started_task.worktree_path)
    checked_out_branch_name = _run_git_command(
        worktree_path,
        ["branch", "--show-current"],
    )
    assert checked_out_branch_name == created_task_branch_name_str
    assert (worktree_path / f".koda/requirements/{created_task_id_str}.json").exists()


def test_project_remote_sync_skips_running_existing_tasks(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote sync should not overwrite a task while automation is running."""
    repo_root_path, _bare_remote_path = _create_repo_with_bare_remote(tmp_path)
    run_account_obj, project_obj = _create_remote_enabled_project(
        db_session,
        repo_root_path,
    )
    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=TaskCreateSchema(
            task_title="Do not overwrite while running",
            project_id=project_obj.id,
        ),
        run_account_id=run_account_obj.id,
    )
    monkeypatch.setattr(
        "backend.dsl.services.automation_runner.is_task_automation_running",
        lambda task_id_str: task_id_str == created_task.id,
    )

    sync_outcome = RemoteRequirementService().sync_project_remote_requirements(
        db_session,
        project_obj,
        run_account_obj.id,
    )

    assert sync_outcome.imported_count == 0
    assert sync_outcome.updated_count == 0
    assert sync_outcome.skipped_count == 1


def test_complete_as_pull_request_records_pr_metadata_and_waits_for_review(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Remote-backed Complete should create a PR and keep the task open."""
    repo_root_path, _bare_remote_path = _create_repo_with_bare_remote(tmp_path)
    run_account_obj, project_obj = _create_remote_enabled_project(
        db_session,
        repo_root_path,
        github_pr_creation_enabled=True,
    )
    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=TaskCreateSchema(
            task_title="Create PR",
            project_id=project_obj.id,
        ),
        run_account_id=run_account_obj.id,
    )
    started_task = TaskService.start_task(db_session, created_task.id)
    assert started_task is not None
    assert started_task.worktree_path is not None
    started_task.workflow_stage = WorkflowStage.SELF_REVIEW_IN_PROGRESS
    db_session.commit()
    (Path(started_task.worktree_path) / "feature.txt").write_text(
        "ready\n",
        encoding="utf-8",
    )
    fake_pr_adapter = FakePullRequestAdapter()

    completed_task = RemoteRequirementService(
        github_adapter=fake_pr_adapter,
    ).complete_as_pull_request(db_session, started_task.id)

    assert completed_task is not None
    assert completed_task.workflow_stage == WorkflowStage.ACCEPTANCE_IN_PROGRESS
    assert completed_task.lifecycle_status == TaskLifecycleStatus.OPEN
    assert completed_task.github_pr_number == 128
    assert completed_task.github_pr_state == "open"
    assert completed_task.remote_requirement_sync_status == "pr_open"
    assert fake_pr_adapter.created_request_list[0]["branch"] == (
        completed_task.task_branch_name
    )


def test_complete_as_pull_request_failure_marks_task_retryable(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Provider failures should leave a retryable task with visible remote error."""
    repo_root_path, _bare_remote_path = _create_repo_with_bare_remote(tmp_path)
    run_account_obj, project_obj = _create_remote_enabled_project(
        db_session,
        repo_root_path,
        github_pr_creation_enabled=True,
    )
    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=TaskCreateSchema(
            task_title="PR failure is retryable",
            project_id=project_obj.id,
        ),
        run_account_id=run_account_obj.id,
    )
    started_task = TaskService.start_task(db_session, created_task.id)
    assert started_task is not None
    assert started_task.worktree_path is not None
    started_task.workflow_stage = WorkflowStage.SELF_REVIEW_IN_PROGRESS
    db_session.commit()
    (Path(started_task.worktree_path) / "feature.txt").write_text(
        "ready\n",
        encoding="utf-8",
    )

    with pytest.raises(RemoteRequirementError):
        RemoteRequirementService(
            github_adapter=FailingPullRequestAdapter(),
        ).complete_as_pull_request(db_session, started_task.id)

    db_session.refresh(started_task)
    assert started_task.workflow_stage == WorkflowStage.CHANGES_REQUESTED
    assert started_task.lifecycle_status == TaskLifecycleStatus.OPEN
    assert started_task.remote_requirement_sync_status == "failed"
    assert started_task.remote_requirement_last_error == "GitHub token missing"


def test_prd_manifest_update_noops_for_local_only_tasks(
    db_session: Session,
) -> None:
    """PRD staging hooks should leave local-only tasks without remote failures."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()
    local_task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title="Local only",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.BACKLOG,
    )
    db_session.add(local_task_obj)
    db_session.commit()

    RemoteRequirementService().update_manifest_after_prd_staging(
        db_session,
        local_task_obj.id,
        "tasks/prd-local.md",
    )

    db_session.refresh(local_task_obj)
    assert local_task_obj.remote_requirement_sync_status is None
    assert local_task_obj.remote_requirement_last_error is None


def test_sync_pull_request_status_closes_merged_remote_task(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """PR status sync should close a task after the PR is merged."""
    repo_root_path, _bare_remote_path = _create_repo_with_bare_remote(tmp_path)
    run_account_obj, project_obj = _create_remote_enabled_project(
        db_session,
        repo_root_path,
    )
    task_obj = Task(
        run_account_id=run_account_obj.id,
        project_id=project_obj.id,
        task_title="Merged PR",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.ACCEPTANCE_IN_PROGRESS,
        task_branch_name="task/12345678-merged-pr",
        github_pr_number=129,
    )
    db_session.add(task_obj)
    db_session.commit()

    synced_task = RemoteRequirementService(
        github_adapter=FakePullRequestAdapter(),
    ).sync_pull_request_status(db_session, task_obj.id)

    assert synced_task is not None
    assert synced_task.workflow_stage == WorkflowStage.DONE
    assert synced_task.lifecycle_status == TaskLifecycleStatus.CLOSED
    assert synced_task.github_pr_state == "merged"
    assert synced_task.remote_requirement_sync_status == "pr_merged"
