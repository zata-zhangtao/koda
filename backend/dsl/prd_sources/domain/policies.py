"""Pure policies for PRD filenames, content, and pending path rules."""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath

from backend.dsl.prd_sources.domain.errors import (
    InvalidPrdContentError,
    UnsafePrdPathError,
)

TASK_PRD_REQUIREMENT_SLUG_MAX_LENGTH = 80
TASK_PRD_FILE_NAME_MAX_BYTES = 255
TASK_PRD_REQUIREMENT_SLUG_MAX_BYTES = TASK_PRD_FILE_NAME_MAX_BYTES - len(
    "prd-12345678-.md".encode("utf-8")
)
MAX_PRD_MARKDOWN_BYTES = 2 * 1024 * 1024
WINDOWS_FORBIDDEN_FILENAME_CHAR_SET = set('<>:"/\\|?*')
ASCII_ALNUM_ONLY_PATTERN = re.compile(r"^[a-z0-9]+$")
HEX_ONLY_PATTERN = re.compile(r"^[0-9a-f]{6,}$")
UUID_LIKE_PATTERN = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4,})+$")


def build_task_prd_file_prefix(task_id_str: str) -> str:
    """Build the task-specific PRD filename prefix.

    Args:
        task_id_str: Task UUID string.

    Returns:
        str: Prefix such as ``prd-cf2b9461``.
    """
    return f"prd-{task_id_str[:8]}"


def build_task_prd_file_name(
    task_id_str: str,
    task_title_str: str,
    prd_markdown_text: str,
) -> str:
    """Build a semantic task PRD filename from markdown and task context.

    Args:
        task_id_str: Task UUID string.
        task_title_str: Task title used as fallback.
        prd_markdown_text: PRD markdown content.

    Returns:
        str: Filename satisfying ``prd-{task8}-<slug>.md``.
    """
    semantic_slug_str = build_semantic_slug_from_available_text(
        task_id_str=task_id_str,
        task_title_str=task_title_str,
        prd_markdown_text=prd_markdown_text,
    )
    return f"{build_task_prd_file_prefix(task_id_str)}-{semantic_slug_str}.md"


def build_semantic_slug_from_available_text(
    *,
    task_id_str: str,
    task_title_str: str,
    prd_markdown_text: str,
) -> str:
    """Resolve the best semantic slug from PRD metadata and task context.

    Args:
        task_id_str: Task UUID string.
        task_title_str: Task title used as fallback.
        prd_markdown_text: PRD markdown content.

    Returns:
        str: Safe semantic slug.
    """
    for raw_candidate_text in (
        extract_prd_metadata_value(prd_markdown_text, "需求名称（AI 归纳）"),
        extract_prd_metadata_value(prd_markdown_text, "原始需求标题"),
        task_title_str,
    ):
        normalized_slug_str = normalize_task_prd_requirement_slug(raw_candidate_text)
        if is_valid_task_prd_semantic_slug(normalized_slug_str, task_id_str):
            return normalized_slug_str

    return normalize_task_prd_requirement_slug("需求文档")


def extract_prd_metadata_value(prd_markdown_text: str, metadata_key_str: str) -> str:
    """Extract a simple Markdown metadata value.

    Args:
        prd_markdown_text: Full PRD markdown text.
        metadata_key_str: Metadata key to find.

    Returns:
        str: Extracted metadata value, or an empty string.
    """
    metadata_pattern = re.compile(
        rf"^\s*(?:[-*]\s*)?(?:\*\*)?{re.escape(metadata_key_str)}(?:\*\*)?\s*[:：]\s*(.+?)\s*$",
        re.MULTILINE,
    )
    metadata_match = metadata_pattern.search(prd_markdown_text)
    if metadata_match is None:
        return ""

    raw_metadata_value_str = metadata_match.group(1).strip()
    return raw_metadata_value_str.strip("`*_ ")


