"""Tests for PRD source API route functions."""

from __future__ import annotations

from io import BytesIO
from datetime import datetime
import re
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import backend.dsl.models  # noqa: F401
from backend.dsl.models.enums import TaskLifecycleStatus, WorkflowStage
from backend.dsl.models.project import Project
from backend.dsl.models.run_account import RunAccount
from backend.dsl.models.task import Task
from backend.dsl.prd_sources.api import (
    import_prd_file,
    import_pasted_prd_markdown,
    list_pending_prd_files,
    select_pending_prd_file,
)
from backend.dsl.prd_sources.domain.policies import MAX_PRD_MARKDOWN_BYTES
from backend.dsl.prd_sources.schemas import (
    ImportPastedPrdRequestSchema,
    SelectPendingPrdRequestSchema,
)
import backend.dsl.prd_sources.domain.policies as prd_policies
from backend.dsl.services import codex_runner
from backend.dsl.services.automation_runner import run_task_implementation
from backend.dsl.services.prd_file_service import find_task_prd_file_path
from utils.database import Base

_FIXED_PRD_FILENAME_DATETIME = datetime(2026, 4, 23, 13, 5, 0)


class _FixedDatetimeModule:
    """Stand-in datetime module used to freeze PRD filename timestamps."""

    @staticmethod
    def now() -> datetime:
        """Return the fixed PRD filename timestamp."""
        return _FIXED_PRD_FILENAME_DATETIME


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite session for PRD source API tests."""
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


@pytest.fixture(autouse=True)
def clear_codex_runtime_state() -> None:
    """Reset in-memory automation state between tests."""
    codex_runner._running_background_task_ids.clear()
    codex_runner._running_codex_processes.clear()
    codex_runner._user_cancelled_tasks.clear()


def _freeze_prd_filename_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force PRD filename generation to use a deterministic timestamp."""
    monkeypatch.setattr(prd_policies, "datetime", _FixedDatetimeModule)
    yield
    codex_runner._running_background_task_ids.clear()
    codex_runner._running_codex_processes.clear()
    codex_runner._user_cancelled_tasks.clear()


def _create_task(
    db_session: Session,
    workspace_dir_path: Path,
    *,
    auto_confirm_prd_and_execute: bool = False,
) -> Task:
    """Create a task with a workspace path for API tests."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    task_obj = Task(
        run_account=run_account_obj,
        task_title="导入 PRD",
        lifecycle_status=TaskLifecycleStatus.PENDING,
        workflow_stage=WorkflowStage.BACKLOG,
        worktree_path=str(workspace_dir_path),
        auto_confirm_prd_and_execute=auto_confirm_prd_and_execute,
    )
    db_session.add_all([run_account_obj, task_obj])
    db_session.commit()
    db_session.refresh(task_obj)
    return task_obj


def test_list_pending_prd_files_returns_empty_when_directory_missing(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Missing tasks/pending should be a normal empty state."""
    task_obj = _create_task(db_session, tmp_path)

    response_schema = list_pending_prd_files(task_obj.id, db_session)

    assert response_schema.files == []


