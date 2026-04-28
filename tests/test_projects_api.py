"""Tests for project editor-opening API helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Generator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import backend.dsl.models  # noqa: F401
import backend.dsl.api.projects as projects_api
from backend.dsl.app import app
from backend.dsl.api.projects import open_project_in_editor, open_project_in_trae
from backend.dsl.models.project import Project
from backend.dsl.worktree_resources import WorktreeResourcePreviewRequestSchema
from utils.database import Base, get_db


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite session for project API tests."""
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


@pytest.fixture
def test_client() -> Generator[TestClient, None, None]:
    """Create an isolated FastAPI test client for project route tests."""
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

    def _get_test_db() -> Generator[Session, None, None]:
        test_db_session = test_session_factory()
        try:
            yield test_db_session
        finally:
            test_db_session.close()

    app.dependency_overrides[get_db] = _get_test_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _run_git_command(repo_root_path: Path, git_argument_list: list[str]) -> str:
    """Run a Git command inside a temporary repository.

    Args:
        repo_root_path: Repository root path.
        git_argument_list: Git argument list.

    Returns:
        str: Trimmed stdout output.
    """
    completed_process = subprocess.run(
        ["git", "-C", str(repo_root_path), *git_argument_list],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed_process.stdout.strip()


def _create_git_repo(repo_root_path: Path) -> Path:
    """Create a real Git repository with main and develop branches.

    Args:
        repo_root_path: Repository root path.

    Returns:
        Path: Created repository root path.
    """
    repo_root_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main", str(repo_root_path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    _run_git_command(repo_root_path, ["config", "user.email", "tester@example.com"])
    _run_git_command(repo_root_path, ["config", "user.name", "Tester"])
    (repo_root_path / "README.md").write_text("hello\n", encoding="utf-8")
    _run_git_command(repo_root_path, ["add", "README.md"])
    _run_git_command(repo_root_path, ["commit", "-m", "init"])
    _run_git_command(repo_root_path, ["checkout", "-b", "develop"])
    return repo_root_path


def test_open_project_in_editor_uses_shared_path_opener(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The neutral project route should delegate to the shared path opener."""
    repo_root_path = tmp_path / "demo-repo"
    repo_root_path.mkdir()
    project_obj = Project(
        display_name="Demo Repo",
        repo_path=str(repo_root_path),
        description="demo",
    )
    db_session.add(project_obj)
    db_session.commit()

    monkeypatch.setattr(
        projects_api.ProjectService,
        "is_repo_path_valid",
        lambda _repo_path: True,
    )
    monkeypatch.setattr(
        projects_api.ProjectService,
        "build_project_consistency_snapshot",
        lambda _project_obj: SimpleNamespace(is_repo_remote_consistent=True),
    )

    opened_target_path_list: list[tuple[Path, str]] = []

    def _fake_open_path_in_editor(target_path: Path, target_kind: str) -> None:
        opened_target_path_list.append((target_path, target_kind))

    monkeypatch.setattr(projects_api, "open_path_in_editor", _fake_open_path_in_editor)

    open_response = open_project_in_editor(project_obj.id, db_session)

    assert open_response == {"opened": str(repo_root_path)}
    assert opened_target_path_list == [(repo_root_path, "project")]


def test_list_project_branches_returns_local_branches_and_current_branch(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """The project branch endpoint should expose local branches for selection."""
    repo_root_path = _create_git_repo(tmp_path / "demo-repo")
    project_obj = Project(
        display_name="Demo Repo",
        repo_path=str(repo_root_path),
        description="demo",
    )
    db_session.add(project_obj)
    db_session.commit()

    branch_response = projects_api.list_project_branches(project_obj.id, db_session)

    assert branch_response.current_branch_name == "develop"
    assert branch_response.branches == ["develop", "main"]


def test_list_projects_does_not_block_on_git_consistency_snapshot(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The project list route should not run Git commands for every project."""

    repo_root_path = tmp_path / "slow-repo"
    repo_root_path.mkdir()
    (repo_root_path / ".git").mkdir()
    project_obj = Project(
        display_name="Slow Repo",
        repo_path=str(repo_root_path),
        description="demo",
    )
    db_session.add(project_obj)
    db_session.commit()

    def _raise_if_full_snapshot_runs(_project_obj: Project) -> object:
        raise AssertionError("full Git consistency snapshot should not run")

    monkeypatch.setattr(
        projects_api.ProjectService,
        "build_project_consistency_snapshot",
        _raise_if_full_snapshot_runs,
    )
    monkeypatch.setattr(
        projects_api.ProjectService,
        "build_project_worktree_resource_policy_snapshot",
        _raise_if_full_snapshot_runs,
    )

    project_response_list = projects_api.list_projects(db_session)

    assert len(project_response_list) == 1
    project_response = project_response_list[0]
    assert project_response.display_name == "Slow Repo"
    assert project_response.is_repo_path_valid is True
    assert project_response.current_repo_remote_url is None
    assert project_response.is_repo_remote_consistent is None


def test_open_project_in_editor_surfaces_path_open_command_errors(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Command-template failures should map to HTTP 500 for project routes."""
    repo_root_path = tmp_path / "demo-repo"
    repo_root_path.mkdir()
    project_obj = Project(
        display_name="Demo Repo",
        repo_path=str(repo_root_path),
        description="demo",
    )
    db_session.add(project_obj)
    db_session.commit()

    monkeypatch.setattr(
        projects_api.ProjectService,
        "is_repo_path_valid",
        lambda _repo_path: True,
    )
    monkeypatch.setattr(
        projects_api.ProjectService,
        "build_project_consistency_snapshot",
        lambda _project_obj: SimpleNamespace(is_repo_remote_consistent=True),
    )

    def _raise_path_open_command_error(*_args: object, **_kwargs: object) -> None:
        raise projects_api.PathOpenCommandError("bad editor config")

    monkeypatch.setattr(
        projects_api,
        "open_path_in_editor",
        _raise_path_open_command_error,
    )

    with pytest.raises(HTTPException) as exc_info:
        open_project_in_editor(project_obj.id, db_session)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "bad editor config"


def test_open_project_in_trae_alias_reuses_editor_logic(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The legacy alias route should reuse the neutral implementation."""
    monkeypatch.setattr(
        projects_api,
        "_open_project_root_in_editor",
        lambda project_id, db_session: {"opened": f"/tmp/{project_id}"},
    )

    open_response = open_project_in_trae("project-123", db_session)

    assert open_response == {"opened": "/tmp/project-123"}


def test_preview_worktree_resource_candidates_returns_repo_candidates(
    tmp_path: Path,
) -> None:
    """The preview route should surface ignored runtime resources."""
    repo_root_path = _create_git_repo(tmp_path / "preview-repo")
    (repo_root_path / ".env").write_text("TOKEN=demo\n", encoding="utf-8")
    (repo_root_path / "node_modules").mkdir()
    (repo_root_path / "node_modules" / "pkg.txt").write_text("deps", encoding="utf-8")

    preview_response = projects_api.preview_worktree_resource_candidates(
        WorktreeResourcePreviewRequestSchema(repo_path=str(repo_root_path))
    )

    preview_path_list = [
        candidate.relative_path for candidate in preview_response.candidates
    ]
    assert ".env" in preview_path_list
    assert "node_modules" in preview_path_list


def test_project_create_http_requires_resource_policy_confirmation(
    test_client: TestClient,
    tmp_path: Path,
) -> None:
    """Project create route should reject missing policy confirmation over HTTP."""
    repo_root_path = _create_git_repo(tmp_path / "http-create-repo")

    missing_confirmation_response = test_client.post(
        "/api/projects",
        json={
            "display_name": "HTTP Create Repo",
            "repo_path": str(repo_root_path),
            "description": None,
        },
    )
    assert missing_confirmation_response.status_code == 422
    assert "worktree_resource_policy_confirmation is required" in str(
        missing_confirmation_response.json()["detail"]
    )

    accepted_default_response = test_client.post(
        "/api/projects",
        json={
            "display_name": "HTTP Create Repo",
            "repo_path": str(repo_root_path),
            "description": None,
            "worktree_resource_policy_confirmation": "accepted_default",
        },
    )

    assert accepted_default_response.status_code == 201
    response_payload = accepted_default_response.json()
    assert response_payload["is_worktree_resource_policy_ready"] is True
    assert (
        response_payload["worktree_resource_policy_confirmation"] == "accepted_default"
    )


def test_preview_worktree_resource_candidates_http_omits_tracked_candidates(
    test_client: TestClient,
    tmp_path: Path,
) -> None:
    """Preview route should only expose local resources needing policy choices."""
    repo_root_path = _create_git_repo(tmp_path / "http-preview-repo")
    (repo_root_path / ".env").write_text("TOKEN=demo\n", encoding="utf-8")

    preview_response = test_client.post(
        "/api/projects/worktree-resource-candidates/preview",
        json={"repo_path": str(repo_root_path)},
    )

    assert preview_response.status_code == 200
    candidate_payload_list = preview_response.json()["candidates"]
    preview_path_list = [
        candidate_payload["relative_path"]
        for candidate_payload in candidate_payload_list
    ]
    assert "README.md" not in preview_path_list
    env_candidate_payload = next(
        candidate_payload
        for candidate_payload in candidate_payload_list
        if candidate_payload["relative_path"] == ".env"
    )
    assert env_candidate_payload["git_state"] == "untracked"
    assert env_candidate_payload["materialization"] == "copy"