def normalize_task_prd_requirement_slug(
    raw_requirement_text: str,
    *,
    max_length_int: int = TASK_PRD_REQUIREMENT_SLUG_MAX_LENGTH,
    max_bytes_int: int = TASK_PRD_REQUIREMENT_SLUG_MAX_BYTES,
) -> str:
    """Normalize requirement text into a cross-platform-safe semantic slug.

    Args:
        raw_requirement_text: Raw requirement text or AI summary.
        max_length_int: Maximum slug length.
        max_bytes_int: Maximum UTF-8 byte length for the slug portion.

    Returns:
        str: Safe semantic slug that may preserve Chinese or other letters.
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
        unicode_category_str = unicodedata.category(raw_character)
        if unicode_category_str.startswith(("L", "N")):
            if pending_separator_bool and normalized_character_list:
                normalized_character_list.append("-")
            normalized_character_list.append(raw_character)
            pending_separator_bool = False
            continue

        if (
            raw_character.isspace()
            or raw_character in WINDOWS_FORBIDDEN_FILENAME_CHAR_SET
            or raw_character in {"-", "_", ".", ",", "(", ")", "[", "]", "{", "}"}
            or unicode_category_str.startswith(("P", "S", "C"))
        ):
            pending_separator_bool = True

    compacted_slug_text = re.sub(
        r"-{2,}",
        "-",
        "".join(normalized_character_list).strip("-"),
    )
    character_limited_slug_text = compacted_slug_text[:max_length_int].strip("-")
    return truncate_task_prd_slug_to_max_bytes(
        character_limited_slug_text,
        max_bytes_int=max_bytes_int,
    )


def is_valid_task_prd_semantic_slug(
    semantic_slug_str: str,
    task_id_str: str,
) -> bool:
    """Check whether a semantic PRD slug satisfies the non-random contract.

    Args:
        semantic_slug_str: Candidate semantic slug.
        task_id_str: Task UUID string.

    Returns:
        bool: ``True`` when the slug is non-empty and not random-like.
    """
    normalized_slug_str = normalize_task_prd_requirement_slug(semantic_slug_str)
    if normalized_slug_str == "":
        return False

    task_short_id_str = task_id_str[:8].lower()
    if normalized_slug_str == task_short_id_str:
        return False
    if HEX_ONLY_PATTERN.fullmatch(normalized_slug_str):
        return False
    if UUID_LIKE_PATTERN.fullmatch(normalized_slug_str):
        return False
    if looks_like_interleaved_short_random_identifier(normalized_slug_str):
        return False
    return True


def validate_pending_prd_relative_path(pending_relative_path_str: str) -> str:
    """Validate a workspace-relative pending PRD path.

    Args:
        pending_relative_path_str: Candidate path supplied by the client.

    Returns:
        str: Normalized POSIX relative path.

    Raises:
        UnsafePrdPathError: If the path is absolute, traverses parents, or is
            outside ``tasks/pending``.
        InvalidPrdContentError: If the file extension is not ``.md``.
    """
    pending_path = PurePosixPath(pending_relative_path_str)
    if pending_path.is_absolute() or ".." in pending_path.parts:
        raise UnsafePrdPathError("Pending PRD path must stay under tasks/pending.")
    if len(pending_path.parts) != 3 or pending_path.parts[:2] != ("tasks", "pending"):
        raise UnsafePrdPathError("Pending PRD path must be tasks/pending/<file>.md.")
    if pending_path.suffix.lower() != ".md":
        raise InvalidPrdContentError("Only Markdown PRD files are supported.")
    return pending_path.as_posix()


def validate_imported_prd_file(
    original_file_name_str: str,
    raw_file_size_int: int,
) -> None:
    """Validate an uploaded PRD file before decoding.

    Args:
        original_file_name_str: Browser-provided filename.
        raw_file_size_int: Uploaded byte length.

    Raises:
        InvalidPrdContentError: If the file is empty, too large, or not Markdown.
    """
    original_file_path = PurePosixPath(original_file_name_str)
    if original_file_path.suffix.lower() != ".md":
        raise InvalidPrdContentError("Only Markdown PRD files are supported.")
    if raw_file_size_int <= 0:
        raise InvalidPrdContentError("PRD file cannot be empty.")
    if raw_file_size_int > MAX_PRD_MARKDOWN_BYTES:
        raise InvalidPrdContentError("PRD file is larger than the supported limit.")


def validate_prd_markdown_text(prd_markdown_text: str) -> None:
    """Validate decoded PRD Markdown content.

    Args:
        prd_markdown_text: Decoded PRD content.

    Raises:
        InvalidPrdContentError: If the content is blank.
    """
    if prd_markdown_text.strip() == "":
        raise InvalidPrdContentError("PRD markdown content cannot be blank.")


def truncate_task_prd_slug_to_max_bytes(
    normalized_slug_str: str,
    *,
    max_bytes_int: int,
) -> str:
    """Trim a normalized slug to a UTF-8 byte limit without splitting codepoints.

    Args:
        normalized_slug_str: Safe slug text.
        max_bytes_int: Maximum UTF-8 byte length.

    Returns:
        str: Truncated slug.
    """
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


def looks_like_interleaved_short_random_identifier(normalized_slug_str: str) -> bool:
    """Detect short random-like ASCII identifiers with mixed letters and digits."""
    if not ASCII_ALNUM_ONLY_PATTERN.fullmatch(normalized_slug_str):
        return False
    if len(normalized_slug_str) < 6 or len(normalized_slug_str) > 12:
        return False
    has_letter_bool = any(
        raw_character.isalpha() for raw_character in normalized_slug_str
    )
    has_digit_bool = any(
        raw_character.isdigit() for raw_character in normalized_slug_str
    )
    return has_letter_bool and has_digit_bool
