"""Regression tests for defensive database bootstrap behavior."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

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
