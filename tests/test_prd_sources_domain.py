"""Tests for PRD source domain policies."""

from __future__ import annotations

from datetime import datetime

import pytest

from backend.dsl.prd_sources.domain.errors import (
    InvalidPrdContentError,
    UnsafePrdPathError,
)
from backend.dsl.prd_sources.domain.policies import (
    MAX_PRD_MARKDOWN_BYTES,
    build_task_draft_requirement_brief_from_prd,
    build_task_draft_title_from_prd,
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
        reference_datetime=datetime(2026, 4, 23, 13, 5, 0),
    )

    assert prd_file_name == "20260423-130500-prd-导入已有-prd.md"


def test_build_task_draft_title_prefers_prd_metadata() -> None:
    """Task draft title should prefer PRD semantic metadata."""
    prd_markdown_text = (
        "# PRD\n\n**需求名称（AI 归纳）**：PRD 先行创建任务\n"
        "\n**原始需求标题**：原始标题\n"
    )

    draft_title = build_task_draft_title_from_prd(
        prd_markdown_text,
        source_file_name_str="fallback-file.md",
    )

    assert draft_title == "PRD 先行创建任务"


def test_build_task_draft_requirement_brief_uses_prd_body() -> None:
    """Task draft description should skip metadata and headings."""
    prd_markdown_text = (
        "# PRD\n\n"
        "**需求名称（AI 归纳）**：PRD 先行创建任务\n\n"
        "允许用户在创建 task 前选择 pending PRD。\n\n"
        "用户确认 AI 预填字段后才创建 task。\n"
    )

    requirement_brief = build_task_draft_requirement_brief_from_prd(
        prd_markdown_text,
        fallback_title_str="PRD 先行创建任务",
    )

    assert "需求名称" not in requirement_brief
    assert "允许用户在创建 task 前选择 pending PRD" in requirement_brief
    assert "用户确认 AI 预填字段后才创建 task" in requirement_brief


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
