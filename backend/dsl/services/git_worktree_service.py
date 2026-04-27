"""Git worktree lifecycle helpers for task automation.

This module centralizes task-specific branch naming, worktree creation,
and cleanup script discovery so the rest of the workflow can use one
consistent source of truth.
"""

from __future__ import annotations

import shutil
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
        requires_post_create_bootstrap: Whether Koda should run the shared
            environment bootstrap after the create command succeeds
    """

    command_argument_list: list[str]
    expected_worktree_path: Path | None
    branch_name_for_lookup: str | None = None
    requires_post_create_bootstrap: bool = False


@dataclass(frozen=True, slots=True)
class WorktreeDestroyResult:
    """Describe the outcome of task worktree cleanup.

    Attributes:
        cleanup_succeeded: Whether the full cleanup completed successfully
        worktree_removed: Whether the worktree directory and Git registration are
            both gone after cleanup
        branch_deleted: Whether all task-local branches for the task are gone after
            cleanup
        output_line_list: Captured stdout/stderr lines from cleanup commands
        failure_reason_text: Optional failure reason when cleanup is incomplete
    """

    cleanup_succeeded: bool
    worktree_removed: bool
    branch_deleted: bool
    output_line_list: list[str]
    failure_reason_text: str | None = None


class GitWorktreeService:
    """Helpers for task branch and worktree lifecycle operations."""

    @staticmethod
    def build_task_branch_name(task_id: str, semantic_slug: str | None = None) -> str:
        """Build the canonical task branch name.

        Args:
            task_id: Task UUID
            semantic_slug: Optional semantic slug for readable branch naming

        Returns:
            str: Task branch name, for example ``task/12345678`` or
                ``task/12345678-fix-login``
        """
        task_short_id_str = task_id[:8]
        if semantic_slug:
            return f"task/{task_short_id_str}-{semantic_slug}"
        return f"task/{task_short_id_str}"

    @staticmethod
    def list_local_task_branch_names(
        git_working_tree_path: Path,
        task_id: str,
    ) -> list[str] | None:
        """List local branch names that belong to one task.

        Args:
            git_working_tree_path: Repository root or worktree path that belongs to the
                target Git repository
            task_id: Task UUID

        Returns:
            list[str] | None: Matching local branch names for the task. Returns an
                empty list when no branch exists, and ``None`` when the repository
                cannot be probed.
        """
        if not git_working_tree_path.exists():
            return None

        canonical_task_branch_name_str = GitWorktreeService.build_task_branch_name(
            task_id
        )
        semantic_task_branch_pattern_str = f"{canonical_task_branch_name_str}-*"

        try:
            completed_process = subprocess.run(
                [
                    "git",
                    "-C",
                    str(git_working_tree_path),
                    "branch",
                    "--list",
                    "--format=%(refname:short)",
                    canonical_task_branch_name_str,
                    semantic_task_branch_pattern_str,
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            return None

        if completed_process.returncode != 0:
            return None

        deduplicated_branch_name_list: list[str] = []
        for raw_branch_name_str in completed_process.stdout.splitlines():
            normalized_branch_name_str = raw_branch_name_str.strip()
            if (
                not normalized_branch_name_str
                or normalized_branch_name_str in deduplicated_branch_name_list
            ):
                continue
            deduplicated_branch_name_list.append(normalized_branch_name_str)

        return deduplicated_branch_name_list

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
    def resolve_git_working_tree_path(candidate_directory_path: Path) -> Path | None:
        """Resolve the Git working-tree root for a candidate directory.

        Args:
            candidate_directory_path: Repository root or worktree path candidate

        Returns:
            Path | None: Resolved working-tree root when the directory belongs to a Git
                working tree; otherwise None
        """
        if not candidate_directory_path.exists():
            return None

        try:
            completed_process = subprocess.run(
                [
                    "git",
                    "-C",
                    str(candidate_directory_path),
                    "rev-parse",
                    "--show-toplevel",
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, subprocess.CalledProcessError):
            return None

        resolved_working_tree_path_str = completed_process.stdout.strip()
        if not resolved_working_tree_path_str:
            return None
        return Path(resolved_working_tree_path_str).resolve()

    @staticmethod
    def check_local_branch_exists(
        git_working_tree_path: Path,
        branch_name_str: str,
    ) -> bool | None:
        """Check whether a local branch exists inside the target Git repository.

        Args:
            git_working_tree_path: Repository root or worktree path that belongs to the
                target Git repository
            branch_name_str: Branch name to verify

        Returns:
            bool | None: True when the branch exists, False when it is missing, and None
                when the repository cannot be probed
        """
        if not git_working_tree_path.exists():
            return None

        try:
            completed_process = subprocess.run(
                [
                    "git",
                    "-C",
                    str(git_working_tree_path),
                    "show-ref",
                    "--verify",
                    "--quiet",
                    f"refs/heads/{branch_name_str}",
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            return None

        if completed_process.returncode == 0:
            return True
        if completed_process.returncode == 1:
            return False
        return None

    @staticmethod
    def is_valid_branch_name(branch_name_str: str) -> bool:
        """Validate a branch name with Git's own refname parser.

        Args:
            branch_name_str: Branch name to validate.

        Returns:
            bool: True when Git accepts the branch name.
        """
        try:
            completed_process = subprocess.run(
                ["git", "check-ref-format", "--branch", branch_name_str],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            return False
        return completed_process.returncode == 0

    @staticmethod
    def create_task_worktree(
        repo_root_path: Path,
        task_id: str,
        task_branch_name_str: str | None = None,
        base_branch_name_str: str = "main",
    ) -> Path:
        """Create a task worktree using repo-local scripts when available.

        Args:
            repo_root_path: Repository root path
            task_id: Task UUID
            task_branch_name_str: Optional branch name override
            base_branch_name_str: Existing local branch used as the worktree base

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
            task_branch_name_str=task_branch_name_str,
            base_branch_name_str=base_branch_name_str,
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
                f"创建 git worktree 后未找到预期目录：{created_worktree_path}"
            )

        if command_spec_obj.requires_post_create_bootstrap:
            GitWorktreeService._bootstrap_worktree_environment(
                repo_root_path=repo_root_path,
                created_worktree_path=created_worktree_path,
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
    def resolve_preferred_remote_name(
        repo_root_path: Path,
        branch_name_str: str = "main",
    ) -> str | None:
        """Resolve the best remote name for sync operations on one branch.

        Args:
            repo_root_path: Repository root path.
            branch_name_str: Branch name whose configured remote should be preferred.

        Returns:
            str | None: Preferred remote name, or ``None`` when no safe choice exists.
        """
        configured_remote_process = subprocess.run(
            ["git", "config", "--get", f"branch.{branch_name_str}.remote"],
            cwd=str(repo_root_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        configured_remote_name_str = (configured_remote_process.stdout or "").strip()
        if configured_remote_name_str:
            remote_probe_process = subprocess.run(
                ["git", "remote", "get-url", configured_remote_name_str],
                cwd=str(repo_root_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if remote_probe_process.returncode == 0:
                return configured_remote_name_str

        remote_list_process = subprocess.run(
            ["git", "remote"],
            cwd=str(repo_root_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if remote_list_process.returncode != 0:
            return None

        remote_name_list = [
            raw_remote_name_str.strip()
            for raw_remote_name_str in remote_list_process.stdout.splitlines()
            if raw_remote_name_str.strip()
        ]
        remote_tracking_ref_process = subprocess.run(
            [
                "git",
                "for-each-ref",
                "--format=%(refname:short)",
                "refs/remotes",
            ],
            cwd=str(repo_root_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if remote_tracking_ref_process.returncode == 0:
            remote_tracking_ref_name_set = {
                raw_remote_tracking_ref_name_str.strip()
                for raw_remote_tracking_ref_name_str in (
                    remote_tracking_ref_process.stdout.splitlines()
                )
                if raw_remote_tracking_ref_name_str.strip()
            }
            matching_remote_name_list = [
                remote_name_str
                for remote_name_str in remote_name_list
                if f"{remote_name_str}/{branch_name_str}"
                in remote_tracking_ref_name_set
            ]
            if len(matching_remote_name_list) == 1:
                return matching_remote_name_list[0]
            if matching_remote_name_list:
                if "origin" in matching_remote_name_list:
                    return "origin"
                if "zata" in matching_remote_name_list:
                    return "zata"
                return matching_remote_name_list[0]

        if len(remote_name_list) == 1:
            return remote_name_list[0]
        if "origin" in remote_name_list:
            return "origin"
        if "zata" in remote_name_list:
            return "zata"
        return None

    @staticmethod
    def cleanup_completed_task_worktree(
        repo_root_path: Path,
        feature_branch_name: str,
        worktree_path: Path | None,
        base_branch_name_str: str = "main",
    ) -> WorktreeDestroyResult:
        """Clean up a successfully merged task worktree and branch.

        Args:
            repo_root_path: Repository root path.
            feature_branch_name: Task branch name already merged into the base branch.
            worktree_path: Task worktree path, if one was recorded.
            base_branch_name_str: Branch used as the merge target and fallback checkout.

        Returns:
            WorktreeDestroyResult: Cleanup execution summary after script and fallback.
        """
        resolved_worktree_path = worktree_path.resolve() if worktree_path else None
        output_line_list: list[str] = []
        cleanup_script_path = GitWorktreeService.resolve_cleanup_script_path(
            repo_root_path
        )
        registered_worktree_exists = False
        if resolved_worktree_path is not None:
            registered_worktree_exists = (
                GitWorktreeService._is_worktree_path_registered(
                    repo_root_path=repo_root_path,
                    worktree_path=resolved_worktree_path,
                )
            )

        if cleanup_script_path is not None and (
            registered_worktree_exists
            or GitWorktreeService._branch_exists(repo_root_path, feature_branch_name)
        ):
            cleanup_command_argument_list = [
                str(cleanup_script_path),
                feature_branch_name,
                base_branch_name_str,
                "--delete",
            ]
            if resolved_worktree_path is not None:
                cleanup_command_argument_list.extend(
                    ["--worktree-path", str(resolved_worktree_path)]
                )
            cleanup_process = subprocess.run(
                cleanup_command_argument_list,
                cwd=str(repo_root_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            output_line_list.extend((cleanup_process.stdout or "").splitlines())
            output_line_list.extend((cleanup_process.stderr or "").splitlines())
            script_worktree_removed = (
                GitWorktreeService._is_task_worktree_fully_removed(
                    repo_root_path=repo_root_path,
                    worktree_path=resolved_worktree_path,
                )
            )
            script_branch_deleted = not GitWorktreeService._branch_exists(
                repo_root_path,
                feature_branch_name,
            )
            if (
                cleanup_process.returncode == 0
                and script_worktree_removed
                and script_branch_deleted
            ):
                return WorktreeDestroyResult(
                    cleanup_succeeded=True,
                    worktree_removed=True,
                    branch_deleted=True,
                    output_line_list=output_line_list,
                )

            output_line_list.append(
                "Repo-local cleanup script did not fully finish completion cleanup; "
                "falling back to direct cleanup."
            )

        if resolved_worktree_path is not None:
            registered_worktree_exists = (
                GitWorktreeService._is_worktree_path_registered(
                    repo_root_path=repo_root_path,
                    worktree_path=resolved_worktree_path,
                )
            )
            if registered_worktree_exists:
                remove_worktree_process = subprocess.run(
                    [
                        "git",
                        "worktree",
                        "remove",
                        "--force",
                        str(resolved_worktree_path),
                    ],
                    cwd=str(repo_root_path),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                output_line_list.extend(
                    (remove_worktree_process.stdout or "").splitlines()
                )
                output_line_list.extend(
                    (remove_worktree_process.stderr or "").splitlines()
                )

            prune_process = subprocess.run(
                ["git", "worktree", "prune"],
                cwd=str(repo_root_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            output_line_list.extend((prune_process.stdout or "").splitlines())
            output_line_list.extend((prune_process.stderr or "").splitlines())

            if (
                resolved_worktree_path.exists()
                and not GitWorktreeService._is_worktree_path_registered(
                    repo_root_path=repo_root_path,
                    worktree_path=resolved_worktree_path,
                )
            ):
                try:
                    GitWorktreeService._remove_orphaned_task_worktree_directory(
                        repo_root_path=repo_root_path,
                        worktree_path=resolved_worktree_path,
                    )
                    output_line_list.append(
                        "Removed orphaned task worktree directory directly because "
                        "Git no longer registered it."
                    )
                except OSError as remove_error:
                    return WorktreeDestroyResult(
                        cleanup_succeeded=False,
                        worktree_removed=False,
                        branch_deleted=not GitWorktreeService._branch_exists(
                            repo_root_path,
                            feature_branch_name,
                        ),
                        output_line_list=output_line_list,
                        failure_reason_text=(
                            "Failed to remove orphaned task worktree directory during "
                            f"completion cleanup: {remove_error}"
                        ),
                    )

        branch_deleted = not GitWorktreeService._branch_exists(
            repo_root_path,
            feature_branch_name,
        )
        if not branch_deleted:
            delete_branch_process = subprocess.run(
                ["git", "branch", "-d", feature_branch_name],
                cwd=str(repo_root_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            output_line_list.extend((delete_branch_process.stdout or "").splitlines())
            output_line_list.extend((delete_branch_process.stderr or "").splitlines())

            branch_deleted = not GitWorktreeService._branch_exists(
                repo_root_path,
                feature_branch_name,
            )
            if not branch_deleted:
                force_delete_branch_process = subprocess.run(
                    ["git", "branch", "-D", feature_branch_name],
                    cwd=str(repo_root_path),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                output_line_list.extend(
                    (force_delete_branch_process.stdout or "").splitlines()
                )
                output_line_list.extend(
                    (force_delete_branch_process.stderr or "").splitlines()
                )
                if force_delete_branch_process.returncode == 0:
                    output_line_list.append(
                        "Force-deleted completed task branch after standard branch "
                        "delete failed."
                    )
                branch_deleted = not GitWorktreeService._branch_exists(
                    repo_root_path,
                    feature_branch_name,
                )

        worktree_removed = GitWorktreeService._is_task_worktree_fully_removed(
            repo_root_path=repo_root_path,
            worktree_path=resolved_worktree_path,
        )
        if not worktree_removed or not branch_deleted:
            cleanup_gap_list: list[str] = []
            if not worktree_removed:
                cleanup_gap_list.append(
                    "task worktree directory or Git registration still exists"
                )
            if not branch_deleted:
                cleanup_gap_list.append("task branch still exists locally")
            return WorktreeDestroyResult(
                cleanup_succeeded=False,
                worktree_removed=worktree_removed,
                branch_deleted=branch_deleted,
                output_line_list=output_line_list,
                failure_reason_text=(
                    "Completed task cleanup did not finish completely: "
                    + "; ".join(cleanup_gap_list)
                ),
            )

        return WorktreeDestroyResult(
            cleanup_succeeded=True,
            worktree_removed=True,
            branch_deleted=True,
            output_line_list=output_line_list,
        )

    @staticmethod
    def resolve_repo_root_path(
        *,
        project_repo_path: Path | None = None,
        worktree_path: Path | None = None,
    ) -> Path:
        """Resolve the canonical repository root for cleanup operations.

        Args:
            project_repo_path: Project repository root path when known
            worktree_path: Task worktree path when available

        Returns:
            Path: Repository root path

        Raises:
            ValueError: When the repository root cannot be determined
        """
        if project_repo_path is not None:
            resolved_project_repo_path = project_repo_path.resolve()
            if (resolved_project_repo_path / ".git").exists():
                return resolved_project_repo_path

        if worktree_path is not None and worktree_path.exists():
            try:
                completed_process = subprocess.run(
                    ["git", "rev-parse", "--git-common-dir"],
                    cwd=str(worktree_path),
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except (OSError, subprocess.CalledProcessError) as resolve_error:
                raise ValueError(
                    "Unable to resolve repository root from the existing worktree."
                ) from resolve_error

            git_common_dir_path = Path(completed_process.stdout.strip())
            if not git_common_dir_path.is_absolute():
                git_common_dir_path = (worktree_path / git_common_dir_path).resolve()
            return git_common_dir_path.parent.resolve()

        raise ValueError(
            "Unable to resolve repository root for task cleanup. "
            "Project repo_path is invalid and the worktree no longer exists."
        )

    @staticmethod
    def destroy_task_worktree(
        repo_root_path: Path,
        task_id: str,
        worktree_path: Path | None,
        base_branch_name_str: str = "main",
    ) -> WorktreeDestroyResult:
        """Clean up an abandoned task worktree and branch.

        This flow is used by the explicit destroy-task API, so it must tolerate
        unmerged branches and therefore force-delete the task branch on fallback.

        Args:
            repo_root_path: Repository root path
            task_id: Task UUID
            worktree_path: Task worktree path, if one was recorded
            base_branch_name_str: Branch used by cleanup scripts as a fallback checkout

        Returns:
            WorktreeDestroyResult: Cleanup execution summary
        """
        resolved_worktree_path = worktree_path.resolve() if worktree_path else None
        output_line_list: list[str] = []
        registered_branch_name_for_worktree = None
        registered_worktree_exists = False
        if resolved_worktree_path is not None:
            registered_branch_name_for_worktree = (
                GitWorktreeService._resolve_branch_name_for_worktree_path(
                    repo_root_path=repo_root_path,
                    worktree_path=resolved_worktree_path,
                )
            )
            registered_worktree_exists = (
                GitWorktreeService._is_worktree_path_registered(
                    repo_root_path=repo_root_path,
                    worktree_path=resolved_worktree_path,
                )
            )

        cleanup_script_path = GitWorktreeService.resolve_cleanup_script_path(
            repo_root_path
        )
        if (
            cleanup_script_path is not None
            and registered_worktree_exists
            and registered_branch_name_for_worktree is not None
        ):
            cleanup_command_argument_list = [
                str(cleanup_script_path),
                registered_branch_name_for_worktree,
                base_branch_name_str,
                "--delete",
            ]
            if resolved_worktree_path is not None:
                cleanup_command_argument_list.extend(
                    ["--worktree-path", str(resolved_worktree_path)]
                )
            cleanup_process = subprocess.run(
                cleanup_command_argument_list,
                cwd=str(repo_root_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            output_line_list.extend((cleanup_process.stdout or "").splitlines())
            output_line_list.extend((cleanup_process.stderr or "").splitlines())
            if cleanup_process.returncode == 0:
                script_worktree_removed = (
                    GitWorktreeService._is_task_worktree_fully_removed(
                        repo_root_path=repo_root_path,
                        worktree_path=resolved_worktree_path,
                    )
                )
                script_branch_deleted = (
                    not GitWorktreeService.list_local_task_branch_names(
                        repo_root_path,
                        task_id,
                    )
                )
                if script_worktree_removed and script_branch_deleted:
                    return WorktreeDestroyResult(
                        cleanup_succeeded=True,
                        worktree_removed=True,
                        branch_deleted=True,
                        output_line_list=output_line_list,
                    )

                output_line_list.append(
                    "Repo-local cleanup script exited successfully but left "
                    "cleanup artifacts behind; falling back to force cleanup."
                )

            if cleanup_process.returncode != 0:
                output_line_list.append(
                    "Repo-local cleanup script failed; falling back to force cleanup."
                )
        elif cleanup_script_path is not None and resolved_worktree_path is not None:
            output_line_list.append(
                "Skipping repo-local cleanup script because the recorded task path "
                "is no longer registered as a Git worktree."
            )

        if resolved_worktree_path is not None:
            registered_worktree_exists = (
                GitWorktreeService._is_worktree_path_registered(
                    repo_root_path=repo_root_path,
                    worktree_path=resolved_worktree_path,
                )
            )

        if resolved_worktree_path is not None and registered_worktree_exists:
            remove_worktree_process = subprocess.run(
                ["git", "worktree", "remove", "--force", str(resolved_worktree_path)],
                cwd=str(repo_root_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            output_line_list.extend((remove_worktree_process.stdout or "").splitlines())
            output_line_list.extend((remove_worktree_process.stderr or "").splitlines())
            if remove_worktree_process.returncode != 0:
                return WorktreeDestroyResult(
                    cleanup_succeeded=False,
                    worktree_removed=GitWorktreeService._is_task_worktree_fully_removed(
                        repo_root_path=repo_root_path,
                        worktree_path=resolved_worktree_path,
                    ),
                    branch_deleted=not bool(
                        GitWorktreeService.list_local_task_branch_names(
                            repo_root_path,
                            task_id,
                        )
                    ),
                    output_line_list=output_line_list,
                    failure_reason_text=(
                        "Failed to remove task worktree during destroy cleanup."
                    ),
                )

        prune_process = subprocess.run(
            ["git", "worktree", "prune"],
            cwd=str(repo_root_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output_line_list.extend((prune_process.stdout or "").splitlines())
        output_line_list.extend((prune_process.stderr or "").splitlines())

        if resolved_worktree_path is not None and resolved_worktree_path.exists():
            try:
                if not GitWorktreeService._is_worktree_path_registered(
                    repo_root_path=repo_root_path,
                    worktree_path=resolved_worktree_path,
                ):
                    GitWorktreeService._remove_orphaned_task_worktree_directory(
                        repo_root_path=repo_root_path,
                        worktree_path=resolved_worktree_path,
                    )
                    output_line_list.append(
                        "Removed orphaned task worktree directory directly because "
                        "Git no longer registered it."
                    )
            except OSError as remove_error:
                return WorktreeDestroyResult(
                    cleanup_succeeded=False,
                    worktree_removed=False,
                    branch_deleted=not bool(
                        GitWorktreeService.list_local_task_branch_names(
                            repo_root_path,
                            task_id,
                        )
                    ),
                    output_line_list=output_line_list,
                    failure_reason_text=(
                        "Failed to remove orphaned task worktree directory during "
                        f"destroy cleanup: {remove_error}"
                    ),
                )

        task_branch_name_list_for_force_delete = (
            GitWorktreeService.list_local_task_branch_names(repo_root_path, task_id)
            or []
        )
        branch_deleted = True
        for remaining_task_branch_name in task_branch_name_list_for_force_delete:
            delete_branch_process = subprocess.run(
                ["git", "branch", "-D", remaining_task_branch_name],
                cwd=str(repo_root_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            output_line_list.extend((delete_branch_process.stdout or "").splitlines())
            output_line_list.extend((delete_branch_process.stderr or "").splitlines())
            if delete_branch_process.returncode != 0:
                return WorktreeDestroyResult(
                    cleanup_succeeded=False,
                    worktree_removed=GitWorktreeService._is_task_worktree_fully_removed(
                        repo_root_path=repo_root_path,
                        worktree_path=resolved_worktree_path,
                    ),
                    branch_deleted=False,
                    output_line_list=output_line_list,
                    failure_reason_text=(
                        "Failed to force-delete the task branch during destroy cleanup."
                    ),
                )

        remaining_task_branch_name_list = (
            GitWorktreeService.list_local_task_branch_names(repo_root_path, task_id)
            or []
        )
        if remaining_task_branch_name_list:
            output_line_list.append(
                "Remaining local task branches: "
                + ", ".join(sorted(remaining_task_branch_name_list))
            )
        branch_deleted = not remaining_task_branch_name_list

        worktree_removed = GitWorktreeService._is_task_worktree_fully_removed(
            repo_root_path=repo_root_path,
            worktree_path=resolved_worktree_path,
        )
        if not worktree_removed or not branch_deleted:
            return WorktreeDestroyResult(
                cleanup_succeeded=False,
                worktree_removed=worktree_removed,
                branch_deleted=branch_deleted,
                output_line_list=output_line_list,
                failure_reason_text=GitWorktreeService._build_destroy_cleanup_failure_reason(
                    worktree_removed=worktree_removed,
                    branch_deleted=branch_deleted,
                ),
            )

        return WorktreeDestroyResult(
            cleanup_succeeded=True,
            worktree_removed=True,
            branch_deleted=True,
            output_line_list=output_line_list,
        )

    @staticmethod
    def _build_worktree_create_command_spec(
        repo_root_path: Path,
        task_id: str,
        task_branch_name_str: str | None = None,
        base_branch_name_str: str = "main",
    ) -> WorktreeCreateCommandSpec:
        """Choose the correct worktree creation command for the repository.

        Args:
            repo_root_path: Repository root path
            task_id: Task UUID
            task_branch_name_str: Optional explicit branch name
            base_branch_name_str: Existing local branch used as the worktree base

        Returns:
            WorktreeCreateCommandSpec: Command and expected path information
        """
        resolved_task_branch_name_str = task_branch_name_str or (
            GitWorktreeService.build_task_branch_name(task_id)
        )
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
                    resolved_task_branch_name_str,
                    base_branch_name_str,
                ],
                expected_worktree_path=default_worktree_path,
                requires_post_create_bootstrap=True,
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
                    resolved_task_branch_name_str,
                    "--base",
                    base_branch_name_str,
                ],
                expected_worktree_path=None,
                branch_name_for_lookup=resolved_task_branch_name_str,
            )

        return WorktreeCreateCommandSpec(
            command_argument_list=[
                "git",
                "worktree",
                "add",
                str(default_worktree_path),
                "-b",
                resolved_task_branch_name_str,
                base_branch_name_str,
            ],
            expected_worktree_path=default_worktree_path,
            requires_post_create_bootstrap=True,
        )

    @staticmethod
    def _bootstrap_worktree_environment(
        repo_root_path: Path,
        created_worktree_path: Path,
    ) -> None:
        """Run the shared worktree environment bootstrap script.

        Args:
            repo_root_path: Source repository root path
            created_worktree_path: Created worktree path

        Raises:
            ValueError: When the bootstrap script is missing or exits with failure
        """
        bootstrap_script_path = GitWorktreeService._resolve_bootstrap_script_path()
        if not bootstrap_script_path.exists():
            raise ValueError(
                "创建 git worktree 后环境准备失败："
                f"未找到环境准备脚本 {bootstrap_script_path}"
            )

        try:
            subprocess.run(
                [
                    "bash",
                    str(bootstrap_script_path),
                    str(repo_root_path),
                    str(created_worktree_path),
                ],
                cwd=str(created_worktree_path),
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.CalledProcessError as bootstrap_error:
            stderr_text = (bootstrap_error.stderr or "").strip()
            stdout_text = (bootstrap_error.stdout or "").strip()
            failure_reason_text = stderr_text or stdout_text or str(bootstrap_error)
            raise ValueError(
                f"创建 git worktree 后环境准备失败：{failure_reason_text}"
            ) from bootstrap_error

    @staticmethod
    def _resolve_bootstrap_script_path() -> Path:
        """Return Koda's shared worktree bootstrap script path.

        Returns:
            Path: Shared bootstrap script path
        """
        current_file_path = Path(__file__).resolve()
        for candidate_project_root_path in current_file_path.parents:
            candidate_bootstrap_script_path = (
                candidate_project_root_path / "scripts" / "bootstrap_worktree_env.sh"
            )
            if candidate_bootstrap_script_path.exists():
                return candidate_bootstrap_script_path

        return current_file_path.parents[3] / "scripts" / "bootstrap_worktree_env.sh"

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
    def _branch_exists(repo_root_path: Path, branch_name_str: str) -> bool:
        """Check whether a local branch still exists.

        Args:
            repo_root_path: Repository root path
            branch_name_str: Local branch name

        Returns:
            bool: Whether the branch exists locally
        """
        completed_process = subprocess.run(
            ["git", "branch", "--list", branch_name_str],
            cwd=str(repo_root_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return bool((completed_process.stdout or "").strip())

    @staticmethod
    def _build_destroy_cleanup_failure_reason(
        *,
        worktree_removed: bool,
        branch_deleted: bool,
    ) -> str:
        """Describe which destroy cleanup targets remain.

        Args:
            worktree_removed: worktree 目录是否已移除
            branch_deleted: 任务分支是否已删除

        Returns:
            str: 标准化失败文案
        """
        cleanup_gap_list: list[str] = []
        if not worktree_removed:
            cleanup_gap_list.append(
                "task worktree directory or Git registration still exists"
            )
        if not branch_deleted:
            cleanup_gap_list.append("task branch still exists locally")
        return "Destroy cleanup did not finish completely: " + "; ".join(
            cleanup_gap_list
        )

    @staticmethod
    def _list_registered_worktree_entries(
        repo_root_path: Path,
    ) -> list[tuple[Path, str | None]]:
        """List registered Git worktree paths and their branch names.

        Args:
            repo_root_path: Repository root path

        Returns:
            list[tuple[Path, str | None]]: Registered worktree entries
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
            return []

        registered_worktree_entry_list: list[tuple[Path, str | None]] = []
        current_worktree_path: Path | None = None
        current_branch_name: str | None = None

        for output_line_str in completed_process.stdout.splitlines() + [""]:
            if output_line_str.startswith("worktree "):
                current_worktree_path = Path(
                    output_line_str.removeprefix("worktree ").strip()
                ).resolve()
                current_branch_name = None
                continue

            if (
                output_line_str.startswith("branch ")
                and current_worktree_path is not None
            ):
                current_branch_reference_str = output_line_str.removeprefix(
                    "branch "
                ).strip()
                current_branch_name = current_branch_reference_str.removeprefix(
                    "refs/heads/"
                )
                continue

            if output_line_str == "" and current_worktree_path is not None:
                registered_worktree_entry_list.append(
                    (current_worktree_path, current_branch_name)
                )
                current_worktree_path = None
                current_branch_name = None

        return registered_worktree_entry_list

    @staticmethod
    def _resolve_branch_name_for_worktree_path(
        repo_root_path: Path,
        worktree_path: Path,
    ) -> str | None:
        """Resolve the branch currently registered for one worktree path.

        Args:
            repo_root_path: Repository root path
            worktree_path: Worktree path to inspect

        Returns:
            str | None: Registered branch name when available
        """
        resolved_worktree_path = worktree_path.resolve()
        for (
            registered_worktree_path,
            registered_branch_name,
        ) in GitWorktreeService._list_registered_worktree_entries(repo_root_path):
            if registered_worktree_path == resolved_worktree_path:
                return registered_branch_name
        return None

    @staticmethod
    def _is_worktree_path_registered(
        repo_root_path: Path,
        worktree_path: Path,
    ) -> bool:
        """Check whether Git still registers a worktree path.

        Args:
            repo_root_path: Repository root path
            worktree_path: Worktree path to verify

        Returns:
            bool: Whether the path still appears in `git worktree list`
        """
        resolved_worktree_path = worktree_path.resolve()
        return any(
            registered_worktree_path == resolved_worktree_path
            for registered_worktree_path, _ in GitWorktreeService._list_registered_worktree_entries(
                repo_root_path
            )
        )

    @staticmethod
    def _is_task_worktree_fully_removed(
        *,
        repo_root_path: Path,
        worktree_path: Path | None,
    ) -> bool:
        """Check whether a task worktree is gone from both disk and Git metadata.

        Args:
            repo_root_path: Repository root path
            worktree_path: Recorded task worktree path

        Returns:
            bool: Whether the worktree path no longer exists and is no longer
                registered by Git
        """
        if worktree_path is None:
            return True

        return (
            not worktree_path.exists()
            and not GitWorktreeService._is_worktree_path_registered(
                repo_root_path=repo_root_path,
                worktree_path=worktree_path,
            )
        )

    @staticmethod
    def _remove_orphaned_task_worktree_directory(
        *,
        repo_root_path: Path,
        worktree_path: Path,
    ) -> None:
        """Remove a residual task directory once Git no longer tracks it.

        Args:
            repo_root_path: Repository root path
            worktree_path: Residual task directory path

        Raises:
            ValueError: When the path is outside the configured task root
            OSError: When recursive removal fails
        """
        GitWorktreeService._validate_worktree_path_within_task_root(
            repo_root_path=repo_root_path,
            created_worktree_path=worktree_path,
        )
        shutil.rmtree(worktree_path)

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
