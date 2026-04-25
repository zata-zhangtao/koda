"""Tests for task worktree lifecycle helpers and Git completion flow."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from backend.dsl.services import codex_runner
from backend.dsl.services.git_worktree_service import GitWorktreeService


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


def _write_text_file(file_path: Path, file_content_text: str) -> Path:
    """Write a UTF-8 text file, creating parent directories as needed.

    Args:
        file_path: Target file path
        file_content_text: File content text

    Returns:
        Path: Written file path
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(file_content_text, encoding="utf-8")
    return file_path


def _commit_all_changes(repo_root_path: Path, commit_message_text: str) -> None:
    """Commit all current repository changes in the temporary repo.

    Args:
        repo_root_path: Repository root path
        commit_message_text: Git commit message
    """
    _run_git_command(repo_root_path, ["add", "."])
    _run_git_command(repo_root_path, ["commit", "-m", commit_message_text])


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


def test_create_task_worktree_accepts_explicit_semantic_branch_name(
    tmp_path: Path,
) -> None:
    """Fallback worktree creation should honor explicit semantic branch names."""
    repo_root_path = _create_git_repo(tmp_path / "demo-repo")
    explicit_branch_name_str = "task/12345678-fix-login-timeout"

    created_worktree_path = GitWorktreeService.create_task_worktree(
        repo_root_path=repo_root_path,
        task_id="12345678-task-id",
        task_branch_name_str=explicit_branch_name_str,
    )

    assert (
        created_worktree_path
        == repo_root_path.parent / "task" / "demo-repo-wt-12345678"
    )
    assert (
        _run_git_command(created_worktree_path, ["symbolic-ref", "--short", "HEAD"])
        == explicit_branch_name_str
    )


