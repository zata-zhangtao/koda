"""FastAPI routes for task preview sandboxes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.dsl.preview_sandboxes.application.use_cases import (
    PreviewSandboxUseCase,
)
from backend.dsl.preview_sandboxes.domain.errors import (
    InvalidPreviewProfileError,
    PreviewCompletionBlockedError,
    PreviewNotAvailableError,
    PreviewSandboxError,
    TaskNotFoundError,
)
from backend.dsl.preview_sandboxes.domain.models import (
    PreviewFailureKind,
    PreviewStatusSnapshot,
)
from backend.dsl.preview_sandboxes.schemas import (
    PreviewProfileSchema,
    PreviewSandboxStatusSchema,
)
from utils.database import get_db

router = APIRouter(
    prefix="/api/tasks/{task_id}/preview-sandbox",
    tags=["preview-sandbox"],
)


@router.get("", response_model=PreviewSandboxStatusSchema)
def get_preview_sandbox_status(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> PreviewSandboxStatusSchema:
    """Return preview sandbox status for a task.

    Args:
        task_id: Task UUID string.
        db_session: Database session.

    Returns:
        PreviewSandboxStatusSchema: Current preview status.
    """
    preview_use_case = PreviewSandboxUseCase(db_session)
    try:
        return _build_status_schema(preview_use_case.get_status(task_id))
    except PreviewSandboxError as preview_error:
        raise _to_http_exception(preview_error) from preview_error


@router.post("/start", response_model=PreviewSandboxStatusSchema)
def start_preview_sandbox(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
    preview_profile_schema: Annotated[PreviewProfileSchema | None, Body()] = None,
) -> PreviewSandboxStatusSchema:
    """Start or reuse a preview sandbox for a task.

    Args:
        task_id: Task UUID string.
        db_session: Database session.
        preview_profile_schema: Optional profile payload to validate and store
            before starting.

    Returns:
        PreviewSandboxStatusSchema: Updated preview status.
    """
    preview_use_case = PreviewSandboxUseCase(db_session)
    try:
        if preview_profile_schema is not None:
            preview_use_case.store_profile(
                task_id,
                preview_profile_schema.model_dump(mode="json"),
            )
        return _build_status_schema(preview_use_case.start(task_id))
    except PreviewSandboxError as preview_error:
        raise _to_http_exception(preview_error) from preview_error


@router.post("/restart", response_model=PreviewSandboxStatusSchema)
def restart_preview_sandbox(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> PreviewSandboxStatusSchema:
    """Restart a task preview sandbox.

    Args:
        task_id: Task UUID string.
        db_session: Database session.

    Returns:
        PreviewSandboxStatusSchema: Updated preview status.
    """
    preview_use_case = PreviewSandboxUseCase(db_session)
    try:
        preview_use_case.stop(task_id)
        return _build_status_schema(preview_use_case.start(task_id))
    except PreviewSandboxError as preview_error:
        raise _to_http_exception(preview_error) from preview_error


@router.post("/stop", response_model=PreviewSandboxStatusSchema)
def stop_preview_sandbox(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> PreviewSandboxStatusSchema:
    """Stop a task preview sandbox.

    Args:
        task_id: Task UUID string.
        db_session: Database session.

    Returns:
        PreviewSandboxStatusSchema: Updated preview status.
    """
    preview_use_case = PreviewSandboxUseCase(db_session)
    try:
        return _build_status_schema(preview_use_case.stop(task_id))
    except PreviewSandboxError as preview_error:
        raise _to_http_exception(preview_error) from preview_error


@router.post("/diagnose", response_model=PreviewSandboxStatusSchema)
def diagnose_preview_sandbox(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> PreviewSandboxStatusSchema:
    """Reclassify the latest preview failure.

    The first target state records an unknown failure when no richer runtime
    evidence is available. A later AI classifier can replace this logic behind
    the same endpoint.

    Args:
        task_id: Task UUID string.
        db_session: Database session.

    Returns:
        PreviewSandboxStatusSchema: Updated preview status.
    """
    preview_use_case = PreviewSandboxUseCase(db_session)
    try:
        status_snapshot = preview_use_case.get_status(task_id)
        if status_snapshot.failure_kind is None:
            status_snapshot = preview_use_case.record_failure(
                task_id,
                PreviewFailureKind.UNKNOWN,
                "Preview diagnosis did not find deterministic evidence.",
            )
        return _build_status_schema(status_snapshot)
    except PreviewSandboxError as preview_error:
        raise _to_http_exception(preview_error) from preview_error


@router.post("/confirm-bypass", response_model=PreviewSandboxStatusSchema)
def confirm_preview_sandbox_bypass(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> PreviewSandboxStatusSchema:
    """Confirm preview bypass for a task.

    Args:
        task_id: Task UUID string.
        db_session: Database session.

    Returns:
        PreviewSandboxStatusSchema: Updated preview status.
    """
    preview_use_case = PreviewSandboxUseCase(db_session)
    try:
        return _build_status_schema(preview_use_case.confirm_bypass(task_id))
    except PreviewSandboxError as preview_error:
        raise _to_http_exception(preview_error) from preview_error


def _build_status_schema(
    status_snapshot: PreviewStatusSnapshot,
) -> PreviewSandboxStatusSchema:
    return PreviewSandboxStatusSchema(
        task_id=status_snapshot.task_id,
        status=status_snapshot.status.value,
        applicability=(
            status_snapshot.applicability.value
            if status_snapshot.applicability is not None
            else None
        ),
        preview_url=status_snapshot.preview_url,
        profile_summary=status_snapshot.profile_summary,
        failure_kind=(
            status_snapshot.failure_kind.value
            if status_snapshot.failure_kind is not None
            else None
        ),
        failure_summary=status_snapshot.failure_summary,
        bypass_confirmed=status_snapshot.bypass_confirmed,
        log_tail=status_snapshot.log_tail,
        container_id=status_snapshot.container_id,
        host_port=status_snapshot.host_port,
        internal_port=status_snapshot.internal_port,
        started_at=status_snapshot.started_at,
    )


def _to_http_exception(preview_error: PreviewSandboxError) -> HTTPException:
    if isinstance(preview_error, TaskNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(preview_error),
        )
    if isinstance(preview_error, InvalidPreviewProfileError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(preview_error),
        )
    if isinstance(
        preview_error,
        (PreviewNotAvailableError, PreviewCompletionBlockedError),
    ):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(preview_error),
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=str(preview_error),
    )
