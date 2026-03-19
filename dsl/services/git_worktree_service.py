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
        expected_worktree_path: Path expected to exist after success for path-aware strategies
        branch_name_for_lookup: Branch name used to resolve the real path for branch-only scripts
    """

    command_argument_list: list[str]
    expected_worktree_path: Path | None
    branch_name_for_lookup: str | None = None


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
        task_worktree_root_path = GitWorktreeService.build_task_worktree_root_path(
            repo_root_path
        )
        return task_worktree_root_path / f"{repo_root_path.name}-wt-{task_short_id_str}"

    @staticmethod
    def build_task_worktree_root_path(repo_root_path: Path) -> Path:
        """Build the default root directory for new task worktrees.

        Args:
            repo_root_path: Repository root path

        Returns:
            Path: Default task worktree root path
        """
        return repo_root_path.parent / "task"

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
        task_worktree_root_path = GitWorktreeService.build_task_worktree_root_path(
            repo_root_path
        )
        task_worktree_root_path.mkdir(parents=True, exist_ok=True)

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
            raise ValueError(
                f"创建 git worktree 失败：{failure_reason_text}"
            ) from git_error

        created_worktree_path = GitWorktreeService._resolve_created_worktree_path(
            repo_root_path=repo_root_path,
            command_spec_obj=command_spec_obj,
        )
        if not created_worktree_path.exists():
            raise ValueError(
                "创建 git worktree 后未找到预期目录：" f"{created_worktree_path}"
            )

        return created_worktree_path

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
        return next(
            (
                candidate
                for candidate in cleanup_script_candidates
                if candidate.exists()
            ),
            None,
        )

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
        default_worktree_path = GitWorktreeService.build_task_worktree_path(
            repo_root_path, task_id
        )

        path_and_branch_script_candidates = [
            repo_root_path / "scripts" / "new-worktree.sh",
            repo_root_path / "scripts" / "create-worktree.sh",
            repo_root_path / "new-worktree.sh",
            repo_root_path / "create-worktree.sh",
        ]
        path_and_branch_script_path = next(
            (
                candidate
                for candidate in path_and_branch_script_candidates
                if candidate.exists()
            ),
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
            (
                candidate
                for candidate in branch_only_script_candidates
                if candidate.exists()
            ),
            None,
        )
        if branch_only_script_path is not None:
            return WorktreeCreateCommandSpec(
                command_argument_list=[
                    str(branch_only_script_path),
                    task_branch_name_str,
                ],
                expected_worktree_path=None,
                branch_name_for_lookup=task_branch_name_str,
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

    @staticmethod
    def _resolve_created_worktree_path(
        repo_root_path: Path,
        command_spec_obj: WorktreeCreateCommandSpec,
    ) -> Path:
        """Resolve the created worktree path after a successful create command.

        Args:
            repo_root_path: Repository root path
            command_spec_obj: Create command specification

        Returns:
            Path: The created worktree path

        Raises:
            ValueError: When the created path cannot be resolved or violates the task root policy
        """
        if command_spec_obj.expected_worktree_path is not None:
            return command_spec_obj.expected_worktree_path

        branch_name_for_lookup = command_spec_obj.branch_name_for_lookup
        if branch_name_for_lookup is None:
            raise ValueError("创建 git worktree 后未找到预期目录：缺少分支定位信息。")

        resolved_worktree_path = GitWorktreeService._resolve_worktree_path_for_branch(
            repo_root_path=repo_root_path,
            branch_name_str=branch_name_for_lookup,
        )
        if resolved_worktree_path is None:
            raise ValueError(
                "创建 git worktree 后未找到预期目录："
                f"未找到分支 {branch_name_for_lookup} 对应的 worktree。"
            )

        GitWorktreeService._validate_worktree_path_within_task_root(
            repo_root_path=repo_root_path,
            created_worktree_path=resolved_worktree_path,
        )
        return resolved_worktree_path

    @staticmethod
    def _resolve_worktree_path_for_branch(
        repo_root_path: Path,
        branch_name_str: str,
    ) -> Path | None:
        """Resolve the worktree path that currently holds the target branch.

        Args:
            repo_root_path: Repository root path
            branch_name_str: Branch name to locate

        Returns:
            Path | None: Matching worktree path when found
        """
        try:
            completed_process = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=str(repo_root_path),
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, subprocess.CalledProcessError):
            return None

        current_worktree_path: Path | None = None
        branch_reference_str = f"refs/heads/{branch_name_str}"
        for output_line_str in completed_process.stdout.splitlines():
            if output_line_str.startswith("worktree "):
                current_worktree_path = Path(
                    output_line_str.removeprefix("worktree ").strip()
                )
                continue

            if (
                output_line_str.startswith("branch ")
                and current_worktree_path is not None
            ):
                current_branch_reference_str = output_line_str.removeprefix(
                    "branch "
                ).strip()
                if current_branch_reference_str == branch_reference_str:
                    return current_worktree_path.resolve()
                current_worktree_path = None

        return None

    @staticmethod
    def _validate_worktree_path_within_task_root(
        repo_root_path: Path,
        created_worktree_path: Path,
    ) -> None:
        """Validate that a created worktree lives under the configured task root.

        Args:
            repo_root_path: Repository root path
            created_worktree_path: Created worktree path resolved from Git metadata

        Raises:
            ValueError: When the created path is outside the `../task/` root
        """
        task_worktree_root_path = GitWorktreeService.build_task_worktree_root_path(
            repo_root_path
        ).resolve()
        resolved_created_worktree_path = created_worktree_path.resolve()

        if (
            resolved_created_worktree_path == task_worktree_root_path
            or task_worktree_root_path in resolved_created_worktree_path.parents
        ):
            return

        raise ValueError(
            "实际路径不在 ../task/ 根目录下："
            f"{resolved_created_worktree_path}（期望根目录：{task_worktree_root_path}）"
        )
