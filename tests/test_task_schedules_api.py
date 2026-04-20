"""Tests for task schedule API route helpers."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import backend.dsl.models  # noqa: F401
from backend.dsl.api.task_schedules import (
    create_task_schedule,
    delete_task_schedule,
    list_task_schedule_runs,
    list_task_schedules,
    run_task_schedule_now,
    update_task_schedule,
)
from backend.dsl.models.enums import TaskLifecycleStatus, TaskScheduleRunStatus, WorkflowStage
from backend.dsl.models.run_account import RunAccount
from backend.dsl.models.task import Task
from backend.dsl.schemas.task_schedule_schema import (
    TaskScheduleCreateSchema,
    TaskScheduleUpdateSchema,
)
from backend.dsl.services.task_scheduler_dispatcher import TaskSchedulerDispatcher
from utils.database import Base


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite session for task schedule API tests."""
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
    """Create a run account + task for task schedule API tests."""
    run_account_obj = RunAccount(
        account_display_name="Scheduler API Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title="Task for schedule API",
        lifecycle_status=TaskLifecycleStatus.PENDING,
        workflow_stage=WorkflowStage.BACKLOG,
    )
    db_session.add(task_obj)
    db_session.commit()
    db_session.refresh(task_obj)
    return task_obj


def test_task_schedule_crud_route_helpers(db_session: Session) -> None:
    """Create/list/update/delete helper routes should persist schedule state."""
    task_obj = _create_seed_task(db_session)

    created_schedule_obj = create_task_schedule(
        task_id=task_obj.id,
        task_schedule_create_schema=TaskScheduleCreateSchema(
            schedule_name="Nightly resume",
            action_type="resume_task",
            trigger_type="cron",
            cron_expr="0 2 * * *",
            timezone_name="UTC",
            is_enabled=True,
        ),
        db_session=db_session,
    )

    listed_schedule_obj_list = list_task_schedules(
        task_id=task_obj.id, db_session=db_session
    )
    assert len(listed_schedule_obj_list) == 1
    assert listed_schedule_obj_list[0].id == created_schedule_obj.id

    updated_schedule_obj = update_task_schedule(
        task_id=task_obj.id,
        schedule_id=created_schedule_obj.id,
        task_schedule_update_schema=TaskScheduleUpdateSchema(
            is_enabled=False,
            schedule_name="Paused nightly resume",
        ),
        db_session=db_session,
    )
    assert updated_schedule_obj.is_enabled is False
    assert updated_schedule_obj.schedule_name == "Paused nightly resume"

    delete_task_schedule(
        task_id=task_obj.id,
        schedule_id=created_schedule_obj.id,
        db_session=db_session,
    )
    assert list_task_schedules(task_id=task_obj.id, db_session=db_session) == []


def test_run_now_route_records_skipped_result_when_task_is_already_running(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run-now should store a skipped run when dispatch sees a running-task conflict."""
    task_obj = _create_seed_task(db_session)
    created_schedule_obj = create_task_schedule(
        task_id=task_obj.id,
        task_schedule_create_schema=TaskScheduleCreateSchema(
            schedule_name="Manual run",
            action_type="resume_task",
            trigger_type="cron",
            cron_expr="0 2 * * *",
            timezone_name="UTC",
            is_enabled=True,
        ),
        db_session=db_session,
    )

    def _raise_conflict(_schedule_obj, _db_session) -> None:
        raise HTTPException(
            status_code=409, detail="Task automation is already running"
        )

    monkeypatch.setattr(
        TaskSchedulerDispatcher,
        "_dispatch_task_action_via_existing_api",
        _raise_conflict,
    )

    created_run_obj = run_task_schedule_now(
        task_id=task_obj.id,
        schedule_id=created_schedule_obj.id,
        db_session=db_session,
    )

    assert created_run_obj.run_status == TaskScheduleRunStatus.SKIPPED
    assert created_run_obj.skip_reason == "Task automation is already running"

    listed_run_obj_list = list_task_schedule_runs(
        task_id=task_obj.id,
        limit=20,
        db_session=db_session,
    )
    assert len(listed_run_obj_list) == 1
    assert listed_run_obj_list[0].id == created_run_obj.id


def test_create_task_schedule_route_rejects_invalid_timezone(
    db_session: Session,
) -> None:
    """Create route should reject invalid timezone values with 422."""
    task_obj = _create_seed_task(db_session)

    invalid_timezone_schema = TaskScheduleCreateSchema.model_construct(
        schedule_name="Invalid tz",
        action_type="start_task",
        trigger_type="once",
        run_at=datetime(2026, 3, 28, 10, 0, 0),
        timezone_name="Mars/Olympus",
        is_enabled=True,
    )

    with pytest.raises(HTTPException) as raised_error:
        create_task_schedule(
            task_id=task_obj.id,
            task_schedule_create_schema=invalid_timezone_schema,
            db_session=db_session,
        )

    assert raised_error.value.status_code == 422
