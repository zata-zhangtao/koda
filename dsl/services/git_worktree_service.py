"""Git worktree lifecycle helpers for task automation.

This module centralizes task-specific branch naming, worktree creation,
and cleanup script discovery so the rest of the workflow can use one
consistent source of truth.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WorktreeCreateCommandSpec:
    """Describe how to create a task worktree.

    Attributes:
        command_argument_list: Command to execute
        expected_worktree_path: Path expected to exist after success
    """

    command_argument_list: list[str]
    expected_worktree_path: Path


class GitWorktreeService:
    """Helpers for task branch and worktree lifecycle operations."""

    @staticmethod
    def build_task_branch_name(task_id: str) -> str:
        """Build the canonical task branch name.

        Args:
            task_id: Task UUID

        Returns:
            str: Task branch name, for example ``task/12345678``
        """
        task_short_id_str = task_id[:8]
        return f"task/{task_short_id_str}"

    @staticmethod
    def build_task_worktree_path(repo_root_path: Path, task_id: str) -> Path:
        """Build the default worktree path used by Koda.

        Args:
            repo_root_path: Repository root path
            task_id: Task UUID

        Returns:
            Path: Default task worktree path
        """
        task_short_id_str = task_id[:8]
        return repo_root_path.parent / f"{repo_root_path.name}-wt-{task_short_id_str}"

    @staticmethod
    def create_task_worktree(repo_root_path: Path, task_id: str) -> Path:
        """Create a task worktree using repo-local scripts when available.

        Args:
            repo_root_path: Repository root path
            task_id: Task UUID

        Returns:
            Path: Created worktree path

        Raises:
            ValueError: When worktree creation fails or the expected path is missing
        """
        command_spec_obj = GitWorktreeService._build_worktree_create_command_spec(
            repo_root_path=repo_root_path,
            task_id=task_id,
        )

        try:
            subprocess.run(
                command_spec_obj.command_argument_list,
                cwd=str(repo_root_path),
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.CalledProcessError as git_error:
            stderr_text = (git_error.stderr or "").strip()
            stdout_text = (git_error.stdout or "").strip()
            failure_reason_text = stderr_text or stdout_text or str(git_error)
            raise ValueError(f"创建 git worktree 失败：{failure_reason_text}") from git_error

        if not command_spec_obj.expected_worktree_path.exists():
            raise ValueError(
                "创建 git worktree 后未找到预期目录："
                f"{command_spec_obj.expected_worktree_path}"
            )

        return command_spec_obj.expected_worktree_path

    @staticmethod
    def resolve_cleanup_script_path(repo_root_path: Path) -> Path | None:
        """Return the repo-local merge/cleanup script when present.

        Args:
            repo_root_path: Repository root path

        Returns:
            Path | None: Cleanup script path when available
        """
        cleanup_script_candidates = [
            repo_root_path / "scripts" / "git_worktree_merge.sh",
            repo_root_path / "git_worktree_merge.sh",
        ]
        return next((candidate for candidate in cleanup_script_candidates if candidate.exists()), None)

    @staticmethod
    def _build_worktree_create_command_spec(
        repo_root_path: Path,
        task_id: str,
    ) -> WorktreeCreateCommandSpec:
        """Choose the correct worktree creation command for the repository.

        Args:
            repo_root_path: Repository root path
            task_id: Task UUID

        Returns:
            WorktreeCreateCommandSpec: Command and expected path information
        """
        task_branch_name_str = GitWorktreeService.build_task_branch_name(task_id)
        default_worktree_path = GitWorktreeService.build_task_worktree_path(repo_root_path, task_id)

        path_and_branch_script_candidates = [
            repo_root_path / "scripts" / "new-worktree.sh",
            repo_root_path / "scripts" / "create-worktree.sh",
            repo_root_path / "new-worktree.sh",
            repo_root_path / "create-worktree.sh",
        ]
        path_and_branch_script_path = next(
            (candidate for candidate in path_and_branch_script_candidates if candidate.exists()),
            None,
        )
        if path_and_branch_script_path is not None:
            return WorktreeCreateCommandSpec(
                command_argument_list=[
                    str(path_and_branch_script_path),
                    str(default_worktree_path),
                    task_branch_name_str,
                ],
                expected_worktree_path=default_worktree_path,
            )

        branch_only_script_candidates = [
            repo_root_path / "scripts" / "git_worktree.sh",
            repo_root_path / "git_worktree.sh",
        ]
        branch_only_script_path = next(
            (candidate for candidate in branch_only_script_candidates if candidate.exists()),
            None,
        )
        if branch_only_script_path is not None:
            script_expected_worktree_path = (repo_root_path.parent / task_branch_name_str).resolve()
            return WorktreeCreateCommandSpec(
                command_argument_list=[str(branch_only_script_path), task_branch_name_str],
                expected_worktree_path=script_expected_worktree_path,
            )

        return WorktreeCreateCommandSpec(
            command_argument_list=[
                "git",
                "worktree",
                "add",
                str(default_worktree_path),
                "-b",
                task_branch_name_str,
                "main",
            ],
            expected_worktree_path=default_worktree_path,
        )
