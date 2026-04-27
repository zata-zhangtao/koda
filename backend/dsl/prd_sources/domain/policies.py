"""Pure policies for PRD filenames, content, and pending path rules."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import PurePosixPath

from backend.dsl.prd_sources.domain.errors import (
    InvalidPrdContentError,
    UnsafePrdPathError,
)

TASK_PRD_REQUIREMENT_SLUG_MAX_LENGTH = 80
TASK_PRD_FILE_NAME_MAX_BYTES = 255
TASK_PRD_FILE_NAME_PREFIX_TEXT = "20260423-130500-prd-"
TASK_PRD_REQUIREMENT_SLUG_MAX_BYTES = TASK_PRD_FILE_NAME_MAX_BYTES - len(
    f"{TASK_PRD_FILE_NAME_PREFIX_TEXT}.md".encode("utf-8")
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


def build_task_prd_timestamp_prefix(
    reference_datetime: datetime | None = None,
) -> str:
    """Build the timestamp prefix used for PRD filenames.

    Args:
        reference_datetime: Optional timestamp reference. When omitted the
            current local time is used.

    Returns:
        str: Prefix in ``YYYYMMDD-HHMMSS`` format.
    """
    timestamp_reference_datetime = reference_datetime or datetime.now()
    return timestamp_reference_datetime.strftime("%Y%m%d-%H%M%S")


def build_task_prd_file_name(
    task_id_str: str,
    task_title_str: str,
    prd_markdown_text: str,
    *,
    reference_datetime: datetime | None = None,
) -> str:
    """Build a semantic task PRD filename from markdown and task context.

    Args:
        task_id_str: Task UUID string.
        task_title_str: Task title used as fallback.
        prd_markdown_text: PRD markdown content.

    Returns:
        str: Filename satisfying ``YYYYMMDD-HHMMSS-prd-<slug>.md``.
    """
    semantic_slug_str = build_semantic_slug_from_available_text(
        task_id_str=task_id_str,
        task_title_str=task_title_str,
        prd_markdown_text=prd_markdown_text,
    )
    timestamp_prefix_text = build_task_prd_timestamp_prefix(reference_datetime)
    return f"{timestamp_prefix_text}-prd-{semantic_slug_str}.md"


def build_task_draft_title_from_prd(
    prd_markdown_text: str,
    *,
    source_file_name_str: str | None = None,
) -> str:
    """Build a task draft title from PRD metadata and headings.

    Args:
        prd_markdown_text: Full PRD Markdown text.
        source_file_name_str: Optional source file name used as a fallback.

    Returns:
        str: Suggested task title.
    """
    candidate_text_tuple = (
        extract_prd_metadata_value(prd_markdown_text, "需求名称（AI 归纳）"),
        extract_prd_metadata_value(prd_markdown_text, "原始需求标题"),
        extract_first_markdown_heading(prd_markdown_text),
        _build_title_from_file_name(source_file_name_str),
        "Imported PRD",
    )
    for candidate_text in candidate_text_tuple:
        normalized_candidate_text = normalize_task_draft_text(candidate_text)
        if normalized_candidate_text:
            return normalized_candidate_text[:200]
    return "Imported PRD"


def build_task_draft_requirement_brief_from_prd(
    prd_markdown_text: str,
    *,
    fallback_title_str: str,
    max_length_int: int = 1200,
) -> str:
    """Build a compact task draft description from PRD Markdown.

    Args:
        prd_markdown_text: Full PRD Markdown text.
        fallback_title_str: Title used when no readable body exists.
        max_length_int: Maximum returned character count.

    Returns:
        str: Suggested task description.
    """
    description_line_list: list[str] = []
    inside_fenced_block_bool = False
    for raw_line_text in prd_markdown_text.splitlines():
        stripped_line_text = raw_line_text.strip()
        if stripped_line_text.startswith("```"):
            inside_fenced_block_bool = not inside_fenced_block_bool
            continue
        if inside_fenced_block_bool:
            continue
        if not stripped_line_text:
            if description_line_list and description_line_list[-1] != "":
                description_line_list.append("")
            continue
        if _is_prd_metadata_line(stripped_line_text):
            continue
        if stripped_line_text.startswith("#"):
            continue

        normalized_line_text = normalize_task_draft_text(stripped_line_text)
        if normalized_line_text:
            description_line_list.append(normalized_line_text)

        joined_description_text = "\n".join(description_line_list).strip()
        if len(joined_description_text) >= max_length_int:
            return joined_description_text[:max_length_int].strip()

    joined_description_text = "\n".join(description_line_list).strip()
    if joined_description_text:
        return joined_description_text[:max_length_int].strip()

    normalized_fallback_title = normalize_task_draft_text(fallback_title_str)
    return f"基于已选择 PRD 创建任务：{normalized_fallback_title or 'Imported PRD'}"


def extract_first_markdown_heading(prd_markdown_text: str) -> str:
    """Extract the first Markdown heading from a PRD document.

    Args:
        prd_markdown_text: Full PRD Markdown text.

    Returns:
        str: Heading text, or an empty string.
    """
    for markdown_line_text in prd_markdown_text.splitlines():
        stripped_line_text = markdown_line_text.strip()
        if stripped_line_text.startswith("#"):
            return stripped_line_text.lstrip("#").strip()
    return ""


def normalize_task_draft_text(raw_text: str | None) -> str:
    """Normalize a text field for task draft display.

    Args:
        raw_text: Raw text value.

    Returns:
        str: Trimmed text with collapsed horizontal whitespace.
    """
    if raw_text is None:
        return ""
    normalized_text = unicodedata.normalize("NFKC", raw_text)
    normalized_line_list = [
        re.sub(r"[ \t]+", " ", line_text).strip()
        for line_text in normalized_text.splitlines()
    ]
    return "\n".join(
        line_text for line_text in normalized_line_list if line_text
    ).strip("`*_ ")


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


def _build_title_from_file_name(source_file_name_str: str | None) -> str:
    """Build a readable fallback title from a file name."""
    if not source_file_name_str:
        return ""
    file_stem_text = source_file_name_str.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return file_stem_text.replace("-", " ").replace("_", " ")


def _is_prd_metadata_line(stripped_line_text: str) -> bool:
    """Return whether a line is one of the PRD metadata fields."""
    return bool(
        re.match(
            r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:需求名称（AI 归纳）|原始需求标题)(?:\*\*)?\s*[:：]",
            stripped_line_text,
        )
    )


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
