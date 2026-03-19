"""Tests for task API helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from dsl.api.tasks import get_task_prd_file
from dsl.models.run_account import RunAccount
from dsl.models.task import Task
from utils.database import Base


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite session for task API tests."""
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


def test_get_task_prd_file_reads_fixed_task_specific_path(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """PRD file lookup should keep using `tasks/prd-{task_id[:8]}.md`."""
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
        task_title="PRD contract verification",
        worktree_path=str(tmp_path),
    )
    db_session.add(task_obj)
    db_session.commit()

    tasks_directory_path = tmp_path / "tasks"
    tasks_directory_path.mkdir()

    expected_prd_file_path = tasks_directory_path / f"prd-{task_obj.id[:8]}.md"
    expected_prd_file_path.write_text(
        "# PRD\n\n- 需求名称（AI 归纳）: PRD 输出合同\n",
        encoding="utf-8",
    )

    legacy_style_prd_file_path = tasks_directory_path / "20260317-prd-random.md"
    legacy_style_prd_file_path.write_text(
        "This older wildcard-style file should be ignored.",
        encoding="utf-8",
    )

    prd_file_response = get_task_prd_file(task_obj.id, db_session)

    assert prd_file_response["content"] == (
        "# PRD\n\n- 需求名称（AI 归纳）: PRD 输出合同\n"
    )
    assert prd_file_response["path"] == str(expected_prd_file_path)
