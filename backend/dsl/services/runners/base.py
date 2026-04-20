"""Runner protocol definitions for task automation."""

from __future__ import annotations

from typing import Protocol


class AutomationRunner(Protocol):
    """Protocol for pluggable automation runners.

    Implementations encapsulate runner-specific CLI behavior while the task
    workflow orchestration remains shared.

    Attributes:
        runner_kind: Stable runner identity used in logs and config.
        runner_display_name: Human-readable runner name.
        executable_name: CLI executable name expected in PATH.
        interruption_marker_tuple: Marker strings indicating interrupted output.
    """

    runner_kind: str
    runner_display_name: str
    executable_name: str
    interruption_marker_tuple: tuple[str, ...]

    def build_exec_argument_list(self, prompt_text_str: str) -> list[str]:
        """Build CLI arguments for non-interactive execution.

        Args:
            prompt_text_str: Prompt text for the runner CLI.

        Returns:
            list[str]: Argument list without the executable itself.
                Implementations may consume the prompt either via argv or stdin.
        """

    def build_stdin_prompt_text(self, prompt_text_str: str) -> str | None:
        """Return prompt text that should be piped to stdin, if any.

        Args:
            prompt_text_str: Prompt text for the runner CLI.

        Returns:
            str | None: Prompt text to write to stdin, or ``None`` when argv
                transport is used instead.
        """

    def build_command_preview(self) -> str:
        """Return a human-readable command preview for logs.

        Returns:
            str: Shell-like command preview with a prompt placeholder.
        """

    def build_missing_cli_hint(self) -> str:
        """Return actionable installation guidance for missing executable.

        Returns:
            str: Runner-specific troubleshooting hint.
        """
