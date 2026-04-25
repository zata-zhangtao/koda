"""Runner-agnostic automation orchestration entrypoints.

This module provides stable workflow entrypoints for API routes while the
underlying runner implementation is selected by configuration.
"""

from __future__ import annotations

from pathlib import Path

from backend.dsl.services.codex_runner import (
    cancel_codex_task,
    clear_task_background_activity,
    get_active_runner_kind,
    get_task_log_path,
    is_codex_task_running,
    register_task_background_activity,
    run_codex_completion,
    run_codex_review_only,
    run_codex_prd,
    run_codex_review_resume,
    run_codex_task,
    run_post_review_lint_resume,
)


def get_current_runner_kind() -> str:
    """Return current configured runner kind.

    Returns:
        str: Active runner kind from runtime config.
    """
    return get_active_runner_kind()


def cancel_task_automation(task_id_str: str) -> bool:
    """Cancel task automation for a task.

    Args:
        task_id_str: Task UUID string.

    Returns:
        bool: Whether a running automation process was interrupted.
    """
    return cancel_codex_task(task_id_str)


def is_task_automation_running(task_id_str: str) -> bool:
    """Check whether task automation is still running.

    Args:
        task_id_str: Task UUID string.

    Returns:
        bool: Whether task automation is still running.
    """
    return is_codex_task_running(task_id_str)


async def run_task_prd(
    task_id_str: str,
    run_account_id_str: str,
    task_title_str: str,
    dev_log_text_list: list[str],
    work_dir_path: Path,
    worktree_path_str: str | None = None,
    auto_confirm_prd_and_execute_bool: bool | None = None,
) -> None:
    """Run PRD generation stage with the active runner.

    Args:
        task_id_str: Task UUID string.
        run_account_id_str: Run account UUID string.
        task_title_str: Task title.
        dev_log_text_list: Task context log texts.
        work_dir_path: Working directory.
        worktree_path_str: Optional worktree path.
        auto_confirm_prd_and_execute_bool: Optional task strategy override for
            skipping manual PRD confirmation and continuing directly to
            implementation.
    """
    await run_codex_prd(
        task_id_str=task_id_str,
        run_account_id_str=run_account_id_str,
        task_title_str=task_title_str,
        dev_log_text_list=dev_log_text_list,
        work_dir_path=work_dir_path,
        worktree_path_str=worktree_path_str,
        auto_confirm_prd_and_execute_bool=auto_confirm_prd_and_execute_bool,
    )


async def run_task_implementation(
    task_id_str: str,
    run_account_id_str: str,
    task_title_str: str,
    dev_log_text_list: list[str],
    work_dir_path: Path,
    worktree_path_str: str | None = None,
) -> None:
    """Run implementation stage with the active runner.

    Args:
        task_id_str: Task UUID string.
        run_account_id_str: Run account UUID string.
        task_title_str: Task title.
        dev_log_text_list: Task context log texts.
        work_dir_path: Working directory.
        worktree_path_str: Optional worktree path.
    """
    await run_codex_task(
        task_id_str=task_id_str,
        run_account_id_str=run_account_id_str,
        task_title_str=task_title_str,
        dev_log_text_list=dev_log_text_list,
        work_dir_path=work_dir_path,
        worktree_path_str=worktree_path_str,
    )


async def run_task_self_review_resume(
    task_id_str: str,
    run_account_id_str: str,
    task_title_str: str,
    dev_log_text_list: list[str],
    work_dir_path: Path,
    worktree_path_str: str | None = None,
) -> None:
    """Resume self-review stage with the active runner.

    Args:
        task_id_str: Task UUID string.
        run_account_id_str: Run account UUID string.
        task_title_str: Task title.
        dev_log_text_list: Task context log texts.
        work_dir_path: Working directory.
        worktree_path_str: Optional worktree path.
    """
    await run_codex_review_resume(
        task_id_str=task_id_str,
        run_account_id_str=run_account_id_str,
        task_title_str=task_title_str,
        dev_log_text_list=dev_log_text_list,
        work_dir_path=work_dir_path,
        worktree_path_str=worktree_path_str,
    )


async def run_task_review(
    task_id_str: str,
    run_account_id_str: str,
    task_title_str: str,
    dev_log_text_list: list[str],
    work_dir_path: Path,
    worktree_path_str: str | None = None,
) -> None:
    """Run standalone review-only stage with the active runner.

    Args:
        task_id_str: Task UUID string.
        run_account_id_str: Run account UUID string.
        task_title_str: Task title.
        dev_log_text_list: Task context log texts.
        work_dir_path: Working directory.
        worktree_path_str: Optional worktree path.
    """
    await run_codex_review_only(
        task_id_str=task_id_str,
        run_account_id_str=run_account_id_str,
        task_title_str=task_title_str,
        dev_log_text_list=dev_log_text_list,
        work_dir_path=work_dir_path,
        worktree_path_str=worktree_path_str,
    )


async def run_task_post_review_lint_resume(
    task_id_str: str,
    run_account_id_str: str,
    task_title_str: str,
    dev_log_text_list: list[str],
    work_dir_path: Path,
    worktree_path_str: str | None = None,
) -> None:
    """Resume post-review lint stage.

    Args:
        task_id_str: Task UUID string.
        run_account_id_str: Run account UUID string.
        task_title_str: Task title.
        dev_log_text_list: Task context log texts.
        work_dir_path: Working directory.
        worktree_path_str: Optional worktree path.
    """
    await run_post_review_lint_resume(
        task_id_str=task_id_str,
        run_account_id_str=run_account_id_str,
        task_title_str=task_title_str,
        dev_log_text_list=dev_log_text_list,
        work_dir_path=work_dir_path,
        worktree_path_str=worktree_path_str,
    )


async def run_task_completion(
    task_id_str: str,
    run_account_id_str: str,
    task_title_str: str,
    commit_information_text_str: str | None,
    commit_information_source_str: str,
    dev_log_text_list: list[str],
    work_dir_path: Path,
    worktree_path_str: str,
    base_branch_name_str: str = "main",
) -> None:
    """Run completion stage with deterministic Git operations.

    Args:
        task_id_str: Task UUID string.
        run_account_id_str: Run account UUID string.
        task_title_str: Task title.
        commit_information_text_str: Resolved commit information text.
        commit_information_source_str: Commit information source label.
        dev_log_text_list: Task context log texts.
        work_dir_path: Working directory.
        worktree_path_str: Worktree path.
        base_branch_name_str: Branch used for rebase and merge target.
    """
    await run_codex_completion(
        task_id_str=task_id_str,
        run_account_id_str=run_account_id_str,
        task_title_str=task_title_str,
        commit_information_text_str=commit_information_text_str,
        commit_information_source_str=commit_information_source_str,
        dev_log_text_list=dev_log_text_list,
        work_dir_path=work_dir_path,
        worktree_path_str=worktree_path_str,
        base_branch_name_str=base_branch_name_str,
    )


__all__ = [
    "cancel_task_automation",
    "clear_task_background_activity",
    "get_current_runner_kind",
    "get_task_log_path",
    "is_task_automation_running",
    "register_task_background_activity",
    "run_task_completion",
    "run_task_implementation",
    "run_task_post_review_lint_resume",
    "run_task_prd",
    "run_task_review",
    "run_task_self_review_resume",
]
