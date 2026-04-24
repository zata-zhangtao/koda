"""Helpers for task-scoped PRD file naming and lookup.

New PRD files use a timestamped semantic filename contract of
``YYYYMMDD-HHMMSS-prd-<requirement-slug>.md`` so the creation time remains
visible in the filename. Older task-id-prefixed filenames stay readable for
backward compatibility, and committed task markdown may still be moved into
``tasks/archive/`` by repository hooks.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path

_TASK_PRD_REQUIREMENT_SLUG_MAX_LENGTH = 80
_TASK_PRD_FILE_NAME_MAX_BYTES = 255
_TASK_PRD_TIMESTAMPED_FILE_NAME_PATTERN = re.compile(
    r"^(?P<timestamp>\d{8}-\d{6})-prd-(?P<slug>.+)\.md$"
)
_TASK_PRD_LEGACY_FIXED_FILE_NAME_PATTERN = re.compile(
    r"^prd-(?P<task_short_id>[0-9a-f]{8})\.md$"
)
_TASK_PRD_LEGACY_SEMANTIC_FILE_NAME_PATTERN = re.compile(
    r"^prd-(?P<task_short_id>[0-9a-f]{8})-(?P<slug>.+)\.md$"
)
_TASK_PRD_REQUIREMENT_SLUG_MAX_BYTES = _TASK_PRD_FILE_NAME_MAX_BYTES - len(
    "20260423-130500-prd-.md".encode("utf-8")
)
_WINDOWS_FORBIDDEN_FILENAME_CHAR_SET = set('<>:"/\\|?*')
_MARKDOWN_INLINE_WRAPPER_PATTERN = re.compile(r"^[`*_]+|[`*_]+$")
_ASCII_ALNUM_ONLY_PATTERN = re.compile(r"^[a-z0-9]+$")
_HEX_ONLY_PATTERN = re.compile(r"^[0-9a-f]{6,}$")
_UUID_LIKE_PATTERN = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4,})+$")


@dataclass(frozen=True, slots=True)
class TaskPrdFileCorrectionResult:
    """Describe one PRD filename validation/correction outcome.

    Attributes:
        resolved_file_path: Final PRD path that should be consumed
        renamed_from_path: Original file path when a rename happened
        semantic_slug_str: Semantic slug present in the resolved filename
        naming_source_str: Source used to derive the semantic slug
    """

    resolved_file_path: Path | None
    renamed_from_path: Path | None = None
    semantic_slug_str: str | None = None
    naming_source_str: str | None = None

    @property
    def applied_correction_bool(self) -> bool:
        """Whether the PRD filename had to be corrected."""
        return self.renamed_from_path is not None


def build_task_prd_file_prefix(task_id_str: str) -> str:
    """Build the legacy task-specific PRD filename prefix.

    Args:
        task_id_str: Task UUID string.

    Returns:
        str: Legacy prefix such as ``prd-cf2b9461``.
    """
    return f"prd-{task_id_str[:8]}"


def build_task_prd_output_path_contract(
    task_id_str: str,
    reference_datetime: datetime | None = None,
) -> str:
    """Build the PRD path contract shown to Codex in prompts.

    Args:
        task_id_str: Task UUID string.

    Returns:
        str: Output contract such as
            ``tasks/20260423-130500-prd-<requirement-slug>.md``.
    """
    _ = task_id_str
    timestamp_prefix_text = build_task_prd_timestamp_prefix(reference_datetime)
    return f"tasks/{timestamp_prefix_text}-prd-<requirement-slug>.md"


def build_task_prd_timestamp_prefix(
    reference_datetime: datetime | None = None,
) -> str:
    """Build the timestamp prefix used for task PRD filenames.

    Args:
        reference_datetime: Optional timestamp reference. When omitted the
            current local time is used.

    Returns:
        str: Timestamp in ``YYYYMMDD-HHMMSS`` format.
    """
    timestamp_reference_datetime = reference_datetime or datetime.now()
    return timestamp_reference_datetime.strftime("%Y%m%d-%H%M%S")


def normalize_task_prd_requirement_slug(
    raw_requirement_text: str,
    *,
    max_length_int: int = _TASK_PRD_REQUIREMENT_SLUG_MAX_LENGTH,
    max_bytes_int: int = _TASK_PRD_REQUIREMENT_SLUG_MAX_BYTES,
) -> str:
    """Normalize requirement text into a cross-platform-safe semantic slug.

    Args:
        raw_requirement_text: Raw requirement text or AI summary
        max_length_int: Maximum slug length
        max_bytes_int: Maximum UTF-8 byte length for the slug portion

    Returns:
        str: Safe semantic slug that may preserve Chinese or other letters
    """
    normalized_requirement_text = unicodedata.normalize(
        "NFKC",
        raw_requirement_text,
    ).strip()
    if normalized_requirement_text == "" or max_length_int <= 0 or max_bytes_int <= 0:
        return ""

    lowered_requirement_text = normalized_requirement_text.lower()
    normalized_character_list: list[str] = []
    pending_separator_bool = False
    for raw_character in lowered_requirement_text:
        unicode_category = unicodedata.category(raw_character)
        if unicode_category.startswith(("L", "N")):
            if pending_separator_bool and normalized_character_list:
                normalized_character_list.append("-")
            normalized_character_list.append(raw_character)
            pending_separator_bool = False
            continue

        if (
            raw_character.isspace()
            or raw_character in _WINDOWS_FORBIDDEN_FILENAME_CHAR_SET
            or raw_character in {"-", "_", ".", ",", "(", ")", "[", "]", "{", "}"}
            or unicode_category.startswith(("P", "S", "C"))
        ):
            pending_separator_bool = True

    compacted_slug_text = re.sub(
        r"-{2,}",
        "-",
        "".join(normalized_character_list).strip("-"),
    )
    character_limited_slug_text = compacted_slug_text[:max_length_int].strip("-")
    truncated_slug_text = _truncate_task_prd_slug_to_max_bytes(
        character_limited_slug_text,
        max_bytes_int=max_bytes_int,
    )
    return truncated_slug_text


def is_valid_task_prd_semantic_slug(
    semantic_slug_str: str,
    task_id_str: str,
) -> bool:
    """Check whether a semantic PRD slug satisfies the non-random contract.

    Args:
        semantic_slug_str: Candidate semantic slug
        task_id_str: Task UUID string

    Returns:
        bool: ``True`` when the slug is non-empty and not random-like
    """
    normalized_slug_str = normalize_task_prd_requirement_slug(semantic_slug_str)
    if normalized_slug_str == "":
        return False

    task_short_id_str = task_id_str[:8].lower()
    if normalized_slug_str == task_short_id_str:
        return False
    if _HEX_ONLY_PATTERN.fullmatch(normalized_slug_str):
        return False
    if _UUID_LIKE_PATTERN.fullmatch(normalized_slug_str):
        return False
    if _looks_like_interleaved_short_random_identifier(normalized_slug_str):
        return False
    return True


def is_valid_task_prd_semantic_file_name(
    file_name_str: str,
    task_id_str: str,
) -> bool:
    """Validate whether a PRD filename satisfies the semantic naming contract.

    Args:
        file_name_str: Candidate PRD filename
        task_id_str: Task UUID string

    Returns:
        bool: ``True`` when the file uses the timestamped semantic PRD contract
    """
    if not file_name_str.endswith(".md"):
        return False
    timestamped_file_name_match = _TASK_PRD_TIMESTAMPED_FILE_NAME_PATTERN.fullmatch(
        file_name_str
    )
    if timestamped_file_name_match is None:
        return False

    semantic_slug_str = timestamped_file_name_match.group("slug")
    if not is_valid_task_prd_semantic_slug(semantic_slug_str, task_id_str):
        return False

    normalized_slug_str = normalize_task_prd_requirement_slug(semantic_slug_str)
    return semantic_slug_str == normalized_slug_str


def is_valid_task_prd_legacy_semantic_file_name(
    file_name_str: str,
    task_id_str: str,
) -> bool:
    """Validate whether a legacy task-id-prefixed PRD filename is semantic.

    Args:
        file_name_str: Candidate PRD filename.
        task_id_str: Task UUID string.

    Returns:
        bool: ``True`` when the file uses the historical task-id prefix with a
        non-random semantic slug.
    """
    legacy_match = _TASK_PRD_LEGACY_SEMANTIC_FILE_NAME_PATTERN.fullmatch(file_name_str)
    if legacy_match is None:
        return False
    if legacy_match.group("task_short_id").lower() != task_id_str[:8].lower():
        return False

    semantic_slug_str = legacy_match.group("slug")
    if not is_valid_task_prd_semantic_slug(semantic_slug_str, task_id_str):
        return False

    normalized_slug_str = normalize_task_prd_requirement_slug(semantic_slug_str)
    return semantic_slug_str == normalized_slug_str


def ensure_task_prd_file_contract(
    worktree_dir_path: Path,
    task_id_str: str,
    task_title_str: str,
    reference_datetime: datetime | None = None,
) -> TaskPrdFileCorrectionResult:
    """Ensure the task PRD file satisfies the semantic filename contract.

    Args:
        worktree_dir_path: Task worktree root directory
        task_id_str: Task UUID string
        task_title_str: Task title used as the final fallback naming source
        reference_datetime: Optional timestamp reference for the target file

    Returns:
        TaskPrdFileCorrectionResult: Final resolved PRD path and correction info
    """
    candidate_prd_file_path_list = _list_unsorted_task_prd_file_paths(
        worktree_dir_path=worktree_dir_path,
        task_id_str=task_id_str,
    )
    if not candidate_prd_file_path_list:
        return TaskPrdFileCorrectionResult(resolved_file_path=None)

    sorted_candidate_prd_file_path_list = _list_ranked_task_prd_file_paths(
        worktree_dir_path=worktree_dir_path,
        task_id_str=task_id_str,
    )
    for candidate_prd_file_path in sorted_candidate_prd_file_path_list:
        if is_valid_task_prd_semantic_file_name(
            candidate_prd_file_path.name,
            task_id_str,
        ):
            semantic_slug_str = _extract_semantic_slug_from_file_name(
                candidate_prd_file_path.name,
                task_id_str,
            )
            return TaskPrdFileCorrectionResult(
                resolved_file_path=candidate_prd_file_path,
                semantic_slug_str=semantic_slug_str,
                naming_source_str="existing_semantic",
            )

    return _repair_task_prd_file_candidates(
        candidate_prd_file_path_list=candidate_prd_file_path_list,
        task_id_str=task_id_str,
        task_title_str=task_title_str,
        reference_datetime=reference_datetime,
    )


def repair_invalid_task_prd_file_for_read(
    worktree_dir_path: Path,
    task_id_str: str,
    task_title_str: str,
    reference_datetime: datetime | None = None,
) -> TaskPrdFileCorrectionResult:
    """Repair invalid random-suffix PRD filenames for read compatibility.

    This helper intentionally avoids mutating the still-supported legacy fixed
    filename. It only repairs invalid task-prefixed candidates when no readable
    semantic or legacy PRD file is currently available.

    Args:
        worktree_dir_path: Task worktree root directory
        task_id_str: Task UUID string
        task_title_str: Task title used as the final fallback naming source
        reference_datetime: Optional timestamp reference for the repaired file

    Returns:
        TaskPrdFileCorrectionResult: Resolved readable path or ``None`` when no
            repairable invalid candidate exists
    """
    existing_readable_prd_file_path = find_task_prd_file_path(
        worktree_dir_path=worktree_dir_path,
        task_id_str=task_id_str,
    )
    if existing_readable_prd_file_path is not None:
        return TaskPrdFileCorrectionResult(
            resolved_file_path=existing_readable_prd_file_path,
            semantic_slug_str=_extract_semantic_slug_from_file_name(
                existing_readable_prd_file_path.name,
                task_id_str,
            ),
            naming_source_str="existing_readable",
        )

    invalid_candidate_prd_file_path_list = [
        candidate_prd_file_path
        for candidate_prd_file_path in _list_ranked_task_prd_file_paths(
            worktree_dir_path=worktree_dir_path,
            task_id_str=task_id_str,
        )
        if _build_task_prd_file_priority_int(candidate_prd_file_path, task_id_str) == 0
    ]
    if not invalid_candidate_prd_file_path_list:
        return TaskPrdFileCorrectionResult(resolved_file_path=None)

    return _repair_task_prd_file_candidates(
        candidate_prd_file_path_list=invalid_candidate_prd_file_path_list,
        task_id_str=task_id_str,
        task_title_str=task_title_str,
        reference_datetime=reference_datetime,
    )


def list_task_prd_file_paths(worktree_dir_path: Path, task_id_str: str) -> list[Path]:
    """List readable live PRD files from ``tasks/`` root.

    Args:
        worktree_dir_path: Task worktree root directory.
        task_id_str: Task UUID string.

    Returns:
        list[Path]: Matching PRD file paths sorted so timestamped semantic files
            are preferred over legacy filename variants.
    """
    return _list_readable_task_prd_file_paths_in_directory(
        task_prd_directory_path=worktree_dir_path / "tasks",
        task_id_str=task_id_str,
    )


def list_all_task_prd_file_paths(
    worktree_dir_path: Path, task_id_str: str
) -> list[Path]:
    """List all task-prefixed PRD files, including invalid repair candidates."""
    return _list_ranked_task_prd_file_paths(
        worktree_dir_path=worktree_dir_path,
        task_id_str=task_id_str,
    )


def _list_ranked_task_prd_file_paths(
    worktree_dir_path: Path,
    task_id_str: str,
) -> list[Path]:
    """List all task PRD candidates for repair, ranked by semantic quality."""
    return _list_ranked_task_prd_file_paths_in_directory(
        task_prd_directory_path=worktree_dir_path / "tasks",
        task_id_str=task_id_str,
    )


def _list_ranked_task_prd_file_paths_in_directory(
    task_prd_directory_path: Path,
    task_id_str: str,
) -> list[Path]:
    """List task PRD candidates from one directory, ranked by semantic quality."""
    matching_prd_file_path_list = _list_unsorted_task_prd_file_paths_in_directory(
        task_prd_directory_path=task_prd_directory_path,
        task_id_str=task_id_str,
    )

    def _sort_key(task_prd_file_path: Path) -> tuple[int, float, str]:
        try:
            last_modified_timestamp = task_prd_file_path.stat().st_mtime
        except OSError:
            last_modified_timestamp = -1.0
        return (
            _build_task_prd_file_priority_int(
                task_prd_file_path=task_prd_file_path,
                task_id_str=task_id_str,
            ),
            last_modified_timestamp,
            task_prd_file_path.name,
        )

    return sorted(
        matching_prd_file_path_list,
        key=_sort_key,
        reverse=True,
    )


def _build_task_prd_file_priority_int(
    task_prd_file_path: Path,
    task_id_str: str,
) -> int:
    """Rank PRD filenames for lookup and repair preference."""
    if is_valid_task_prd_semantic_file_name(task_prd_file_path.name, task_id_str):
        return 3

    if is_valid_task_prd_legacy_semantic_file_name(
        task_prd_file_path.name,
        task_id_str,
    ):
        return 2

    if _TASK_PRD_LEGACY_FIXED_FILE_NAME_PATTERN.fullmatch(task_prd_file_path.name):
        return 1
    return 0


def _is_readable_task_prd_file_path(
    task_prd_file_path: Path,
    task_id_str: str,
) -> bool:
    """Return whether the PRD file is legal to expose through read APIs."""
    return _build_task_prd_file_priority_int(task_prd_file_path, task_id_str) > 0


def find_task_prd_file_path(worktree_dir_path: Path, task_id_str: str) -> Path | None:
    """Resolve the best live PRD file path from ``tasks/`` root.

    Args:
        worktree_dir_path: Task worktree root directory.
        task_id_str: Task UUID string.

    Returns:
        Path | None: The best matching PRD file path, or ``None`` when absent.
    """
    matching_prd_file_path_list = list_task_prd_file_paths(
        worktree_dir_path=worktree_dir_path,
        task_id_str=task_id_str,
    )
    if not matching_prd_file_path_list:
        return None

    return matching_prd_file_path_list[0]


def find_task_readable_prd_file_path(
    worktree_dir_path: Path,
    task_id_str: str,
) -> Path | None:
    """Resolve the best readable PRD path, including archive fallback.

    This helper prefers the live ``tasks/`` PRD so newly generated content wins
    over history, then falls back to ``tasks/archive/`` because committed task
    markdown is archived by repository hooks while the task may still remain
    open in later workflow stages.

    Args:
        worktree_dir_path: Task worktree root directory.
        task_id_str: Task UUID string.

    Returns:
        Path | None: Best matching live-or-archived PRD file path.
    """
    live_prd_file_path = find_task_prd_file_path(worktree_dir_path, task_id_str)
    if live_prd_file_path is not None:
        return live_prd_file_path

    archived_prd_file_path_list = _list_readable_task_prd_file_paths_in_directory(
        task_prd_directory_path=worktree_dir_path / "tasks" / "archive",
        task_id_str=task_id_str,
    )
    if not archived_prd_file_path_list:
        return None

    return archived_prd_file_path_list[0]


def _list_unsorted_task_prd_file_paths(
    worktree_dir_path: Path,
    task_id_str: str,
) -> list[Path]:
    """Collect all task-scoped PRD files without ranking them."""
    return _list_unsorted_task_prd_file_paths_in_directory(
        task_prd_directory_path=worktree_dir_path / "tasks",
        task_id_str=task_id_str,
    )


def _list_unsorted_task_prd_file_paths_in_directory(
    task_prd_directory_path: Path,
    task_id_str: str,
) -> list[Path]:
    """Collect task-scoped PRD files from one concrete directory."""
    if not task_prd_directory_path.exists():
        return []

    task_prd_candidate_list: list[Path] = []
    for task_prd_file_path in task_prd_directory_path.glob("*.md"):
        if _is_task_prd_candidate_file_name(task_prd_file_path.name, task_id_str):
            task_prd_candidate_list.append(task_prd_file_path)
    return task_prd_candidate_list


def _list_readable_task_prd_file_paths_in_directory(
    task_prd_directory_path: Path,
    task_id_str: str,
) -> list[Path]:
    """List readable task PRDs from one concrete directory."""
    ranked_prd_file_path_list = _list_ranked_task_prd_file_paths_in_directory(
        task_prd_directory_path=task_prd_directory_path,
        task_id_str=task_id_str,
    )
    return [
        task_prd_file_path
        for task_prd_file_path in ranked_prd_file_path_list
        if _is_readable_task_prd_file_path(
            task_prd_file_path=task_prd_file_path,
            task_id_str=task_id_str,
        )
    ]


def _pick_latest_prd_file_path(candidate_prd_file_path_list: list[Path]) -> Path:
    """Pick the most recently modified PRD file from a candidate list."""

    def _sort_key(task_prd_file_path: Path) -> tuple[int, float, str]:
        try:
            last_modified_timestamp = task_prd_file_path.stat().st_mtime
        except OSError:
            last_modified_timestamp = -1.0
        timestamp_sort_key_int = _extract_prd_timestamp_sort_key_int(
            task_prd_file_path.name
        )
        return (
            timestamp_sort_key_int,
            last_modified_timestamp,
            task_prd_file_path.name,
        )

    return max(candidate_prd_file_path_list, key=_sort_key)


def _repair_task_prd_file_candidates(
    candidate_prd_file_path_list: list[Path],
    *,
    task_id_str: str,
    task_title_str: str,
    reference_datetime: datetime | None = None,
) -> TaskPrdFileCorrectionResult:
    """Repair one PRD candidate set into a valid semantic filename."""
    if not candidate_prd_file_path_list:
        return TaskPrdFileCorrectionResult(resolved_file_path=None)

    source_prd_file_path = _pick_latest_prd_file_path(candidate_prd_file_path_list)
    source_prd_markdown_text = ""
    try:
        source_prd_markdown_text = source_prd_file_path.read_text(encoding="utf-8")
    except OSError:
        source_prd_markdown_text = ""

    semantic_slug_str, naming_source_str = _build_semantic_slug_from_available_text(
        task_id_str=task_id_str,
        task_title_str=task_title_str,
        prd_markdown_text=source_prd_markdown_text,
    )
    if semantic_slug_str == "":
        return TaskPrdFileCorrectionResult(resolved_file_path=None)

    target_prd_file_path = source_prd_file_path.parent / (
        f"{build_task_prd_timestamp_prefix(reference_datetime)}"
        f"-prd-{semantic_slug_str}.md"
    )
    if target_prd_file_path == source_prd_file_path:
        return TaskPrdFileCorrectionResult(
            resolved_file_path=source_prd_file_path,
            semantic_slug_str=semantic_slug_str,
            naming_source_str=naming_source_str,
        )

    if target_prd_file_path.exists():
        try:
            source_prd_file_path.unlink()
        except OSError:
            return TaskPrdFileCorrectionResult(resolved_file_path=None)
    else:
        source_prd_file_path.replace(target_prd_file_path)

    return TaskPrdFileCorrectionResult(
        resolved_file_path=target_prd_file_path,
        renamed_from_path=source_prd_file_path,
        semantic_slug_str=semantic_slug_str,
        naming_source_str=naming_source_str,
    )


def _build_semantic_slug_from_available_text(
    *,
    task_id_str: str,
    task_title_str: str,
    prd_markdown_text: str,
) -> tuple[str, str]:
    """Resolve the best semantic slug from PRD metadata and task context."""
    for naming_source_str, raw_candidate_text in (
        (
            "ai_summary",
            _extract_prd_metadata_value(prd_markdown_text, "需求名称（AI 归纳）"),
        ),
        (
            "original_title",
            _extract_prd_metadata_value(prd_markdown_text, "原始需求标题"),
        ),
        ("task_title", task_title_str),
    ):
        normalized_slug_str = normalize_task_prd_requirement_slug(raw_candidate_text)
        if is_valid_task_prd_semantic_slug(normalized_slug_str, task_id_str):
            return normalized_slug_str, naming_source_str

    fallback_slug_str = normalize_task_prd_requirement_slug("需求文档")
    return fallback_slug_str, "default_fallback"


def _truncate_task_prd_slug_to_max_bytes(
    normalized_slug_str: str,
    *,
    max_bytes_int: int,
) -> str:
    """Trim a normalized slug to a UTF-8 byte limit without splitting codepoints."""
    if len(normalized_slug_str.encode("utf-8")) <= max_bytes_int:
        return normalized_slug_str

    truncated_character_list: list[str] = []
    current_byte_count_int = 0
    for raw_character in normalized_slug_str:
        character_byte_count_int = len(raw_character.encode("utf-8"))
        if current_byte_count_int + character_byte_count_int > max_bytes_int:
            break
        truncated_character_list.append(raw_character)
        current_byte_count_int += character_byte_count_int

    return "".join(truncated_character_list).strip("-")


def _looks_like_interleaved_short_random_identifier(normalized_slug_str: str) -> bool:
    """Detect short random-like identifiers that are not semantic requirement names.

    This focuses on short single-token ASCII slugs such as ``k9m2qz`` or
    ``a1b2c`` where digits appear in multiple separate clusters. Semantic
    version-like slugs such as ``ios17`` remain allowed.

    Args:
        normalized_slug_str: Normalized candidate slug text.

    Returns:
        bool: ``True`` when the slug still looks like a short random identifier.
    """
    if not _ASCII_ALNUM_ONLY_PATTERN.fullmatch(normalized_slug_str):
        return False

    slug_length_int = len(normalized_slug_str)
    if slug_length_int < 5 or slug_length_int > 8:
        return False

    digit_count_int = sum(
        raw_character.isdigit() for raw_character in normalized_slug_str
    )
    letter_count_int = slug_length_int - digit_count_int
    if digit_count_int < 2 or letter_count_int < 2:
        return False

    digit_cluster_count_int = 0
    previous_character_was_digit_bool = False
    for raw_character in normalized_slug_str:
        current_character_is_digit_bool = raw_character.isdigit()
        if current_character_is_digit_bool and not previous_character_was_digit_bool:
            digit_cluster_count_int += 1
        previous_character_was_digit_bool = current_character_is_digit_bool

    return digit_cluster_count_int >= 2


def _extract_prd_metadata_value(
    prd_markdown_text: str,
    field_name_str: str,
) -> str:
    """Extract one top-level PRD metadata value from Markdown text."""
    metadata_pattern = re.compile(
        rf"^\s*(?:[-*]\s*)?(?:\*\*)?{re.escape(field_name_str)}(?:\*\*)?\s*[：:]\s*(.+?)\s*$",
        re.MULTILINE,
    )
    metadata_match = metadata_pattern.search(prd_markdown_text)
    if metadata_match is None:
        return ""

    metadata_value_str = metadata_match.group(1).strip()
    return _MARKDOWN_INLINE_WRAPPER_PATTERN.sub("", metadata_value_str).strip()


def _extract_semantic_slug_from_file_name(
    file_name_str: str,
    task_id_str: str,
) -> str | None:
    """Extract the semantic slug portion from a valid PRD filename."""
    timestamped_file_name_match = _TASK_PRD_TIMESTAMPED_FILE_NAME_PATTERN.fullmatch(
        file_name_str
    )
    if timestamped_file_name_match is not None:
        return timestamped_file_name_match.group("slug")

    if not _TASK_PRD_LEGACY_SEMANTIC_FILE_NAME_PATTERN.fullmatch(file_name_str):
        return None
    task_prd_file_prefix = build_task_prd_file_prefix(task_id_str)
    legacy_prefix_text = f"{task_prd_file_prefix}-"
    if not file_name_str.startswith(legacy_prefix_text):
        return None
    return file_name_str[len(legacy_prefix_text) : -len(".md")]


def _extract_prd_timestamp_sort_key_int(file_name_str: str) -> int:
    """Extract a sortable timestamp key from a PRD filename."""
    timestamped_file_name_match = _TASK_PRD_TIMESTAMPED_FILE_NAME_PATTERN.fullmatch(
        file_name_str
    )
    if timestamped_file_name_match is None:
        return 0
    timestamp_text = timestamped_file_name_match.group("timestamp")
    try:
        return int(timestamp_text)
    except ValueError:
        return 0


def _is_task_prd_file_name(file_name_str: str, task_id_str: str) -> bool:
    """Return whether a filename looks like a task PRD file."""
    if is_valid_task_prd_semantic_file_name(file_name_str, task_id_str):
        return True
    if is_valid_task_prd_legacy_semantic_file_name(file_name_str, task_id_str):
        return True
    if _TASK_PRD_LEGACY_FIXED_FILE_NAME_PATTERN.fullmatch(file_name_str):
        return True
    return False


def _is_task_prd_candidate_file_name(file_name_str: str, task_id_str: str) -> bool:
    """Return whether a filename could be a PRD candidate for repair."""
    if _TASK_PRD_TIMESTAMPED_FILE_NAME_PATTERN.fullmatch(file_name_str):
        return True
    if _TASK_PRD_LEGACY_FIXED_FILE_NAME_PATTERN.fullmatch(file_name_str):
        return True
    legacy_prefix_text = f"prd-{task_id_str[:8]}-"
    if file_name_str.startswith(legacy_prefix_text) and file_name_str.endswith(".md"):
        return True
    return False
