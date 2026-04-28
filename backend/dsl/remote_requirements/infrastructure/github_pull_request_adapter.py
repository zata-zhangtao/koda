"""GitHub pull request provider adapter for remote requirements."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any

import httpx

from backend.dsl.remote_requirements.domain import (
    PullRequestMetadata,
    RemoteRequirementError,
)

GITHUB_CLI_COMMAND_TIMEOUT_SECONDS = 30.0
GITHUB_AUTH_ENVIRONMENT_VARIABLE_LIST = (
    "KODA_GITHUB_TOKEN",
    "GITHUB_TOKEN",
    "GH_TOKEN",
)


class GitHubPullRequestAdapter:
    """Create and inspect GitHub pull requests through REST or GitHub CLI."""

    def __init__(
        self,
        token_str: str | None = None,
        *,
        gh_executable_path_str: str | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            token_str: Optional GitHub token. When omitted, Koda reads
                ``KODA_GITHUB_TOKEN``, ``GITHUB_TOKEN`` or ``GH_TOKEN``.
            gh_executable_path_str: Optional GitHub CLI executable override.
        """
        self._token_str = (
            token_str
            or os.getenv("KODA_GITHUB_TOKEN")
            or os.getenv("GITHUB_TOKEN")
            or os.getenv("GH_TOKEN")
        )
        self._gh_executable_path_str = gh_executable_path_str
        self._gh_auth_verified_bool = False

    @staticmethod
    def _build_authentication_hint() -> str:
        """Build a user-facing authentication setup hint.

        Returns:
            str: Authentication setup hint for GitHub PR operations.
        """
        token_name_list_text = ", ".join(GITHUB_AUTH_ENVIRONMENT_VARIABLE_LIST)
        return (
            f"GitHub PR operations require one of {token_name_list_text}, "
            "or an installed and authenticated GitHub CLI. Run `gh auth login` "
            "and verify with `gh auth status --active`."
        )

    def _build_headers(self) -> dict[str, str]:
        """Build GitHub REST API headers.

        Returns:
            dict[str, str]: Request headers.

        Raises:
            RemoteRequirementError: Raised when no token is configured.
        """
        if not self._token_str:
            raise RemoteRequirementError(self._build_authentication_hint())
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token_str}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @staticmethod
    def _build_metadata_from_payload(
        pull_request_payload: dict[str, Any],
    ) -> PullRequestMetadata:
        """Convert a GitHub PR payload into provider-neutral metadata.

        Args:
            pull_request_payload: JSON object returned by GitHub.

        Returns:
            PullRequestMetadata: Normalized pull request metadata.
        """
        state_str = str(pull_request_payload.get("state") or "open").lower()
        merged_bool = bool(pull_request_payload.get("merged"))
        if merged_bool:
            state_str = "merged"
        return PullRequestMetadata(
            number=int(pull_request_payload["number"]),
            url=str(pull_request_payload["html_url"]),
            state=state_str,
            merged=merged_bool,
        )

    @staticmethod
    def _build_metadata_from_cli_payload(
        pull_request_payload: dict[str, Any],
    ) -> PullRequestMetadata:
        """Convert a GitHub CLI PR payload into normalized metadata.

        Args:
            pull_request_payload: JSON object returned by ``gh pr``.

        Returns:
            PullRequestMetadata: Normalized pull request metadata.
        """
        state_str = str(pull_request_payload.get("state") or "open").lower()
        merged_bool = bool(pull_request_payload.get("mergedAt"))
        if merged_bool:
            state_str = "merged"
        return PullRequestMetadata(
            number=int(pull_request_payload["number"]),
            url=str(pull_request_payload["url"]),
            state=state_str,
            merged=merged_bool,
        )

    @staticmethod
    def _parse_cli_json_output(
        raw_stdout_text: str,
        *,
        context_text: str,
    ) -> Any:
        """Parse JSON returned by GitHub CLI.

        Args:
            raw_stdout_text: Raw stdout text.
            context_text: Human-readable operation context.

        Returns:
            Any: Parsed JSON payload.

        Raises:
            RemoteRequirementError: Raised when the CLI returned invalid JSON.
        """
        try:
            return json.loads(raw_stdout_text or "null")
        except json.JSONDecodeError as json_error:
            raise RemoteRequirementError(
                f"{context_text} returned invalid JSON from GitHub CLI."
            ) from json_error

    @staticmethod
    def _extract_pull_request_url(raw_stdout_text: str) -> str:
        """Extract a pull request URL from ``gh pr create`` output.

        Args:
            raw_stdout_text: Raw stdout text from ``gh pr create``.

        Returns:
            str: Pull request URL.

        Raises:
            RemoteRequirementError: Raised when no PR URL is present.
        """
        url_match = re.search(r"https://\S+/pull/\d+", raw_stdout_text)
        if not url_match:
            raise RemoteRequirementError(
                "GitHub CLI PR creation did not return a pull request URL."
            )
        return url_match.group(0)

    def _resolve_gh_executable_path(self) -> str:
        """Resolve the GitHub CLI executable path.

        Returns:
            str: Resolved GitHub CLI executable path.

        Raises:
            RemoteRequirementError: Raised when the executable cannot be found.
        """
        configured_executable_path_str = (self._gh_executable_path_str or "").strip()
        if configured_executable_path_str:
            return configured_executable_path_str

        detected_executable_path_str = shutil.which("gh")
        if detected_executable_path_str:
            return detected_executable_path_str

        raise RemoteRequirementError(
            f"{self._build_authentication_hint()} GitHub CLI executable `gh` was not found."
        )

    def _run_gh_command(
        self,
        gh_argument_list: list[str],
        *,
        context_text: str,
    ) -> subprocess.CompletedProcess[str]:
        """Run a GitHub CLI command.

        Args:
            gh_argument_list: GitHub CLI arguments without the executable name.
            context_text: Human-readable operation context.

        Returns:
            subprocess.CompletedProcess[str]: Completed process.

        Raises:
            RemoteRequirementError: Raised when the command fails.
        """
        gh_executable_path_str = self._resolve_gh_executable_path()
        command_argument_list = [gh_executable_path_str, *gh_argument_list]
        try:
            completed_process = subprocess.run(
                command_argument_list,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=GITHUB_CLI_COMMAND_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as file_error:
            raise RemoteRequirementError(
                f"{self._build_authentication_hint()} GitHub CLI executable `gh` was not found."
            ) from file_error
        except subprocess.TimeoutExpired as timeout_error:
            raise RemoteRequirementError(
                f"{context_text} timed out while running GitHub CLI."
            ) from timeout_error

        if completed_process.returncode != 0:
            stderr_text = (completed_process.stderr or "").strip()
            stdout_text = (completed_process.stdout or "").strip()
            failure_reason_text = stderr_text or stdout_text or "unknown error"
            raise RemoteRequirementError(
                f"{context_text} failed via GitHub CLI: {failure_reason_text}"
            )
        return completed_process

    def _ensure_gh_authentication(self) -> None:
        """Ensure the local GitHub CLI has an active authenticated account.

        Raises:
            RemoteRequirementError: Raised when ``gh`` is unavailable or not logged in.
        """
        if self._gh_auth_verified_bool:
            return
        try:
            self._run_gh_command(
                ["auth", "status", "--active"],
                context_text="GitHub CLI authentication check",
            )
        except RemoteRequirementError as auth_error:
            authentication_hint_text = self._build_authentication_hint()
            if authentication_hint_text in str(auth_error):
                raise
            raise RemoteRequirementError(
                f"{authentication_hint_text} {auth_error}"
            ) from auth_error
        self._gh_auth_verified_bool = True

    def find_pull_request(
        self,
        *,
        repository_full_name_str: str,
        head_owner_login_str: str,
        branch_name_str: str,
        base_branch_name_str: str,
    ) -> PullRequestMetadata | None:
        """Find an existing PR for a branch/base pair.

        Args:
            repository_full_name_str: GitHub repository full name, ``owner/repo``.
            head_owner_login_str: Repository owner login used in the head filter.
            branch_name_str: Task branch name.
            base_branch_name_str: PR base branch.

        Returns:
            PullRequestMetadata | None: Existing PR metadata when found.
        """
        if not self._token_str:
            return self._find_pull_request_cli(
                repository_full_name_str=repository_full_name_str,
                branch_name_str=branch_name_str,
                base_branch_name_str=base_branch_name_str,
            )
        return self._find_pull_request_rest(
            repository_full_name_str=repository_full_name_str,
            head_owner_login_str=head_owner_login_str,
            branch_name_str=branch_name_str,
            base_branch_name_str=base_branch_name_str,
        )

    def _find_pull_request_rest(
        self,
        *,
        repository_full_name_str: str,
        head_owner_login_str: str,
        branch_name_str: str,
        base_branch_name_str: str,
    ) -> PullRequestMetadata | None:
        """Find an existing PR through the GitHub REST API.

        Args:
            repository_full_name_str: GitHub repository full name.
            head_owner_login_str: Repository owner login used in the head filter.
            branch_name_str: Task branch name.
            base_branch_name_str: PR base branch.

        Returns:
            PullRequestMetadata | None: Existing PR metadata when found.
        """
        request_url_str = (
            f"https://api.github.com/repos/{repository_full_name_str}/pulls"
        )
        try:
            with httpx.Client(
                timeout=20.0, headers=self._build_headers()
            ) as http_client:
                response = http_client.get(
                    request_url_str,
                    params={
                        "state": "all",
                        "head": f"{head_owner_login_str}:{branch_name_str}",
                        "base": base_branch_name_str,
                        "per_page": "1",
                    },
                )
        except httpx.HTTPError as http_error:
            raise RemoteRequirementError(
                f"GitHub PR lookup failed: {http_error}"
            ) from http_error
        if response.status_code >= 400:
            raise RemoteRequirementError(
                f"GitHub PR lookup failed: HTTP {response.status_code} {response.text}"
            )
        pull_request_payload_list = response.json()
        if not pull_request_payload_list:
            return None
        return self._build_metadata_from_payload(pull_request_payload_list[0])

    def _find_pull_request_cli(
        self,
        *,
        repository_full_name_str: str,
        branch_name_str: str,
        base_branch_name_str: str,
    ) -> PullRequestMetadata | None:
        """Find an existing PR through GitHub CLI.

        Args:
            repository_full_name_str: GitHub repository full name.
            branch_name_str: Task branch name.
            base_branch_name_str: PR base branch.

        Returns:
            PullRequestMetadata | None: Existing PR metadata when found.
        """
        self._ensure_gh_authentication()
        completed_process = self._run_gh_command(
            [
                "pr",
                "list",
                "--repo",
                repository_full_name_str,
                "--head",
                branch_name_str,
                "--base",
                base_branch_name_str,
                "--state",
                "all",
                "--limit",
                "1",
                "--json",
                "number,url,state,mergedAt",
            ],
            context_text="GitHub CLI PR lookup",
        )
        pull_request_payload_list = self._parse_cli_json_output(
            completed_process.stdout,
            context_text="GitHub CLI PR lookup",
        )
        if not isinstance(pull_request_payload_list, list):
            raise RemoteRequirementError(
                "GitHub CLI PR lookup returned an unexpected payload."
            )
        if not pull_request_payload_list:
            return None
        first_pull_request_payload = pull_request_payload_list[0]
        if not isinstance(first_pull_request_payload, dict):
            raise RemoteRequirementError(
                "GitHub CLI PR lookup returned an invalid pull request payload."
            )
        return self._build_metadata_from_cli_payload(first_pull_request_payload)

    def create_pull_request(
        self,
        *,
        repository_full_name_str: str,
        branch_name_str: str,
        base_branch_name_str: str,
        title_str: str,
        body_str: str,
    ) -> PullRequestMetadata:
        """Create a GitHub pull request.

        Args:
            repository_full_name_str: GitHub repository full name, ``owner/repo``.
            branch_name_str: Task branch name.
            base_branch_name_str: PR base branch.
            title_str: Pull request title.
            body_str: Pull request body.

        Returns:
            PullRequestMetadata: Created pull request metadata.
        """
        if not self._token_str:
            return self._create_pull_request_cli(
                repository_full_name_str=repository_full_name_str,
                branch_name_str=branch_name_str,
                base_branch_name_str=base_branch_name_str,
                title_str=title_str,
                body_str=body_str,
            )
        return self._create_pull_request_rest(
            repository_full_name_str=repository_full_name_str,
            branch_name_str=branch_name_str,
            base_branch_name_str=base_branch_name_str,
            title_str=title_str,
            body_str=body_str,
        )

    def _create_pull_request_rest(
        self,
        *,
        repository_full_name_str: str,
        branch_name_str: str,
        base_branch_name_str: str,
        title_str: str,
        body_str: str,
    ) -> PullRequestMetadata:
        """Create a GitHub pull request through the REST API.

        Args:
            repository_full_name_str: GitHub repository full name.
            branch_name_str: Task branch name.
            base_branch_name_str: PR base branch.
            title_str: Pull request title.
            body_str: Pull request body.

        Returns:
            PullRequestMetadata: Created pull request metadata.
        """
        request_url_str = (
            f"https://api.github.com/repos/{repository_full_name_str}/pulls"
        )
        try:
            with httpx.Client(
                timeout=20.0, headers=self._build_headers()
            ) as http_client:
                response = http_client.post(
                    request_url_str,
                    json={
                        "title": title_str,
                        "head": branch_name_str,
                        "base": base_branch_name_str,
                        "body": body_str,
                    },
                )
        except httpx.HTTPError as http_error:
            raise RemoteRequirementError(
                f"GitHub PR creation failed: {http_error}"
            ) from http_error
        if response.status_code >= 400:
            raise RemoteRequirementError(
                f"GitHub PR creation failed: HTTP {response.status_code} {response.text}"
            )
        return self._build_metadata_from_payload(response.json())

    def _create_pull_request_cli(
        self,
        *,
        repository_full_name_str: str,
        branch_name_str: str,
        base_branch_name_str: str,
        title_str: str,
        body_str: str,
    ) -> PullRequestMetadata:
        """Create a GitHub pull request through GitHub CLI.

        Args:
            repository_full_name_str: GitHub repository full name.
            branch_name_str: Task branch name.
            base_branch_name_str: PR base branch.
            title_str: Pull request title.
            body_str: Pull request body.

        Returns:
            PullRequestMetadata: Created pull request metadata.
        """
        self._ensure_gh_authentication()
        completed_process = self._run_gh_command(
            [
                "pr",
                "create",
                "--repo",
                repository_full_name_str,
                "--head",
                branch_name_str,
                "--base",
                base_branch_name_str,
                "--title",
                title_str,
                "--body",
                body_str,
            ],
            context_text="GitHub CLI PR creation",
        )
        pull_request_url_str = self._extract_pull_request_url(completed_process.stdout)
        return self._view_pull_request_cli(
            repository_full_name_str=repository_full_name_str,
            pull_request_identifier_str=pull_request_url_str,
            context_text="GitHub CLI created PR metadata lookup",
        )

    def create_or_get_pull_request(
        self,
        *,
        repository_full_name_str: str,
        head_owner_login_str: str,
        branch_name_str: str,
        base_branch_name_str: str,
        title_str: str,
        body_str: str,
    ) -> PullRequestMetadata:
        """Return an existing PR or create a new one.

        Args:
            repository_full_name_str: GitHub repository full name, ``owner/repo``.
            head_owner_login_str: Repository owner login used in the head filter.
            branch_name_str: Task branch name.
            base_branch_name_str: PR base branch.
            title_str: Pull request title.
            body_str: Pull request body.

        Returns:
            PullRequestMetadata: Existing or newly created pull request metadata.
        """
        existing_pull_request = self.find_pull_request(
            repository_full_name_str=repository_full_name_str,
            head_owner_login_str=head_owner_login_str,
            branch_name_str=branch_name_str,
            base_branch_name_str=base_branch_name_str,
        )
        if existing_pull_request is not None:
            return existing_pull_request
        return self.create_pull_request(
            repository_full_name_str=repository_full_name_str,
            branch_name_str=branch_name_str,
            base_branch_name_str=base_branch_name_str,
            title_str=title_str,
            body_str=body_str,
        )

    def get_pull_request(
        self,
        *,
        repository_full_name_str: str,
        pull_request_number_int: int,
    ) -> PullRequestMetadata:
        """Load a GitHub pull request by number.

        Args:
            repository_full_name_str: GitHub repository full name, ``owner/repo``.
            pull_request_number_int: Pull request number.

        Returns:
            PullRequestMetadata: Current PR metadata.
        """
        if not self._token_str:
            self._ensure_gh_authentication()
            return self._view_pull_request_cli(
                repository_full_name_str=repository_full_name_str,
                pull_request_identifier_str=str(pull_request_number_int),
                context_text="GitHub CLI PR status lookup",
            )
        return self._get_pull_request_rest(
            repository_full_name_str=repository_full_name_str,
            pull_request_number_int=pull_request_number_int,
        )

    def _get_pull_request_rest(
        self,
        *,
        repository_full_name_str: str,
        pull_request_number_int: int,
    ) -> PullRequestMetadata:
        """Load a GitHub pull request by number through the REST API.

        Args:
            repository_full_name_str: GitHub repository full name.
            pull_request_number_int: Pull request number.

        Returns:
            PullRequestMetadata: Current PR metadata.
        """
        request_url_str = (
            f"https://api.github.com/repos/{repository_full_name_str}/pulls/"
            f"{pull_request_number_int}"
        )
        try:
            with httpx.Client(
                timeout=20.0, headers=self._build_headers()
            ) as http_client:
                response = http_client.get(request_url_str)
        except httpx.HTTPError as http_error:
            raise RemoteRequirementError(
                f"GitHub PR status lookup failed: {http_error}"
            ) from http_error
        if response.status_code >= 400:
            raise RemoteRequirementError(
                f"GitHub PR status lookup failed: HTTP {response.status_code} {response.text}"
            )
        return self._build_metadata_from_payload(response.json())

    def _view_pull_request_cli(
        self,
        *,
        repository_full_name_str: str,
        pull_request_identifier_str: str,
        context_text: str,
    ) -> PullRequestMetadata:
        """View one pull request through GitHub CLI.

        Args:
            repository_full_name_str: GitHub repository full name.
            pull_request_identifier_str: Pull request number, URL, or branch.
            context_text: Human-readable operation context.

        Returns:
            PullRequestMetadata: Current PR metadata.
        """
        completed_process = self._run_gh_command(
            [
                "pr",
                "view",
                pull_request_identifier_str,
                "--repo",
                repository_full_name_str,
                "--json",
                "number,url,state,mergedAt",
            ],
            context_text=context_text,
        )
        pull_request_payload = self._parse_cli_json_output(
            completed_process.stdout,
            context_text=context_text,
        )
        if not isinstance(pull_request_payload, dict):
            raise RemoteRequirementError(
                f"{context_text} returned an unexpected payload."
            )
        return self._build_metadata_from_cli_payload(pull_request_payload)
