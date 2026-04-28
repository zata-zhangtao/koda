"""GitHub pull request provider adapter for remote requirements."""

from __future__ import annotations

import os
from typing import Any

import httpx

from backend.dsl.remote_requirements.domain import (
    PullRequestMetadata,
    RemoteRequirementError,
)


class GitHubPullRequestAdapter:
    """Create and inspect GitHub pull requests through the REST API."""

    def __init__(self, token_str: str | None = None) -> None:
        """Initialize the adapter.

        Args:
            token_str: Optional GitHub token. When omitted, Koda reads
                ``KODA_GITHUB_TOKEN``, ``GITHUB_TOKEN`` or ``GH_TOKEN``.
        """
        self._token_str = (
            token_str
            or os.getenv("KODA_GITHUB_TOKEN")
            or os.getenv("GITHUB_TOKEN")
            or os.getenv("GH_TOKEN")
        )

    def _build_headers(self) -> dict[str, str]:
        """Build GitHub REST API headers.

        Returns:
            dict[str, str]: Request headers.

        Raises:
            RemoteRequirementError: Raised when no token is configured.
        """
        if not self._token_str:
            raise RemoteRequirementError(
                "GitHub PR creation requires KODA_GITHUB_TOKEN, GITHUB_TOKEN, or GH_TOKEN."
            )
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
