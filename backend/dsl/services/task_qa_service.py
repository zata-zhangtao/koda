"""Task-scoped sidecar Q&A service implementation.

This service keeps independent task Q&A isolated from the main automation
timeline. It persists messages in a dedicated table, builds read-only task
context, invokes the chat-model helper layer, and never changes
`workflow_stage` or `is_codex_task_running`.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ai_agent.utils import create_task_qa_chat_model
from backend.dsl.models.dev_log import DevLog
from backend.dsl.models.enums import (
    TaskLifecycleStatus,
    TaskQaContextScope,
    TaskQaGenerationStatus,
    TaskQaMessageRole,
)
from backend.dsl.models.project import Project
from backend.dsl.models.task import Task
from backend.dsl.models.task_qa_message import TaskQaMessage
from backend.dsl.schemas.task_qa_schema import TaskQaMessageCreateSchema
from backend.dsl.services.prd_file_service import find_task_prd_file_path
from utils.database import SessionLocal
from utils.helpers import utc_now_naive
from utils.logger import logger
from utils.settings import config

_MAX_RECENT_DEV_LOG_COUNT = 12
_MAX_RECENT_QA_MESSAGE_COUNT = 6
_MAX_LOG_SUMMARY_LENGTH = 280
_TASK_QA_MODEL_TIMEOUT_SECONDS = 60.0
_TASK_QA_MODEL_MAX_RETRIES = 1
_TASK_QA_PENDING_REPLY_EXPIRATION_SECONDS = 300.0
_TASK_QA_PENDING_REPLY_EXPIRED_ERROR_TEXT = (
    "This sidecar Q&A reply did not finish in time and was released from pending. "
    "Please ask again if you still need an answer."
)
_TASK_QA_SYSTEM_PROMPT = """你是 Koda 的任务内独立问答 sidecar。

你的职责是基于当前任务上下文回答问题，帮助用户澄清 PRD、实现方案、风险和下一步建议。

