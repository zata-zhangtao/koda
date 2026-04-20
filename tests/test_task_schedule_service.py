"""Tests for task schedule service behavior."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import backend.dsl.models  # noqa: F401
from backend.dsl.models.enums import (
    TaskLifecycleStatus,
    TaskScheduleRunStatus,
    WorkflowStage,
)
from backend.dsl.models.run_account import RunAccount
from backend.dsl.models.task import Task
from backend.dsl.schemas.task_schedule_schema import (
    TaskScheduleCreateSchema,
    TaskScheduleUpdateSchema,
)
from backend.dsl.services.task_schedule_service import TaskScheduleService
from backend.dsl.services.task_scheduler_dispatcher import TaskSchedulerDispatcher
from utils.database import Base
from utils.helpers import utc_now_naive


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite session for task schedule service tests."""
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


def _create_seed_task(db_session: Session) -> Task:
    """Create a run account + task for schedule tests."""
    run_account_obj = RunAccount(
        account_display_name="Scheduler Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title="Scheduled task",
        lifecycle_status=TaskLifecycleStatus.PENDING,
        workflow_stage=WorkflowStage.BACKLOG,
    )
    db_session.add(task_obj)
    db_session.commit()
    db_session.refresh(task_obj)
    return task_obj


def test_compute_next_cron_run_at_respects_timezone_boundary() -> None:
    """Cron next-run calculation should honor timezone conversion correctly."""
    next_run_at_utc_naive_datetime = TaskScheduleService.compute_next_cron_run_at(
        cron_expr_text="0 2 * * *",
        timezone_name_str="Asia/Shanghai",
        reference_utc_naive_datetime=datetime(2026, 3, 26, 17, 10, 0),
    )

    assert next_run_at_utc_naive_datetime == datetime(2026, 3, 26, 18, 0, 0)


def test_compute_next_cron_run_at_supports_weekday_range_with_sunday_alias() -> None:
    """Cron parser should support weekday ranges and Sunday alias values."""
    next_run_at_utc_naive_datetime = TaskScheduleService.compute_next_cron_run_at(
        cron_expr_text="0 9 * * 1-5",
        timezone_name_str="UTC",
        reference_utc_naive_datetime=datetime(2026, 3, 27, 10, 0, 0),
    )

    assert next_run_at_utc_naive_datetime == datetime(2026, 3, 30, 9, 0, 0)

    sunday_alias_next_run_utc_naive_datetime = (
        TaskScheduleService.compute_next_cron_run_at(
            cron_expr_text="0 12 * * 7",
            timezone_name_str="UTC",
            reference_utc_naive_datetime=datetime(2026, 3, 28, 8, 0, 0),
        )
    )
    assert sunday_alias_next_run_utc_naive_datetime == datetime(2026, 3, 29, 12, 0, 0)


def test_normalize_run_at_to_utc_naive_preserves_aware_datetime_instant() -> None:
    """Aware datetime input should preserve instant regardless of schedule timezone."""
    normalized_run_at_utc_naive_datetime = (
        TaskScheduleService.normalize_run_at_to_utc_naive(
            run_at_datetime=datetime(2026, 3, 27, 2, 0, 0, tzinfo=UTC),
            timezone_name_str="Asia/Shanghai",
        )
    )

    assert normalized_run_at_utc_naive_datetime == datetime(2026, 3, 27, 2, 0, 0)


def test_once_schedule_auto_disables_after_dispatch_result(db_session: Session) -> None:
    """A once schedule should disable itself after one automatic trigger."""
    task_obj = _create_seed_task(db_session)
    created_task_schedule_obj = TaskScheduleService.create_task_schedule(
        db_session,
        task_obj,
        TaskScheduleCreateSchema(
            schedule_name="One-time start",
            action_type="start_task",
            trigger_type="once",
            run_at=datetime(2026, 3, 27, 2, 0, 0),
            timezone_name="UTC",
            is_enabled=True,
        ),
    )

    planned_run_at_utc_naive_datetime = created_task_schedule_obj.next_run_at
    assert planned_run_at_utc_naive_datetime is not None

    applied_schedule_run_obj = TaskScheduleService.apply_schedule_dispatch_result(
        db_session,
        task_schedule_obj=created_task_schedule_obj,
        planned_run_at_utc_naive_datetime=planned_run_at_utc_naive_datetime,
        triggered_at_utc_naive_datetime=utc_now_naive(),
        run_status=TaskScheduleRunStatus.SUCCEEDED,
        should_advance_schedule_bool=True,
    )

    assert applied_schedule_run_obj is not None
    db_session.refresh(created_task_schedule_obj)

    assert created_task_schedule_obj.is_enabled is False
    assert created_task_schedule_obj.next_run_at is None
    assert (
        created_task_schedule_obj.last_result_status == TaskScheduleRunStatus.SUCCEEDED
    )


