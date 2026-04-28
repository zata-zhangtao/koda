"""API tests for remote requirement collaboration routes."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import backend.dsl.api.projects as projects_api
import backend.dsl.api.tasks as tasks_api
from backend.dsl.app import app
from backend.dsl.models.dev_log import DevLog
from backend.dsl.models.enums import TaskLifecycleStatus, WorkflowStage
from backend.dsl.models.project import Project
from backend.dsl.models.run_account import RunAccount
from backend.dsl.models.task import Task
from backend.dsl.remote_requirements.domain import (
    RemoteRequirementError,
    RemoteRequirementSyncOutcome,
)
from utils.database import Base, get_db


@pytest.fixture
def session_factory() -> Generator[sessionmaker, None, None]:
    """Create an isolated SQLite session factory for API route tests.

    Yields:
        sessionmaker: Test session factory.
    """
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )
    Base.metadata.create_all(bind=test_engine)
    yield test_session_factory
    test_engine.dispose()


def _override_get_db(
    test_session_factory: sessionmaker,
) -> Generator[Session, None, None]:
    """Yield request-scoped SQLAlchemy sessions for API tests.

    Args:
        test_session_factory: Test session factory.

    Yields:
        Session: SQLAlchemy session.
    """
    test_db_session = test_session_factory()
    try:
        yield test_db_session
    finally:
        test_db_session.close()


class FakeTaskRemoteRequirementService:
    """Fake remote requirement service for task route tests."""

    def push_progress(
        self,
        db_session: Session,
        task_id_str: str,
    ) -> Task | None:
        """Record push-progress metadata on a task.

        Args:
            db_session: Database session.
            task_id_str: Task UUID.

        Returns:
            Task | None: Updated task or None.
        """
        task_obj = db_session.get(Task, task_id_str)
        if task_obj is None:
            return None
        task_obj.task_branch_name = "task/12345678-api-route"
        task_obj.remote_requirement_sync_status = "pushed"
        task_obj.remote_requirement_synced_commit_hash = "abc123"
        db_session.commit()
        db_session.refresh(task_obj)
        return task_obj

    def sync_pull_request_status(
        self,
        db_session: Session,
        task_id_str: str,
    ) -> Task | None:
        """Record merged PR metadata on a task.

        Args:
            db_session: Database session.
            task_id_str: Task UUID.

        Returns:
            Task | None: Updated task or None.
        """
        task_obj = db_session.get(Task, task_id_str)
        if task_obj is None:
            return None
        task_obj.github_pr_state = "merged"
        task_obj.remote_requirement_sync_status = "pr_merged"
        task_obj.lifecycle_status = TaskLifecycleStatus.CLOSED
        task_obj.workflow_stage = WorkflowStage.DONE
        db_session.commit()
        db_session.refresh(task_obj)
        return task_obj


class FailingCompleteRemoteRequirementService:
    """Fake remote service that rejects invalid Complete requests."""

    @staticmethod
    def should_use_pull_request_completion(
        project_obj: Project | None,
        task_obj: Task | None,
    ) -> bool:
        """Force the Complete route into the PR-backed branch.

        Args:
            project_obj: Linked project object.
            task_obj: Task object.

        Returns:
            bool: Always true when a task exists.
        """
        return task_obj is not None

    def complete_as_pull_request(
        self,
        db_session: Session,
        task_id_str: str,
        *,
        allow_complete_from_changes_requested_bool: bool = False,
    ) -> Task | None:
        """Raise the same validation error shape as TaskService.

        Args:
            db_session: Database session.
            task_id_str: Task UUID.
            allow_complete_from_changes_requested_bool: Whether changes requested
                completion is allowed.

        Returns:
            Task | None: This fake never returns successfully.

        Raises:
            ValueError: Always raised for this fake.
        """
        raise ValueError("Task cannot complete from stage backlog.")


class FailingPushRemoteRequirementService:
    """Fake remote service that rejects Push Progress requests."""

    def push_progress(
        self,
        db_session: Session,
        task_id_str: str,
    ) -> Task | None:
        """Raise a deterministic remote requirement error.

        Args:
            db_session: Database session.
            task_id_str: Task UUID.

        Returns:
            Task | None: This fake never returns successfully.

        Raises:
            RemoteRequirementError: Always raised for this fake.
        """
        raise RemoteRequirementError("Remote unavailable")


class FakeProjectRemoteRequirementService:
    """Fake remote requirement service for project route tests."""

    def sync_project_remote_requirements(
        self,
        db_session: Session,
        project_obj: Project,
        run_account_id_str: str,
    ) -> RemoteRequirementSyncOutcome:
        """Return deterministic project sync counts.

        Args:
            db_session: Database session.
            project_obj: Project object.
            run_account_id_str: Active run account ID.

        Returns:
            RemoteRequirementSyncOutcome: Fake sync summary.
        """
        return RemoteRequirementSyncOutcome(
            imported_count=2,
            updated_count=1,
            skipped_count=0,
        )


def test_push_progress_route_returns_remote_metadata(
    session_factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The HTTP task route should expose Push Progress remote metadata."""
    seed_session = session_factory()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        seed_session.add(run_account_obj)
        seed_session.commit()
        task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Push via API",
            lifecycle_status=TaskLifecycleStatus.OPEN,
            workflow_stage=WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
        )
        seed_session.add(task_obj)
        seed_session.commit()
        task_id_str = task_obj.id
    finally:
        seed_session.close()

    monkeypatch.setattr(tasks_api, "is_codex_task_running", lambda _task_id: False)
    monkeypatch.setattr(
        tasks_api,
        "RemoteRequirementService",
        lambda: FakeTaskRemoteRequirementService(),
    )

    def _get_test_db() -> Generator[Session, None, None]:
        yield from _override_get_db(session_factory)

    app.dependency_overrides[get_db] = _get_test_db
    with TestClient(app) as test_client:
        response = test_client.post(f"/api/tasks/{task_id_str}/push-progress")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    response_payload = response.json()
    assert response_payload["task_branch_name"] == "task/12345678-api-route"
    assert response_payload["remote_requirement_sync_status"] == "pushed"
    assert response_payload["remote_requirement_synced_commit_hash"] == "abc123"


