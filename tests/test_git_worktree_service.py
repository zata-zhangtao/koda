"""Tests for task worktree lifecycle helpers and Git completion flow."""

from __future__ import annotations

import subprocess
from pathlib import Path

from dsl.services import codex_runner
from dsl.services.git_worktree_service import GitWorktreeService


def _run_git_command(repo_root_path: Path, git_argument_list: list[str]) -> str:
    """Run a Git command inside a temporary repository.

    Args:
        repo_root_path: Repository root path
        git_argument_list: Git argument list

    Returns:
        str: Trimmed stdout output
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
    """Create a real Git repository on ``main`` with one commit.

    Args:
        repo_root_path: Repository root path

    Returns:
        Path: Created repository root path
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

    tracked_file_path = repo_root_path / "README.md"
    tracked_file_path.write_text("hello\n", encoding="utf-8")
    _run_git_command(repo_root_path, ["add", "README.md"])
    _run_git_command(repo_root_path, ["commit", "-m", "init"])
    return repo_root_path


def test_create_task_worktree_uses_default_branch_and_path(tmp_path: Path) -> None:
    """Fallback worktree creation should create the expected task branch and path."""
    repo_root_path = _create_git_repo(tmp_path / "demo-repo")

    created_worktree_path = GitWorktreeService.create_task_worktree(
        repo_root_path=repo_root_path,
        task_id="12345678-task-id",
    )

    assert created_worktree_path == repo_root_path.parent / "demo-repo-wt-12345678"
    assert created_worktree_path.exists() is True
    assert _run_git_command(created_worktree_path, ["symbolic-ref", "--short", "HEAD"]) == "task/12345678"


def test_execute_git_completion_flow_merges_and_cleans_up_worktree(tmp_path: Path) -> None:
    """The deterministic completion flow should merge the task branch into main and remove the worktree."""
    repo_root_path = _create_git_repo(tmp_path / "demo-repo")
    created_worktree_path = GitWorktreeService.create_task_worktree(
        repo_root_path=repo_root_path,
        task_id="12345678-task-id",
    )

    changed_file_path = created_worktree_path / "README.md"
    changed_file_path.write_text("hello\nfeature change\n", encoding="utf-8")

    original_write_log_to_db = codex_runner._write_log_to_db
    original_codex_log_dir = codex_runner._CODEX_LOG_DIR

    try:
        codex_runner._write_log_to_db = lambda *args, **kwargs: None
        codex_runner._CODEX_LOG_DIR = tmp_path

        completion_result = codex_runner._execute_git_completion_flow(
            task_id_str="12345678-task-id",
            run_account_id_str="run-account-1",
            task_title_str="Finalize branch",
            task_summary_str="Summarize the completed branch behavior",
            dev_log_text_list=["Implementation already passed review."],
            worktree_path_str=str(created_worktree_path),
        )
    finally:
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._CODEX_LOG_DIR = original_codex_log_dir

    assert completion_result.merged_to_main is True
    assert completion_result.cleanup_succeeded is True
    assert completion_result.worktree_removed is True
    assert created_worktree_path.exists() is False
    assert _run_git_command(repo_root_path, ["branch", "--show-current"]) == "main"
    assert "feature change" in (repo_root_path / "README.md").read_text(encoding="utf-8")
    assert _run_git_command(repo_root_path, ["branch", "--list", "task/12345678"]) == ""
    assert _run_git_command(repo_root_path, ["log", "--format=%s", "-1"]) == "Summarize the completed branch behavior"