def test_update_schedule_rejects_invalid_trigger_field_combination(
    db_session: Session,
) -> None:
    """Switching to cron with invalid field combinations should be rejected."""
    task_obj = _create_seed_task(db_session)
    created_task_schedule_obj = TaskScheduleService.create_task_schedule(
        db_session,
        task_obj,
        TaskScheduleCreateSchema(
            schedule_name="One-time start",
            action_type="start_task",
            trigger_type="once",
            run_at=datetime(2026, 3, 27, 2, 0, 0),
            timezone_name="UTC",
            is_enabled=False,
        ),
    )

    with pytest.raises(ValueError, match="cron_expr is required"):
        TaskScheduleService.update_task_schedule(
            db_session,
            created_task_schedule_obj,
            TaskScheduleUpdateSchema(trigger_type="cron", run_at=None),
        )

    with pytest.raises(ValueError, match="run_at must be empty"):
        TaskScheduleService.update_task_schedule(
            db_session,
            created_task_schedule_obj,
            TaskScheduleUpdateSchema(
                trigger_type="cron",
                cron_expr="0 2 * * *",
                run_at=datetime(2026, 3, 27, 4, 0, 0),
            ),
        )


def test_dispatch_claim_prevents_duplicate_action_for_same_window(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Automatic dispatch should claim the window before action execution."""
    task_obj = _create_seed_task(db_session)
    created_task_schedule_obj = TaskScheduleService.create_task_schedule(
        db_session,
        task_obj,
        TaskScheduleCreateSchema(
            schedule_name="Nightly resume",
            action_type="resume_task",
            trigger_type="cron",
            cron_expr="*/5 * * * *",
            timezone_name="UTC",
            is_enabled=True,
        ),
    )
    planned_run_at_utc_naive_datetime = created_task_schedule_obj.next_run_at
    assert planned_run_at_utc_naive_datetime is not None

    dispatch_call_count_int = 0

    def _noop_dispatch_action(_task_schedule_obj, _db_session) -> None:
        nonlocal dispatch_call_count_int
        dispatch_call_count_int += 1

    monkeypatch.setattr(
        TaskSchedulerDispatcher,
        "_dispatch_task_action_via_existing_api",
        _noop_dispatch_action,
    )

    first_schedule_run_obj = TaskSchedulerDispatcher._dispatch_single_schedule(
        db_session,
        task_schedule_obj=created_task_schedule_obj,
        planned_run_at_utc_naive_datetime=planned_run_at_utc_naive_datetime,
        should_advance_schedule_bool=True,
    )
    second_schedule_run_obj = TaskSchedulerDispatcher._dispatch_single_schedule(
        db_session,
        task_schedule_obj=created_task_schedule_obj,
        planned_run_at_utc_naive_datetime=planned_run_at_utc_naive_datetime,
        should_advance_schedule_bool=True,
    )

    assert first_schedule_run_obj is not None
    assert second_schedule_run_obj is None
    assert dispatch_call_count_int == 1

    db_session.refresh(created_task_schedule_obj)
    assert created_task_schedule_obj.next_run_at is not None
    assert created_task_schedule_obj.next_run_at > planned_run_at_utc_naive_datetime


def test_dispatch_task_action_routes_review_schedule_to_review_api(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review schedules should call the dedicated review-only task API helper."""
    import backend.dsl.api.tasks as task_api_module

    task_obj = _create_seed_task(db_session)
    created_task_schedule_obj = TaskScheduleService.create_task_schedule(
        db_session,
        task_obj,
        TaskScheduleCreateSchema(
            schedule_name="Nightly review",
            action_type="review_task",
            trigger_type="cron",
            cron_expr="0 9 * * 1-5",
            timezone_name="UTC",
            is_enabled=True,
        ),
    )

    recorded_call_dict: dict[str, object] = {}

    def _fake_review_task(*, task_id: str, background_tasks, db_session) -> None:
        recorded_call_dict["task_id"] = task_id
        recorded_call_dict["background_task_count"] = len(background_tasks.tasks)
        recorded_call_dict["db_session"] = db_session
        background_tasks.add_task(lambda: None)

    monkeypatch.setattr(task_api_module, "review_task", _fake_review_task)

    TaskSchedulerDispatcher._dispatch_task_action_via_existing_api(
        created_task_schedule_obj,
        db_session,
    )

    assert recorded_call_dict["task_id"] == task_obj.id
    assert recorded_call_dict["background_task_count"] == 0
    assert recorded_call_dict["db_session"] is db_session
