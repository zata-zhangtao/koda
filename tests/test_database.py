"""Regression tests for defensive database bootstrap behavior."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import dsl.models  # noqa: F401
import utils.database as database_module
from dsl.models.enums import (
    TaskQaContextScope,
    TaskQaGenerationStatus,
    TaskQaMessageRole,
)
from dsl.models.run_account import RunAccount
from dsl.models.task import Task
from dsl.models.task_qa_message import TaskQaMessage
from utils.database import DatabaseSession


def test_database_session_bootstraps_empty_sqlite_file(tmp_path: Path) -> None:
    """Opening a session should create the schema for a brand-new SQLite file."""
    database_file_path = tmp_path / "fresh-dsl.db"
    test_engine = create_engine(
        f"sqlite:///{database_file_path}",
        connect_args={"check_same_thread": False},
    )
    test_session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
        class_=DatabaseSession,
    )

    with test_session_factory():
        database_inspector = inspect(test_engine)
        discovered_table_name_set = set(database_inspector.get_table_names())
        project_column_name_set = {
            column_definition_dict["name"]
            for column_definition_dict in database_inspector.get_columns("projects")
        }
        task_column_name_set = {
            column_definition_dict["name"]
            for column_definition_dict in database_inspector.get_columns("tasks")
        }

    assert database_file_path.exists() is True
    assert database_file_path.stat().st_size > 0
    assert {
        "dev_logs",
        "email_settings",
        "projects",
        "run_accounts",
        "tasks",
        "webdav_settings",
    }.issubset(discovered_table_name_set)
    assert {"repo_remote_url", "repo_head_commit_hash"}.issubset(
        project_column_name_set
    )
    assert "requirement_brief" in task_column_name_set
    assert "auto_confirm_prd_and_execute" in task_column_name_set


def test_create_database_engine_enables_sqlite_wal_and_busy_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQLite engines should enable WAL mode and a longer busy timeout."""
    database_file_path = tmp_path / "lock-safe.db"
    monkeypatch.setattr(
        database_module,
        "DATABASE_URL",
        f"sqlite:///{database_file_path}",
    )

    test_engine = database_module.create_database_engine()
    try:
        with test_engine.connect() as database_connection:
            journal_mode_value = database_connection.execute(
                text("PRAGMA journal_mode")
            ).scalar_one()
            busy_timeout_value = database_connection.execute(
                text("PRAGMA busy_timeout")
            ).scalar_one()
    finally:
        test_engine.dispose()

    assert str(journal_mode_value).lower() == "wal"
    assert int(busy_timeout_value) == 30_000


def test_database_bootstrap_repairs_duplicate_pending_sidecar_replies(
    tmp_path: Path,
) -> None:
    """Bootstrap should repair duplicate pending sidecar replies before indexing."""

    database_file_path = tmp_path / "task-qa-repair.db"
    test_engine = create_engine(
        f"sqlite:///{database_file_path}",
        connect_args={"check_same_thread": False},
    )
    test_session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )
    database_module.Base.metadata.create_all(bind=test_engine)

    with test_engine.begin() as database_connection:
        database_connection.execute(
            text("DROP INDEX IF EXISTS uq_task_qa_messages_single_pending_assistant")
        )

    seed_session = test_session_factory()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            is_active=True,
        )
        seed_session.add(run_account_obj)
        seed_session.commit()
        seed_session.refresh(run_account_obj)

        task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Repair pending duplicates",
        )
        seed_session.add(task_obj)
        seed_session.commit()
        seed_session.refresh(task_obj)
        task_id = task_obj.id

        first_user_message_obj = TaskQaMessage(
            task_id=task_obj.id,
            run_account_id=run_account_obj.id,
            role=TaskQaMessageRole.USER,
            context_scope=TaskQaContextScope.PRD_CONFIRMATION,
            generation_status=TaskQaGenerationStatus.COMPLETED,
            content_markdown="first",
            created_at=datetime(2026, 3, 26, 9, 0, 0),
        )
        seed_session.add(first_user_message_obj)
        seed_session.flush()
        first_assistant_message_obj = TaskQaMessage(
            task_id=task_obj.id,
            run_account_id=run_account_obj.id,
            role=TaskQaMessageRole.ASSISTANT,
            context_scope=TaskQaContextScope.PRD_CONFIRMATION,
            generation_status=TaskQaGenerationStatus.PENDING,
            reply_to_message_id=first_user_message_obj.id,
            content_markdown="",
            created_at=datetime(2026, 3, 26, 9, 0, 1),
        )

        second_user_message_obj = TaskQaMessage(
            task_id=task_obj.id,
            run_account_id=run_account_obj.id,
            role=TaskQaMessageRole.USER,
            context_scope=TaskQaContextScope.PRD_CONFIRMATION,
            generation_status=TaskQaGenerationStatus.COMPLETED,
            content_markdown="second",
            created_at=datetime(2026, 3, 26, 9, 0, 2),
        )
        seed_session.add(second_user_message_obj)
        seed_session.flush()
        second_assistant_message_obj = TaskQaMessage(
            task_id=task_obj.id,
            run_account_id=run_account_obj.id,
            role=TaskQaMessageRole.ASSISTANT,
            context_scope=TaskQaContextScope.PRD_CONFIRMATION,
            generation_status=TaskQaGenerationStatus.PENDING,
            reply_to_message_id=second_user_message_obj.id,
            content_markdown="",
            created_at=datetime(2026, 3, 26, 9, 0, 3),
        )

        seed_session.add_all(
            [
                first_assistant_message_obj,
                second_assistant_message_obj,
            ]
        )
        seed_session.commit()
    finally:
        seed_session.close()

    database_module.ensure_database_schema_ready(database_engine=test_engine)

    check_session = test_session_factory()
    try:
        repaired_assistant_message_list = (
            check_session.query(TaskQaMessage)
            .filter(
                TaskQaMessage.task_id == task_id,
                TaskQaMessage.role == TaskQaMessageRole.ASSISTANT,
            )
            .order_by(TaskQaMessage.created_at.asc(), TaskQaMessage.id.asc())
            .all()
        )
    finally:
        check_session.close()

    with test_engine.connect() as database_connection:
        index_row_list = database_connection.execute(
            text("PRAGMA index_list('task_qa_messages')")
        ).fetchall()

    pending_assistant_message_list = [
        message
        for message in repaired_assistant_message_list
        if message.generation_status == TaskQaGenerationStatus.PENDING
    ]
    failed_assistant_message_list = [
        message
        for message in repaired_assistant_message_list
        if message.generation_status == TaskQaGenerationStatus.FAILED
    ]

    assert len(pending_assistant_message_list) == 1
    assert len(failed_assistant_message_list) == 1
    assert "schema repair" in (failed_assistant_message_list[0].error_text or "")
    assert any(
        index_row[1] == "uq_task_qa_messages_single_pending_assistant"
        for index_row in index_row_list
    )
