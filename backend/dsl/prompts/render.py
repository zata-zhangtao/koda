"""Prompt template rendering helpers."""

from __future__ import annotations

from pathlib import Path

_PROMPT_TEMPLATE_DIRECTORY_PATH = Path(__file__).resolve().parent / "templates"


def _read_prompt_template(template_file_name_str: str) -> str:
    """Read one UTF-8 prompt template from disk.

    Args:
        template_file_name_str: Template file name under ``templates/``.

    Returns:
        str: Template text.
    """
    prompt_template_path = _PROMPT_TEMPLATE_DIRECTORY_PATH / template_file_name_str
    return prompt_template_path.read_text(encoding="utf-8")


def render_prompt_template(
    template_file_name_str: str,
    *,
    template_context_dict: dict[str, str],
) -> str:
    """Render one prompt template with ``str.format`` placeholders.

    Args:
        template_file_name_str: Template file name under ``templates/``.
        template_context_dict: Placeholder values passed to ``str.format``.

    Returns:
        str: Rendered prompt text.
    """
    prompt_template_text = _read_prompt_template(template_file_name_str)
    return prompt_template_text.format(**template_context_dict)
