"""Claude CLI runner implementation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClaudeCliRunner:
    """Claude Code implementation of the automation runner protocol."""

    runner_kind: str = "claude"
    runner_display_name: str = "Claude Code"
    executable_name: str = "claude"
    interruption_marker_tuple: tuple[str, ...] = (
        "interrupted",
        "operation cancelled",
    )

    def build_exec_argument_list(self, prompt_text_str: str) -> list[str]:
        """Build non-interactive Claude Code CLI arguments.

        Args:
            prompt_text_str: Prompt text passed to Claude Code.

        Returns:
            list[str]: Claude argument list without executable.
        """
        del prompt_text_str
        return [
            "-p",
            "--dangerously-skip-permissions",
        ]

    def build_stdin_prompt_text(self, prompt_text_str: str) -> str | None:
        """Return Claude prompt text for stdin transport.

        Args:
            prompt_text_str: Prompt text passed to Claude Code.

        Returns:
            str | None: Prompt text written to stdin.
        """
        return prompt_text_str

    def build_command_preview(self) -> str:
        """Return the command preview used in diagnostics.

        Returns:
            str: Shell-like command string.
        """
        return "claude -p <prompt> --dangerously-skip-permissions"

    def build_missing_cli_hint(self) -> str:
        """Return missing executable guidance for Claude Code.

        Returns:
            str: Actionable hint text.
        """
        return (
            "请先安装 Claude Code CLI，并确保 `claude` 可执行文件在 PATH 中；"
            "安装后可执行 `claude --version` 自检。"
        )


CLAUDE_CLI_RUNNER = ClaudeCliRunner()