def test_create_task_worktree_passes_task_root_to_path_aware_script(
    tmp_path: Path,
) -> None:
    """Path-aware scripts should receive the new task-root worktree path explicitly."""
    repo_root_path = _create_git_repo(tmp_path / "demo-repo")
    source_env_file_path = _write_text_file(repo_root_path / ".env", "TOKEN=demo\n")
    script_capture_path = repo_root_path / "script-invocation.txt"
    _write_shell_script(
        repo_root_path / "scripts" / "new-worktree.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
target_path="$1"
branch_name="$2"
base_branch_name="$3"
printf '%s\\n%s\\n%s\\n' "$target_path" "$branch_name" "$base_branch_name" > "{script_capture_path}"
git worktree add "$target_path" -b "$branch_name" "$base_branch_name" >/dev/null
""",
    )

    created_worktree_path = GitWorktreeService.create_task_worktree(
        repo_root_path=repo_root_path,
        task_id="12345678-task-id",
        base_branch_name_str="main",
    )

    assert (
        created_worktree_path
        == repo_root_path.parent / "task" / "demo-repo-wt-12345678"
    )
    assert created_worktree_path.exists() is True
    assert script_capture_path.read_text(encoding="utf-8").splitlines() == [
        str(created_worktree_path),
        "task/12345678",
        "main",
    ]
    assert (created_worktree_path / ".env").read_text(encoding="utf-8") == (
        source_env_file_path.read_text(encoding="utf-8")
    )


def test_create_task_worktree_bootstraps_env_and_dependencies_for_raw_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raw fallback should bootstrap env files and dependency commands."""
    repo_root_path = _create_git_repo(tmp_path / "demo-repo")
    _write_text_file(
        repo_root_path / "pyproject.toml",
        '[project]\nname = "demo-repo"\nversion = "0.1.0"\nrequires-python = ">=3.13"\n',
    )
    _write_text_file(
        repo_root_path / "frontend" / "package.json",
        '{\n  "name": "demo-frontend",\n  "version": "0.1.0"\n}\n',
    )
    _write_text_file(
        repo_root_path / "frontend" / "package-lock.json",
        '{\n  "name": "demo-frontend",\n  "lockfileVersion": 3,\n  "requires": true,\n  "packages": {\n    "": {\n      "name": "demo-frontend",\n      "version": "0.1.0"\n    }\n  }\n}\n',
    )
    _commit_all_changes(repo_root_path, "add bootstrap fixtures")

    _write_text_file(repo_root_path / ".env", "API_KEY=secret\n")
    _write_text_file(
        repo_root_path / "frontend" / ".env.local",
        "VITE_API_URL=http://localhost\n",
    )

    fake_bin_directory_path = tmp_path / "fake-bin"
    fake_bin_directory_path.mkdir(parents=True, exist_ok=True)
    npm_log_path = tmp_path / "npm.log"
    uv_log_path = tmp_path / "uv.log"
    _write_shell_script(
        fake_bin_directory_path / "npm",
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "{npm_log_path}"
mkdir -p node_modules
touch node_modules/.fake-installed
""",
    )
    _write_shell_script(
        fake_bin_directory_path / "uv",
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "{uv_log_path}"
""",
    )
    monkeypatch.setenv(
        "PATH",
        f"{fake_bin_directory_path}:{os.environ.get('PATH', '')}",
    )

    created_worktree_path = GitWorktreeService.create_task_worktree(
        repo_root_path=repo_root_path,
        task_id="12345678-task-id",
    )

    assert (created_worktree_path / ".env").read_text(
        encoding="utf-8"
    ) == "API_KEY=secret\n"
    assert (created_worktree_path / "frontend" / ".env.local").read_text(
        encoding="utf-8"
    ) == "VITE_API_URL=http://localhost\n"
    assert (
        created_worktree_path / "frontend" / "node_modules" / ".fake-installed"
    ).exists()
    assert npm_log_path.read_text(encoding="utf-8").strip() == "ci --ignore-scripts"
    assert uv_log_path.read_text(encoding="utf-8").strip() == "sync --all-extras"


def test_create_task_worktree_can_use_non_main_base_branch(tmp_path: Path) -> None:
    """Raw fallback worktree creation should branch from the selected local base."""
    repo_root_path = _create_git_repo(tmp_path / "demo-repo")
    _run_git_command(repo_root_path, ["checkout", "-b", "develop"])
    develop_marker_file_path = repo_root_path / "develop.txt"
    develop_marker_file_path.write_text("develop branch only\n", encoding="utf-8")
    _commit_all_changes(repo_root_path, "add develop marker")
    _run_git_command(repo_root_path, ["checkout", "main"])

    created_worktree_path = GitWorktreeService.create_task_worktree(
        repo_root_path=repo_root_path,
        task_id="12345678-task-id",
        base_branch_name_str="develop",
    )

    assert (
        _run_git_command(created_worktree_path, ["symbolic-ref", "--short", "HEAD"])
        == "task/12345678"
    )
    assert (created_worktree_path / "develop.txt").read_text(
        encoding="utf-8"
    ) == "develop branch only\n"


def test_create_task_worktree_fails_when_post_create_bootstrap_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Path-aware create should fail fast when shared bootstrap exits non-zero."""
    repo_root_path = _create_git_repo(tmp_path / "demo-repo")
    _write_text_file(
        repo_root_path / "pyproject.toml",
        '[project]\nname = "demo-repo"\nversion = "0.1.0"\nrequires-python = ">=3.13"\n',
    )
    _commit_all_changes(repo_root_path, "add pyproject")
    _write_shell_script(
        repo_root_path / "scripts" / "new-worktree.sh",
        """#!/usr/bin/env bash
set -euo pipefail
target_path="$1"
branch_name="$2"
base_branch_name="${3:-main}"
git worktree add "$target_path" -b "$branch_name" "$base_branch_name" >/dev/null
""",
    )

    fake_bin_directory_path = tmp_path / "fake-bin"
    fake_bin_directory_path.mkdir(parents=True, exist_ok=True)
    _write_shell_script(
        fake_bin_directory_path / "uv",
        """#!/usr/bin/env bash
set -euo pipefail
echo "uv sync failed in test" >&2
exit 1
""",
    )
    monkeypatch.setenv(
        "PATH",
        f"{fake_bin_directory_path}:{os.environ.get('PATH', '')}",
    )

    with pytest.raises(ValueError, match="环境准备失败"):
        GitWorktreeService.create_task_worktree(
            repo_root_path=repo_root_path,
            task_id="12345678-task-id",
        )


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
base_branch_name="main"
if [ "${2:-}" = "--base" ]; then
  base_branch_name="$3"
fi
branch_short_name="${branch_name#task/}"
target_path="../rogue/${branch_short_name}"
git worktree add "$target_path" -b "$branch_name" "$base_branch_name" >/dev/null
""",
    )

    with pytest.raises(ValueError, match=r"实际路径不在 \.\./task/ 根目录下"):
        GitWorktreeService.create_task_worktree(
            repo_root_path=repo_root_path,
            task_id="12345678-task-id",
        )

    assert (repo_root_path.parent / "task").exists() is True


