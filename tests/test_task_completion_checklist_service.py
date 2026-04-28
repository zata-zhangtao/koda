"""Tests for canonical task completion checklist generation."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import backend.dsl.models  # noqa: F401
from backend.dsl.models.enums import TaskLifecycleStatus, WorkflowStage
from backend.dsl.models.run_account import RunAccount
from backend.dsl.models.task import Task
from backend.dsl.schemas.task_schema import TaskCompletionConfirmationSchema
from backend.dsl.services.task_completion_checklist_service import (
    TaskCompletionChecklistService,
    TaskCompletionChecklistValidationError,
)
from utils.database import Base


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite session for checklist service tests."""
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


def _create_run_account(db_session: Session) -> RunAccount:
    """Create the default run account used by checklist tests.

    Args:
        db_session: Test database session.

    Returns:
        RunAccount: Persisted run account.
    """
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()
    return run_account_obj


def _create_worktree_backed_task(
    db_session: Session,
    tmp_path: Path,
    *,
    task_title_str: str = "Checklist task",
) -> Task:
    """Create a worktree-backed task for checklist tests.

    Args:
        db_session: Test database session.
        tmp_path: Temporary directory root.
        task_title_str: Task title.

    Returns:
        Task: Persisted task.
    """
    run_account_obj = _create_run_account(db_session)
    worktree_path = tmp_path / "task-worktree"
    worktree_path.mkdir()
    task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title=task_title_str,
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.TEST_IN_PROGRESS,
        worktree_path=str(worktree_path),
    )
    db_session.add(task_obj)
    db_session.commit()
    return task_obj


def test_completion_checklist_summarizes_long_prd_acceptance_section(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Long PRD acceptance checklists should be capped and summarized."""
    task_obj = _create_worktree_backed_task(db_session, tmp_path)
    tasks_directory_path = Path(task_obj.worktree_path) / "tasks"
    tasks_directory_path.mkdir()
    prd_file_path = tasks_directory_path / f"prd-{task_obj.id[:8]}.md"
    prd_file_path.write_text(
        """# PRD

## 7. Acceptance Checklist

### Architecture Acceptance

- [ ] Service-layer checklist generation is canonical.
- [ ] No checklist table is introduced.

### Behavior Acceptance

- [ ] Complete opens a checklist before posting.
- [ ] Users must check every displayed item.

### API Acceptance

- [ ] POST complete rejects stale signatures.
- [ ] PUT status rejects CLOSED.

## 8. User Stories
""",
        encoding="utf-8",
    )

    checklist_response = TaskCompletionChecklistService.build_completion_checklist(
        db_session=db_session,
        task_id_str=task_obj.id,
        checklist_mode="complete",
    )

    assert checklist_response is not None
    assert checklist_response.mode == "complete"
    assert checklist_response.checklist_signature.startswith("sha256:")
    assert len(checklist_response.items) == 5
    assert (
        checklist_response.items[0].label
        == "Behavior Acceptance: Complete opens a checklist before posting."
    )
    assert (
        checklist_response.items[1].label
        == "Behavior Acceptance: Users must check every displayed item."
    )
    assert checklist_response.items[2].item_id.startswith("prd-summary-")
    assert checklist_response.items[2].covered_source_item_count == 4
    assert [checklist_item.source for checklist_item in checklist_response.items].count(
        "system_safety"
    ) == 2


def test_validate_completion_confirmation_rejects_missing_displayed_item(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Validation should require every displayed canonical item ID."""
    task_obj = _create_worktree_backed_task(db_session, tmp_path)
    checklist_response = TaskCompletionChecklistService.build_completion_checklist(
        db_session=db_session,
        task_id_str=task_obj.id,
        checklist_mode="complete",
    )
    assert checklist_response is not None
    missing_item_id_text = checklist_response.items[-1].item_id
    incomplete_confirmation = TaskCompletionConfirmationSchema(
        checklist_mode="complete",
        checklist_signature=checklist_response.checklist_signature,
        confirmed_checklist_item_ids=[
            checklist_item.item_id for checklist_item in checklist_response.items[:-1]
        ],
    )

    with pytest.raises(TaskCompletionChecklistValidationError) as raised_error:
        TaskCompletionChecklistService.validate_completion_confirmation(
            db_session=db_session,
            task_id_str=task_obj.id,
            expected_checklist_mode="complete",
            confirmation_schema=incomplete_confirmation,
        )

    assert raised_error.value.status_code_int == 422
    assert raised_error.value.missing_checklist_item_id_list == [missing_item_id_text]


def test_validate_completion_confirmation_rejects_stale_signature(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Validation should force a checklist refresh when the signature is stale."""
    task_obj = _create_worktree_backed_task(db_session, tmp_path)
    checklist_response = TaskCompletionChecklistService.build_completion_checklist(
        db_session=db_session,
        task_id_str=task_obj.id,
        checklist_mode="complete",
    )
    assert checklist_response is not None
    stale_confirmation = TaskCompletionConfirmationSchema(
        checklist_mode="complete",
        checklist_signature="sha256:stale",
        confirmed_checklist_item_ids=[
            checklist_item.item_id for checklist_item in checklist_response.items
        ],
    )

    with pytest.raises(TaskCompletionChecklistValidationError) as raised_error:
        TaskCompletionChecklistService.validate_completion_confirmation(
            db_session=db_session,
            task_id_str=task_obj.id,
            expected_checklist_mode="complete",
            confirmation_schema=stale_confirmation,
        )

    assert raised_error.value.status_code_int == 409
    assert raised_error.value.refresh_required_bool is True


def test_completion_checklist_rejects_no_worktree_complete(
    db_session: Session,
) -> None:
    """Normal completion checklist should not exist for no-worktree tasks."""
    run_account_obj = _create_run_account(db_session)
    task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title="No worktree task",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.BACKLOG,
        worktree_path=None,
    )
    db_session.add(task_obj)
    db_session.commit()

    with pytest.raises(TaskCompletionChecklistValidationError) as raised_error:
        TaskCompletionChecklistService.build_completion_checklist(
            db_session=db_session,
            task_id_str=task_obj.id,
            checklist_mode="complete",
        )

    assert "worktree_path" in str(raised_error.value)
