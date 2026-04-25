"""Tests for project editor-opening API helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import backend.dsl.models  # noqa: F401
import backend.dsl.api.projects as projects_api
from backend.dsl.api.projects import open_project_in_editor, open_project_in_trae
from backend.dsl.models.project import Project
from utils.database import Base


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
