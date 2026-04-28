"""Tests for the task archive pre-commit hook."""

from __future__ import annotations

import subprocess
from pathlib import Path

from hooks import archive_tasks


def _run_git_command(
    repo_root_path: Path, git_args: list[str]
) -> subprocess.CompletedProcess[str]:
    """Run a git command in the temporary repository.

    Args:
        repo_root_path (Path): Repository root for the git command.
        git_args (list[str]): Git arguments excluding the ``git`` executable.

    Returns:
        subprocess.CompletedProcess[str]: Completed process with captured output.
    """

    return subprocess.run(
        ["git", *git_args],
        cwd=repo_root_path,
        check=True,
        capture_output=True,
        text=True,
    )


def _create_initialized_git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repository for archive hook tests.

    Args:
        tmp_path (Path): Pytest temporary directory.

    Returns:
        Path: Initialized repository root path.
    """

    _run_git_command(tmp_path, ["init"])
    _run_git_command(tmp_path, ["config", "user.name", "Test User"])
    _run_git_command(tmp_path, ["config", "user.email", "test@example.com"])
    return tmp_path


def test_archive_tasks_skips_staged_pending_prd(monkeypatch, tmp_path: Path) -> None:
    """Staged PRD templates in tasks/pending must stay in pending."""

    repo_root_path = _create_initialized_git_repo(tmp_path)
    pending_prd_path = repo_root_path / "tasks" / "pending" / "draft.md"
    pending_prd_path.parent.mkdir(parents=True)
    pending_prd_path.write_text("# Pending draft\n", encoding="utf-8")
    _run_git_command(repo_root_path, ["add", "tasks/pending/draft.md"])
    monkeypatch.setattr(archive_tasks, "_repo_root", lambda: repo_root_path)

    exit_code = archive_tasks.main()

    assert exit_code == 0
    assert pending_prd_path.exists()
    assert not (repo_root_path / "tasks" / "archive" / "draft.md").exists()


def test_archive_tasks_moves_staged_root_task_markdown(
    monkeypatch, tmp_path: Path
) -> None:
    """Staged root task Markdown files are still archived before commit."""

    repo_root_path = _create_initialized_git_repo(tmp_path)
    task_markdown_path = repo_root_path / "tasks" / "active.md"
    task_markdown_path.parent.mkdir(parents=True)
    task_markdown_path.write_text("# Active task\n", encoding="utf-8")
    _run_git_command(repo_root_path, ["add", "tasks/active.md"])
    monkeypatch.setattr(archive_tasks, "_repo_root", lambda: repo_root_path)

    exit_code = archive_tasks.main()

    assert exit_code == 0
    assert not task_markdown_path.exists()
    assert (repo_root_path / "tasks" / "archive" / "active.md").exists()
