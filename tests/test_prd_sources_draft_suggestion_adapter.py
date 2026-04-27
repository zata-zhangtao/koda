"""Tests for PRD task draft suggestion infrastructure."""

from __future__ import annotations

from types import SimpleNamespace

from backend.dsl.prd_sources.infrastructure import draft_suggestion_adapter
from backend.dsl.prd_sources.infrastructure.draft_suggestion_adapter import (
    CliPrdTaskDraftSuggestionAdapter,
)


def test_cli_prd_task_draft_suggestion_adapter_uses_read_only_codex(
    monkeypatch,
) -> None:
    """AI draft suggestions must not reuse the dangerous task automation runner."""
    captured_command_list: list[str] = []

    def fake_run(command_list: list[str], **kwargs):
        """Capture the command and return a valid JSON payload."""
        captured_command_list.extend(command_list)
        assert kwargs["input"]
        return SimpleNamespace(
            returncode=0,
            stdout='{"task_title":"Safe title","requirement_brief":"Safe brief"}',
            stderr="",
        )

    monkeypatch.setattr(
        draft_suggestion_adapter.config, "KODA_AUTOMATION_RUNNER", "codex"
    )
    monkeypatch.setattr(
        draft_suggestion_adapter.shutil, "which", lambda name: "/bin/codex"
    )
    monkeypatch.setattr(draft_suggestion_adapter.subprocess, "run", fake_run)

    suggestion = CliPrdTaskDraftSuggestionAdapter().suggest_task_draft(
        prd_markdown_text="# PRD\n\nBuild the safe thing.",
        source_file_name_str="safe.md",
    )

    assert suggestion is not None
    assert suggestion.task_title_str == "Safe title"
    assert "--dangerously-bypass-approvals-and-sandbox" not in captured_command_list
    assert "--dangerously-skip-permissions" not in captured_command_list
    assert captured_command_list == [
        "/bin/codex",
        "exec",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "-",
    ]


def test_cli_prd_task_draft_suggestion_adapter_skips_unsupported_runner(
    monkeypatch,
) -> None:
    """Unsupported safe suggestion runners should fall back deterministically."""
    monkeypatch.setattr(
        draft_suggestion_adapter.config, "KODA_AUTOMATION_RUNNER", "claude"
    )

    suggestion = CliPrdTaskDraftSuggestionAdapter().suggest_task_draft(
        prd_markdown_text="# PRD\n\nBuild the safe thing.",
        source_file_name_str="safe.md",
    )

    assert suggestion is None