def test_destroy_task_worktree_falls_back_when_cleanup_script_leaves_artifacts(
    tmp_path: Path,
) -> None:
    """Destroy cleanup should force-clean leftovers for semantic task branches."""
    repo_root_path = _create_git_repo(tmp_path / "demo-repo")
    explicit_branch_name_str = "task/12345678-fix-login-timeout"
    created_worktree_path = GitWorktreeService.create_task_worktree(
        repo_root_path=repo_root_path,
        task_id="12345678-task-id",
        task_branch_name_str=explicit_branch_name_str,
    )
    _write_shell_script(
        repo_root_path / "scripts" / "git_worktree_merge.sh",
        """#!/usr/bin/env bash
set -euo pipefail
echo "noop cleanup"
""",
    )

    destroy_result = GitWorktreeService.destroy_task_worktree(
        repo_root_path=repo_root_path,
        task_id="12345678-task-id",
        worktree_path=created_worktree_path,
    )

    assert destroy_result.cleanup_succeeded is True
    assert destroy_result.worktree_removed is True
    assert destroy_result.branch_deleted is True
    assert created_worktree_path.exists() is False
    assert (
        _run_git_command(repo_root_path, ["branch", "--list", "task/12345678*"]) == ""
    )
    assert any(
        "falling back to force cleanup" in output_line
        for output_line in destroy_result.output_line_list
    )


def test_destroy_task_worktree_removes_orphaned_directory_and_semantic_branch(
    tmp_path: Path,
) -> None:
    """Destroy cleanup should delete orphaned task directories outside Git metadata."""
    repo_root_path = _create_git_repo(tmp_path / "demo-repo")
    orphaned_worktree_path = (
        GitWorktreeService.build_task_worktree_root_path(repo_root_path)
        / "12345678-fix-login-timeout"
    )
    _write_text_file(
        orphaned_worktree_path
        / "demo-frontend"
        / ".vite"
        / "deps_temp_bf8604c5"
        / "package.json",
        '{\n  "name": "demo-frontend"\n}\n',
    )
    _run_git_command(
        repo_root_path,
        ["branch", "task/12345678-fix-login-timeout"],
    )

    destroy_result = GitWorktreeService.destroy_task_worktree(
        repo_root_path=repo_root_path,
        task_id="12345678-task-id",
        worktree_path=orphaned_worktree_path,
    )

    assert destroy_result.cleanup_succeeded is True
    assert destroy_result.worktree_removed is True
    assert destroy_result.branch_deleted is True
    assert orphaned_worktree_path.exists() is False
    assert (
        _run_git_command(repo_root_path, ["branch", "--list", "task/12345678*"]) == ""
    )
    assert any(
        "Removed orphaned task worktree directory directly" in output_line
        for output_line in destroy_result.output_line_list
    )


def test_cleanup_completed_task_worktree_falls_back_when_cleanup_script_leaves_artifacts(
    tmp_path: Path,
) -> None:
    """Completion cleanup should fall back when the repo-local script leaves artifacts."""
    repo_root_path = _create_git_repo(tmp_path / "demo-repo")
    explicit_branch_name_str = "task/12345678-fix-login-timeout"
    created_worktree_path = GitWorktreeService.create_task_worktree(
        repo_root_path=repo_root_path,
        task_id="12345678-task-id",
        task_branch_name_str=explicit_branch_name_str,
    )
    changed_file_path = created_worktree_path / "README.md"
    changed_file_path.write_text("hello\nfeature change\n", encoding="utf-8")
    _commit_all_changes(created_worktree_path, "feature change")
    _run_git_command(
        repo_root_path,
        ["merge", "--no-ff", explicit_branch_name_str, "-m", "merge feature"],
    )
    _write_shell_script(
        repo_root_path / "scripts" / "git_worktree_merge.sh",
        """#!/usr/bin/env bash
set -euo pipefail
echo "noop cleanup"
exit 1
""",
    )

    cleanup_result = GitWorktreeService.cleanup_completed_task_worktree(
        repo_root_path=repo_root_path,
        feature_branch_name=explicit_branch_name_str,
        worktree_path=created_worktree_path,
    )

    assert cleanup_result.cleanup_succeeded is True
    assert cleanup_result.worktree_removed is True
    assert cleanup_result.branch_deleted is True
    assert created_worktree_path.exists() is False
    assert (
        _run_git_command(repo_root_path, ["branch", "--list", explicit_branch_name_str])
        == ""
    )
    assert any(
        "falling back to direct cleanup" in output_line
        for output_line in cleanup_result.output_line_list
    )


