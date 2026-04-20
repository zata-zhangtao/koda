"""Tests for project path validation and Git fingerprint consistency behavior."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.dsl.api.projects import _to_response
from backend.dsl.models.enums import TaskLifecycleStatus, WorkflowStage
from backend.dsl.models.project import Project
from backend.dsl.models.run_account import RunAccount
from backend.dsl.models.task import Task
from backend.dsl.schemas.project_schema import ProjectCreateSchema, ProjectUpdateSchema
from backend.dsl.services.project_service import ProjectService
from utils.database import Base
from utils.helpers import utc_now_naive


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite session for project service tests."""
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


def _run_git_command(repo_root_path: Path, git_argument_list: list[str]) -> str:
    """Run a Git command inside the temporary repository.

    Args:
        repo_root_path: Repository root path
        git_argument_list: Git argument list

    Returns:
        str: Trimmed stdout output
    """
    completed_process = subprocess.run(
        ["git", "-C", str(repo_root_path), *git_argument_list],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed_process.stdout.strip()


def _create_git_repo(
    repo_root_path: Path,
    *,
    remote_url: str | None,
    initial_file_name: str = "README.md",
    initial_file_content: str = "hello",
) -> Path:
    """Create a real Git repository with one commit for fingerprint tests.

    Args:
        repo_root_path: Repository root path
        remote_url: Remote origin URL to configure; None to skip
        initial_file_name: Initial tracked file name
        initial_file_content: Initial tracked file content

    Returns:
        Path: The created repository root path
    """
    repo_root_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", str(repo_root_path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    _run_git_command(repo_root_path, ["config", "user.email", "tester@example.com"])
    _run_git_command(repo_root_path, ["config", "user.name", "Tester"])
    if remote_url is not None:
        _run_git_command(repo_root_path, ["remote", "add", "origin", remote_url])

    tracked_file_path = repo_root_path / initial_file_name
    tracked_file_path.write_text(initial_file_content, encoding="utf-8")
    _run_git_command(repo_root_path, ["add", initial_file_name])
    _run_git_command(repo_root_path, ["commit", "-m", "init"])
    return repo_root_path


def test_create_project_persists_normalized_repo_path_and_git_fingerprint(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Project creation should store repo path plus normalized remote and HEAD."""
    repo_root_path = _create_git_repo(
        tmp_path / "demo-repo",
        remote_url="git@github.com:example/demo-repo.git",
    )
    repo_input_path_str = str(repo_root_path / ".." / "demo-repo")

    created_project = ProjectService.create_project(
        db_session=db_session,
        project_create_schema=ProjectCreateSchema(
            display_name="Demo Repo",
            project_category="backend",
            repo_path=repo_input_path_str,
            description="normalized path test",
        ),
    )

    expected_head_commit_hash = _run_git_command(repo_root_path, ["rev-parse", "HEAD"])

    assert created_project.repo_path == str(repo_root_path.resolve())
    assert created_project.project_category == "backend"
    assert ProjectService.is_repo_path_valid(created_project.repo_path) is True
    assert created_project.repo_remote_url == "github.com/example/demo-repo"
    assert created_project.repo_head_commit_hash == expected_head_commit_hash


def test_update_project_rebinds_repo_path_and_clears_missing_worktrees(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Rebinding should keep the synced fingerprint and clear missing worktrees."""
    original_repo_root_path = _create_git_repo(
        tmp_path / "repo-a",
        remote_url="https://github.com/example/portable-repo.git",
        initial_file_content="old machine",
    )
    rebound_repo_root_path = _create_git_repo(
        tmp_path / "repo-b",
        remote_url="git@github.com:example/portable-repo.git",
        initial_file_content="new machine clone",
    )
    existing_worktree_path = tmp_path / "existing-worktree"
    existing_worktree_path.mkdir()

    project_obj = Project(
        display_name="Portable Repo",
        project_category="legacy-sync",
        repo_path=str(original_repo_root_path),
        repo_remote_url="github.com/example/portable-repo",
        repo_head_commit_hash=_run_git_command(
            original_repo_root_path, ["rev-parse", "HEAD"]
        ),
        description="sync test",
    )
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add_all([project_obj, run_account_obj])
    db_session.commit()

    missing_worktree_task_obj = Task(
        run_account_id=run_account_obj.id,
        project_id=project_obj.id,
        task_title="Missing worktree",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.BACKLOG,
        worktree_path=str(tmp_path / "missing-worktree"),
    )
    existing_worktree_task_obj = Task(
        run_account_id=run_account_obj.id,
        project_id=project_obj.id,
        task_title="Existing worktree",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.BACKLOG,
        worktree_path=str(existing_worktree_path),
    )
    db_session.add_all([missing_worktree_task_obj, existing_worktree_task_obj])
    db_session.commit()

    updated_project = ProjectService.update_project(
        db_session=db_session,
        project_id=project_obj.id,
        project_update_schema=ProjectUpdateSchema(
            display_name="Portable Repo",
            project_category="platform",
            repo_path=str(rebound_repo_root_path),
            description="updated path",
        ),
    )

    assert updated_project is not None
    assert updated_project.repo_path == str(rebound_repo_root_path.resolve())
    assert updated_project.project_category == "platform"
    assert updated_project.repo_remote_url == "github.com/example/portable-repo"
    assert updated_project.repo_head_commit_hash == _run_git_command(
        original_repo_root_path,
        ["rev-parse", "HEAD"],
    )

    reloaded_missing_task_obj = db_session.get(Task, missing_worktree_task_obj.id)
    reloaded_existing_task_obj = db_session.get(Task, existing_worktree_task_obj.id)

    assert reloaded_missing_task_obj is not None
    assert reloaded_missing_task_obj.worktree_path is None
    assert reloaded_existing_task_obj is not None
    assert reloaded_existing_task_obj.worktree_path == str(existing_worktree_path)


def test_update_project_rejects_different_remote_repo(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Rebinding should fail if the selected repo points to a different remote."""
    original_repo_root_path = _create_git_repo(
        tmp_path / "repo-a",
        remote_url="https://github.com/example/service-a.git",
    )
    wrong_repo_root_path = _create_git_repo(
        tmp_path / "repo-b",
        remote_url="https://github.com/example/service-b.git",
    )

    project_obj = Project(
        display_name="Service A",
        repo_path=str(original_repo_root_path),
        repo_remote_url="github.com/example/service-a",
        repo_head_commit_hash=_run_git_command(
            original_repo_root_path, ["rev-parse", "HEAD"]
        ),
        description=None,
    )
    db_session.add(project_obj)
    db_session.commit()

    with pytest.raises(ValueError, match="origin remote"):
        ProjectService.update_project(
            db_session=db_session,
            project_id=project_obj.id,
            project_update_schema=ProjectUpdateSchema(
                display_name="Service A",
                repo_path=str(wrong_repo_root_path),
                description=None,
            ),
        )


def test_refresh_project_repo_fingerprints_updates_stored_head(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Refreshing fingerprints should advance the stored HEAD before WebDAV upload."""
    repo_root_path = _create_git_repo(
        tmp_path / "refreshable-repo",
        remote_url="https://github.com/example/refreshable.git",
    )
    initial_head_commit_hash = _run_git_command(repo_root_path, ["rev-parse", "HEAD"])

    project_obj = Project(
        display_name="Refreshable Repo",
        repo_path=str(repo_root_path),
        repo_remote_url="github.com/example/refreshable",
        repo_head_commit_hash=initial_head_commit_hash,
        description=None,
    )
    db_session.add(project_obj)
    db_session.commit()

    next_file_path = repo_root_path / "next.txt"
    next_file_path.write_text("next revision", encoding="utf-8")
    _run_git_command(repo_root_path, ["add", "next.txt"])
    _run_git_command(repo_root_path, ["commit", "-m", "next"])
    next_head_commit_hash = _run_git_command(repo_root_path, ["rev-parse", "HEAD"])

    updated_project_count_int = ProjectService.refresh_project_repo_fingerprints(
        db_session,
        only_missing=False,
    )

    refreshed_project_obj = db_session.get(Project, project_obj.id)

    assert updated_project_count_int == 1
    assert refreshed_project_obj is not None
    assert refreshed_project_obj.repo_head_commit_hash == next_head_commit_hash


def test_project_response_marks_invalid_repo_path_for_restored_projects() -> None:
    """Project responses should flag repo paths that are invalid on this machine."""
    restored_project_obj = Project(
        id="restored-project-id",
        display_name="Restored Repo",
        repo_path="/tmp/definitely-missing-koda-project-path",
        repo_remote_url="github.com/example/restored-repo",
        repo_head_commit_hash="abc1234567890",
        description="restored from another machine",
        created_at=utc_now_naive(),
    )

    project_response = _to_response(restored_project_obj)

    assert project_response.is_repo_path_valid is False
    assert project_response.repo_consistency_note is not None


def test_project_response_marks_head_mismatch_for_valid_repo(
    tmp_path: Path,
) -> None:
    """Project responses should surface commit drift when path is valid but HEAD changed."""
    repo_root_path = _create_git_repo(
        tmp_path / "drifted-repo",
        remote_url="https://github.com/example/drifted.git",
    )
    expected_head_commit_hash = _run_git_command(repo_root_path, ["rev-parse", "HEAD"])

    drift_file_path = repo_root_path / "drift.txt"
    drift_file_path.write_text("drift", encoding="utf-8")
    _run_git_command(repo_root_path, ["add", "drift.txt"])
    _run_git_command(repo_root_path, ["commit", "-m", "drift"])
    current_head_commit_hash = _run_git_command(repo_root_path, ["rev-parse", "HEAD"])

    restored_project_obj = Project(
        id="drifted-project-id",
        display_name="Drifted Repo",
        repo_path=str(repo_root_path),
        repo_remote_url="github.com/example/drifted",
        repo_head_commit_hash=expected_head_commit_hash,
        description="restored from another machine",
        created_at=utc_now_naive(),
    )

    project_response = _to_response(restored_project_obj)

    assert project_response.is_repo_path_valid is True
    assert project_response.is_repo_remote_consistent is True
    assert project_response.is_repo_head_consistent is False
    assert project_response.current_repo_head_commit_hash == current_head_commit_hash
