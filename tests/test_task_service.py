"""Tests for task creation project-link behavior."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import pytest

from dsl.models.dev_log import DevLog
from dsl.models.enums import TaskLifecycleStatus, WorkflowStage
from dsl.models.project import Project
from dsl.models.run_account import RunAccount
from dsl.models.task import Task
from dsl.schemas.task_schema import (
    TaskCreateSchema,
    TaskStageUpdateSchema,
    TaskStatusUpdateSchema,
    TaskUpdateSchema,
)
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
    assert created_task.stage_updated_at is not None
    assert created_task.auto_confirm_prd_and_execute is False


def test_create_task_persists_auto_confirm_prd_and_execute_flag(
    db_session: Session,
) -> None:
    """Task creation should persist the auto-confirm-and-execute flag."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=TaskCreateSchema(
            task_title="Auto execute after PRD",
            auto_confirm_prd_and_execute=True,
        ),
        run_account_id=run_account_obj.id,
    )

    assert created_task.auto_confirm_prd_and_execute is True


def test_update_task_allows_project_rebinding_for_backlog_tasks(
    db_session: Session,
) -> None:
    """Backlog tasks without a worktree should allow project rebinding."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    project_one_obj = Project(
        display_name="project-one",
        repo_path="/tmp/project-one",
        description=None,
    )
    project_two_obj = Project(
        display_name="project-two",
        repo_path="/tmp/project-two",
        description=None,
    )
    db_session.add_all([run_account_obj, project_one_obj, project_two_obj])
    db_session.commit()

    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=TaskCreateSchema(
            task_title="Needs rebind",
            project_id=project_one_obj.id,
            requirement_brief="old summary",
        ),
        run_account_id=run_account_obj.id,
    )

    updated_task = TaskService.update_task(
        db_session,
        created_task.id,
        TaskUpdateSchema(
            task_title="Needs rebind (edited)",
            requirement_brief="new summary",
            project_id=project_two_obj.id,
        ),
    )

    assert updated_task is not None
    assert updated_task.task_title == "Needs rebind (edited)"
    assert updated_task.requirement_brief == "new summary"
    assert updated_task.project_id == project_two_obj.id


def test_update_task_rejects_project_rebinding_after_task_start(
    db_session: Session,
) -> None:
    """Started tasks should reject project rebinding requests."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    project_one_obj = Project(
        display_name="project-one",
        repo_path="/tmp/project-one",
        description=None,
    )
    project_two_obj = Project(
        display_name="project-two",
        repo_path="/tmp/project-two",
        description=None,
    )
    db_session.add_all([run_account_obj, project_one_obj, project_two_obj])
    db_session.commit()

    started_task = Task(
        run_account_id=run_account_obj.id,
        task_title="Started task",
        project_id=project_one_obj.id,
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.PRD_GENERATING,
        worktree_path="/tmp/project-one-wt-12345678",
    )
    db_session.add(started_task)
    db_session.commit()

    with pytest.raises(
        ValueError,
        match=r"Only backlog tasks without a worktree can change project_id",
    ):
        TaskService.update_task(
            db_session,
            started_task.id,
            TaskUpdateSchema(
                task_title="Started task",
                project_id=project_two_obj.id,
            ),
        )


def test_destroy_task_records_reason_and_clears_worktree_path(
    db_session: Session,
) -> None:
    """Destroying a started task should persist reason metadata."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    started_task = Task(
        run_account_id=run_account_obj.id,
        task_title="Destroy target",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
        worktree_path="/tmp/project-wt-12345678",
    )
    db_session.add(started_task)
    db_session.commit()

    destroyed_task = TaskService.destroy_task(
        db_session,
        started_task.id,
        "Wrong repo binding, recreate from scratch",
    )

    assert destroyed_task is not None
    assert destroyed_task.lifecycle_status == TaskLifecycleStatus.DELETED
    assert destroyed_task.destroy_reason == "Wrong repo binding, recreate from scratch"
    assert destroyed_task.destroyed_at is not None
    assert destroyed_task.worktree_path is None


def test_update_task_status_rejects_started_task_deletion_via_legacy_status_route(
    db_session: Session,
) -> None:
    """Started tasks should not bypass destroy through the legacy status API."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    started_task = Task(
        run_account_id=run_account_obj.id,
        task_title="Started task",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.PRD_GENERATING,
        worktree_path="/tmp/project-wt-12345678",
    )
    db_session.add(started_task)
    db_session.commit()

    with pytest.raises(
        ValueError,
        match="Started tasks must use the destroy flow",
    ):
        TaskService.update_task_status(
            db_session,
            started_task.id,
            TaskStatusUpdateSchema(lifecycle_status=TaskLifecycleStatus.DELETED),
        )

    db_session.refresh(started_task)
    assert started_task.lifecycle_status == TaskLifecycleStatus.OPEN
    assert started_task.destroyed_at is None


