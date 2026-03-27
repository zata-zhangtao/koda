"""Task sidecar Q&A API routes.

Exposes task-scoped independent Q&A endpoints that stay separate from `DevLog`
and from the main automation workflow.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from dsl.models.run_account import RunAccount
from dsl.models.task_qa_message import TaskQaMessage
from dsl.schemas.task_qa_schema import (
    TaskQaCreateResponseSchema,
    TaskQaFeedbackDraftResponseSchema,
    TaskQaMessageCreateSchema,
    TaskQaMessageResponseSchema,
)
from dsl.services.task_qa_service import TaskQaService
from utils.database import get_db

router = APIRouter(prefix="/api/tasks", tags=["task_qa"])


def _get_current_run_account_id(db_session: Session) -> str:
    """Fetch the currently active run account ID.

    Args:
        db_session: Database session.

    Returns:
        str: Current active run account ID.

    Raises:
        HTTPException: If no active run account exists.
    """

    active_run_account = (
        db_session.query(RunAccount).filter(RunAccount.is_active).first()
    )
    if active_run_account is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active run account. Please create a run account first.",
        )
    return active_run_account.id


@router.get(
    "/{task_id}/qa/messages",
    response_model=list[TaskQaMessageResponseSchema],
)
def list_task_qa_messages(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> list[TaskQaMessage]:
    """List all sidecar Q&A messages for one task.

    Args:
        task_id: Target task ID.
        db_session: Database session.

    Returns:
        list[TaskQaMessage]: Chronologically ordered sidecar Q&A messages.

    Raises:
        HTTPException: If the task cannot be accessed.
    """

    run_account_id = _get_current_run_account_id(db_session)
    try:
        return TaskQaService.list_messages(db_session, task_id, run_account_id)
    except ValueError as task_qa_error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(task_qa_error),
        ) from task_qa_error


@router.post(
    "/{task_id}/qa/messages",
    response_model=TaskQaCreateResponseSchema,
    status_code=status.HTTP_201_CREATED,
)
def create_task_qa_message(
    task_id: str,
    task_qa_message_create: TaskQaMessageCreateSchema,
    background_tasks: BackgroundTasks,
    db_session: Annotated[Session, Depends(get_db)],
) -> TaskQaCreateResponseSchema:
    """Submit a new task-scoped sidecar Q&A question.

    Args:
        task_id: Target task ID.
        task_qa_message_create: Question submission payload.
        background_tasks: FastAPI background task scheduler.
        db_session: Database session.

    Returns:
        TaskQaCreateResponseSchema: Persisted user question and pending assistant reply.

    Raises:
        HTTPException: If validation fails or another reply is still pending.
    """

    run_account_id = _get_current_run_account_id(db_session)
    try:
        (
            user_message_obj,
            assistant_message_obj,
        ) = TaskQaService.create_question(
            db_session,
            task_id,
            run_account_id,
            task_qa_message_create,
        )
    except ValueError as task_qa_error:
        error_text = str(task_qa_error)
        http_status_code = (
            status.HTTP_409_CONFLICT
            if "pending" in error_text.lower()
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        if "not found" in error_text.lower():
            http_status_code = status.HTTP_404_NOT_FOUND
        raise HTTPException(
            status_code=http_status_code,
            detail=error_text,
        ) from task_qa_error

    background_tasks.add_task(
        TaskQaService.process_pending_reply,
        assistant_message_obj.id,
    )
    return TaskQaCreateResponseSchema(
        user_message=user_message_obj,
        assistant_message=assistant_message_obj,
    )


@router.post(
    "/{task_id}/qa/messages/{message_id}/feedback-draft",
    response_model=TaskQaFeedbackDraftResponseSchema,
)
def convert_task_qa_message_to_feedback_draft(
    task_id: str,
    message_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> TaskQaFeedbackDraftResponseSchema:
    """Convert a completed assistant answer into a feedback draft.

    Args:
        task_id: Target task ID.
        message_id: Assistant message ID used as the source conclusion.
        db_session: Database session.

    Returns:
        TaskQaFeedbackDraftResponseSchema: Feedback draft payload.

    Raises:
        HTTPException: If the source message is invalid.
    """

    run_account_id = _get_current_run_account_id(db_session)
    try:
        feedback_draft_markdown = TaskQaService.build_feedback_draft_from_message(
            db_session,
            task_id,
            run_account_id,
            message_id,
        )
    except ValueError as task_qa_error:
        error_text = str(task_qa_error)
        http_status_code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in error_text.lower()
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(
            status_code=http_status_code,
            detail=error_text,
        ) from task_qa_error

    return TaskQaFeedbackDraftResponseSchema(
        source_message_id=message_id,
        draft_markdown=feedback_draft_markdown,
    )
