"""Regression tests for defensive database bootstrap behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import utils.database as database_module
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
