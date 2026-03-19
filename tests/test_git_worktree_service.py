"""Tests for task worktree lifecycle helpers and Git completion flow."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

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


def _write_shell_script(script_path: Path, script_content_text: str) -> Path:
    """Write an executable shell script for repo-local worktree tests.

    Args:
        script_path: Script file path
        script_content_text: Script content

    Returns:
        Path: The executable script path
    """
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script_content_text, encoding="utf-8")
    script_path.chmod(0o755)
    return script_path


def test_create_task_worktree_uses_default_branch_and_path(tmp_path: Path) -> None:
    """Fallback worktree creation should create the expected task branch and path."""
    repo_root_path = _create_git_repo(tmp_path / "demo-repo")

    created_worktree_path = GitWorktreeService.create_task_worktree(
        repo_root_path=repo_root_path,
        task_id="12345678-task-id",
    )

    assert (
        created_worktree_path
        == repo_root_path.parent / "task" / "demo-repo-wt-12345678"
    )
    assert created_worktree_path.exists() is True
    assert (repo_root_path.parent / "task").exists() is True
    assert (
        _run_git_command(created_worktree_path, ["symbolic-ref", "--short", "HEAD"])
        == "task/12345678"
    )


def test_create_task_worktree_passes_task_root_to_path_aware_script(
    tmp_path: Path,
) -> None:
    """Path-aware scripts should receive the new task-root worktree path explicitly."""
    repo_root_path = _create_git_repo(tmp_path / "demo-repo")
    script_capture_path = repo_root_path / "script-invocation.txt"
    _write_shell_script(
        repo_root_path / "scripts" / "new-worktree.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
target_path="$1"
branch_name="$2"
printf '%s\\n%s\\n' "$target_path" "$branch_name" > "{script_capture_path}"
git worktree add "$target_path" -b "$branch_name" main >/dev/null
""",
    )

    created_worktree_path = GitWorktreeService.create_task_worktree(
        repo_root_path=repo_root_path,
        task_id="12345678-task-id",
    )

    assert (
        created_worktree_path
        == repo_root_path.parent / "task" / "demo-repo-wt-12345678"
    )
    assert created_worktree_path.exists() is True
    assert script_capture_path.read_text(encoding="utf-8").splitlines() == [
        str(created_worktree_path),
        "task/12345678",
    ]


def test_create_task_worktree_rejects_branch_only_script_outside_task_root(
    tmp_path: Path,
) -> None:
    """Branch-only scripts should fail when the created worktree is outside `../task/`."""
    repo_root_path = _create_git_repo(tmp_path / "demo-repo")
    _write_shell_script(
        repo_root_path / "git_worktree.sh",
        """#!/usr/bin/env bash
set -euo pipefail
branch_name="$1"
branch_short_name="${branch_name#task/}"
target_path="../rogue/${branch_short_name}"
git worktree add "$target_path" -b "$branch_name" main >/dev/null
""",
    )

    with pytest.raises(ValueError, match=r"实际路径不在 \.\./task/ 根目录下"):
        GitWorktreeService.create_task_worktree(
            repo_root_path=repo_root_path,
            task_id="12345678-task-id",
        )

    assert (repo_root_path.parent / "task").exists() is True


def test_execute_git_completion_flow_merges_and_cleans_up_worktree(
    tmp_path: Path,
) -> None:
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
    assert "feature change" in (repo_root_path / "README.md").read_text(
        encoding="utf-8"
    )
    assert _run_git_command(repo_root_path, ["branch", "--list", "task/12345678"]) == ""
    assert (
        _run_git_command(repo_root_path, ["log", "--format=%s", "-1"])
        == "Summarize the completed branch behavior"
    )
