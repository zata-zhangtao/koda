"""Service for generating semantic task worktree branch names."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any

from utils.settings import Config


@dataclass(frozen=True, slots=True)
class WorktreeBranchNamingResult:
    """Describe one resolved worktree branch naming decision.

    Attributes:
        branch_name_str: Final branch name used for worktree creation
        naming_source_str: Naming source label (`ai`, `title_fallback`, `legacy_fallback`)
        semantic_slug_str: Normalized semantic slug when available
    """

    branch_name_str: str
    naming_source_str: str
    semantic_slug_str: str | None = None


class WorktreeBranchNamingService:
    """Generate semantic task branch names with AI-first fallback logic."""

    _SEMANTIC_SLUG_MAX_LENGTH = 40

    @classmethod
    def build_task_branch_naming_result(
        cls,
        task_id_str: str,
        task_title_str: str,
        requirement_brief_str: str | None = None,
        recent_context_text_list: list[str] | None = None,
    ) -> WorktreeBranchNamingResult:
        """Resolve a task branch name with deterministic fallback.

        Args:
            task_id_str: Task UUID string
            task_title_str: Task title text
            requirement_brief_str: Optional requirement brief text
            recent_context_text_list: Optional recent task context snippets

        Returns:
            WorktreeBranchNamingResult: Final branch naming result
        """
        task_short_id_str = task_id_str[:8]
        ai_semantic_slug_str = cls._build_semantic_slug_with_ai(
            task_title_str=task_title_str,
            requirement_brief_str=requirement_brief_str,
            recent_context_text_list=recent_context_text_list,
        )
        if ai_semantic_slug_str:
            return WorktreeBranchNamingResult(
                branch_name_str=cls._build_branch_name(
                    task_short_id_str=task_short_id_str,
                    semantic_slug_str=ai_semantic_slug_str,
                ),
                naming_source_str="ai",
                semantic_slug_str=ai_semantic_slug_str,
            )

        local_fallback_slug_str = cls.normalize_semantic_slug(
            task_title_str,
            max_length_int=cls._SEMANTIC_SLUG_MAX_LENGTH,
        )
        if local_fallback_slug_str:
            return WorktreeBranchNamingResult(
                branch_name_str=cls._build_branch_name(
                    task_short_id_str=task_short_id_str,
                    semantic_slug_str=local_fallback_slug_str,
                ),
                naming_source_str="title_fallback",
                semantic_slug_str=local_fallback_slug_str,
            )

        return WorktreeBranchNamingResult(
            branch_name_str=cls._build_branch_name(
                task_short_id_str=task_short_id_str,
                semantic_slug_str=None,
            ),
            naming_source_str="legacy_fallback",
            semantic_slug_str=None,
        )

    @classmethod
    def normalize_semantic_slug(
        cls,
        raw_semantic_slug_text: str,
        *,
        max_length_int: int,
    ) -> str:
        """Normalize arbitrary text to a Git-safe semantic slug.

        Args:
            raw_semantic_slug_text: Raw semantic text to normalize
            max_length_int: Maximum output length

        Returns:
            str: Normalized slug, empty string when no valid token remains
        """
        lowered_slug_text = raw_semantic_slug_text.strip().lower()
        replaced_slug_text = re.sub(r"[^a-z0-9]+", "-", lowered_slug_text)
        compacted_slug_text = re.sub(r"-{2,}", "-", replaced_slug_text).strip("-")
        if max_length_int <= 0:
            return ""
        truncated_slug_text = compacted_slug_text[:max_length_int].strip("-")
        return truncated_slug_text

    @classmethod
    def _build_semantic_slug_with_ai(
        cls,
        *,
        task_title_str: str,
        requirement_brief_str: str | None,
        recent_context_text_list: list[str] | None,
    ) -> str | None:
        """Try to generate a semantic slug from the configured AI model.

        Args:
            task_title_str: Task title text
            requirement_brief_str: Optional requirement brief text
            recent_context_text_list: Optional recent context snippets

        Returns:
            str | None: Normalized slug when successful; otherwise None
        """
        if not Config.WORKTREE_BRANCH_AI_NAMING_ENABLED:
            return None

        from ai_agent.utils.model_loader import create_chat_model

        branch_naming_prompt_text = cls._build_branch_naming_prompt_text(
            task_title_str=task_title_str,
            requirement_brief_str=requirement_brief_str,
            recent_context_text_list=recent_context_text_list,
        )
        if not branch_naming_prompt_text:
            return None

        try:
            chat_model_obj = create_chat_model(
                Config.WORKTREE_BRANCH_AI_MODEL,
                temperature=0.0,
                client_kwargs={
                    "timeout": Config.WORKTREE_BRANCH_AI_TIMEOUT_SECONDS,
                },
            )
            raw_ai_result_text = cls._invoke_model_with_timeout(
                chat_model_obj=chat_model_obj,
                prompt_text=branch_naming_prompt_text,
                timeout_seconds_float=Config.WORKTREE_BRANCH_AI_TIMEOUT_SECONDS,
            )
        except Exception:
            return None

        normalized_slug_text = cls.normalize_semantic_slug(
            raw_ai_result_text,
            max_length_int=cls._SEMANTIC_SLUG_MAX_LENGTH,
        )
        if not normalized_slug_text:
            return None
        return normalized_slug_text

    @staticmethod
    def _invoke_model_with_timeout(
        *,
        chat_model_obj: Any,
        prompt_text: str,
        timeout_seconds_float: float,
    ) -> str:
        """Invoke a model with a hard timeout and extract plain text output.

        Args:
            chat_model_obj: LangChain-like chat model object
            prompt_text: Prompt text
            timeout_seconds_float: Timeout threshold in seconds

        Returns:
            str: Extracted plain text response

        Raises:
            TimeoutError: Raised when model invocation times out
            Exception: Re-raises model invocation errors
        """
        safe_timeout_seconds_float = max(timeout_seconds_float, 0.1)
        executor = ThreadPoolExecutor(max_workers=1)
        invoke_future = executor.submit(chat_model_obj.invoke, prompt_text)
        try:
            model_response_obj = invoke_future.result(
                timeout=safe_timeout_seconds_float
            )
        except FutureTimeoutError as timeout_error:
            invoke_future.cancel()
            raise TimeoutError("AI branch naming timed out.") from timeout_error
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        model_response_content = getattr(
            model_response_obj, "content", model_response_obj
        )
        return WorktreeBranchNamingService._coerce_message_content_to_text(
            model_response_content
        ).strip()

    @staticmethod
    def _coerce_message_content_to_text(message_content_obj: Any) -> str:
        """Convert LangChain response content to plain text.

        Args:
            message_content_obj: Response content that may be str/list/dict

        Returns:
            str: Flattened text representation
        """
        if isinstance(message_content_obj, str):
            return message_content_obj

        if isinstance(message_content_obj, list):
            extracted_text_part_list: list[str] = []
            for content_item_obj in message_content_obj:
                if isinstance(content_item_obj, str):
                    extracted_text_part_list.append(content_item_obj)
                    continue
                if isinstance(content_item_obj, dict):
                    possible_text_value = content_item_obj.get("text")
                    if isinstance(possible_text_value, str):
                        extracted_text_part_list.append(possible_text_value)
            return "\n".join(extracted_text_part_list)

        if isinstance(message_content_obj, dict):
            possible_text_value = message_content_obj.get("text")
            if isinstance(possible_text_value, str):
                return possible_text_value

        return str(message_content_obj)

    @classmethod
    def _build_branch_naming_prompt_text(
        cls,
        *,
        task_title_str: str,
        requirement_brief_str: str | None,
        recent_context_text_list: list[str] | None,
    ) -> str:
        """Construct a compact prompt for semantic branch slug generation.

        Args:
            task_title_str: Task title text
            requirement_brief_str: Optional requirement brief text
            recent_context_text_list: Optional recent context snippets

        Returns:
            str: Prompt text; empty string when no useful context exists
        """
        normalized_task_title_str = task_title_str.strip()
        normalized_requirement_brief_str = (requirement_brief_str or "").strip()
        normalized_recent_context_line_list = [
            context_line_str.strip()
            for context_line_str in (recent_context_text_list or [])
            if context_line_str.strip()
        ][:3]
        if (
            normalized_task_title_str == ""
            and normalized_requirement_brief_str == ""
            and not normalized_recent_context_line_list
        ):
            return ""

        recent_context_block_str = (
            "\n".join(
                f"- {context_line_str}"
                for context_line_str in normalized_recent_context_line_list
            )
            if normalized_recent_context_line_list
            else "- (none)"
        )
        return (
            "You generate one short semantic branch slug for a software task.\n"
            "Rules:\n"
            "1. Output only the slug text, no explanation, no quotes.\n"
            "2. Use 2-6 English words, lower-case, concise.\n"
            "3. Prefer hyphen-separated words.\n"
            "4. Do not include task id, prefixes, punctuation, or emoji.\n"
            "\n"
            f"Task title: {normalized_task_title_str or '(empty)'}\n"
            f"Requirement brief: {normalized_requirement_brief_str or '(empty)'}\n"
            "Recent context:\n"
            f"{recent_context_block_str}\n"
        )

    @staticmethod
    def _build_branch_name(
        *,
        task_short_id_str: str,
        semantic_slug_str: str | None,
    ) -> str:
        """Build the final task branch name.

        Args:
            task_short_id_str: Task short id
            semantic_slug_str: Optional semantic slug

        Returns:
            str: Branch name
        """
        if semantic_slug_str:
            return f"task/{task_short_id_str}-{semantic_slug_str}"
        return f"task/{task_short_id_str}"
