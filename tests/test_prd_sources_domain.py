"""Tests for PRD source domain policies."""

from __future__ import annotations

import pytest

from backend.dsl.prd_sources.domain.errors import (
    InvalidPrdContentError,
    UnsafePrdPathError,
)
from backend.dsl.prd_sources.domain.policies import (
    MAX_PRD_MARKDOWN_BYTES,
    build_task_prd_file_name,
    validate_imported_prd_file,
    validate_pending_prd_relative_path,
)


def test_build_task_prd_file_name_prefers_ai_summary_metadata() -> None:
    """Task PRD filenames should use semantic metadata before task title."""
    prd_markdown_text = (
        "# PRD\n\n**需求名称（AI 归纳）**：导入已有 PRD\n\n**原始需求标题**：原始标题\n"
    )

    prd_file_name = build_task_prd_file_name(
        task_id_str="cf2b9461-0000-4000-8000-000000000000",
        task_title_str="fallback title",
        prd_markdown_text=prd_markdown_text,
    )

    assert prd_file_name == "prd-cf2b9461-导入已有-prd.md"


def test_validate_pending_prd_relative_path_rejects_traversal() -> None:
    """Pending PRD selection should reject path traversal attempts."""
    with pytest.raises(UnsafePrdPathError):
        validate_pending_prd_relative_path("tasks/pending/../secret.md")


def test_validate_imported_prd_file_rejects_non_markdown() -> None:
    """Manual import should only accept Markdown filenames."""
    with pytest.raises(InvalidPrdContentError):
        validate_imported_prd_file(
            original_file_name_str="prd.txt",
            raw_file_size_int=100,
        )


def test_validate_imported_prd_file_rejects_oversized_markdown() -> None:
    """Manual import should reject Markdown files above the size limit."""
    with pytest.raises(InvalidPrdContentError):
        validate_imported_prd_file(
            original_file_name_str="prd.md",
            raw_file_size_int=MAX_PRD_MARKDOWN_BYTES + 1,
        )
