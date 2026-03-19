"""Tests for incremental log list API behavior."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from dsl.api.logs import list_logs
from dsl.models.dev_log import DevLog
from dsl.models.enums import DevLogStateTag
from dsl.models.run_account import RunAccount
from dsl.models.task import Task
from utils.database import Base
from utils.helpers import serialize_datetime_for_api


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite session for log API tests."""
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


def test_list_logs_filters_incremental_results_from_created_after(
    db_session: Session,
) -> None:
    """Log listing should support incremental fetches from a timestamp cursor."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title="Incremental polling task",
    )
    db_session.add(task_obj)
    db_session.commit()

    older_log = DevLog(
        task_id=task_obj.id,
        run_account_id=run_account_obj.id,
        created_at=datetime(2026, 3, 19, 5, 0, 0),
        text_content="older",
        state_tag=DevLogStateTag.NONE,
    )
    newer_log = DevLog(
        task_id=task_obj.id,
        run_account_id=run_account_obj.id,
        created_at=datetime(2026, 3, 19, 5, 0, 5),
        text_content="newer",
        state_tag=DevLogStateTag.FIXED,
    )
    db_session.add_all([older_log, newer_log])
    db_session.commit()

    incremental_log_list = list_logs(
        task_id=task_obj.id,
        limit=20,
        offset=0,
        created_after=serialize_datetime_for_api(older_log.created_at),
        db_session=db_session,
    )

    assert [log_item.id for log_item in incremental_log_list] == [newer_log.id]
    assert incremental_log_list[0].task_title == task_obj.task_title


def test_list_logs_rejects_invalid_created_after_timestamp(
    db_session: Session,
) -> None:
    """Log listing should fail fast on malformed incremental cursors."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        list_logs(
            task_id=None,
            limit=20,
            offset=0,
            created_after="not-a-timestamp",
            db_session=db_session,
        )

    assert exc_info.value.status_code == 422
    assert "created_after" in str(exc_info.value.detail)