def test_update_workflow_stage_refreshes_stage_updated_at_only_on_stage_change(
    db_session: Session,
) -> None:
    """Stage timestamps should only refresh when the task actually enters a new stage."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    created_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=TaskCreateSchema(task_title="Stage timestamp test"),
        run_account_id=run_account_obj.id,
    )
    original_stage_updated_at = created_task.stage_updated_at

    same_stage_task = TaskService.update_workflow_stage(
        db_session,
        created_task.id,
        TaskStageUpdateSchema(workflow_stage=WorkflowStage.BACKLOG),
    )
    assert same_stage_task is not None
    assert same_stage_task.stage_updated_at == original_stage_updated_at

    updated_task = TaskService.update_workflow_stage(
        db_session,
        created_task.id,
        TaskStageUpdateSchema(workflow_stage=WorkflowStage.PRD_GENERATING),
    )
    assert updated_task is not None
    assert updated_task.stage_updated_at >= original_stage_updated_at
    assert updated_task.workflow_stage == WorkflowStage.PRD_GENERATING


def test_get_task_log_count_map_returns_grouped_counts(db_session: Session) -> None:
    """Task log counts should be calculated with one grouped result map."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    first_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=TaskCreateSchema(task_title="First task"),
        run_account_id=run_account_obj.id,
    )
    second_task = TaskService.create_task(
        db_session=db_session,
        task_create_schema=TaskCreateSchema(task_title="Second task"),
        run_account_id=run_account_obj.id,
    )

    db_session.add_all(
        [
            DevLog(
                task_id=first_task.id,
                run_account_id=run_account_obj.id,
                text_content="one",
            ),
            DevLog(
                task_id=first_task.id,
                run_account_id=run_account_obj.id,
                text_content="two",
            ),
            DevLog(
                task_id=second_task.id,
                run_account_id=run_account_obj.id,
                text_content="three",
            ),
        ]
    )
    db_session.commit()

    task_log_count_map = TaskService.get_task_log_count_map(
        db_session,
        [first_task.id, second_task.id, "missing-task-id"],
    )

    assert task_log_count_map[first_task.id] == 2
    assert task_log_count_map[second_task.id] == 1
    assert "missing-task-id" not in task_log_count_map


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


def test_prepare_task_completion_rejects_changes_requested_tasks(
    db_session: Session,
) -> None:
    """Completion should reject worktree tasks that still require rerun after manual changes."""
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
    created_task.workflow_stage = WorkflowStage.CHANGES_REQUESTED
    created_task.lifecycle_status = TaskLifecycleStatus.OPEN
    db_session.commit()

    with pytest.raises(
        ValueError, match="cannot complete from stage 'changes_requested'"
    ):
        TaskService.prepare_task_completion(db_session, created_task.id)


def test_start_task_persists_created_worktree_path_under_task_root(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Starting a linked task should persist the created path and copy env files."""
    from utils.settings import Config

    monkeypatch.setattr(Config, "WORKTREE_BRANCH_AI_NAMING_ENABLED", False)

    repo_root_path = _create_git_repo(tmp_path / "demo-repo")
    source_env_file_path = repo_root_path / ".env"
    source_env_file_path.write_text("API_KEY=demo\n", encoding="utf-8")
    nested_source_env_file_path = repo_root_path / "frontend" / ".env.local"
    nested_source_env_file_path.parent.mkdir(parents=True, exist_ok=True)
    nested_source_env_file_path.write_text(
        "VITE_API_URL=http://localhost\n",
        encoding="utf-8",
    )
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
        == f"task/{created_task.id[:8]}-create-linked-worktree"
    )
    assert (expected_worktree_path / ".env").read_text(encoding="utf-8") == (
        source_env_file_path.read_text(encoding="utf-8")
    )
    assert (expected_worktree_path / "frontend" / ".env.local").read_text(
        encoding="utf-8"
    ) == nested_source_env_file_path.read_text(encoding="utf-8")
