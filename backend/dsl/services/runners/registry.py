"""Runner registry utilities for automation orchestration."""

from __future__ import annotations

from backend.dsl.services.runners.base import AutomationRunner
from backend.dsl.services.runners.claude_cli_runner import CLAUDE_CLI_RUNNER
from backend.dsl.services.runners.codex_cli_runner import CODEX_CLI_RUNNER

_DEFAULT_RUNNER_KIND = "codex"
_registered_runner_by_kind: dict[str, AutomationRunner] = {
    CODEX_CLI_RUNNER.runner_kind: CODEX_CLI_RUNNER,
    CLAUDE_CLI_RUNNER.runner_kind: CLAUDE_CLI_RUNNER,
}


def list_supported_runner_kind_list() -> list[str]:
    """List registered runner kinds.

    Returns:
        list[str]: Sorted runner kind values.
    """
    return sorted(_registered_runner_by_kind.keys())


def get_runner_by_kind(runner_kind_str: str) -> AutomationRunner:
    """Resolve a runner by kind.

    Args:
        runner_kind_str: Requested runner kind value.

    Returns:
        AutomationRunner: Registered runner instance.

    Raises:
        ValueError: If the runner kind is unsupported.
    """
    normalized_runner_kind_str = runner_kind_str.strip().lower()
    runner_obj = _registered_runner_by_kind.get(normalized_runner_kind_str)
    if runner_obj is None:
        supported_runner_kind_text = ", ".join(list_supported_runner_kind_list())
        raise ValueError(
            "Unsupported automation runner kind "
            f"'{runner_kind_str}'. Supported values: {supported_runner_kind_text}."
        )
    return runner_obj


def resolve_runner_kind(runner_kind_str: str | None) -> str:
    """Resolve and normalize a runner kind with default fallback.

    Args:
        runner_kind_str: Requested runner kind from config.

    Returns:
        str: Normalized runner kind.

    Raises:
        ValueError: If a non-empty configured value is unsupported.
    """
    if runner_kind_str is None or runner_kind_str.strip() == "":
        return _DEFAULT_RUNNER_KIND
    return get_runner_by_kind(runner_kind_str).runner_kind


def get_default_runner_kind() -> str:
    """Return the default runner kind.

    Returns:
        str: Default runner kind value.
    """
    return _DEFAULT_RUNNER_KIND