强约束：
1. 你不是主执行链路，不要声称已经修改代码、修改 PRD、推进 workflow_stage，或已经触发 execute/resume/cancel/regenerate-prd。
2. 你可以解释、比较、提出建议，但所有正式动作都必须由用户显式走反馈通道确认。
3. 如果上下文中缺少 PRD 文件或其他资料，要明确说明降级依据，而不是假装看过不存在的内容。
4. 回答尽量直接、结构清晰、面向当前任务，不要泛泛而谈。
"""


def _clean_markdown_preview(raw_markdown_text: str) -> str:
    """Build a compact one-line preview from markdown text.

    Args:
        raw_markdown_text: Raw markdown content.

    Returns:
        str: Compacted preview text.
    """

    collapsed_markdown_text = re.sub(r"\s+", " ", raw_markdown_text).strip()
    without_markdown_link_text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r"\1",
        collapsed_markdown_text,
    )
    return without_markdown_link_text


def _truncate_text(raw_text: str, max_length: int) -> str:
    """Truncate text while keeping the result readable.

    Args:
        raw_text: Source text.
        max_length: Maximum length.

    Returns:
        str: Truncated text.
    """

    if len(raw_text) <= max_length:
        return raw_text
    if max_length <= 1:
        return raw_text[:max_length]
    return f"{raw_text[: max_length - 1].rstrip()}…"


def _format_context_scope_label(task_qa_context_scope: TaskQaContextScope) -> str:
    """Map a scope enum to a human-readable label.

    Args:
        task_qa_context_scope: Scope enum value.

    Returns:
        str: Human-readable scope label.
    """

    if task_qa_context_scope == TaskQaContextScope.PRD_CONFIRMATION:
        return "PRD 确认"
    return "实现陪跑"


def _normalize_generated_content(raw_generated_content: object) -> str:
    """Normalize LLM output content into plain markdown text.

    Args:
        raw_generated_content: Raw content returned by a LangChain message.

    Returns:
        str: Normalized markdown text.
    """

    if isinstance(raw_generated_content, str):
        return raw_generated_content.strip()

    if isinstance(raw_generated_content, list):
        normalized_content_part_list: list[str] = []
        for content_part in raw_generated_content:
            if isinstance(content_part, str):
                normalized_content_part_list.append(content_part.strip())
                continue
            if (
                isinstance(content_part, dict)
                and content_part.get("type") == "text"
                and isinstance(content_part.get("text"), str)
            ):
                normalized_content_part_list.append(content_part["text"].strip())
        return "\n\n".join(
            content_part
            for content_part in normalized_content_part_list
            if content_part
        ).strip()

    return str(raw_generated_content).strip()


class TaskQaService:
    """Service object for task-scoped sidecar Q&A behavior."""

    @staticmethod
    def get_task_or_raise(
        db_session: Session,
        task_id: str,
        run_account_id: str,
        *,
        lock_for_update: bool = False,
    ) -> Task:
        """Fetch one accessible task or fail fast.

        Args:
            db_session: Database session.
            task_id: Target task ID.
            run_account_id: Active run account ID.
            lock_for_update: Whether to serialize writes with a task-row lock when
                the database dialect supports it.

        Returns:
            Task: Accessible task object.

        Raises:
            ValueError: If the task is missing or inaccessible.
        """

        task_query = db_session.query(Task).filter(
            Task.id == task_id,
            Task.run_account_id == run_account_id,
        )
        if lock_for_update and TaskQaService._supports_task_row_lock(db_session):
            task_query = task_query.with_for_update()

        task_obj = task_query.first()
        if task_obj is None:
            raise ValueError(f"Task with id {task_id} not found")
        return task_obj

    @staticmethod
    def _supports_task_row_lock(db_session: Session) -> bool:
        """Return whether the current database dialect supports task row locks.

        Args:
            db_session: Database session.

        Returns:
            bool: `True` when `SELECT ... FOR UPDATE` is meaningful.
        """

        database_bind = db_session.get_bind()
        return database_bind is not None and database_bind.dialect.name != "sqlite"

    @staticmethod
    def _get_pending_assistant_message(
        db_session: Session,
        task_id: str,
        run_account_id: str,
    ) -> TaskQaMessage | None:
        """Fetch the current pending assistant reply for a task, if any.

        Args:
            db_session: Database session.
            task_id: Target task ID.
            run_account_id: Active run account ID.

        Returns:
            TaskQaMessage | None: Existing pending assistant reply, if present.
        """

        return (
            db_session.query(TaskQaMessage)
            .filter(
                TaskQaMessage.task_id == task_id,
                TaskQaMessage.run_account_id == run_account_id,
                TaskQaMessage.role == TaskQaMessageRole.ASSISTANT,
                TaskQaMessage.generation_status == TaskQaGenerationStatus.PENDING,
            )
            .first()
        )

    @staticmethod
    def list_messages(
        db_session: Session,
        task_id: str,
        run_account_id: str,
    ) -> list[TaskQaMessage]:
        """List task-scoped sidecar Q&A messages in chronological order.

        Args:
            db_session: Database session.
            task_id: Target task ID.
            run_account_id: Active run account ID.

        Returns:
            list[TaskQaMessage]: Chronologically ordered Q&A messages.
        """

        TaskQaService.get_task_or_raise(db_session, task_id, run_account_id)
        TaskQaService._release_expired_pending_replies(
            db_session,
            task_id,
            run_account_id,
        )
        return (
            db_session.query(TaskQaMessage)
            .filter(
                TaskQaMessage.task_id == task_id,
                TaskQaMessage.run_account_id == run_account_id,
            )
            .order_by(TaskQaMessage.created_at.asc(), TaskQaMessage.id.asc())
            .all()
        )

    @staticmethod
    def create_question(
        db_session: Session,
        task_id: str,
        run_account_id: str,
        task_qa_message_create: TaskQaMessageCreateSchema,
    ) -> tuple[TaskQaMessage, TaskQaMessage]:
        """Persist a task-sidecar question and its pending reply placeholder.

        Args:
            db_session: Database session.
            task_id: Target task ID.
            run_account_id: Active run account ID.
            task_qa_message_create: Question submission payload.

        Returns:
            tuple[TaskQaMessage, TaskQaMessage]: User question message and pending
                assistant reply placeholder.

        Raises:
            ValueError: If the task cannot accept the question.
        """

        task_obj = TaskQaService.get_task_or_raise(
            db_session,
            task_id,
            run_account_id,
            lock_for_update=True,
        )
        if task_obj.lifecycle_status in {
            TaskLifecycleStatus.CLOSED,
            TaskLifecycleStatus.DELETED,
        }:
            raise ValueError("Closed or deleted tasks do not accept sidecar Q&A.")

        TaskQaService._release_expired_pending_replies(
            db_session,
            task_id,
            run_account_id,
            commit_changes=False,
        )

        pending_assistant_message = TaskQaService._get_pending_assistant_message(
            db_session,
            task_id,
            run_account_id,
        )
        if pending_assistant_message is not None:
            raise ValueError(
                "Another sidecar Q&A reply is still pending for this task."
            )

        normalized_question_markdown = task_qa_message_create.question_markdown.strip()
        if not normalized_question_markdown:
            raise ValueError("Question markdown must not be blank.")

        user_message_obj = TaskQaMessage(
            task_id=task_id,
            run_account_id=run_account_id,
            role=TaskQaMessageRole.USER,
            context_scope=task_qa_message_create.context_scope,
            generation_status=TaskQaGenerationStatus.COMPLETED,
            content_markdown=normalized_question_markdown,
        )
        db_session.add(user_message_obj)
        db_session.flush()

        assistant_message_obj = TaskQaMessage(
            task_id=task_id,
            run_account_id=run_account_id,
            role=TaskQaMessageRole.ASSISTANT,
            context_scope=task_qa_message_create.context_scope,
            generation_status=TaskQaGenerationStatus.PENDING,
            reply_to_message_id=user_message_obj.id,
            content_markdown="",
            model_name=config.TASK_QA_MODEL_NAME,
        )
        db_session.add(assistant_message_obj)
        try:
            db_session.commit()
        except IntegrityError as integrity_error:
            db_session.rollback()
            concurrent_pending_assistant_message = (
                TaskQaService._get_pending_assistant_message(
                    db_session,
                    task_id,
                    run_account_id,
                )
            )
            if concurrent_pending_assistant_message is not None:
                raise ValueError(
                    "Another sidecar Q&A reply is still pending for this task."
                ) from integrity_error
            raise

        db_session.refresh(user_message_obj)
        db_session.refresh(assistant_message_obj)
        return user_message_obj, assistant_message_obj

    @staticmethod
    def process_pending_reply(assistant_message_id: str) -> None:
        """Generate one pending assistant reply in a fresh database session.

        Args:
            assistant_message_id: Pending assistant message ID.
        """

        db_session = SessionLocal()
        try:
            TaskQaService._process_pending_reply_in_session(
                db_session,
                assistant_message_id,
            )
        finally:
            db_session.close()

    @staticmethod
    def _process_pending_reply_in_session(
        db_session: Session,
        assistant_message_id: str,
    ) -> None:
        """Generate one pending assistant reply with a provided session.

        Args:
            db_session: Database session.
            assistant_message_id: Pending assistant message ID.
        """

        assistant_message_obj = (
            db_session.query(TaskQaMessage)
            .filter(TaskQaMessage.id == assistant_message_id)
            .first()
        )
        if assistant_message_obj is None:
            logger.warning(
                "Task sidecar Q&A assistant message not found: %s",
                assistant_message_id,
            )
            return

        if assistant_message_obj.generation_status != TaskQaGenerationStatus.PENDING:
            return

        expiration_cutoff = utc_now_naive() - timedelta(
            seconds=_TASK_QA_PENDING_REPLY_EXPIRATION_SECONDS
        )
        if assistant_message_obj.created_at <= expiration_cutoff:
            assistant_message_obj.generation_status = TaskQaGenerationStatus.FAILED
            assistant_message_obj.error_text = _TASK_QA_PENDING_REPLY_EXPIRED_ERROR_TEXT
            db_session.commit()
            logger.warning(
                "Task sidecar Q&A reply %s expired before generation started",
                assistant_message_id,
            )
            return

        user_message_obj = (
            db_session.query(TaskQaMessage)
            .filter(TaskQaMessage.id == assistant_message_obj.reply_to_message_id)
            .first()
        )
        if user_message_obj is None:
            assistant_message_obj.generation_status = TaskQaGenerationStatus.FAILED
            assistant_message_obj.error_text = (
                "Missing linked user question for this sidecar Q&A reply."
            )
            db_session.commit()
            return

        try:
            task_context_markdown = TaskQaService.build_task_context_markdown(
                db_session=db_session,
                task_id=assistant_message_obj.task_id,
                run_account_id=assistant_message_obj.run_account_id,
                latest_user_question_markdown=user_message_obj.content_markdown,
                task_qa_context_scope=assistant_message_obj.context_scope,
            )
            assistant_reply_markdown = TaskQaService.generate_answer_markdown(
                task_context_markdown=task_context_markdown,
                user_question_markdown=user_message_obj.content_markdown,
            )
            assistant_message_obj.content_markdown = assistant_reply_markdown
            assistant_message_obj.generation_status = TaskQaGenerationStatus.COMPLETED
            assistant_message_obj.error_text = None
            assistant_message_obj.model_name = config.TASK_QA_MODEL_NAME
            db_session.commit()
        except Exception as task_qa_error:  # pragma: no cover - defensive path
            assistant_message_obj.generation_status = TaskQaGenerationStatus.FAILED
            assistant_message_obj.error_text = str(task_qa_error)
            db_session.commit()
            logger.exception(
                "Task sidecar Q&A generation failed for message %s: %s",
                assistant_message_id,
                task_qa_error,
            )

    @staticmethod
    def generate_answer_markdown(
        task_context_markdown: str,
        user_question_markdown: str,
    ) -> str:
        """Call the configured chat model and return normalized markdown text.

        Args:
            task_context_markdown: Serialized read-only task context.
            user_question_markdown: User-authored markdown question.

        Returns:
            str: Normalized assistant markdown reply.

        Raises:
            RuntimeError: If the model returns an empty response.
        """

        if config.TASK_QA_BACKEND != "chat_model":
            raise RuntimeError(
                "Task sidecar Q&A currently supports only TASK_QA_BACKEND=chat_model."
            )

        task_qa_chat_model = create_task_qa_chat_model(
            model_name=config.TASK_QA_MODEL_NAME,
            temperature=config.TASK_QA_MODEL_TEMPERATURE,
            client_kwargs={
                "timeout": _TASK_QA_MODEL_TIMEOUT_SECONDS,
                "max_retries": _TASK_QA_MODEL_MAX_RETRIES,
            },
        )
        llm_response_message = task_qa_chat_model.invoke(
            [
                SystemMessage(content=_TASK_QA_SYSTEM_PROMPT),
                HumanMessage(
                    content=(
                        f"{task_context_markdown}\n\n"
                        "## Current User Question\n"
                        f"{user_question_markdown.strip()}"
                    )
                ),
            ]
        )
        assistant_reply_markdown = _normalize_generated_content(
            getattr(llm_response_message, "content", "")
        )
        if not assistant_reply_markdown:
            raise RuntimeError("Task sidecar Q&A model returned an empty response.")
        return assistant_reply_markdown

    @staticmethod
    def _release_expired_pending_replies(
        db_session: Session,
        task_id: str,
        run_account_id: str,
        *,
        commit_changes: bool = True,
    ) -> int:
        """Fail expired pending assistant replies so the task does not stay locked.

        Args:
            db_session: Database session.
            task_id: Target task ID.
            run_account_id: Active run account ID.
            commit_changes: Whether to commit immediately after releasing stale rows.

        Returns:
            int: Number of pending replies released from the locked state.
        """

        expiration_cutoff = utc_now_naive() - timedelta(
            seconds=_TASK_QA_PENDING_REPLY_EXPIRATION_SECONDS
        )
        expired_pending_message_list = (
            db_session.query(TaskQaMessage)
            .filter(
                TaskQaMessage.task_id == task_id,
                TaskQaMessage.run_account_id == run_account_id,
                TaskQaMessage.role == TaskQaMessageRole.ASSISTANT,
                TaskQaMessage.generation_status == TaskQaGenerationStatus.PENDING,
                TaskQaMessage.created_at <= expiration_cutoff,
            )
            .all()
        )
        if not expired_pending_message_list:
            return 0

        for expired_pending_message_obj in expired_pending_message_list:
            expired_pending_message_obj.generation_status = (
                TaskQaGenerationStatus.FAILED
            )
            expired_pending_message_obj.error_text = (
                _TASK_QA_PENDING_REPLY_EXPIRED_ERROR_TEXT
            )

        if commit_changes:
            db_session.commit()
        else:
            db_session.flush()
        logger.warning(
            "Released %s expired task sidecar Q&A pending replies for task %s",
            len(expired_pending_message_list),
            task_id,
        )
        return len(expired_pending_message_list)

    @staticmethod
    def build_task_context_markdown(
        db_session: Session,
        task_id: str,
        run_account_id: str,
        latest_user_question_markdown: str,
        task_qa_context_scope: TaskQaContextScope,
    ) -> str:
        """Build the read-only task context used by sidecar Q&A.

        Args:
            db_session: Database session.
            task_id: Target task ID.
            run_account_id: Active run account ID.
            latest_user_question_markdown: Latest user question content.
            task_qa_context_scope: Requested Q&A context scope.

        Returns:
            str: Serialized markdown context block.
        """

        task_obj = TaskQaService.get_task_or_raise(db_session, task_id, run_account_id)
        prd_context_block = TaskQaService._build_prd_context_block(db_session, task_obj)
        recent_dev_log_summary_block = (
            TaskQaService._build_recent_dev_log_summary_block(
                db_session,
                task_id,
            )
        )
        recent_task_qa_history_block = (
            TaskQaService._build_recent_task_qa_history_block(
                db_session,
                task_id,
                exclude_user_message_markdown=latest_user_question_markdown,
            )
        )

        requirement_summary_markdown = (
            task_obj.requirement_brief.strip()
            if task_obj.requirement_brief and task_obj.requirement_brief.strip()
            else "No requirement brief captured yet."
        )
        return "\n\n".join(
            [
                "## Task Metadata",
                f"- Title: {task_obj.task_title}",
                f"- Workflow stage: {task_obj.workflow_stage.value}",
                f"- Q&A scope: {_format_context_scope_label(task_qa_context_scope)}",
                "",
                "## Requirement Summary",
                requirement_summary_markdown,
                "",
                recent_dev_log_summary_block,
                "",
                prd_context_block,
                "",
                recent_task_qa_history_block,
                "",
                "## Sidecar Q&A Boundary",
                "- This question must not mutate workflow_stage.",
                "- This answer must not imply execute/resume/cancel/regenerate-prd already happened.",
                "- If the user wants action, tell them to convert the conclusion into feedback first.",
            ]
        ).strip()

    @staticmethod
    def _build_prd_context_block(db_session: Session, task_obj: Task) -> str:
        """Build the PRD context block for sidecar Q&A.

        Args:
            db_session: Database session.
            task_obj: Target task object.

        Returns:
            str: PRD context block with graceful fallback text.
        """

        effective_work_dir_path = TaskQaService._resolve_task_effective_work_dir_path(
            db_session,
            task_obj,
        )
        prd_file_path = find_task_prd_file_path(effective_work_dir_path, task_obj.id)
        if prd_file_path is None:
            return (
                "## Current PRD File\n"
                "No PRD file is currently available for this task. "
                "Answer using the task title, requirement summary, and recent logs."
            )

        try:
            prd_markdown_text = prd_file_path.read_text(encoding="utf-8").strip()
        except OSError as prd_read_error:
            logger.warning(
                "Failed to read task PRD file for sidecar Q&A: %s",
                prd_read_error,
            )
            return (
                "## Current PRD File\n"
                "A PRD file path exists, but it could not be read at the moment. "
                "Answer using the remaining task context."
            )

        if not prd_markdown_text:
            return "## Current PRD File\nThe current PRD file exists but is empty."

        return f"## Current PRD File\n{prd_markdown_text}"

    @staticmethod
    def _build_recent_dev_log_summary_block(
        db_session: Session,
        task_id: str,
    ) -> str:
        """Build a compact recent DevLog summary block.

        Args:
            db_session: Database session.
            task_id: Target task ID.

        Returns:
            str: Recent DevLog summary markdown.
        """

        recent_dev_log_list = (
            db_session.query(DevLog)
            .filter(DevLog.task_id == task_id)
            .order_by(DevLog.created_at.desc(), DevLog.id.desc())
            .limit(_MAX_RECENT_DEV_LOG_COUNT)
            .all()
        )
        if not recent_dev_log_list:
            return "## Recent DevLog Summary\n- No DevLog history yet."

        recent_dev_log_summary_line_list = ["## Recent DevLog Summary"]
        for dev_log_item in reversed(recent_dev_log_list):
            preview_text = _truncate_text(
                _clean_markdown_preview(dev_log_item.text_content or ""),
                _MAX_LOG_SUMMARY_LENGTH,
            )
            if not preview_text:
                continue
            recent_dev_log_summary_line_list.append(
                f"- [{dev_log_item.state_tag.value}] {preview_text}"
            )
        if len(recent_dev_log_summary_line_list) == 1:
            recent_dev_log_summary_line_list.append("- No readable DevLog summary yet.")
        return "\n".join(recent_dev_log_summary_line_list)

    @staticmethod
    def _build_recent_task_qa_history_block(
        db_session: Session,
        task_id: str,
        exclude_user_message_markdown: str,
    ) -> str:
        """Build a compact recent sidecar Q&A history block.

        Args:
            db_session: Database session.
            task_id: Target task ID.
            exclude_user_message_markdown: Latest question text to exclude.

        Returns:
            str: Recent sidecar Q&A history markdown.
        """

        recent_task_qa_message_list = (
            db_session.query(TaskQaMessage)
            .filter(
                TaskQaMessage.task_id == task_id,
                TaskQaMessage.generation_status == TaskQaGenerationStatus.COMPLETED,
            )
            .order_by(TaskQaMessage.created_at.desc(), TaskQaMessage.id.desc())
            .limit(_MAX_RECENT_QA_MESSAGE_COUNT)
            .all()
        )
        if not recent_task_qa_message_list:
            return (
                "## Recent Sidecar Q&A History\n- No earlier sidecar Q&A history yet."
            )

        recent_task_qa_history_line_list = ["## Recent Sidecar Q&A History"]
        normalized_excluded_question = exclude_user_message_markdown.strip()
        for task_qa_message_obj in reversed(recent_task_qa_message_list):
            normalized_content_markdown = task_qa_message_obj.content_markdown.strip()
            if (
                task_qa_message_obj.role == TaskQaMessageRole.USER
                and normalized_content_markdown == normalized_excluded_question
            ):
                continue
            role_label = (
                "User"
                if task_qa_message_obj.role == TaskQaMessageRole.USER
                else "Assistant"
            )
            preview_text = _truncate_text(
                _clean_markdown_preview(normalized_content_markdown),
                _MAX_LOG_SUMMARY_LENGTH,
            )
            if not preview_text:
                continue
            recent_task_qa_history_line_list.append(f"- {role_label}: {preview_text}")
        if len(recent_task_qa_history_line_list) == 1:
            recent_task_qa_history_line_list.append(
                "- No earlier sidecar Q&A history yet."
            )
        return "\n".join(recent_task_qa_history_line_list)

    @staticmethod
    def build_feedback_draft_from_message(
        db_session: Session,
        task_id: str,
        run_account_id: str,
        assistant_message_id: str,
    ) -> str:
        """Convert a completed assistant answer into a feedback draft.

        Args:
            db_session: Database session.
            task_id: Target task ID.
            run_account_id: Active run account ID.
            assistant_message_id: Assistant message ID to convert.

        Returns:
            str: Feedback draft markdown text.

        Raises:
            ValueError: If the source message is invalid.
        """

        task_obj = TaskQaService.get_task_or_raise(db_session, task_id, run_account_id)
        assistant_message_obj = (
            db_session.query(TaskQaMessage)
            .filter(
                TaskQaMessage.id == assistant_message_id,
                TaskQaMessage.task_id == task_id,
                TaskQaMessage.run_account_id == run_account_id,
            )
            .first()
        )
        if assistant_message_obj is None:
            raise ValueError(
                f"Task Q&A message with id {assistant_message_id} not found"
            )
        if assistant_message_obj.role != TaskQaMessageRole.ASSISTANT:
            raise ValueError(
                "Only assistant Q&A messages can be converted into drafts."
            )
        if assistant_message_obj.generation_status != TaskQaGenerationStatus.COMPLETED:
            raise ValueError("Only completed assistant Q&A messages can be converted.")

        user_message_obj = (
            db_session.query(TaskQaMessage)
            .filter(TaskQaMessage.id == assistant_message_obj.reply_to_message_id)
            .first()
        )
        question_markdown = (
            user_message_obj.content_markdown.strip()
            if user_message_obj is not None
            and user_message_obj.content_markdown.strip()
            else "No original question content recorded."
        )
        return "\n".join(
            [
                "请基于以下已确认的 sidecar Q&A 结论继续处理当前任务：",
                "",
                f"- 任务：{task_obj.task_title}",
                f"- 当前阶段：{task_obj.workflow_stage.value}",
                f"- 问答作用域：{assistant_message_obj.context_scope.value}",
                "",
                "原始问题：",
                question_markdown,
                "",
                "问答结论：",
                assistant_message_obj.content_markdown.strip(),
                "",
                "请把上面的结论视为正式反馈输入，必要时据此更新 PRD 或实现方案。",
            ]
        ).strip()

    @staticmethod
    def _resolve_task_effective_work_dir_path(
        db_session: Session,
        task_obj: Task,
    ) -> Path:
        """Resolve the best available task working directory.

        Args:
            db_session: Database session.
            task_obj: Target task object.

        Returns:
            Path: Existing worktree path, project root, or repo base directory.
        """

        if task_obj.worktree_path:
            worktree_dir_path = Path(task_obj.worktree_path)
            if worktree_dir_path.exists():
                return worktree_dir_path

        if task_obj.project_id:
            project_obj = (
                db_session.query(Project)
                .filter(Project.id == task_obj.project_id)
                .first()
            )
            if project_obj is not None:
                project_repo_path = Path(project_obj.repo_path)
                if project_repo_path.exists():
                    return project_repo_path

        return config.BASE_DIR
