"""Tests for GitHub pull request adapter provider selection."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from backend.dsl.remote_requirements.domain import RemoteRequirementError
from backend.dsl.remote_requirements.infrastructure import (
    github_pull_request_adapter as adapter_module,
)
from backend.dsl.remote_requirements.infrastructure.github_pull_request_adapter import (
    GitHubPullRequestAdapter,
)


def _completed_process(
    command_argument_list: list[str],
    *,
    return_code_int: int = 0,
    stdout_text: str = "",
    stderr_text: str = "",
) -> subprocess.CompletedProcess[str]:
    """Build a completed process for fake GitHub CLI calls.

    Args:
        command_argument_list: Command arguments passed to subprocess.
        return_code_int: Process return code.
        stdout_text: Fake stdout text.
        stderr_text: Fake stderr text.

    Returns:
        subprocess.CompletedProcess[str]: Fake completed process.
    """
    return subprocess.CompletedProcess(
        args=command_argument_list,
        returncode=return_code_int,
        stdout=stdout_text,
        stderr=stderr_text,
    )


def _clear_github_token_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove supported GitHub token environment variables for fallback tests.

    Args:
        monkeypatch: Pytest monkeypatch helper.
    """
    for environment_variable_name_str in (
        "KODA_GITHUB_TOKEN",
        "GITHUB_TOKEN",
        "GH_TOKEN",
    ):
        monkeypatch.delenv(environment_variable_name_str, raising=False)


def test_token_present_uses_rest_provider_without_gh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured token should keep the adapter on the REST provider path."""
    adapter = GitHubPullRequestAdapter(token_str="token-value")

    def fake_get_pull_request_rest(
        *,
        repository_full_name_str: str,
        pull_request_number_int: int,
    ):
        """Return deterministic metadata from the REST helper."""
        assert repository_full_name_str == "example/demo"
        assert pull_request_number_int == 12
        return adapter_module.PullRequestMetadata(
            number=12,
            url="https://github.com/example/demo/pull/12",
            state="open",
        )

    def fail_if_gh_is_resolved(_executable_name_str: str) -> str:
        """Fail the test if the CLI provider is used."""
        raise AssertionError("GitHub CLI should not be resolved when token exists.")

    monkeypatch.setattr(
        adapter,
        "_get_pull_request_rest",
        fake_get_pull_request_rest,
    )
    monkeypatch.setattr(adapter_module.shutil, "which", fail_if_gh_is_resolved)

    pull_request_metadata = adapter.get_pull_request(
        repository_full_name_str="example/demo",
        pull_request_number_int=12,
    )

    assert pull_request_metadata.number == 12
    assert pull_request_metadata.state == "open"


def test_cli_find_pull_request_when_token_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a token, existing PR lookup should use authenticated ``gh``."""
    _clear_github_token_environment(monkeypatch)
    command_call_list: list[list[str]] = []

    monkeypatch.setattr(adapter_module.shutil, "which", lambda _name: "/usr/bin/gh")

    def fake_subprocess_run(
        command_argument_list: list[str],
        **_subprocess_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        """Return fake auth and PR list results."""
        command_call_list.append(command_argument_list)
        gh_argument_list = command_argument_list[1:]
        if gh_argument_list == ["auth", "status", "--active"]:
            return _completed_process(command_argument_list)
        if gh_argument_list[:2] == ["pr", "list"]:
            return _completed_process(
                command_argument_list,
                stdout_text=json.dumps(
                    [
                        {
                            "number": 42,
                            "url": "https://github.com/example/demo/pull/42",
                            "state": "OPEN",
                            "mergedAt": None,
                        }
                    ]
                ),
            )
        raise AssertionError(f"Unexpected gh command: {gh_argument_list}")

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_subprocess_run)

    pull_request_metadata = GitHubPullRequestAdapter().find_pull_request(
        repository_full_name_str="example/demo",
        head_owner_login_str="example",
        branch_name_str="task/12345678-demo",
        base_branch_name_str="main",
    )

    assert pull_request_metadata is not None
    assert pull_request_metadata.number == 42
    assert pull_request_metadata.state == "open"
    assert pull_request_metadata.merged is False
    list_command_argument_list = command_call_list[1]
    assert "--head" in list_command_argument_list
    assert "task/12345678-demo" in list_command_argument_list
    assert "example:task/12345678-demo" not in list_command_argument_list


