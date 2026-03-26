"""Codex CLI runner implementation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CodexCliRunner:
    """Codex implementation of the automation runner protocol."""

    runner_kind: str = "codex"
    runner_display_name: str = "Codex"
    executable_name: str = "codex"
    interruption_marker_tuple: tuple[str, ...] = ("task interrupted",)

    def build_exec_argument_list(self, prompt_text_str: str) -> list[str]:
        """Build non-interactive Codex CLI arguments.

        Args:
            prompt_text_str: Prompt text passed to Codex.

        Returns:
            list[str]: Codex argument list without executable.
        """
        return [
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            prompt_text_str,
        ]

    def build_command_preview(self) -> str:
        """Return the command preview used in diagnostics.

        Returns:
            str: Shell-like command string.
        """
        return "codex exec --dangerously-bypass-approvals-and-sandbox <prompt>"

    def build_missing_cli_hint(self) -> str:
        """Return missing executable guidance for Codex.

        Returns:
            str: Actionable hint text.
        """
        return (
            "请先安装 Codex CLI，并确保 `codex` 可执行文件在 PATH 中；"
            "安装后可执行 `codex --version` 自检。"
        )


CODEX_CLI_RUNNER = CodexCliRunner()
