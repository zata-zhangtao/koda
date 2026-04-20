"""Tests for project editor-opening API helpers."""

from __future__ import annotations

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