def test_list_pending_prd_files_prefers_project_repo_when_worktree_exists(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Project tasks should list pending PRDs from project repo, not worktree."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    project_root_path = tmp_path / "project-root"
    worktree_root_path = tmp_path / "task-worktree"
    project_pending_directory_path = project_root_path / "tasks" / "pending"
    worktree_pending_directory_path = worktree_root_path / "tasks" / "pending"
    project_pending_directory_path.mkdir(parents=True)
    worktree_pending_directory_path.mkdir(parents=True)
    (project_pending_directory_path / "project.md").write_text(
        "# Project Pending\n",
        encoding="utf-8",
    )
    (worktree_pending_directory_path / "worktree.md").write_text(
        "# Worktree Pending\n",
        encoding="utf-8",
    )
    project_obj = Project(
        display_name="Demo Project",
        repo_path=str(project_root_path),
        description=None,
    )
    task_obj = Task(
        run_account=run_account_obj,
        project=project_obj,
        task_title="导入 PRD",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.BACKLOG,
        worktree_path=str(worktree_root_path),
    )
    db_session.add_all([run_account_obj, project_obj, task_obj])
    db_session.commit()
    db_session.refresh(task_obj)

    response_schema = list_pending_prd_files(task_obj.id, db_session)

    assert [pending_file.file_name for pending_file in response_schema.files] == [
        "project.md"
    ]


def test_select_pending_prd_file_moves_to_tasks_root_and_marks_ready(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting a pending PRD should move it and enter PRD confirmation."""
    task_obj = _create_task(db_session, tmp_path)
    _freeze_prd_filename_timestamp(monkeypatch)
    pending_directory_path = tmp_path / "tasks" / "pending"
    pending_directory_path.mkdir(parents=True)
    pending_file_path = pending_directory_path / "manual.md"
    pending_file_path.write_text(
        "# PRD\n\n**需求名称（AI 归纳）**：选择已有 PRD\n",
        encoding="utf-8",
    )
    background_tasks = BackgroundTasks()

    updated_task = select_pending_prd_file(
        task_obj.id,
        SelectPendingPrdRequestSchema(relative_path="tasks/pending/manual.md"),
        background_tasks,
        db_session,
    )

    staged_prd_file_path = find_task_prd_file_path(tmp_path, task_obj.id)
    assert staged_prd_file_path is not None
    assert re.fullmatch(
        r"\d{8}-\d{6}-prd-选择已有-prd\.md",
        staged_prd_file_path.name,
    )
    assert staged_prd_file_path.read_text(encoding="utf-8").startswith("# PRD")
    assert not pending_file_path.exists()
    assert updated_task.workflow_stage == WorkflowStage.PRD_WAITING_CONFIRMATION
    assert updated_task.lifecycle_status == TaskLifecycleStatus.OPEN
    assert background_tasks.tasks == []


def test_select_pending_prd_file_moves_project_pending_into_created_worktree(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backlog project tasks should move pending PRDs from project root to worktree."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    project_root_path = tmp_path / "project-root"
    project_root_path.mkdir()
    worktree_root_path = tmp_path / "task-worktree"
    existing_project_prd_directory_path = worktree_root_path / "tasks"
    existing_project_prd_directory_path.mkdir(parents=True)
    existing_project_prd_file_path = (
        existing_project_prd_directory_path
        / "20260425-135415-prd-template-asset-import.md"
    )
    existing_project_prd_file_path.write_text(
        "# Historical Project PRD\n\nThis file belongs to the project, not the task.\n",
        encoding="utf-8",
    )
    project_obj = Project(
        display_name="Demo Project",
        repo_path=str(project_root_path),
        description=None,
    )
    task_obj = Task(
        run_account=run_account_obj,
        project=project_obj,
        task_title="导入 PRD",
        lifecycle_status=TaskLifecycleStatus.PENDING,
        workflow_stage=WorkflowStage.BACKLOG,
    )
    db_session.add_all([run_account_obj, project_obj, task_obj])
    db_session.commit()
    db_session.refresh(task_obj)
    _freeze_prd_filename_timestamp(monkeypatch)
    pending_directory_path = project_root_path / "tasks" / "pending"
    pending_directory_path.mkdir(parents=True)
    pending_file_path = pending_directory_path / "manual.md"
    pending_file_path.write_text(
        "# PRD\n\n**需求名称（AI 归纳）**：项目 pending PRD\n",
        encoding="utf-8",
    )

    def fake_ensure_task_worktree_if_needed(
        db_session: Session,
        task_obj: Task,
    ) -> None:
        """Simulate task worktree creation after pending was listed from project."""
        _ = db_session
        worktree_root_path.mkdir(parents=True, exist_ok=True)
        worktree_pending_directory_path = worktree_root_path / "tasks" / "pending"
        worktree_pending_directory_path.mkdir(parents=True, exist_ok=True)
        (worktree_pending_directory_path / "manual.md").write_text(
            "# PRD\n\n**需求名称（AI 归纳）**：项目 pending PRD\n",
            encoding="utf-8",
        )
        task_obj.worktree_path = str(worktree_root_path)

    monkeypatch.setattr(
        "backend.dsl.prd_sources.infrastructure.task_workflow_adapter."
        "TaskService._ensure_task_worktree_if_needed",
        fake_ensure_task_worktree_if_needed,
    )

    updated_task = select_pending_prd_file(
        task_obj.id,
        SelectPendingPrdRequestSchema(relative_path="tasks/pending/manual.md"),
        BackgroundTasks(),
        db_session,
    )

    staged_prd_file_path = find_task_prd_file_path(worktree_root_path, task_obj.id)
    assert staged_prd_file_path is not None
    assert re.fullmatch(
        r"\d{8}-\d{6}-prd-项目-pending-prd\.md",
        staged_prd_file_path.name,
    )
    assert staged_prd_file_path.read_text(encoding="utf-8").startswith("# PRD")
    assert existing_project_prd_file_path.exists()
    assert pending_file_path.exists()
    assert not (worktree_root_path / "tasks" / "pending" / "manual.md").exists()
    assert updated_task.worktree_path == str(worktree_root_path)
    assert updated_task.workflow_stage == WorkflowStage.PRD_WAITING_CONFIRMATION


def test_select_pending_prd_file_moves_existing_worktree_pending(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing worktrees should move their pending copy and preserve project templates."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    project_root_path = tmp_path / "project-root"
    project_root_path.mkdir()
    worktree_root_path = tmp_path / "task-worktree"
    project_obj = Project(
        display_name="Demo Project",
        repo_path=str(project_root_path),
        description=None,
    )
    task_obj = Task(
        run_account=run_account_obj,
        project=project_obj,
        task_title="导入 PRD",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.BACKLOG,
        worktree_path=str(worktree_root_path),
    )
    db_session.add_all([run_account_obj, project_obj, task_obj])
    db_session.commit()
    db_session.refresh(task_obj)
    _freeze_prd_filename_timestamp(monkeypatch)

    project_pending_directory_path = project_root_path / "tasks" / "pending"
    project_pending_directory_path.mkdir(parents=True)
    project_pending_file_path = project_pending_directory_path / "manual.md"
    project_pending_file_path.write_text(
        "# PRD\n\n**需求名称（AI 归纳）**：项目 pending PRD\n",
        encoding="utf-8",
    )
    worktree_pending_directory_path = worktree_root_path / "tasks" / "pending"
    worktree_pending_directory_path.mkdir(parents=True)
    worktree_pending_file_path = worktree_pending_directory_path / "manual.md"
    worktree_pending_file_path.write_text(
        "# PRD\n\n**需求名称（AI 归纳）**：旧 worktree pending 副本\n",
        encoding="utf-8",
    )

    updated_task = select_pending_prd_file(
        task_obj.id,
        SelectPendingPrdRequestSchema(relative_path="tasks/pending/manual.md"),
        BackgroundTasks(),
        db_session,
    )

    staged_prd_file_path = find_task_prd_file_path(worktree_root_path, task_obj.id)
    assert staged_prd_file_path is not None
    assert "旧 worktree pending 副本" in staged_prd_file_path.read_text(
        encoding="utf-8"
    )
    assert project_pending_file_path.exists()
    assert not worktree_pending_file_path.exists()
    assert updated_task.workflow_stage == WorkflowStage.PRD_WAITING_CONFIRMATION


def test_select_pending_prd_file_copies_project_template_when_worktree_missing(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing worktree pending files should fall back to the project template."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    project_root_path = tmp_path / "project-root"
    project_root_path.mkdir()
    worktree_root_path = tmp_path / "task-worktree"
    (worktree_root_path / "tasks").mkdir(parents=True)
    project_obj = Project(
        display_name="Demo Project",
        repo_path=str(project_root_path),
        description=None,
    )
    task_obj = Task(
        run_account=run_account_obj,
        project=project_obj,
        task_title="导入 PRD",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.BACKLOG,
        worktree_path=str(worktree_root_path),
    )
    db_session.add_all([run_account_obj, project_obj, task_obj])
    db_session.commit()
    db_session.refresh(task_obj)
    _freeze_prd_filename_timestamp(monkeypatch)

    project_pending_directory_path = project_root_path / "tasks" / "pending"
    project_pending_directory_path.mkdir(parents=True)
    project_pending_file_path = project_pending_directory_path / "manual.md"
    project_pending_file_path.write_text(
        "# PRD\n\n**需求名称（AI 归纳）**：项目 pending PRD\n",
        encoding="utf-8",
    )

    updated_task = select_pending_prd_file(
        task_obj.id,
        SelectPendingPrdRequestSchema(relative_path="tasks/pending/manual.md"),
        BackgroundTasks(),
        db_session,
    )

    staged_prd_file_path = find_task_prd_file_path(worktree_root_path, task_obj.id)
    assert staged_prd_file_path is not None
    assert "项目 pending PRD" in staged_prd_file_path.read_text(encoding="utf-8")
    assert project_pending_file_path.exists()
    assert updated_task.workflow_stage == WorkflowStage.PRD_WAITING_CONFIRMATION


def test_import_prd_file_writes_tasks_root_and_marks_ready(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manual PRD import should write Markdown into the task PRD root."""
    task_obj = _create_task(db_session, tmp_path)
    _freeze_prd_filename_timestamp(monkeypatch)
    uploaded_prd_file = UploadFile(
        filename="manual.md",
        file=BytesIO("**需求名称（AI 归纳）**：手动导入 PRD\n".encode("utf-8")),
    )

    updated_task = import_prd_file(
        task_id=task_obj.id,
        background_tasks=BackgroundTasks(),
        db_session=db_session,
        uploaded_prd_file=uploaded_prd_file,
    )

    staged_prd_file_path = find_task_prd_file_path(tmp_path, task_obj.id)
    assert staged_prd_file_path is not None
    assert re.fullmatch(
        r"\d{8}-\d{6}-prd-手动导入-prd\.md",
        staged_prd_file_path.name,
    )
    assert (
        staged_prd_file_path.read_text(encoding="utf-8")
        == "**需求名称（AI 归纳）**：手动导入 PRD\n"
    )
    assert updated_task.workflow_stage == WorkflowStage.PRD_WAITING_CONFIRMATION


def test_import_pasted_prd_markdown_writes_tasks_root_and_marks_ready(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pasted PRD Markdown should stage into the task root and mark ready."""
    task_obj = _create_task(db_session, tmp_path)
    _freeze_prd_filename_timestamp(monkeypatch)

    updated_task = import_pasted_prd_markdown(
        task_id=task_obj.id,
        request_schema=ImportPastedPrdRequestSchema(
            prd_markdown_text="**需求名称（AI 归纳）**：粘贴导入 PRD\n"
        ),
        background_tasks=BackgroundTasks(),
        db_session=db_session,
    )

    staged_prd_file_path = find_task_prd_file_path(tmp_path, task_obj.id)
    assert staged_prd_file_path is not None
    assert re.fullmatch(
        r"\d{8}-\d{6}-prd-粘贴导入-prd\.md",
        staged_prd_file_path.name,
    )
    assert (
        staged_prd_file_path.read_text(encoding="utf-8")
        == "**需求名称（AI 归纳）**：粘贴导入 PRD\n"
    )
    assert updated_task.workflow_stage == WorkflowStage.PRD_WAITING_CONFIRMATION


def test_select_pending_prd_file_rejects_traversal_without_stage_change(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Unsafe pending paths should fail and preserve the task stage."""
    task_obj = _create_task(db_session, tmp_path)

    with pytest.raises(HTTPException) as http_exception_info:
        select_pending_prd_file(
            task_obj.id,
            SelectPendingPrdRequestSchema(relative_path="tasks/pending/../secret.md"),
            BackgroundTasks(),
            db_session,
        )

    db_session.refresh(task_obj)
    assert http_exception_info.value.status_code == 422
    assert task_obj.workflow_stage == WorkflowStage.BACKLOG


def test_import_prd_file_rejects_non_utf8_without_stage_change(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Non-UTF-8 imports should fail before staging or stage changes."""
    task_obj = _create_task(db_session, tmp_path)
    uploaded_prd_file = UploadFile(
        filename="manual.md",
        file=BytesIO(b"\xff\xfe\xfa"),
    )

    with pytest.raises(HTTPException) as http_exception_info:
        import_prd_file(
            task_id=task_obj.id,
            background_tasks=BackgroundTasks(),
            db_session=db_session,
            uploaded_prd_file=uploaded_prd_file,
        )

    db_session.refresh(task_obj)
    assert http_exception_info.value.status_code == 422
    assert task_obj.workflow_stage == WorkflowStage.BACKLOG
    assert find_task_prd_file_path(tmp_path, task_obj.id) is None


def test_import_pasted_prd_markdown_rejects_blank_content_without_stage_change(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Blank pasted Markdown should fail before staging or stage changes."""
    task_obj = _create_task(db_session, tmp_path)

    with pytest.raises(HTTPException) as http_exception_info:
        import_pasted_prd_markdown(
            task_id=task_obj.id,
            request_schema=ImportPastedPrdRequestSchema(prd_markdown_text=" \n\t "),
            background_tasks=BackgroundTasks(),
            db_session=db_session,
        )

    db_session.refresh(task_obj)
    assert http_exception_info.value.status_code == 422
    assert task_obj.workflow_stage == WorkflowStage.BACKLOG
    assert find_task_prd_file_path(tmp_path, task_obj.id) is None


def test_import_prd_file_rejects_non_markdown_without_stage_change(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Non-Markdown imports should fail before staging or stage changes."""
    task_obj = _create_task(db_session, tmp_path)
    uploaded_prd_file = UploadFile(
        filename="manual.txt",
        file=BytesIO(b"# PRD\n"),
    )

    with pytest.raises(HTTPException) as http_exception_info:
        import_prd_file(
            task_id=task_obj.id,
            background_tasks=BackgroundTasks(),
            db_session=db_session,
            uploaded_prd_file=uploaded_prd_file,
        )

    db_session.refresh(task_obj)
    assert http_exception_info.value.status_code == 422
    assert task_obj.workflow_stage == WorkflowStage.BACKLOG
    assert find_task_prd_file_path(tmp_path, task_obj.id) is None


def test_import_prd_file_rejects_oversized_markdown_without_stage_change(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Oversized Markdown imports should fail without staging a PRD."""
    task_obj = _create_task(db_session, tmp_path)
    uploaded_prd_file = UploadFile(
        filename="manual.md",
        file=BytesIO(b"#" * (MAX_PRD_MARKDOWN_BYTES + 10)),
    )

    with pytest.raises(HTTPException) as http_exception_info:
        import_prd_file(
            task_id=task_obj.id,
            background_tasks=BackgroundTasks(),
            db_session=db_session,
            uploaded_prd_file=uploaded_prd_file,
        )

    db_session.refresh(task_obj)
    assert http_exception_info.value.status_code == 422
    assert task_obj.workflow_stage == WorkflowStage.BACKLOG
    assert find_task_prd_file_path(tmp_path, task_obj.id) is None


def test_import_prd_file_rejects_existing_task_prd_with_conflict(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Import should reject replacing an existing current task PRD."""
    task_obj = _create_task(db_session, tmp_path)
    tasks_directory_path = tmp_path / "tasks"
    tasks_directory_path.mkdir()
    existing_prd_file_path = tasks_directory_path / (
        f"prd-{task_obj.id[:8]}-existing.md"
    )
    existing_prd_file_path.write_text(
        "**需求名称（AI 归纳）**：Existing\n",
        encoding="utf-8",
    )
    uploaded_prd_file = UploadFile(
        filename="manual.md",
        file=BytesIO("**需求名称（AI 归纳）**：New\n".encode("utf-8")),
    )

    with pytest.raises(HTTPException) as http_exception_info:
        import_prd_file(
            task_id=task_obj.id,
            background_tasks=BackgroundTasks(),
            db_session=db_session,
            uploaded_prd_file=uploaded_prd_file,
        )

    db_session.refresh(task_obj)
    assert http_exception_info.value.status_code == 409
    assert task_obj.workflow_stage == WorkflowStage.BACKLOG
    assert existing_prd_file_path.read_text(encoding="utf-8") == (
        "**需求名称（AI 归纳）**：Existing\n"
    )


def test_import_prd_file_auto_confirm_schedules_implementation(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Auto-confirm tasks should proceed into implementation after import."""
    task_obj = _create_task(
        db_session,
        tmp_path,
        auto_confirm_prd_and_execute=True,
    )
    background_tasks = BackgroundTasks()
    uploaded_prd_file = UploadFile(
        filename="manual.md",
        file=BytesIO("**需求名称（AI 归纳）**：自动导入 PRD\n".encode("utf-8")),
    )

    updated_task = import_prd_file(
        task_id=task_obj.id,
        background_tasks=background_tasks,
        db_session=db_session,
        uploaded_prd_file=uploaded_prd_file,
    )

    assert updated_task.workflow_stage == WorkflowStage.IMPLEMENTATION_IN_PROGRESS
    assert updated_task.is_codex_task_running is True
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0].func is run_task_implementation
