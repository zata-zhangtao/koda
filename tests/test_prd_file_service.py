"""Tests for PRD filename normalization and repair helpers."""

from __future__ import annotations

from pathlib import Path

from backend.dsl.services.prd_file_service import (
    build_task_prd_file_prefix,
    ensure_task_prd_file_contract,
    find_task_prd_file_path,
    is_valid_task_prd_semantic_file_name,
    normalize_task_prd_requirement_slug,
    repair_invalid_task_prd_file_for_read,
)


def test_normalize_task_prd_requirement_slug_preserves_chinese_semantics() -> None:
    """Slug normalization should keep readable Chinese tokens after cleaning."""
    normalized_slug_str = normalize_task_prd_requirement_slug(
        "  修改 PRD 命令：支持中文/随机值?  ",
    )

    assert normalized_slug_str == "修改-prd-命令-支持中文-随机值"


def test_normalize_task_prd_requirement_slug_truncates_to_safe_utf8_byte_limit() -> (
    None
):
    """Slug normalization should keep the final PRD basename within 255 UTF-8 bytes."""
    task_id_str = "cf2b9461-1234-5678-9012-abcdefabcdef"
    normalized_slug_str = normalize_task_prd_requirement_slug("汉" * 100)
    final_file_name_str = (
        f"{build_task_prd_file_prefix(task_id_str)}-{normalized_slug_str}.md"
    )

    assert len(normalized_slug_str) < 80
    assert len(final_file_name_str.encode("utf-8")) <= 255


def test_is_valid_task_prd_semantic_file_name_rejects_short_random_alnum_suffixes() -> (
    None
):
    """Short interleaved alnum suffixes should not pass as semantic PRD names."""
    task_id_str = "cf2b9461-1234-5678-9012-abcdefabcdef"

    assert not is_valid_task_prd_semantic_file_name(
        "prd-cf2b9461-k9m2qz.md",
        task_id_str,
    )
    assert not is_valid_task_prd_semantic_file_name(
        "prd-cf2b9461-a1b2c.md",
        task_id_str,
    )
    assert is_valid_task_prd_semantic_file_name(
        "prd-cf2b9461-ios17.md",
        task_id_str,
    )


def test_ensure_task_prd_file_contract_repairs_legacy_file_name_with_title_fallback(
    tmp_path: Path,
) -> None:
    """Legacy PRD files should be renamed to a semantic filename when repaired."""
    tasks_directory_path = tmp_path / "tasks"
    tasks_directory_path.mkdir()

    legacy_prd_file_path = tasks_directory_path / "prd-cf2b9461.md"
    legacy_prd_file_path.write_text(
        ("# PRD\n**原始需求标题**：修改 prd 命令\n**需求名称（AI 归纳）**：c3e023d8\n"),
        encoding="utf-8",
    )

    correction_result = ensure_task_prd_file_contract(
        worktree_dir_path=tmp_path,
        task_id_str="cf2b9461-1234-5678-9012-abcdefabcdef",
        task_title_str="修改 prd 命令",
    )

    expected_prd_file_path = tasks_directory_path / "prd-cf2b9461-修改-prd-命令.md"
    assert correction_result.resolved_file_path == expected_prd_file_path
    assert correction_result.renamed_from_path == legacy_prd_file_path
    assert correction_result.semantic_slug_str == "修改-prd-命令"
    assert correction_result.naming_source_str == "original_title"
    assert not legacy_prd_file_path.exists()
    assert expected_prd_file_path.read_text(encoding="utf-8").startswith("# PRD")


def test_find_task_prd_file_path_returns_none_when_only_random_suffix_files_exist(
    tmp_path: Path,
) -> None:
    """Read lookup should ignore invalid random-suffix PRD filenames."""
    tasks_directory_path = tmp_path / "tasks"
    tasks_directory_path.mkdir()

    random_hex_prd_file_path = tasks_directory_path / "prd-cf2b9461-c3e023d8.md"
    random_hex_prd_file_path.write_text("# PRD\n", encoding="utf-8")
    random_short_prd_file_path = tasks_directory_path / "prd-cf2b9461-k9m2qz.md"
    random_short_prd_file_path.write_text("# PRD\n", encoding="utf-8")

    resolved_prd_file_path = find_task_prd_file_path(
        worktree_dir_path=tmp_path,
        task_id_str="cf2b9461-1234-5678-9012-abcdefabcdef",
    )

    assert resolved_prd_file_path is None


def test_repair_invalid_task_prd_file_for_read_repairs_random_suffix_with_task_title(
    tmp_path: Path,
) -> None:
    """Read repair should convert an invalid random suffix into a semantic filename."""
    tasks_directory_path = tmp_path / "tasks"
    tasks_directory_path.mkdir()

    invalid_random_prd_file_path = tasks_directory_path / "prd-cf2b9461-k9m2qz.md"
    invalid_random_prd_file_path.write_text("# PRD\n", encoding="utf-8")

    correction_result = repair_invalid_task_prd_file_for_read(
        worktree_dir_path=tmp_path,
        task_id_str="cf2b9461-1234-5678-9012-abcdefabcdef",
        task_title_str="修改 prd 命令",
    )

    expected_prd_file_path = tasks_directory_path / "prd-cf2b9461-修改-prd-命令.md"
    assert correction_result.resolved_file_path == expected_prd_file_path
    assert correction_result.renamed_from_path == invalid_random_prd_file_path
    assert expected_prd_file_path.exists()
