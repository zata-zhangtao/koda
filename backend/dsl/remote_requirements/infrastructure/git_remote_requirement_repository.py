"""Git infrastructure for remote requirement collaboration."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from pydantic import ValidationError

from backend.dsl.remote_requirements.domain import (
    REMOTE_REQUIREMENT_MANIFEST_ROOT,
    RemoteRequirementBranchManifest,
    RemoteRequirementError,
    RemoteRequirementManifest,
)
from backend.dsl.services.git_worktree_service import GitWorktreeService


class GitRemoteRequirementRepository:
    """Run low-level Git commands for remote-backed requirement branches."""

    @staticmethod
    def _parse_manifest_json_text(
        manifest_json_text: str,
    ) -> RemoteRequirementManifest | None:
        """Parse manifest JSON into a domain model.

        Args:
            manifest_json_text: Raw JSON text read from Git or filesystem.

        Returns:
            RemoteRequirementManifest | None: Parsed manifest when valid.
        """
        try:
            manifest_payload = json.loads(manifest_json_text)
            return RemoteRequirementManifest.model_validate(manifest_payload)
        except (json.JSONDecodeError, ValidationError, ValueError):
            return None

    @staticmethod
    def _run_git_command(
        repo_path_obj: Path,
        git_argument_list: list[str],
        *,
        check_bool: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a Git command with UTF-8 process decoding.

        Args:
            repo_path_obj: Repository or worktree path used as command cwd.
            git_argument_list: Git argument list without the leading ``git``.
            check_bool: Whether non-zero exits should raise.

        Returns:
            subprocess.CompletedProcess[str]: Completed Git process.

        Raises:
            RemoteRequirementError: Raised when Git exits non-zero and
                ``check_bool`` is true.
        """
        completed_process = subprocess.run(
            ["git", "-C", str(repo_path_obj), *git_argument_list],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check_bool and completed_process.returncode != 0:
            stderr_text = (completed_process.stderr or "").strip()
            stdout_text = (completed_process.stdout or "").strip()
            failure_reason_text = stderr_text or stdout_text or str(completed_process)
            raise RemoteRequirementError(f"Git command failed: {failure_reason_text}")
        return completed_process

    def get_head_commit_hash(self, repo_path_obj: Path) -> str:
        """Return the current HEAD commit hash.

        Args:
            repo_path_obj: Repository or worktree path.

        Returns:
            str: Current HEAD commit hash.
        """
        completed_process = self._run_git_command(repo_path_obj, ["rev-parse", "HEAD"])
        return completed_process.stdout.strip()

    def get_remote_branch_commit_hash(
        self,
        repo_path_obj: Path,
        remote_name_str: str,
        branch_name_str: str,
    ) -> str | None:
        """Return the local remote-tracking commit hash for a branch.

        Args:
            repo_path_obj: Repository path.
            remote_name_str: Git remote name.
            branch_name_str: Branch name without remote prefix.

        Returns:
            str | None: Remote-tracking commit hash when present.
        """
        completed_process = self._run_git_command(
            repo_path_obj,
            [
                "rev-parse",
                "--verify",
                f"refs/remotes/{remote_name_str}/{branch_name_str}",
            ],
            check_bool=False,
        )
        if completed_process.returncode != 0:
            return None
        return completed_process.stdout.strip() or None

    def fetch_remote(self, repo_path_obj: Path, remote_name_str: str) -> None:
        """Fetch one Git remote.

        Args:
            repo_path_obj: Repository path.
            remote_name_str: Git remote name.
        """
        self._run_git_command(repo_path_obj, ["fetch", "--prune", remote_name_str])

    def remote_branch_exists(
        self,
        repo_path_obj: Path,
        remote_name_str: str,
        branch_name_str: str,
    ) -> bool:
        """Return whether a remote branch exists.

        Args:
            repo_path_obj: Repository path.
            remote_name_str: Git remote name.
            branch_name_str: Branch name without remote prefix.

        Returns:
            bool: Whether ``remote_name_str/branch_name_str`` exists remotely.
        """
        completed_process = self._run_git_command(
            repo_path_obj,
            ["ls-remote", "--exit-code", "--heads", remote_name_str, branch_name_str],
            check_bool=False,
        )
        return completed_process.returncode == 0

    def create_manifest_branch(
        self,
        *,
        repo_root_path: Path,
        remote_name_str: str,
        branch_name_str: str,
        base_branch_name_str: str,
        manifest_relative_path_str: str,
        manifest_json_text: str,
        commit_message_text: str,
    ) -> str:
        """Create, commit, and push the initial manifest branch.

        Args:
            repo_root_path: Project repository root.
            remote_name_str: Git remote name.
            branch_name_str: New task branch name.
            base_branch_name_str: Local base branch used for branch creation.
            manifest_relative_path_str: Manifest path in the repository.
            manifest_json_text: JSON text to write.
            commit_message_text: Initial commit message.

        Returns:
            str: Pushed branch commit hash.

        Raises:
            RemoteRequirementError: Raised when local or remote branch creation fails.
        """
        if GitWorktreeService.check_local_branch_exists(
            repo_root_path, branch_name_str
        ):
            raise RemoteRequirementError(
                f"Local branch already exists: {branch_name_str}"
            )
        if self.remote_branch_exists(repo_root_path, remote_name_str, branch_name_str):
            raise RemoteRequirementError(
                f"Remote branch already exists: {remote_name_str}/{branch_name_str}"
            )

        task_worktree_root_path = GitWorktreeService.build_task_worktree_root_path(
            repo_root_path
        )
        task_worktree_root_path.mkdir(parents=True, exist_ok=True)
        temporary_worktree_path = Path(
            tempfile.mkdtemp(
                prefix=f"koda-remote-init-{branch_name_str.split('/')[-1]}-",
                dir=str(task_worktree_root_path),
            )
        )

        try:
            self._run_git_command(
                repo_root_path,
                [
                    "worktree",
                    "add",
                    "--detach",
                    str(temporary_worktree_path),
                    base_branch_name_str,
                ],
            )
            self._run_git_command(
                temporary_worktree_path,
                ["checkout", "-b", branch_name_str],
            )
            manifest_file_path = temporary_worktree_path / manifest_relative_path_str
            manifest_file_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_file_path.write_text(manifest_json_text, encoding="utf-8")
            self._run_git_command(
                temporary_worktree_path, ["add", manifest_relative_path_str]
            )
            self._run_git_command(
                temporary_worktree_path,
                ["commit", "-m", commit_message_text],
            )
            commit_hash_str = self.get_head_commit_hash(temporary_worktree_path)
            self._run_git_command(
                temporary_worktree_path,
                ["push", "-u", remote_name_str, branch_name_str],
            )
            return commit_hash_str
        finally:
            self._run_git_command(
                repo_root_path,
                ["worktree", "remove", "--force", str(temporary_worktree_path)],
                check_bool=False,
            )
            if temporary_worktree_path.exists():
                shutil.rmtree(temporary_worktree_path, ignore_errors=True)
            self._run_git_command(
                repo_root_path, ["worktree", "prune"], check_bool=False
            )

    def write_manifest_to_worktree(
        self,
        worktree_path: Path,
        manifest_relative_path_str: str,
        manifest_json_text: str,
    ) -> None:
        """Write a manifest file in an existing worktree.

        Args:
            worktree_path: Task worktree path.
            manifest_relative_path_str: Manifest path in the repository.
            manifest_json_text: JSON text to write.
        """
        manifest_file_path = worktree_path / manifest_relative_path_str
        manifest_file_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_file_path.write_text(manifest_json_text, encoding="utf-8")

    def read_manifest_from_worktree(
        self,
        worktree_path: Path,
        manifest_relative_path_str: str,
    ) -> RemoteRequirementManifest | None:
        """Read a manifest from an existing worktree.

        Args:
            worktree_path: Task worktree path.
            manifest_relative_path_str: Manifest path in the repository.

        Returns:
            RemoteRequirementManifest | None: Parsed manifest when present and valid.
        """
        manifest_file_path = worktree_path / manifest_relative_path_str
        if not manifest_file_path.exists():
            return None
        try:
            manifest_json_text = manifest_file_path.read_text(encoding="utf-8")
        except OSError:
            return None
        return self._parse_manifest_json_text(manifest_json_text)

    def read_manifest_from_git_ref(
        self,
        repo_root_path: Path,
        git_ref_str: str,
        manifest_relative_path_str: str,
    ) -> RemoteRequirementManifest | None:
        """Read a manifest from a Git ref without checking it out.

        Args:
            repo_root_path: Project repository root.
            git_ref_str: Git ref or branch name to read.
            manifest_relative_path_str: Manifest path in the repository.

        Returns:
            RemoteRequirementManifest | None: Parsed manifest when present and valid.
        """
        manifest_json_process = self._run_git_command(
            repo_root_path,
            ["show", f"{git_ref_str}:{manifest_relative_path_str}"],
            check_bool=False,
        )
        if manifest_json_process.returncode != 0:
            return None
        return self._parse_manifest_json_text(manifest_json_process.stdout)

    def commit_all_changes_if_needed(
        self,
        worktree_path: Path,
        commit_message_text: str,
    ) -> str:
        """Stage all worktree changes and commit when needed.

        Args:
            worktree_path: Task worktree path.
            commit_message_text: Commit message to use when there are staged changes.

        Returns:
            str: Current HEAD commit hash after the optional commit.
        """
        self._run_git_command(worktree_path, ["add", "."])
        diff_process = self._run_git_command(
            worktree_path,
            ["diff", "--cached", "--quiet"],
            check_bool=False,
        )
        if diff_process.returncode == 1:
            self._run_git_command(worktree_path, ["commit", "-m", commit_message_text])
        elif diff_process.returncode != 0:
            stderr_text = (diff_process.stderr or "").strip()
            raise RemoteRequirementError(
                f"Unable to inspect staged changes: {stderr_text}"
            )
        return self.get_head_commit_hash(worktree_path)

    def push_branch(
        self,
        worktree_path: Path,
        remote_name_str: str,
        branch_name_str: str,
    ) -> str:
        """Push a task branch and return the pushed commit hash.

        Args:
            worktree_path: Task worktree path.
            remote_name_str: Git remote name.
            branch_name_str: Branch name without remote prefix.

        Returns:
            str: Current HEAD commit hash.
        """
        self._run_git_command(
            worktree_path, ["push", "-u", remote_name_str, branch_name_str]
        )
        return self.get_head_commit_hash(worktree_path)

    def write_manifest_to_branch(
        self,
        *,
        repo_root_path: Path,
        remote_name_str: str,
        branch_name_str: str,
        manifest_relative_path_str: str,
        manifest_json_text: str,
        commit_message_text: str,
    ) -> str:
        """Write a manifest on a task branch without requiring a task worktree.

        Args:
            repo_root_path: Project repository root.
            remote_name_str: Git remote name.
            branch_name_str: Branch name without the remote prefix.
            manifest_relative_path_str: Manifest path in the repository.
            manifest_json_text: JSON text to write.
            commit_message_text: Commit message to use when changes exist.

        Returns:
            str: Pushed branch commit hash.
        """
        task_worktree_root_path = GitWorktreeService.build_task_worktree_root_path(
            repo_root_path
        )
        task_worktree_root_path.mkdir(parents=True, exist_ok=True)
        temporary_worktree_path = Path(
            tempfile.mkdtemp(
                prefix=f"koda-remote-sync-{branch_name_str.split('/')[-1]}-",
                dir=str(task_worktree_root_path),
            )
        )

        try:
            if GitWorktreeService.check_local_branch_exists(
                repo_root_path,
                branch_name_str,
            ):
                self._run_git_command(
                    repo_root_path,
                    [
                        "worktree",
                        "add",
                        str(temporary_worktree_path),
                        branch_name_str,
                    ],
                )
            else:
                self.fetch_remote(repo_root_path, remote_name_str)
                self._run_git_command(
                    repo_root_path,
                    [
                        "worktree",
                        "add",
                        "--track",
                        "-b",
                        branch_name_str,
                        str(temporary_worktree_path),
                        f"{remote_name_str}/{branch_name_str}",
                    ],
                )

            self.write_manifest_to_worktree(
                temporary_worktree_path,
                manifest_relative_path_str,
                manifest_json_text,
            )
            self.commit_all_changes_if_needed(
                temporary_worktree_path,
                commit_message_text,
            )
            return self.push_branch(
                temporary_worktree_path,
                remote_name_str,
                branch_name_str,
            )
        finally:
            self._run_git_command(
                repo_root_path,
                ["worktree", "remove", "--force", str(temporary_worktree_path)],
                check_bool=False,
            )
            if temporary_worktree_path.exists():
                shutil.rmtree(temporary_worktree_path, ignore_errors=True)
            self._run_git_command(
                repo_root_path, ["worktree", "prune"], check_bool=False
            )

    def rebase_onto_base_branch(
        self,
        worktree_path: Path,
        base_branch_name_str: str,
    ) -> None:
        """Rebase a task worktree onto the configured base branch.

        Args:
            worktree_path: Task worktree path.
            base_branch_name_str: Base branch name.
        """
        self._run_git_command(worktree_path, ["rebase", base_branch_name_str])

    def list_remote_branch_manifests(
        self,
        repo_root_path: Path,
        remote_name_str: str,
        branch_prefix_str: str,
    ) -> list[RemoteRequirementBranchManifest]:
        """Read all remote requirement manifests under a branch prefix.

        Args:
            repo_root_path: Project repository root.
            remote_name_str: Git remote name.
            branch_prefix_str: Branch prefix such as ``task``.

        Returns:
            list[RemoteRequirementBranchManifest]: Parsed remote manifests.
        """
        self.fetch_remote(repo_root_path, remote_name_str)
        remote_ref_process = self._run_git_command(
            repo_root_path,
            [
                "for-each-ref",
                "--format=%(refname:short)",
                f"refs/remotes/{remote_name_str}/{branch_prefix_str}",
            ],
        )
        remote_branch_manifest_list: list[RemoteRequirementBranchManifest] = []
        for raw_remote_ref_name_str in remote_ref_process.stdout.splitlines():
            remote_ref_name_str = raw_remote_ref_name_str.strip()
            if not remote_ref_name_str or not remote_ref_name_str.startswith(
                f"{remote_name_str}/"
            ):
                continue
            branch_name_str = remote_ref_name_str.removeprefix(f"{remote_name_str}/")
            remote_ref_str = f"refs/remotes/{remote_name_str}/{branch_name_str}"
            commit_hash_str = self._run_git_command(
                repo_root_path,
                ["rev-parse", remote_ref_str],
            ).stdout.strip()
            manifest_path_process = self._run_git_command(
                repo_root_path,
                [
                    "ls-tree",
                    "-r",
                    "--name-only",
                    remote_ref_str,
                    REMOTE_REQUIREMENT_MANIFEST_ROOT,
                ],
                check_bool=False,
            )
            if manifest_path_process.returncode != 0:
                continue
            for raw_manifest_path_str in manifest_path_process.stdout.splitlines():
                manifest_relative_path_str = raw_manifest_path_str.strip()
                if not manifest_relative_path_str.endswith(".json"):
                    continue
                manifest_json_process = self._run_git_command(
                    repo_root_path,
                    ["show", f"{remote_ref_str}:{manifest_relative_path_str}"],
                    check_bool=False,
                )
                if manifest_json_process.returncode != 0:
                    continue
                manifest = self._parse_manifest_json_text(manifest_json_process.stdout)
                if manifest is None:
                    continue
                remote_branch_manifest_list.append(
                    RemoteRequirementBranchManifest(
                        branch_name_str=branch_name_str,
                        manifest_relative_path_str=manifest_relative_path_str,
                        commit_hash_str=commit_hash_str,
                        manifest=manifest,
                    )
                )
        return remote_branch_manifest_list
