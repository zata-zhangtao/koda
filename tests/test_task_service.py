"""Tests for task creation project-link behavior."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import pytest

from dsl.models.enums import TaskLifecycleStatus, WorkflowStage
from dsl.models.project import Project
from dsl.models.run_account import RunAccount
from dsl.schemas.task_schema import TaskCreateSchema
from dsl.services.task_service import TaskService
from utils.database import Base


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite session for task service tests."""
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
    """Run a Git command inside a temporary repository.

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


def _create_git_repo(repo_root_path: Path) -> Path:
    """Create a real Git repository on `main` with one commit.

    Args:
        repo_root_path: Repository root path

    Returns:
        Path: Created repository root path
    """
    repo_root_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main", str(repo_root_path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    _run_git_command(repo_root_path, ["config", "user.email", "tester@example.com"])
    _run_git_command(repo_root_path, ["config", "user.name", "Tester"])

    tracked_file_path = repo_root_path / "README.md"
    tracked_file_path.write_text("hello\n", encoding="utf-8")
    _run_git_command(repo_root_path, ["add", "README.md"])
    _run_git_command(repo_root_path, ["commit", "-m", "init"])
    return repo_root_path


def test_create_task_persists_selected_project_id(db_session: Session) -> None:
    """Task creation should store the exact selected project ID."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    project_one_obj = Project(
        display_name="project1",
        repo_path="/tmp/project1",
        description=None,
    )
    project_two_obj = Project(
        display_name="project2",
        repo_path="/tmp/project2",
        description=None,
    )
    db_session.add_all([run_account_obj, project_one_obj, project_two_obj])
    db_session.commit()

    task_create_schema = TaskCreateSchema(
        task_title="Link to project2",
        project_id=project_two_obj.id,
    )

    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=task_create_schema,
        run_account_id=run_account_obj.id,
    )

    reloaded_task = TaskService.get_task_by_id(db_session, created_task.id)

    assert reloaded_task is not None
    assert reloaded_task.project_id == project_two_obj.id
    assert reloaded_task.project_id != project_one_obj.id


def test_create_task_rejects_missing_project_id(db_session: Session) -> None:
    """Task creation should fail when the submitted project ID does not exist."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    task_create_schema = TaskCreateSchema(
        task_title="Invalid project",
        project_id="missing-project-id",
    )

    with pytest.raises(
        ValueError, match="Project with id missing-project-id not found"
    ):
        TaskService.create_task(
            db_session=db_session,
            task_create_schema=task_create_schema,
            run_account_id=run_account_obj.id,
        )


def test_create_task_allows_unlinked_tasks(db_session: Session) -> None:
    """Task creation should still allow tasks without a linked project."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    task_create_schema = TaskCreateSchema(
        task_title="Standalone task",
        project_id=None,
    )

    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=task_create_schema,
        run_account_id=run_account_obj.id,
    )

    assert created_task.project_id is None
    assert created_task.lifecycle_status.value == "PENDING"


def test_prepare_task_completion_moves_worktree_task_into_pr_preparing(
    db_session: Session,
) -> None:
    """Completion should move eligible worktree tasks into pr_preparing."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    task_create_schema = TaskCreateSchema(task_title="Finalize branch")
    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=task_create_schema,
        run_account_id=run_account_obj.id,
    )
    created_task.worktree_path = "/tmp/project-wt-12345678"
    created_task.workflow_stage = WorkflowStage.SELF_REVIEW_IN_PROGRESS
    created_task.lifecycle_status = TaskLifecycleStatus.OPEN
    db_session.commit()

    updated_task = TaskService.prepare_task_completion(db_session, created_task.id)

    assert updated_task is not None
    assert updated_task.workflow_stage == WorkflowStage.PR_PREPARING
    assert updated_task.lifecycle_status == TaskLifecycleStatus.OPEN


def test_prepare_task_completion_rejects_tasks_without_worktree(
    db_session: Session,
) -> None:
    """Completion should fail when the task has no worktree path."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    task_create_schema = TaskCreateSchema(task_title="Finalize branch")
    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=task_create_schema,
        run_account_id=run_account_obj.id,
    )
    created_task.workflow_stage = WorkflowStage.SELF_REVIEW_IN_PROGRESS
    created_task.lifecycle_status = TaskLifecycleStatus.OPEN
    db_session.commit()

    with pytest.raises(ValueError, match="has no worktree_path"):
        TaskService.prepare_task_completion(db_session, created_task.id)


def test_start_task_persists_created_worktree_path_under_task_root(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Starting a linked task should persist the created `../task/...` worktree path."""
    repo_root_path = _create_git_repo(tmp_path / "demo-repo")
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
        description=None,
    )
    db_session.add_all([run_account_obj, project_obj])
    db_session.commit()

    task_create_schema = TaskCreateSchema(
        task_title="Create linked worktree",
        project_id=project_obj.id,
    )
    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=task_create_schema,
        run_account_id=run_account_obj.id,
    )

    started_task = TaskService.start_task(db_session, created_task.id)
    expected_worktree_path = (
        repo_root_path.parent
        / "task"
        / f"{repo_root_path.name}-wt-{created_task.id[:8]}"
    )

    assert started_task is not None
    assert started_task.workflow_stage == WorkflowStage.PRD_GENERATING
    assert started_task.worktree_path == str(expected_worktree_path)
    assert expected_worktree_path.exists() is True
    assert (
        _run_git_command(
            expected_worktree_path,
            ["symbolic-ref", "--short", "HEAD"],
        )
        == f"task/{created_task.id[:8]}"
    )
