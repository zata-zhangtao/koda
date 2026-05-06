"""Tests for managed preview sandbox use cases and APIs."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import backend.dsl.models  # noqa: F401
from backend.dsl.models.dev_log import DevLog
from backend.dsl.models.enums import DevLogStateTag
from backend.dsl.models.enums import TaskLifecycleStatus, WorkflowStage
from backend.dsl.models.run_account import RunAccount
from backend.dsl.models.task import Task
from backend.dsl.preview_sandboxes.api import router as preview_sandbox_router
from backend.dsl.preview_sandboxes.application.use_cases import (
    PreviewSandboxUseCase,
    ai_preview_profile_generator,
    docker_preview_runtime,
    is_preview_enabled,
    preview_runtime_registry,
)
from backend.dsl.preview_sandboxes.domain.errors import (
    InvalidPreviewProfileError,
    PreviewCompletionBlockedError,
    PreviewNotAvailableError,
)
from backend.dsl.preview_sandboxes.domain.models import (
    PreviewFailureKind,
    PreviewRuntimeHandle,
)
from backend.dsl.preview_sandboxes.infrastructure.docker_preview_runtime import (
    _sanitize_log_text,
)
from utils.database import Base, get_db
from utils.settings import config


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite session for preview sandbox tests."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
def clear_preview_runtime_registry() -> None:
    """Reset preview runtime handles between tests."""
    preview_runtime_registry._runtime_handle_by_task_id.clear()


def _create_task(db_session: Session, tmp_path: Path) -> Task:
    """Create a worktree-backed task for preview tests."""
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    task_obj = Task(
        run_account=run_account_obj,
        task_title="Preview target",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.TEST_IN_PROGRESS,
        worktree_path=str(worktree_path),
    )
    db_session.add_all([run_account_obj, task_obj])
    db_session.commit()
    db_session.refresh(task_obj)
    return task_obj


def _app_with_db(db_session: Session) -> FastAPI:
    """Build a FastAPI test app with an overridden DB dependency."""
    test_app = FastAPI()
    test_app.include_router(preview_sandbox_router)

    def override_get_db():
        yield db_session

    test_app.dependency_overrides[get_db] = override_get_db
    return test_app


def _applicable_profile() -> dict[str, object]:
    """Return a minimal valid applicable preview profile."""
    return {
        "schema_version": 1,
        "applicability": "applicable",
        "applicability_reason": "Vite app detected.",
        "profile_fingerprint": {
            "git_head": "abc123",
            "dirty_diff_hash": "sha256:test",
        },
        "runtime_kind": "node",
        "working_directory": ".",
        "dependency_commands": ["npm install"],
        "start_command": "npm run dev -- --host 0.0.0.0 --port 5173",
        "internal_port": 5173,
        "healthcheck_path": "/",
        "preview_path": "/",
        "readiness_timeout_seconds": 90,
        "notes": "Test profile",
    }


def test_store_not_applicable_profile_returns_not_applicable_status(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Not-applicable profiles should not require Docker startup."""
    task_obj = _create_task(db_session, tmp_path)
    preview_use_case = PreviewSandboxUseCase(db_session)

    status_snapshot = preview_use_case.store_profile(
        task_obj.id,
        {
            "schema_version": 1,
            "applicability": "not_applicable",
            "applicability_reason": "No HTTP preview target.",
            "runtime_kind": "unknown",
        },
    )

    assert status_snapshot.status.value == "not_applicable"
    assert status_snapshot.applicability.value == "not_applicable"
    assert "No HTTP preview target" in (status_snapshot.profile_summary or "")


