"""AI-backed PRD task draft suggestion adapter."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

from backend.dsl.prompts import render_prompt_template
from backend.dsl.prd_sources.domain.models import PrdTaskDraftTextSuggestion
from utils.settings import config

_PRD_DRAFT_SUGGESTION_TIMEOUT_SECONDS = 45
_PRD_DRAFT_CONTEXT_MAX_LENGTH = 12000
_CODEX_RUNNER_KIND = "codex"
_CODEX_EXECUTABLE_NAME = "codex"


class CliPrdTaskDraftSuggestionAdapter:
    """Generate task draft suggestions through a safe read-only Codex runner."""

    def suggest_task_draft(
        self,
        *,
        prd_markdown_text: str,
        source_file_name_str: str | None,
    ) -> PrdTaskDraftTextSuggestion | None:
        """Ask the active runner for title and description suggestions.

        Args:
            prd_markdown_text: PRD Markdown content.
            source_file_name_str: Optional source file name.

        Returns:
            PrdTaskDraftTextSuggestion | None: AI suggestion, or None on failure.
        """
        if config.KODA_AUTOMATION_RUNNER != _CODEX_RUNNER_KIND:
            return None

        runner_executable_path_str = shutil.which(_CODEX_EXECUTABLE_NAME)
        if runner_executable_path_str is None:
            return None

        runner_prompt_text_str = _build_prd_task_draft_prompt(
            prd_markdown_text=prd_markdown_text,
            source_file_name_str=source_file_name_str,
        )
        try:
            completed_process = subprocess.run(
                [
                    runner_executable_path_str,
                    "exec",
                    "--sandbox",
                    "read-only",
                    "--ephemeral",
                    "-",
                ],
                cwd=str(config.BASE_DIR),
                capture_output=True,
                input=runner_prompt_text_str,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_PRD_DRAFT_SUGGESTION_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

        if completed_process.returncode != 0:
            return None

        output_text = "\n".join(
            text_part.strip()
            for text_part in (completed_process.stdout, completed_process.stderr)
            if text_part and text_part.strip()
        )
        parsed_payload = _parse_first_json_object(output_text)
        if parsed_payload is None:
            return None

        task_title_str = str(parsed_payload.get("task_title") or "").strip()
        requirement_brief_str = str(
            parsed_payload.get("requirement_brief") or ""
        ).strip()
        if not task_title_str or not requirement_brief_str:
            return None
        return PrdTaskDraftTextSuggestion(
            task_title_str=task_title_str[:200],
            requirement_brief_str=requirement_brief_str[:1200],
        )


def _build_prd_task_draft_prompt(
    *,
    prd_markdown_text: str,
    source_file_name_str: str | None,
) -> str:
    """Build the prompt used to derive task fields from PRD content."""
    trimmed_prd_markdown_text = prd_markdown_text[:_PRD_DRAFT_CONTEXT_MAX_LENGTH]
    source_name_text = source_file_name_str or "pasted-prd.md"
    return render_prompt_template(
        "prd_task_draft_prompt.txt",
        template_context_dict={
            "source_file_name": source_name_text,
            "prd_markdown_text": trimmed_prd_markdown_text,
        },
    )


def _parse_first_json_object(output_text: str) -> dict[str, object] | None:
    """Parse the first JSON object from runner output."""
    stripped_output_text = output_text.strip()
    if not stripped_output_text:
        return None

    try:
        parsed_json = json.loads(stripped_output_text)
    except json.JSONDecodeError:
        json_match = re.search(r"\{[\s\S]*\}", stripped_output_text)
        if json_match is None:
            return None
        try:
            parsed_json = json.loads(json_match.group(0))
        except json.JSONDecodeError:
            return None

    if not isinstance(parsed_json, dict):
        return None
    return parsed_json
