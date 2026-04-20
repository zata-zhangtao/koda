"""Tests for semantic worktree branch naming service."""

from __future__ import annotations

from backend.dsl.services.worktree_branch_naming_service import (
    WorktreeBranchNamingService,
)


def test_normalize_semantic_slug_replaces_invalid_chars_and_truncates() -> None:
    """Slug normalization should keep only lowercase alnum and hyphen tokens."""
    normalized_slug_str = WorktreeBranchNamingService.normalize_semantic_slug(
        "  Fix 登录 !!! Timeout__Handler with very very very long title  ",
        max_length_int=24,
    )

    assert normalized_slug_str == "fix-timeout-handler-with"


def test_build_task_branch_naming_result_prefers_ai_slug_when_present(
    monkeypatch,
) -> None:
    """AI slug should be used as first priority when available."""
    monkeypatch.setattr(
        WorktreeBranchNamingService,
        "_build_semantic_slug_with_ai",
        classmethod(lambda cls, **_: "ai-generated-slug"),
    )

    naming_result_obj = WorktreeBranchNamingService.build_task_branch_naming_result(
        task_id_str="12345678-task-id",
        task_title_str="Fix timeout handling",
        requirement_brief_str="Improve resilience",
    )

    assert naming_result_obj.branch_name_str == "task/12345678-ai-generated-slug"
    assert naming_result_obj.naming_source_str == "ai"
    assert naming_result_obj.semantic_slug_str == "ai-generated-slug"


def test_build_task_branch_naming_result_falls_back_to_title_slug(
    monkeypatch,
) -> None:
    """Title slug should be used when AI naming fails."""
    monkeypatch.setattr(
        WorktreeBranchNamingService,
        "_build_semantic_slug_with_ai",
        classmethod(lambda cls, **_: None),
    )

    naming_result_obj = WorktreeBranchNamingService.build_task_branch_naming_result(
        task_id_str="12345678-task-id",
        task_title_str="Create linked worktree",
        requirement_brief_str="",
    )

    assert naming_result_obj.branch_name_str == "task/12345678-create-linked-worktree"
    assert naming_result_obj.naming_source_str == "title_fallback"
    assert naming_result_obj.semantic_slug_str == "create-linked-worktree"


def test_build_task_branch_naming_result_falls_back_to_legacy_when_title_empty(
    monkeypatch,
) -> None:
    """Legacy short-id format should be used when both AI and title slug fail."""
    monkeypatch.setattr(
        WorktreeBranchNamingService,
        "_build_semantic_slug_with_ai",
        classmethod(lambda cls, **_: None),
    )

    naming_result_obj = WorktreeBranchNamingService.build_task_branch_naming_result(
        task_id_str="12345678-task-id",
        task_title_str="！！！",
        requirement_brief_str="",
    )

    assert naming_result_obj.branch_name_str == "task/12345678"
    assert naming_result_obj.naming_source_str == "legacy_fallback"
    assert naming_result_obj.semantic_slug_str is None