def test_store_uncertain_profile_returns_uncertain_status(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Uncertain profiles should be visible without auto-starting Docker."""
    task_obj = _create_task(db_session, tmp_path)
    preview_use_case = PreviewSandboxUseCase(db_session)

    status_snapshot = preview_use_case.store_profile(
        task_obj.id,
        {
            "schema_version": 1,
            "applicability": "uncertain",
            "applicability_reason": "Python project detected without a clear HTTP entrypoint.",
            "runtime_kind": "python",
            "working_directory": ".",
            "dependency_commands": ["uv sync"],
        },
    )

    assert status_snapshot.status.value == "uncertain"
    assert status_snapshot.applicability.value == "uncertain"
    assert "Python project detected" in (status_snapshot.profile_summary or "")


def test_invalid_profile_rejects_unsafe_dependency_command(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Unsafe dependency commands should be rejected before execution."""
    task_obj = _create_task(db_session, tmp_path)
    preview_use_case = PreviewSandboxUseCase(db_session)
    unsafe_profile = _applicable_profile()
    unsafe_profile["dependency_commands"] = ["npm install | cat"]

    with pytest.raises(InvalidPreviewProfileError):
        preview_use_case.store_profile(task_obj.id, unsafe_profile)


def test_invalid_profile_rejects_multi_command_start_string(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Preview start commands must stay single-command and shell-safe."""
    task_obj = _create_task(db_session, tmp_path)
    preview_use_case = PreviewSandboxUseCase(db_session)
    unsafe_profile = _applicable_profile()
    unsafe_profile["start_command"] = "npm run dev && echo hacked"

    with pytest.raises(InvalidPreviewProfileError):
        preview_use_case.store_profile(task_obj.id, unsafe_profile)


def test_python_applicable_profile_rejects_uv_sync_dependency_command(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Python Docker previews cannot depend on uv inside the runtime image."""
    task_obj = _create_task(db_session, tmp_path)
    preview_use_case = PreviewSandboxUseCase(db_session)
    python_profile = _applicable_profile()
    python_profile["runtime_kind"] = "python"
    python_profile["dependency_commands"] = ["uv sync"]
    python_profile["start_command"] = "python -m http.server 8000 --bind 0.0.0.0"
    python_profile["internal_port"] = 8000

    with pytest.raises(InvalidPreviewProfileError):
        preview_use_case.store_profile(task_obj.id, python_profile)


def test_start_is_idempotent_for_running_preview(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Starting an already-running preview should return the same handle."""
    task_obj = _create_task(db_session, tmp_path)
    preview_use_case = PreviewSandboxUseCase(db_session)
    preview_use_case.store_profile(task_obj.id, _applicable_profile())
    monkeypatch.setattr(
        type(docker_preview_runtime),
        "start",
        lambda _self, **_: PreviewRuntimeHandle(
            task_id=task_obj.id,
            container_id="container-123",
            host_port=35173,
            internal_port=5173,
            preview_url="http://127.0.0.1:35173/",
            log_tail="runtime-started",
        ),
    )

    first_status = preview_use_case.start(task_obj.id)
    second_status = preview_use_case.start(task_obj.id)

    assert first_status.status.value == "running"
    assert second_status.status.value == "running"
    assert second_status.preview_url == first_status.preview_url


def test_get_status_returns_disabled_when_preview_flag_is_off(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Feature flag disablement should surface a disabled status."""
    task_obj = _create_task(db_session, tmp_path)
    preview_use_case = PreviewSandboxUseCase(db_session)
    assert is_preview_enabled() is True
    monkeypatch.setattr(config, "KODA_PREVIEW_ENABLED", False)

    status_snapshot = preview_use_case.get_status(task_obj.id)

    assert status_snapshot.status.value == "disabled"


def test_complete_is_blocked_after_non_code_failure_until_bypass(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Non-code preview failures should require retry or explicit bypass."""
    task_obj = _create_task(db_session, tmp_path)
    preview_use_case = PreviewSandboxUseCase(db_session)
    preview_use_case.record_failure(
        task_obj.id,
        PreviewFailureKind.ENVIRONMENT_ERROR,
        "DATABASE_URL is missing.",
    )

    with pytest.raises(PreviewCompletionBlockedError):
        preview_use_case.assert_complete_allowed(task_obj.id)

    preview_use_case.confirm_bypass(task_obj.id)

    preview_use_case.assert_complete_allowed(task_obj.id)


def test_preview_api_start_accepts_profile_payload(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The start endpoint should store a profile and return running status."""
    task_obj = _create_task(db_session, tmp_path)
    test_client = TestClient(_app_with_db(db_session))
    monkeypatch.setattr(
        type(docker_preview_runtime),
        "start",
        lambda _self, **_: PreviewRuntimeHandle(
            task_id=task_obj.id,
            container_id="container-123",
            host_port=35173,
            internal_port=5173,
            preview_url="http://127.0.0.1:35173/",
            log_tail="runtime-started",
        ),
    )

    response = test_client.post(
        f"/api/tasks/{task_obj.id}/preview-sandbox/start",
        json=_applicable_profile(),
    )

    assert response.status_code == 200
    response_payload = response.json()
    assert response_payload["status"] == "running"
    assert response_payload["preview_url"] == "http://127.0.0.1:35173/"


def test_start_infers_frontend_profile_when_missing(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Start should infer a frontend preview profile when one is missing."""
    task_obj = _create_task(db_session, tmp_path)
    frontend_dir_path = Path(task_obj.worktree_path or "") / "frontend"
    frontend_dir_path.mkdir()
    (frontend_dir_path / "package.json").write_text("{}", encoding="utf-8")
    preview_use_case = PreviewSandboxUseCase(db_session)
    monkeypatch.setattr(
        type(docker_preview_runtime),
        "start",
        lambda _self, **_: PreviewRuntimeHandle(
            task_id=task_obj.id,
            container_id="container-frontend",
            host_port=35173,
            internal_port=5173,
            preview_url="http://127.0.0.1:35173/",
            log_tail="runtime-started",
        ),
    )

    status_snapshot = preview_use_case.start(task_obj.id)

    assert status_snapshot.status.value == "running"
    assert status_snapshot.preview_url == "http://127.0.0.1:35173/"


def test_start_records_sandbox_failure_as_human_action(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preview start failures should persist as retry-or-bypass state."""
    task_obj = _create_task(db_session, tmp_path)
    preview_use_case = PreviewSandboxUseCase(db_session)
    preview_use_case.store_profile(task_obj.id, _applicable_profile())

    def _raise_preview_not_available(
        _self: object,
        **_: object,
    ) -> PreviewRuntimeHandle:
        raise PreviewNotAvailableError(
            "Docker preview start failed: daemon unavailable"
        )

    monkeypatch.setattr(
        type(docker_preview_runtime),
        "start",
        _raise_preview_not_available,
    )

    status_snapshot = preview_use_case.start(task_obj.id)

    assert status_snapshot.status.value == "needs_human_action"
    assert status_snapshot.failure_kind == PreviewFailureKind.SANDBOX_ERROR
    assert "daemon unavailable" in (status_snapshot.failure_summary or "")


def test_start_uses_ai_preview_profile_for_uncertain_python_project(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AI fallback should resolve uncertain Python projects into a runnable profile."""
    task_obj = _create_task(db_session, tmp_path)
    worktree_path = Path(task_obj.worktree_path or "")
    (worktree_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\n", encoding="utf-8"
    )
    preview_use_case = PreviewSandboxUseCase(db_session)

    monkeypatch.setattr(
        type(ai_preview_profile_generator),
        "generate_preview_profile_dict",
        lambda _self, **_: {
            "schema_version": 1,
            "applicability": "applicable",
            "applicability_reason": "Streamlit app detected from app.py.",
            "runtime_kind": "python",
            "working_directory": ".",
            "dependency_commands": ["pip install -e ."],
            "start_command": (
                "python -m streamlit run app.py --server.address 0.0.0.0 "
                "--server.port 8501"
            ),
            "internal_port": 8501,
            "healthcheck_path": "/",
            "preview_path": "/",
            "readiness_timeout_seconds": 90,
            "notes": "AI-derived preview profile.",
        },
    )
    monkeypatch.setattr(
        type(docker_preview_runtime),
        "start",
        lambda _self, **_: PreviewRuntimeHandle(
            task_id=task_obj.id,
            container_id="container-python",
            host_port=38501,
            internal_port=8501,
            preview_url="http://127.0.0.1:38501/",
            log_tail="runtime-started",
        ),
    )

    status_snapshot = preview_use_case.start(task_obj.id)

    assert status_snapshot.status.value == "running"
    assert status_snapshot.preview_url == "http://127.0.0.1:38501/"
    latest_status_snapshot = preview_use_case.get_status(task_obj.id)
    assert latest_status_snapshot.applicability is not None
    assert latest_status_snapshot.applicability.value == "applicable"


def test_start_keeps_uncertain_when_ai_preview_profile_generation_fails(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unresolved AI fallback should keep the task in uncertain state."""
    task_obj = _create_task(db_session, tmp_path)
    worktree_path = Path(task_obj.worktree_path or "")
    (worktree_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\n", encoding="utf-8"
    )
    preview_use_case = PreviewSandboxUseCase(db_session)

    monkeypatch.setattr(
        type(ai_preview_profile_generator),
        "generate_preview_profile_dict",
        lambda _self, **_: None,
    )

    status_snapshot = preview_use_case.start(task_obj.id)

    assert status_snapshot.status.value == "uncertain"


def test_stop_returns_stopped_status_instead_of_runtime_lost(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deliberate stop should remain stopped on later status reads."""
    task_obj = _create_task(db_session, tmp_path)
    preview_use_case = PreviewSandboxUseCase(db_session)
    preview_use_case.store_profile(task_obj.id, _applicable_profile())
    monkeypatch.setattr(
        type(docker_preview_runtime),
        "start",
        lambda _self, **_: PreviewRuntimeHandle(
            task_id=task_obj.id,
            container_id="container-stop",
            host_port=35173,
            internal_port=5173,
            preview_url="http://127.0.0.1:35173/",
            log_tail="runtime-started",
        ),
    )
    monkeypatch.setattr(
        type(docker_preview_runtime), "stop", lambda _self, _handle: None
    )

    preview_use_case.start(task_obj.id)
    preview_use_case.stop(task_obj.id)
    status_snapshot = preview_use_case.get_status(task_obj.id)

    assert status_snapshot.status.value == "stopped"


def test_status_returns_runtime_state_lost_after_start_attempt_without_handle(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """A prior start attempt with no in-memory handle should surface lost state."""
    task_obj = _create_task(db_session, tmp_path)
    preview_use_case = PreviewSandboxUseCase(db_session)
    preview_use_case.store_profile(task_obj.id, _applicable_profile())
    db_session.add(
        DevLog(
            task_id=task_obj.id,
            run_account_id=task_obj.run_account_id,
            text_content=(
                "<!-- preview-sandbox:start-attempted -->\n"
                "Preview sandbox start attempted."
            ),
            state_tag=DevLogStateTag.OPTIMIZATION,
        )
    )
    db_session.commit()

    status_snapshot = preview_use_case.get_status(task_obj.id)

    assert status_snapshot.status.value == "runtime_state_lost"


def test_sanitize_log_text_redacts_uppercase_assignments() -> None:
    """Preview log sanitization should redact simple env-style assignments."""
    sanitized_log_text = _sanitize_log_text(
        "DATABASE_URL=postgres://secret\nhello world\nAPI_TOKEN=abc123"
    )

    assert sanitized_log_text == "DATABASE_URL=***\nhello world\nAPI_TOKEN=***"