def test_execute_git_completion_flow_merges_and_cleans_up_worktree(
    tmp_path: Path,
    monkeypatch,
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
        monkeypatch.setattr(
            codex_runner,
            "_run_logged_runner_commit_message_generation",
            lambda **kwargs: (
                "fix(complete): summarize completed branch behavior",
                ["COMMIT_MESSAGE: fix(complete): summarize completed branch behavior"],
                None,
            ),
        )

        completion_result = codex_runner._execute_git_completion_flow(
            task_id_str="12345678-task-id",
            run_account_id_str="run-account-1",
            task_title_str="Finalize branch",
            commit_information_text_str="Summarize the completed branch behavior",
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
        == "fix(complete): summarize completed branch behavior"
    )


def test_execute_git_completion_flow_uses_non_origin_main_remote(
    tmp_path: Path,
) -> None:
    """Completion should resolve and use the configured non-origin remote for main."""
    repo_root_path = _create_git_repo(tmp_path / "demo-repo")
    bare_remote_path = tmp_path / "demo-remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(bare_remote_path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    _run_git_command(repo_root_path, ["remote", "add", "zata", str(bare_remote_path)])
    _run_git_command(repo_root_path, ["push", "-u", "zata", "main"])

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
            commit_information_text_str="Summarize the completed branch behavior",
            dev_log_text_list=["Implementation already passed review."],
            worktree_path_str=str(created_worktree_path),
        )
    finally:
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._CODEX_LOG_DIR = original_codex_log_dir

    assert completion_result.merged_to_main is True
    assert completion_result.cleanup_succeeded is True
    assert completion_result.worktree_removed is True
    task_log_path = tmp_path / "koda-12345678.log"
    task_log_text = task_log_path.read_text(encoding="utf-8")
    assert "git-fetch-zata" in task_log_text
    assert "git-pull-ff-only-zata" in task_log_text


def test_execute_git_completion_flow_retries_commit_after_hook_autofix(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Completion should restage and retry once when commit hooks mutate files."""
    repo_root_path = _create_git_repo(tmp_path / "demo-repo")
    created_worktree_path = GitWorktreeService.create_task_worktree(
        repo_root_path=repo_root_path,
        task_id="12345678-task-id",
    )

    changed_file_path = created_worktree_path / "README.md"
    changed_file_path.write_text("hello\nfeature change\n", encoding="utf-8")

    _write_shell_script(
        repo_root_path / ".git" / "hooks" / "pre-commit",
        """#!/usr/bin/env bash
set -euo pipefail
marker_file_path="$(git rev-parse --git-common-dir)/commit-hook-ran"
if [ ! -f "${marker_file_path}" ]; then
    printf 'hook generated\\n' > hook-generated.txt
    touch "${marker_file_path}"
    exit 1
fi
""",
    )

    original_write_log_to_db = codex_runner._write_log_to_db
    original_codex_log_dir = codex_runner._CODEX_LOG_DIR

    try:
        codex_runner._write_log_to_db = lambda *args, **kwargs: None
        codex_runner._CODEX_LOG_DIR = tmp_path
        monkeypatch.setattr(
            codex_runner,
            "_run_logged_runner_commit_message_generation",
            lambda **kwargs: (
                "docs: document feature change",
                ["COMMIT_MESSAGE: docs: document feature change"],
                None,
            ),
        )

        completion_result = codex_runner._execute_git_completion_flow(
            task_id_str="12345678-task-id",
            run_account_id_str="run-account-1",
            task_title_str="Finalize branch",
            commit_information_text_str="Summarize the completed branch behavior",
            dev_log_text_list=["Implementation already passed review."],
            worktree_path_str=str(created_worktree_path),
        )
    finally:
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._CODEX_LOG_DIR = original_codex_log_dir

    assert completion_result.merged_to_main is True
    assert completion_result.cleanup_succeeded is True
    assert completion_result.worktree_removed is True
    assert (repo_root_path / "hook-generated.txt").read_text(encoding="utf-8") == (
        "hook generated\n"
    )
    assert (
        _run_git_command(repo_root_path, ["log", "--format=%s", "-1"])
        == "docs: document feature change"
    )

    task_log_path = tmp_path / "koda-12345678.log"
    task_log_text = task_log_path.read_text(encoding="utf-8")
    assert "git-add-after-commit-hook" in task_log_text
    assert "git-commit-rerun" in task_log_text
