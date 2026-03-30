"""Tests for stuck-task watchdog recovery."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import dsl.models  # noqa: F401
from dsl.models.dev_log import DevLog
from dsl.models.enums import DevLogStateTag, TaskLifecycleStatus, WorkflowStage
from dsl.models.run_account import RunAccount
from dsl.models.task import Task
import dsl.services.automation_runner as automation_runner
import dsl.services.task_runner_watchdog_service as watchdog_service
from dsl.services.task_runner_watchdog_service import TaskRunnerWatchdogService
from utils.database import Base
from utils.helpers import utc_now_naive


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite session for watchdog tests."""
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
def clear_watchdog_runtime_state() -> None:
    """Reset in-memory watchdog state between tests."""
    watchdog_service._session_resume_counts.clear()
    yield
    watchdog_service._session_resume_counts.clear()


def test_watchdog_recovers_stale_pr_preparing_runtime_flag(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale `pr_preparing` running flags should be cleared and resumed."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    stale_stage_updated_at = utc_now_naive() - timedelta(minutes=10)
    task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title="Stuck completion runtime flag",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.PR_PREPARING,
        stage_updated_at=stale_stage_updated_at,
        worktree_path="/tmp/repo-wt-stuck-complete",
    )
    db_session.add(task_obj)
    db_session.commit()

    test_session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=db_session.get_bind(),
    )
    monkeypatch.setattr(watchdog_service, "SessionLocal", test_session_factory)

    running_state_by_task_id = {task_obj.id: True}
    cleared_task_id_list: list[str] = []
    resumed_task_id_list: list[str] = []

    def _fake_is_task_automation_running(task_id_str: str) -> bool:
        return running_state_by_task_id.get(task_id_str, False)

    def _fake_clear_task_background_activity(task_id_str: str) -> None:
        cleared_task_id_list.append(task_id_str)
        running_state_by_task_id[task_id_str] = False

    def _fake_attempt_resume_stuck_task(
        task_id_str: str,
        db_session: Session,
    ) -> bool:
        del db_session
        resumed_task_id_list.append(task_id_str)
        return True

    monkeypatch.setattr(
        automation_runner,
        "is_task_automation_running",
        _fake_is_task_automation_running,
    )
    monkeypatch.setattr(
        automation_runner,
        "clear_task_background_activity",
        _fake_clear_task_background_activity,
    )
    monkeypatch.setattr(
        watchdog_service,
        "_attempt_resume_stuck_task",
        _fake_attempt_resume_stuck_task,
    )

    resumed_task_count_int = TaskRunnerWatchdogService.scan_and_resume_stuck_tasks()

    assert resumed_task_count_int == 1
    assert cleared_task_id_list == [task_obj.id]
    assert resumed_task_id_list == [task_obj.id]


def test_watchdog_does_not_clear_active_pr_preparing_task_with_start_log(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Completion tasks that already emitted a start log should not be force-resumed."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    stale_stage_updated_at = utc_now_naive() - timedelta(minutes=10)
    task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title="Active completion should stay untouched",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.PR_PREPARING,
        stage_updated_at=stale_stage_updated_at,
        worktree_path="/tmp/repo-wt-active-complete",
    )
    db_session.add(task_obj)
    db_session.commit()

    db_session.add(
        DevLog(
            task_id=task_obj.id,
            run_account_id=run_account_obj.id,
            text_content=(
                "🚀 已收到完成请求，Koda 正在执行：`git add .` -> `git commit` -> "
                "`git rebase main`。"
            ),
            state_tag=DevLogStateTag.OPTIMIZATION,
        )
    )
    db_session.commit()

    test_session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=db_session.get_bind(),
    )
    monkeypatch.setattr(watchdog_service, "SessionLocal", test_session_factory)

    cleared_task_id_list: list[str] = []
    resumed_task_id_list: list[str] = []

    monkeypatch.setattr(
        automation_runner,
        "is_task_automation_running",
        lambda _task_id_str: True,
    )
    monkeypatch.setattr(
        automation_runner,
        "clear_task_background_activity",
        lambda task_id_str: cleared_task_id_list.append(task_id_str),
    )
    monkeypatch.setattr(
        watchdog_service,
        "_attempt_resume_stuck_task",
        lambda task_id_str, db_session: (
            resumed_task_id_list.append(task_id_str) or True
        ),
    )

    resumed_task_count_int = TaskRunnerWatchdogService.scan_and_resume_stuck_tasks()

    assert resumed_task_count_int == 0
    assert cleared_task_id_list == []
    assert resumed_task_id_list == []