def test_push_progress_route_returns_422_without_success_log_on_remote_failure(
    session_factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The HTTP route should not emit success semantics when Push Progress fails."""
    seed_session = session_factory()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        seed_session.add(run_account_obj)
        seed_session.commit()
        task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Fail push via API",
            lifecycle_status=TaskLifecycleStatus.OPEN,
            workflow_stage=WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
        )
        seed_session.add(task_obj)
        seed_session.commit()
        task_id_str = task_obj.id
    finally:
        seed_session.close()

    monkeypatch.setattr(tasks_api, "is_codex_task_running", lambda _task_id: False)
    monkeypatch.setattr(
        tasks_api,
        "RemoteRequirementService",
        lambda: FailingPushRemoteRequirementService(),
    )

    def _get_test_db() -> Generator[Session, None, None]:
        yield from _override_get_db(session_factory)

    app.dependency_overrides[get_db] = _get_test_db
    with TestClient(app) as test_client:
        response = test_client.post(f"/api/tasks/{task_id_str}/push-progress")
    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"] == "Remote unavailable"

    assertion_session = session_factory()
    try:
        success_log_count_int = (
            assertion_session.query(DevLog)
            .filter(DevLog.task_id == task_id_str)
            .count()
        )
    finally:
        assertion_session.close()
    assert success_log_count_int == 0


def test_sync_pr_status_route_returns_closed_task(
    session_factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The HTTP task route should expose synced PR status."""
    seed_session = session_factory()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        seed_session.add(run_account_obj)
        seed_session.commit()
        task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Sync PR via API",
            lifecycle_status=TaskLifecycleStatus.OPEN,
            workflow_stage=WorkflowStage.ACCEPTANCE_IN_PROGRESS,
            github_pr_number=128,
        )
        seed_session.add(task_obj)
        seed_session.commit()
        task_id_str = task_obj.id
    finally:
        seed_session.close()

    monkeypatch.setattr(
        tasks_api,
        "RemoteRequirementService",
        lambda: FakeTaskRemoteRequirementService(),
    )

    def _get_test_db() -> Generator[Session, None, None]:
        yield from _override_get_db(session_factory)

    app.dependency_overrides[get_db] = _get_test_db
    with TestClient(app) as test_client:
        response = test_client.post(f"/api/tasks/{task_id_str}/sync-pr-status")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    response_payload = response.json()
    assert response_payload["workflow_stage"] == "done"
    assert response_payload["lifecycle_status"] == "CLOSED"
    assert response_payload["github_pr_state"] == "merged"
    assert response_payload["remote_requirement_sync_status"] == "pr_merged"


def test_remote_complete_route_maps_validation_errors_to_422(
    session_factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The PR-backed Complete route should not leak validation errors as 500s."""
    seed_session = session_factory()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        project_obj = Project(
            display_name="Demo",
            repo_path="/tmp/demo",
            remote_requirement_management_enabled=True,
            github_pr_creation_enabled=True,
        )
        seed_session.add_all([run_account_obj, project_obj])
        seed_session.commit()
        task_obj = Task(
            run_account_id=run_account_obj.id,
            project_id=project_obj.id,
            task_title="Invalid remote complete",
            lifecycle_status=TaskLifecycleStatus.PENDING,
            workflow_stage=WorkflowStage.BACKLOG,
            task_branch_name="task/12345678-invalid-complete",
        )
        seed_session.add(task_obj)
        seed_session.commit()
        task_id_str = task_obj.id
    finally:
        seed_session.close()

    monkeypatch.setattr(tasks_api, "is_codex_task_running", lambda _task_id: False)
    monkeypatch.setattr(
        tasks_api,
        "RemoteRequirementService",
        FailingCompleteRemoteRequirementService,
    )

    def _get_test_db() -> Generator[Session, None, None]:
        yield from _override_get_db(session_factory)

    app.dependency_overrides[get_db] = _get_test_db
    with TestClient(app) as test_client:
        response = test_client.post(f"/api/tasks/{task_id_str}/complete")
    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "cannot complete" in response.json()["detail"]


def test_project_remote_sync_route_returns_counts(
    session_factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The HTTP project route should expose remote sync counts."""
    seed_session = session_factory()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        seed_session.add(run_account_obj)
        seed_session.commit()
        project_obj = Project(
            display_name="Demo",
            repo_path="/tmp/demo",
            remote_requirement_management_enabled=True,
        )
        seed_session.add(project_obj)
        seed_session.commit()
        project_id_str = project_obj.id
    finally:
        seed_session.close()

    monkeypatch.setattr(
        projects_api,
        "RemoteRequirementService",
        lambda: FakeProjectRemoteRequirementService(),
    )

    def _get_test_db() -> Generator[Session, None, None]:
        yield from _override_get_db(session_factory)

    app.dependency_overrides[get_db] = _get_test_db
    with TestClient(app) as test_client:
        response = test_client.post(
            f"/api/projects/{project_id_str}/sync-remote-requirements"
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    response_payload = response.json()
    assert response_payload["project_id"] == project_id_str
    assert response_payload["imported_count"] == 2
    assert response_payload["updated_count"] == 1
    assert response_payload["skipped_count"] == 0
