"""Tests for the UTC storage and UTC+8 presentation contract."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from dsl.api.app_config import router as app_config_router
from dsl.models.dev_log import DevLog
from dsl.models.enums import DevLogStateTag, TaskLifecycleStatus, WorkflowStage
from dsl.models.run_account import RunAccount
from dsl.models.task import Task
from dsl.schemas.task_schema import TaskResponseSchema
from dsl.services.chronicle_service import ChronicleService
from utils.database import Base
from utils.helpers import (
    app_aware_to_utc_naive,
    get_app_timezone_offset_label,
    serialize_datetime_for_api,
)
from utils.settings import config


def _create_test_session() -> Session:
    """Create an isolated SQLite session for timezone contract tests.

    Returns:
        Session: In-memory SQLAlchemy session
    """
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
    return test_session_factory()


def test_timezone_helpers_preserve_utc_storage_semantics() -> None:
    """UTC naive storage should map cleanly to Asia/Shanghai API output."""
    stored_utc_naive_datetime = datetime(2026, 3, 18, 23, 30, 0)
    app_timezone_datetime = datetime(
        2026,
        3,
        19,
        7,
        30,
        0,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )

    assert (
        serialize_datetime_for_api(stored_utc_naive_datetime)
        == "2026-03-19T07:30:00+08:00"
    )
    assert app_aware_to_utc_naive(app_timezone_datetime) == stored_utc_naive_datetime
    assert (
        app_aware_to_utc_naive(datetime(2026, 3, 19, 7, 30, 0))
        == stored_utc_naive_datetime
    )


def test_task_response_schema_serializes_datetime_with_explicit_offset() -> None:
    """Response schemas should emit explicit timezone offsets for datetime fields."""
    task_response = TaskResponseSchema(
        id="task-1",
        run_account_id="run-1",
        project_id=None,
        task_title="Timezone contract",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.BACKLOG,
        stage_updated_at=datetime(2026, 3, 18, 22, 0, 0),
        worktree_path=None,
        requirement_brief=None,
        created_at=datetime(2026, 3, 18, 23, 30, 0),
        closed_at=None,
        log_count=0,
    )

    response_payload = task_response.model_dump(mode="json")

    assert response_payload["created_at"] == "2026-03-19T07:30:00+08:00"
    assert response_payload["stage_updated_at"] == "2026-03-19T06:00:00+08:00"


def test_app_config_route_exposes_runtime_timezone() -> None:
    """Frontend config route should expose the validated runtime timezone."""
    application = FastAPI()
    application.include_router(app_config_router)
    test_client = TestClient(application)

    response = test_client.get("/api/app-config")

    assert response.status_code == 200
    assert response.json() == {
        "app_timezone": config.APP_TIMEZONE,
        "app_timezone_offset": get_app_timezone_offset_label(),
    }


def test_chronicle_service_uses_app_timezone_for_cross_day_timeline_and_export() -> (
    None
):
    """Chronicle output should group cross-day records by UTC+8 natural days."""
    db_session = _create_test_session()
    try:
        run_account = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="macOS",
            git_branch_name="main",
            is_active=True,
            created_at=datetime(2026, 3, 18, 12, 0, 0),
        )
        db_session.add(run_account)
        db_session.commit()
        db_session.refresh(run_account)

        task = Task(
            run_account_id=run_account.id,
            task_title="Timezone boundary task",
            lifecycle_status=TaskLifecycleStatus.OPEN,
            workflow_stage=WorkflowStage.BACKLOG,
            created_at=datetime(2026, 3, 18, 15, 0, 0),
            closed_at=datetime(2026, 3, 19, 1, 0, 0),
        )
        db_session.add(task)
        db_session.commit()
        db_session.refresh(task)

        earlier_log = DevLog(
            task_id=task.id,
            run_account_id=run_account.id,
            created_at=datetime(2026, 3, 18, 15, 30, 0),
            text_content="Earlier UTC log",
            state_tag=DevLogStateTag.NONE,
        )
        cross_day_log = DevLog(
            task_id=task.id,
            run_account_id=run_account.id,
            created_at=datetime(2026, 3, 18, 23, 30, 0),
            text_content="Cross-day UTC log",
            state_tag=DevLogStateTag.FIXED,
        )
        db_session.add_all([earlier_log, cross_day_log])
        db_session.commit()

        timeline_entry_list = ChronicleService.get_timeline(
            db_session,
            run_account.id,
            limit=10,
        )
        task_markdown = ChronicleService.export_markdown(
            db_session,
            run_account.id,
            task_id=task.id,
        )
        timeline_markdown = ChronicleService.export_markdown(
            db_session,
            run_account.id,
        )

        assert [entry["created_at"] for entry in timeline_entry_list] == [
            "2026-03-19T07:30:00+08:00",
            "2026-03-18T23:30:00+08:00",
        ]
        assert "**Created:** 2026-03-18 23:00:00 UTC+08:00" in task_markdown
        assert "**Closed:** 2026-03-19 09:00:00 UTC+08:00" in task_markdown
        assert "**Timezone:** Asia/Shanghai (UTC+08:00)" in timeline_markdown
        assert "# 2026-03-19" in timeline_markdown
        assert "# 2026-03-18" in timeline_markdown
        assert timeline_markdown.index("# 2026-03-19") < timeline_markdown.index(
            "# 2026-03-18"
        )
        assert "## ✅ [07:30:00 UTC+08:00] Timezone boundary task" in timeline_markdown
    finally:
        db_session.close()
