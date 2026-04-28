"""Canonical completion checklist generation and confirmation validation.

This module keeps completion checklist business rules in the service layer so
the preview endpoint and completion mutation endpoints share the same source of
truth.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from sqlalchemy.orm import Session

from backend.dsl.models.enums import DevLogStateTag
from backend.dsl.models.task import Task
from backend.dsl.schemas.dev_log_schema import DevLogCreateSchema
from backend.dsl.schemas.task_schema import (
    TaskCompletionChecklistItemSchema,
    TaskCompletionChecklistMode,
    TaskCompletionChecklistResponseSchema,
    TaskCompletionConfirmationSchema,
)
from backend.dsl.services.log_service import LogService
from backend.dsl.services.prd_file_service import find_task_readable_prd_file_path
from backend.dsl.services.task_service import TaskService

_MAX_DISPLAYED_CHECKLIST_ITEMS = 5
_DIRECT_PRD_ITEM_LIMIT_BEFORE_SUMMARY = 3
_DIRECT_PRD_ITEM_COUNT_WITH_SUMMARY = 2
_PRD_ACCEPTANCE_SOURCE = "prd_acceptance_checklist"
_SYSTEM_SAFETY_SOURCE = "system_safety"
_PRD_ACCEPTANCE_GROUP = "PRD Acceptance Checklist"
_SYSTEM_SAFETY_GROUP = "Completion Safety"
_DEFAULT_ACCEPTANCE_HEADING = "General Acceptance"
_HEADING_PATTERN = re.compile(r"^(?P<markers>#{1,6})\s+(?P<title>.+?)\s*$")
_CHECKBOX_PATTERN = re.compile(r"^\s*[-*]\s+\[(?: |x|X)\]\s+(?P<label>.+?)\s*$")
_HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->")
_NON_ALNUM_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
_ACCEPTANCE_HEADING_PRIORITY_LIST = [
    "Behavior Acceptance",
    "API Acceptance",
    "Validation Acceptance",
    "Architecture Acceptance",
    "Documentation Acceptance",
    "Dependency Acceptance",
]
_ACCEPTANCE_HEADING_PRIORITY_MAP = {
    heading_text.lower(): heading_index
    for heading_index, heading_text in enumerate(_ACCEPTANCE_HEADING_PRIORITY_LIST)
}


@dataclass(frozen=True, slots=True)
class PrdAcceptanceChecklistCandidate:
    """Parsed PRD acceptance checklist candidate.

    Attributes:
        heading_text: Heading that owns the checklist item.
        label_text: Raw checklist label from the PRD.
        heading_order_index: First-seen order of the heading inside the section.
        item_order_index: First-seen order of the checklist item inside the PRD.
    """

    heading_text: str
    label_text: str
    heading_order_index: int
    item_order_index: int


class TaskCompletionChecklistValidationError(ValueError):
    """Validation error raised when a completion confirmation is not acceptable.

    Attributes:
        status_code_int: HTTP status code the route should expose.
        refresh_required_bool: Whether the client should refetch the checklist.
        missing_checklist_item_id_list: Required item IDs missing from the request.
    """

    def __init__(
        self,
        message_text: str,
        *,
        status_code_int: int = 422,
        refresh_required_bool: bool = False,
        missing_checklist_item_id_list: list[str] | None = None,
    ) -> None:
        """Initialize a validation error.

        Args:
            message_text: Human-readable validation failure.
            status_code_int: HTTP status code the API route should return.
            refresh_required_bool: Whether the frontend should refresh preview data.
            missing_checklist_item_id_list: Missing required checklist item IDs.
        """
        super().__init__(message_text)
        self.status_code_int = status_code_int
        self.refresh_required_bool = refresh_required_bool
        self.missing_checklist_item_id_list = missing_checklist_item_id_list or []


def _normalize_key_text(raw_text: str) -> str:
    """Normalize text for deterministic comparison.

    Args:
        raw_text: Raw text to normalize.

    Returns:
        str: Lowercase, whitespace-normalized comparison key.
    """
    normalized_text = unicodedata.normalize("NFKC", raw_text).strip().lower()
    without_comment_text = _HTML_COMMENT_PATTERN.sub("", normalized_text)
    return re.sub(r"\s+", " ", without_comment_text).strip(" :#")


def _build_slug_text(raw_text: str) -> str:
    """Build a compact ASCII slug for stable item IDs.

    Args:
        raw_text: Raw text to slugify.

    Returns:
        str: Stable ASCII slug, or ``item`` when text has no ASCII tokens.
    """
    normalized_text = unicodedata.normalize("NFKD", raw_text).encode(
        "ascii",
        "ignore",
    )
    ascii_text = normalized_text.decode("ascii").lower()
    compacted_text = _NON_ALNUM_SLUG_PATTERN.sub("-", ascii_text).strip("-")
    return compacted_text[:64].strip("-") or "item"


def _strip_markdown_label_noise(raw_label_text: str) -> str:
    """Remove Markdown decoration that should not affect labels or signatures.

    Args:
        raw_label_text: Raw checkbox label.

    Returns:
        str: Cleaned label text.
    """
    without_comment_text = _HTML_COMMENT_PATTERN.sub("", raw_label_text)
    return re.sub(r"\s+", " ", without_comment_text).strip()


def _is_acceptance_section_heading(heading_text: str) -> bool:
    """Return whether a heading starts the PRD acceptance checklist section.

    Args:
        heading_text: Heading text without leading ``#`` markers.

    Returns:
        bool: ``True`` when this heading names an acceptance checklist section.
    """
    normalized_heading_text = _normalize_key_text(heading_text)
    return normalized_heading_text.endswith("acceptance checklist") or (
        "acceptance checklist" in normalized_heading_text
    )


def _normalize_acceptance_heading(raw_heading_text: str) -> str:
    """Normalize a PRD acceptance subsection heading for display.

    Args:
        raw_heading_text: Raw heading text.

    Returns:
        str: Clean heading text.
    """
    cleaned_heading_text = _strip_markdown_label_noise(raw_heading_text).rstrip(":")
    return cleaned_heading_text or _DEFAULT_ACCEPTANCE_HEADING


def _looks_like_acceptance_subheading_line(raw_line_text: str) -> bool:
    """Return whether a plain line should be treated as an acceptance heading.

    Args:
        raw_line_text: Raw markdown line.

    Returns:
        bool: ``True`` for conventional ``Architecture Acceptance:`` style lines.
    """
    stripped_line_text = raw_line_text.strip()
    if not stripped_line_text.endswith(":"):
        return False
    normalized_line_text = _normalize_key_text(stripped_line_text.rstrip(":"))
    return normalized_line_text.endswith(" acceptance")


def _extract_prd_acceptance_candidates(
    prd_markdown_text: str,
) -> list[PrdAcceptanceChecklistCandidate]:
    """Extract checkbox candidates from a PRD Acceptance Checklist section.

    Args:
        prd_markdown_text: Full PRD Markdown content.

    Returns:
        list[PrdAcceptanceChecklistCandidate]: Parsed candidate items in document
            order before priority sorting.
    """
    is_inside_acceptance_section_bool = False
    acceptance_heading_level_int = 0
    current_heading_text = _DEFAULT_ACCEPTANCE_HEADING
    heading_order_map: dict[str, int] = {current_heading_text: 0}
    candidate_item_list: list[PrdAcceptanceChecklistCandidate] = []
    is_inside_fenced_code_block_bool = False

    for raw_line_text in prd_markdown_text.splitlines():
        stripped_line_text = raw_line_text.strip()
        if stripped_line_text.startswith("```"):
            is_inside_fenced_code_block_bool = not is_inside_fenced_code_block_bool
            continue
        if is_inside_fenced_code_block_bool:
            continue

        heading_match = _HEADING_PATTERN.match(stripped_line_text)
        if heading_match is not None:
            heading_level_int = len(heading_match.group("markers"))
            heading_text = _normalize_acceptance_heading(heading_match.group("title"))
            if _is_acceptance_section_heading(heading_text):
                is_inside_acceptance_section_bool = True
                acceptance_heading_level_int = heading_level_int
                current_heading_text = _DEFAULT_ACCEPTANCE_HEADING
                continue
            if (
                is_inside_acceptance_section_bool
                and heading_level_int <= acceptance_heading_level_int
            ):
                break
            if is_inside_acceptance_section_bool:
                current_heading_text = heading_text
                heading_order_map.setdefault(
                    current_heading_text,
                    len(heading_order_map),
                )
            continue

        if not is_inside_acceptance_section_bool:
            continue

        if _looks_like_acceptance_subheading_line(stripped_line_text):
            current_heading_text = _normalize_acceptance_heading(stripped_line_text)
            heading_order_map.setdefault(current_heading_text, len(heading_order_map))
            continue

        checkbox_match = _CHECKBOX_PATTERN.match(raw_line_text)
        if checkbox_match is None:
            continue

        cleaned_label_text = _strip_markdown_label_noise(checkbox_match.group("label"))
        if not cleaned_label_text:
            continue

        candidate_item_list.append(
            PrdAcceptanceChecklistCandidate(
                heading_text=current_heading_text,
                label_text=cleaned_label_text,
                heading_order_index=heading_order_map[current_heading_text],
                item_order_index=len(candidate_item_list),
            )
        )

    return candidate_item_list


def _sort_and_deduplicate_prd_candidates(
    candidate_item_list: list[PrdAcceptanceChecklistCandidate],
) -> list[PrdAcceptanceChecklistCandidate]:
    """Sort PRD candidates by the fixed acceptance-heading priority.

    Args:
        candidate_item_list: Parsed candidate items.

    Returns:
        list[PrdAcceptanceChecklistCandidate]: Deduplicated and priority-sorted
            candidate items.
    """
    unique_candidate_item_list: list[PrdAcceptanceChecklistCandidate] = []
    seen_candidate_key_set: set[tuple[str, str]] = set()
    for candidate_item in candidate_item_list:
        candidate_key_tuple = (
            _normalize_key_text(candidate_item.heading_text),
            _normalize_key_text(candidate_item.label_text),
        )
        if candidate_key_tuple in seen_candidate_key_set:
            continue
        seen_candidate_key_set.add(candidate_key_tuple)
        unique_candidate_item_list.append(candidate_item)

    return sorted(
        unique_candidate_item_list,
        key=lambda candidate_item: (
            _ACCEPTANCE_HEADING_PRIORITY_MAP.get(
                _normalize_key_text(candidate_item.heading_text),
                len(_ACCEPTANCE_HEADING_PRIORITY_MAP)
                + candidate_item.heading_order_index,
            ),
            candidate_item.item_order_index,
        ),
    )


def _build_prd_item_label(candidate_item: PrdAcceptanceChecklistCandidate) -> str:
    """Build the displayed label for one direct PRD checklist item.

    Args:
        candidate_item: PRD candidate item.

    Returns:
        str: Display label containing the acceptance group and item text.
    """
    if candidate_item.heading_text == _DEFAULT_ACCEPTANCE_HEADING:
        return candidate_item.label_text
    return f"{candidate_item.heading_text}: {candidate_item.label_text}"


def _build_direct_prd_checklist_item(
    candidate_item: PrdAcceptanceChecklistCandidate,
    displayed_index_int: int,
) -> TaskCompletionChecklistItemSchema:
    """Convert one PRD candidate into a displayed checklist item.

    Args:
        candidate_item: PRD candidate item.
        displayed_index_int: Display order within the PRD checklist subset.

    Returns:
        TaskCompletionChecklistItemSchema: Displayed checklist item.
    """
    item_label_text = _build_prd_item_label(candidate_item)
    item_slug_text = _build_slug_text(
        f"{candidate_item.heading_text} {candidate_item.label_text}"
    )
    return TaskCompletionChecklistItemSchema(
        item_id=f"prd-{displayed_index_int + 1}-{item_slug_text}",
        label=item_label_text,
        group=_PRD_ACCEPTANCE_GROUP,
        required=True,
        source=_PRD_ACCEPTANCE_SOURCE,
        covered_source_item_count=1,
    )


def _build_prd_summary_checklist_item(
    remaining_candidate_item_list: list[PrdAcceptanceChecklistCandidate],
) -> TaskCompletionChecklistItemSchema:
    """Build the PRD summary checklist item for long acceptance sections.

    Args:
        remaining_candidate_item_list: Candidate items represented by the summary.

    Returns:
        TaskCompletionChecklistItemSchema: Summary checklist item.
    """
    remaining_item_count_int = len(remaining_candidate_item_list)
    remaining_heading_count_int = len(
        {
            _normalize_key_text(candidate_item.heading_text)
            for candidate_item in remaining_candidate_item_list
        }
    )
    return TaskCompletionChecklistItemSchema(
        item_id=(
            "prd-summary-"
            f"{remaining_item_count_int}-items-{remaining_heading_count_int}-headings"
        ),
        label=(
            "Review remaining PRD acceptance coverage "
            f"({remaining_item_count_int} items across "
            f"{remaining_heading_count_int} headings)."
        ),
        group=_PRD_ACCEPTANCE_GROUP,
        required=True,
        source=_PRD_ACCEPTANCE_SOURCE,
        covered_source_item_count=remaining_item_count_int,
    )


def _build_prd_checklist_items(
    prd_markdown_text: str,
) -> list[TaskCompletionChecklistItemSchema]:
    """Build displayed PRD checklist items from Markdown.

    Args:
        prd_markdown_text: Full PRD Markdown content.

    Returns:
        list[TaskCompletionChecklistItemSchema]: Zero to three displayed PRD
            items, with long checklists summarized deterministically.
    """
    sorted_candidate_item_list = _sort_and_deduplicate_prd_candidates(
        _extract_prd_acceptance_candidates(prd_markdown_text)
    )
    if len(sorted_candidate_item_list) <= _DIRECT_PRD_ITEM_LIMIT_BEFORE_SUMMARY:
        return [
            _build_direct_prd_checklist_item(
                candidate_item=candidate_item,
                displayed_index_int=displayed_index_int,
            )
            for displayed_index_int, candidate_item in enumerate(
                sorted_candidate_item_list
            )
        ]

    direct_candidate_item_list = sorted_candidate_item_list[
        :_DIRECT_PRD_ITEM_COUNT_WITH_SUMMARY
    ]
    remaining_candidate_item_list = sorted_candidate_item_list[
        _DIRECT_PRD_ITEM_COUNT_WITH_SUMMARY:
    ]
    direct_checklist_item_list = [
        _build_direct_prd_checklist_item(
            candidate_item=candidate_item,
            displayed_index_int=displayed_index_int,
        )
        for displayed_index_int, candidate_item in enumerate(direct_candidate_item_list)
    ]
    return [
        *direct_checklist_item_list,
        _build_prd_summary_checklist_item(remaining_candidate_item_list),
    ]


def _build_mode_system_checklist_items(
    checklist_mode: TaskCompletionChecklistMode,
) -> list[TaskCompletionChecklistItemSchema]:
    """Build mode-specific system safety checklist items.

    Args:
        checklist_mode: Completion mode.

    Returns:
        list[TaskCompletionChecklistItemSchema]: Ordered system safety items.
    """
    if checklist_mode == "manual_complete":
        system_item_tuple_list = [
            (
                "system-manual-timeline-reviewed",
                "Review latest Timeline and result evidence before manual completion.",
            ),
            (
                "system-manual-missing-branch-intentional",
                "Confirm the missing task branch is intentional after manual merge or cleanup.",
            ),
            (
                "system-manual-archive-understood",
                "Understand this will close the task into the completed archive without rerunning Git finalization.",
            ),
        ]
    else:
        system_item_tuple_list = [
            (
                "system-complete-timeline-reviewed",
                "Review latest Timeline and result evidence before completing.",
            ),
            (
                "system-complete-worktree-ready",
                "Confirm worktree/code state is ready for Git finalization.",
            ),
            (
                "system-complete-git-finalization-understood",
                "Understand Complete will run git add, commit if needed, rebase, merge, and cleanup.",
            ),
        ]

    return [
        TaskCompletionChecklistItemSchema(
            item_id=item_id_text,
            label=item_label_text,
            group=_SYSTEM_SAFETY_GROUP,
            required=True,
            source=_SYSTEM_SAFETY_SOURCE,
            covered_source_item_count=None,
        )
        for item_id_text, item_label_text in system_item_tuple_list
    ]


def _build_checklist_signature(
    *,
    task_id_str: str,
    checklist_mode: TaskCompletionChecklistMode,
    checklist_item_list: list[TaskCompletionChecklistItemSchema],
) -> str:
    """Build the canonical checklist signature.

    Args:
        task_id_str: Task ID.
        checklist_mode: Completion mode.
        checklist_item_list: Ordered displayed checklist items.

    Returns:
        str: ``sha256:`` signature over the ordered checklist contract.
    """
    signature_payload_dict = {
        "task_id": task_id_str,
        "mode": checklist_mode,
        "items": [
            {
                "item_id": checklist_item.item_id,
                "label": checklist_item.label,
                "source": checklist_item.source,
                "covered_source_item_count": (checklist_item.covered_source_item_count),
            }
            for checklist_item in checklist_item_list
        ],
    }
    serialized_payload_text = json.dumps(
        signature_payload_dict,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    signature_digest_text = hashlib.sha256(
        serialized_payload_text.encode("utf-8")
    ).hexdigest()
    return f"sha256:{signature_digest_text}"


def _read_task_prd_markdown_if_available(task_obj: Task) -> str | None:
    """Read the task PRD Markdown when a readable PRD exists.

    Args:
        task_obj: Task whose worktree may contain a PRD file.

    Returns:
        str | None: PRD Markdown text, or ``None`` when unavailable.
    """
    if not task_obj.worktree_path:
        return None

    worktree_dir_path = Path(task_obj.worktree_path)
    if not worktree_dir_path.exists():
        return None

    task_prd_file_path = find_task_readable_prd_file_path(
        worktree_dir_path,
        task_obj.id,
    )
    if task_prd_file_path is None:
        return None

    try:
        return task_prd_file_path.read_text(encoding="utf-8")
    except OSError:
        return None


class TaskCompletionChecklistService:
    """Service for completion checklist preview, validation, and audit logs."""

    @staticmethod
    def build_completion_checklist(
        db_session: Session,
        task_id_str: str,
        checklist_mode: TaskCompletionChecklistMode,
    ) -> TaskCompletionChecklistResponseSchema | None:
        """Build the canonical checklist for one task completion attempt.

        Args:
            db_session: Database session.
            task_id_str: Task ID.
            checklist_mode: Completion mode.

        Returns:
            TaskCompletionChecklistResponseSchema | None: Checklist response, or
                ``None`` when the task does not exist.

        Raises:
            TaskCompletionChecklistValidationError: Raised when the task is not
                eligible for the requested completion mode.
        """
        task_obj = TaskService.get_task_by_id(db_session, task_id_str)
        if task_obj is None:
            return None

        task_branch_health = TaskService.build_task_branch_health(task_obj)
        if checklist_mode == "manual_complete":
            try:
                TaskService.validate_manual_completion_candidate(
                    task_obj,
                    task_branch_health,
                )
            except ValueError as manual_completion_error:
                raise TaskCompletionChecklistValidationError(
                    str(manual_completion_error)
                ) from manual_completion_error
        else:
            if task_branch_health.manual_completion_candidate:
                raise TaskCompletionChecklistValidationError(
                    "Task branch is missing. Review the timeline/code state and use "
                    "mode=manual_complete or /manual-complete instead of the "
                    "normal Complete flow."
                )
            if not task_obj.worktree_path:
                raise TaskCompletionChecklistValidationError(
                    "Task has no worktree_path. Complete is only available for "
                    "worktree-backed tasks."
                )

        prd_markdown_text = _read_task_prd_markdown_if_available(task_obj)
        prd_checklist_item_list = (
            _build_prd_checklist_items(prd_markdown_text)
            if prd_markdown_text is not None
            else []
        )
        system_checklist_item_list = _build_mode_system_checklist_items(checklist_mode)
        displayed_checklist_item_list = [
            *prd_checklist_item_list,
            *system_checklist_item_list,
        ][:_MAX_DISPLAYED_CHECKLIST_ITEMS]

        if len(displayed_checklist_item_list) > _MAX_DISPLAYED_CHECKLIST_ITEMS:
            raise TaskCompletionChecklistValidationError(
                "Completion checklist generation exceeded the maximum item count."
            )

        checklist_signature_text = _build_checklist_signature(
            task_id_str=task_id_str,
            checklist_mode=checklist_mode,
            checklist_item_list=displayed_checklist_item_list,
        )
        return TaskCompletionChecklistResponseSchema(
            task_id=task_id_str,
            mode=checklist_mode,
            checklist_signature=checklist_signature_text,
            items=displayed_checklist_item_list,
        )

    @staticmethod
    def validate_completion_confirmation(
        db_session: Session,
        task_id_str: str,
        expected_checklist_mode: TaskCompletionChecklistMode,
        confirmation_schema: TaskCompletionConfirmationSchema | None,
    ) -> TaskCompletionChecklistResponseSchema | None:
        """Validate that the submitted checklist confirmation is complete.

        Args:
            db_session: Database session.
            task_id_str: Task ID.
            expected_checklist_mode: Completion mode required by the endpoint.
            confirmation_schema: Request body submitted by the frontend.

        Returns:
            TaskCompletionChecklistResponseSchema | None: Regenerated canonical
                checklist, or ``None`` when the task does not exist.

        Raises:
            TaskCompletionChecklistValidationError: Raised when the confirmation
                payload is missing, stale, wrong-mode, or incomplete.
        """
        if confirmation_schema is None:
            raise TaskCompletionChecklistValidationError(
                "Completion checklist confirmation payload is required."
            )

        if confirmation_schema.checklist_mode != expected_checklist_mode:
            raise TaskCompletionChecklistValidationError(
                "Completion checklist mode does not match this endpoint."
            )

        checklist_response = TaskCompletionChecklistService.build_completion_checklist(
            db_session=db_session,
            task_id_str=task_id_str,
            checklist_mode=expected_checklist_mode,
        )
        if checklist_response is None:
            return None

        if len(checklist_response.items) > _MAX_DISPLAYED_CHECKLIST_ITEMS:
            raise TaskCompletionChecklistValidationError(
                "Completion checklist generation exceeded the maximum item count."
            )

        if (
            confirmation_schema.checklist_signature
            != checklist_response.checklist_signature
        ):
            raise TaskCompletionChecklistValidationError(
                "Completion checklist is stale. Refresh the checklist and confirm it again.",
                status_code_int=409,
                refresh_required_bool=True,
            )

        submitted_item_id_set = set(confirmation_schema.confirmed_checklist_item_ids)
        missing_required_item_id_list = [
            checklist_item.item_id
            for checklist_item in checklist_response.items
            if checklist_item.required
            and checklist_item.item_id not in submitted_item_id_set
        ]
        if missing_required_item_id_list:
            raise TaskCompletionChecklistValidationError(
                "All displayed completion checklist items must be confirmed.",
                missing_checklist_item_id_list=missing_required_item_id_list,
            )

        return checklist_response

    @staticmethod
    def create_confirmation_audit_log(
        db_session: Session,
        task_obj: Task,
        checklist_response: TaskCompletionChecklistResponseSchema,
    ) -> str:
        """Persist a DevLog recording that the checklist was confirmed.

        Args:
            db_session: Database session.
            task_obj: Task being completed.
            checklist_response: Canonical checklist that was confirmed.

        Returns:
            str: Persisted audit log text.
        """
        audit_log_text = (
            "Completion checklist confirmed before task completion.\n"
            f"- mode: {checklist_response.mode}\n"
            f"- confirmed item count: {len(checklist_response.items)}\n"
            f"- checklist signature: {checklist_response.checklist_signature}"
        )
        LogService.create_log(
            db_session,
            DevLogCreateSchema(
                task_id=task_obj.id,
                text_content=audit_log_text,
                state_tag=DevLogStateTag.FIXED,
            ),
            task_obj.run_account_id,
        )
        return audit_log_text
