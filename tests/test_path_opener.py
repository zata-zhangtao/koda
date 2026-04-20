"""Tests for configurable editor path opening helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

import backend.dsl.services.path_opener as path_opener
from backend.dsl.services.path_opener import (
    PathOpenCommandError,
    PathOpenTargetNotFoundError,
    build_path_open_command,
    open_path_in_editor,
)


def test_build_path_open_command_uses_shell_safe_path_and_target_kind(
    tmp_path: Path,
) -> None:
    """Templates should receive the resolved path and semantic target kind."""
    target_path = tmp_path / "repo with spaces"
    target_path.mkdir()

    rendered_command = build_path_open_command(
        target_path=target_path,
        target_kind="worktree",
        path_open_command_template=(
            "code --kind {target_kind} --folder {target_path_shell}"
        ),
    )

    assert rendered_command == [
        "code",
        "--kind",
        "worktree",
        "--folder",
        str(target_path.resolve()),
    ]


def test_build_path_open_command_rejects_unknown_placeholder(
    tmp_path: Path,
) -> None:
    """Unknown placeholders should fail with a clear configuration error."""
    target_path = tmp_path / "repo"
    target_path.mkdir()

    with pytest.raises(PathOpenCommandError, match="unknown placeholder"):
        build_path_open_command(
            target_path=target_path,
            target_kind="project",
            path_open_command_template="code {unknown_placeholder}",
        )


def test_open_path_in_editor_rejects_missing_target_path(tmp_path: Path) -> None:
    """Missing directories should fail before any process launch is attempted."""
    missing_target_path = tmp_path / "missing"

    with pytest.raises(PathOpenTargetNotFoundError, match="Target path does not exist"):
        open_path_in_editor(
            target_path=missing_target_path,
            target_kind="project",
            path_open_command_template="code {target_path_shell}",
        )


def test_open_path_in_editor_reports_missing_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing editor binary should surface as a readable runtime error."""
    target_path = tmp_path / "repo"
    target_path.mkdir()

    def _raise_file_not_found(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError

    monkeypatch.setattr(path_opener.subprocess, "Popen", _raise_file_not_found)

    with pytest.raises(PathOpenCommandError, match="Configured editor executable"):
        open_path_in_editor(
            target_path=target_path,
            target_kind="project",
            path_open_command_template="missing-editor {target_path_shell}",
        )