def test_cli_create_pull_request_fetches_created_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI PR creation should use non-interactive flags then normalize metadata."""
    _clear_github_token_environment(monkeypatch)
    command_call_list: list[list[str]] = []
    monkeypatch.setattr(adapter_module.shutil, "which", lambda _name: "/usr/bin/gh")

    def fake_subprocess_run(
        command_argument_list: list[str],
        **_subprocess_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        """Return fake auth, create, and view results."""
        command_call_list.append(command_argument_list)
        gh_argument_list = command_argument_list[1:]
        if gh_argument_list == ["auth", "status", "--active"]:
            return _completed_process(command_argument_list)
        if gh_argument_list[:2] == ["pr", "create"]:
            return _completed_process(
                command_argument_list,
                stdout_text="https://github.com/example/demo/pull/55\n",
            )
        if gh_argument_list[:2] == ["pr", "view"]:
            return _completed_process(
                command_argument_list,
                stdout_text=json.dumps(
                    {
                        "number": 55,
                        "url": "https://github.com/example/demo/pull/55",
                        "state": "OPEN",
                        "mergedAt": None,
                    }
                ),
            )
        raise AssertionError(f"Unexpected gh command: {gh_argument_list}")

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_subprocess_run)

    pull_request_metadata = GitHubPullRequestAdapter().create_pull_request(
        repository_full_name_str="example/demo",
        branch_name_str="task/12345678-demo",
        base_branch_name_str="main",
        title_str="Create a PR",
        body_str="Body text",
    )

    assert pull_request_metadata.number == 55
    assert pull_request_metadata.url == "https://github.com/example/demo/pull/55"
    create_command_argument_list = command_call_list[1]
    assert "--title" in create_command_argument_list
    assert "Create a PR" in create_command_argument_list
    assert "--body" in create_command_argument_list
    assert "Body text" in create_command_argument_list


def test_cli_get_pull_request_maps_merged_at_to_merged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI PR status sync should map ``mergedAt`` into merged metadata."""
    _clear_github_token_environment(monkeypatch)
    monkeypatch.setattr(adapter_module.shutil, "which", lambda _name: "/usr/bin/gh")

    def fake_subprocess_run(
        command_argument_list: list[str],
        **_subprocess_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        """Return fake auth and merged PR view results."""
        gh_argument_list = command_argument_list[1:]
        if gh_argument_list == ["auth", "status", "--active"]:
            return _completed_process(command_argument_list)
        if gh_argument_list[:2] == ["pr", "view"]:
            return _completed_process(
                command_argument_list,
                stdout_text=json.dumps(
                    {
                        "number": 77,
                        "url": "https://github.com/example/demo/pull/77",
                        "state": "MERGED",
                        "mergedAt": "2026-04-28T08:00:00Z",
                    }
                ),
            )
        raise AssertionError(f"Unexpected gh command: {gh_argument_list}")

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_subprocess_run)

    pull_request_metadata = GitHubPullRequestAdapter().get_pull_request(
        repository_full_name_str="example/demo",
        pull_request_number_int=77,
    )

    assert pull_request_metadata.number == 77
    assert pull_request_metadata.state == "merged"
    assert pull_request_metadata.merged is True


def test_cli_create_or_get_reuses_existing_pr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI create-or-get should not create a duplicate when lookup succeeds."""
    _clear_github_token_environment(monkeypatch)
    monkeypatch.setattr(adapter_module.shutil, "which", lambda _name: "/usr/bin/gh")

    def fake_subprocess_run(
        command_argument_list: list[str],
        **_subprocess_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        """Return an existing PR and reject duplicate creation."""
        gh_argument_list = command_argument_list[1:]
        if gh_argument_list == ["auth", "status", "--active"]:
            return _completed_process(command_argument_list)
        if gh_argument_list[:2] == ["pr", "list"]:
            return _completed_process(
                command_argument_list,
                stdout_text=json.dumps(
                    [
                        {
                            "number": 88,
                            "url": "https://github.com/example/demo/pull/88",
                            "state": "OPEN",
                            "mergedAt": None,
                        }
                    ]
                ),
            )
        if gh_argument_list[:2] == ["pr", "create"]:
            raise AssertionError("Existing PR should be reused.")
        raise AssertionError(f"Unexpected gh command: {gh_argument_list}")

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_subprocess_run)

    pull_request_metadata = GitHubPullRequestAdapter().create_or_get_pull_request(
        repository_full_name_str="example/demo",
        head_owner_login_str="example",
        branch_name_str="task/12345678-demo",
        base_branch_name_str="main",
        title_str="Title",
        body_str="Body",
    )

    assert pull_request_metadata.number == 88


def test_cli_missing_executable_reports_token_or_gh_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing ``gh`` should produce an actionable authentication error."""
    _clear_github_token_environment(monkeypatch)
    monkeypatch.setattr(adapter_module.shutil, "which", lambda _name: None)

    with pytest.raises(RemoteRequirementError) as error_info:
        GitHubPullRequestAdapter().get_pull_request(
            repository_full_name_str="example/demo",
            pull_request_number_int=5,
        )

    error_text = str(error_info.value)
    assert "KODA_GITHUB_TOKEN" in error_text
    assert "GitHub CLI" in error_text
    assert "`gh` was not found" in error_text


def test_cli_auth_failure_reports_login_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unauthenticated ``gh`` should tell the user to log in."""
    _clear_github_token_environment(monkeypatch)
    monkeypatch.setattr(adapter_module.shutil, "which", lambda _name: "/usr/bin/gh")

    def fake_subprocess_run(
        command_argument_list: list[str],
        **_subprocess_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        """Return an authentication failure from GitHub CLI."""
        return _completed_process(
            command_argument_list,
            return_code_int=1,
            stderr_text="not logged in",
        )

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_subprocess_run)

    with pytest.raises(RemoteRequirementError) as error_info:
        GitHubPullRequestAdapter().find_pull_request(
            repository_full_name_str="example/demo",
            head_owner_login_str="example",
            branch_name_str="task/12345678-demo",
            base_branch_name_str="main",
        )

    error_text = str(error_info.value)
    assert "gh auth login" in error_text
    assert "not logged in" in error_text
