"""Read-only AI preview profile generation for uncertain worktrees."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from backend.dsl.preview_sandboxes.domain.models import PreviewProfile
from backend.dsl.prompts import render_prompt_template
from utils.settings import config

_PREVIEW_PROFILE_GENERATION_TIMEOUT_SECONDS = 60
_CODEX_RUNNER_KIND = "codex"
_CODEX_EXECUTABLE_NAME = "codex"


class CliAiPreviewProfileGenerator:
    """Generate preview profile candidates through a safe read-only runner."""

    def generate_preview_profile_dict(
        self,
        *,
        worktree_path_str: str,
        deterministic_profile: PreviewProfile,
    ) -> dict[str, Any] | None:
        """Ask the safe runner for a preview profile candidate.

        Args:
            worktree_path_str: Absolute worktree path.
            deterministic_profile: Current deterministic profile candidate.

        Returns:
            dict[str, Any] | None: Raw profile candidate, or ``None`` on failure.
        """
        if config.KODA_AUTOMATION_RUNNER != _CODEX_RUNNER_KIND:
            return None

        runner_executable_path_str = shutil.which(_CODEX_EXECUTABLE_NAME)
        if runner_executable_path_str is None:
            return None

        runner_prompt_text_str = _build_preview_profile_prompt(
            worktree_path_str=worktree_path_str,
            deterministic_profile=deterministic_profile,
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
                cwd=worktree_path_str,
                capture_output=True,
                input=runner_prompt_text_str,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_PREVIEW_PROFILE_GENERATION_TIMEOUT_SECONDS,
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
        return parsed_payload


def _build_preview_profile_prompt(
    *,
    worktree_path_str: str,
    deterministic_profile: PreviewProfile,
) -> str:
    """Render the read-only preview profile prompt."""
    worktree_name_str = Path(worktree_path_str).name or "task-worktree"
    deterministic_summary_text = "\n".join(
        [
            f"- applicability: {deterministic_profile.applicability.value}",
            f"- applicability_reason: {deterministic_profile.applicability_reason}",
            f"- runtime_kind: {deterministic_profile.runtime_kind.value}",
            f"- working_directory: {deterministic_profile.working_directory or '.'}",
            (
                "- dependency_commands: "
                + (
                    ", ".join(deterministic_profile.dependency_commands)
                    if deterministic_profile.dependency_commands
                    else "(none)"
                )
            ),
            f"- start_command: {deterministic_profile.start_command or '(none)'}",
            f"- internal_port: {deterministic_profile.internal_port or '(none)'}",
        ]
    )
    return render_prompt_template(
        "preview_profile_prompt.txt",
        template_context_dict={
            "worktree_name": worktree_name_str,
            "deterministic_summary": deterministic_summary_text,
        },
    )


def _parse_first_json_object(output_text: str) -> dict[str, Any] | None:
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
