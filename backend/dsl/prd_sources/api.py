"""FastAPI routes for PRD source selection and import."""

from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from backend.dsl.models.task import Task
from backend.dsl.prd_sources.application.use_cases import (
    ImportPrdUseCase,
    ListPendingPrdFilesUseCase,
    SelectPendingPrdUseCase,
)
from backend.dsl.prd_sources.domain.errors import (
    InvalidPrdContentError,
    InvalidTaskStageError,
    PendingPrdNotFoundError,
    PrdAlreadyExistsError,
    PrdSourceError,
    TaskAutomationRunningError,
    TaskNotFoundError,
    UnsafePrdPathError,
)
from backend.dsl.prd_sources.domain.policies import MAX_PRD_MARKDOWN_BYTES
from backend.dsl.prd_sources.infrastructure.filesystem_prd_repository import (
    FilesystemPrdRepository,
)
from backend.dsl.prd_sources.infrastructure.task_workflow_adapter import (
    SqlAlchemyTaskWorkflowAdapter,
)
from backend.dsl.prd_sources.schemas import (
    ImportPastedPrdRequestSchema,
    PendingPrdFileListSchema,
    PendingPrdFileSchema,
    SelectPendingPrdRequestSchema,
)
from backend.dsl.schemas.task_schema import TaskResponseSchema
from backend.dsl.services.automation_runner import is_task_automation_running
from backend.dsl.services.task_service import TaskService
from utils.database import get_db

router = APIRouter(prefix="/api/tasks/{task_id}/prd-sources", tags=["prd-sources"])


@router.get("/pending", response_model=PendingPrdFileListSchema)
def list_pending_prd_files(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> PendingPrdFileListSchema:
    """List pending Markdown PRDs for a task workspace.

    Args:
        task_id: Task UUID string.
        db_session: Database session.

    Returns:
        PendingPrdFileListSchema: Pending PRD files.
    """
    task_workflow_adapter = SqlAlchemyTaskWorkflowAdapter(db_session)
    pending_file_use_case = ListPendingPrdFilesUseCase(
        task_workflow_port=task_workflow_adapter,
        prd_source_repository=FilesystemPrdRepository(),
    )
    try:
        pending_prd_candidate_list = pending_file_use_case.execute(task_id)
    except PrdSourceError as prd_source_error:
        raise _to_http_exception(prd_source_error) from prd_source_error

    return PendingPrdFileListSchema(
        files=[
            PendingPrdFileSchema(
                file_name=pending_prd_candidate.file_name_str,
                relative_path=pending_prd_candidate.relative_path_str,
                size_bytes=pending_prd_candidate.size_bytes_int,
                updated_at=pending_prd_candidate.updated_at,
                title_preview=pending_prd_candidate.title_preview_text,
            )
            for pending_prd_candidate in pending_prd_candidate_list
        ]
    )


@router.post("/select-pending", response_model=TaskResponseSchema)
def select_pending_prd_file(
    task_id: str,
    request_schema: SelectPendingPrdRequestSchema,
    background_tasks: BackgroundTasks,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """Move a selected pending PRD into the task PRD root.

    Args:
        task_id: Task UUID string.
        request_schema: Selected pending PRD request.
        background_tasks: FastAPI background task container.
        db_session: Database session.

    Returns:
        Task: Updated task object.
    """
    task_workflow_adapter = SqlAlchemyTaskWorkflowAdapter(db_session, background_tasks)
    select_pending_use_case = SelectPendingPrdUseCase(
        task_workflow_port=task_workflow_adapter,
        prd_source_repository=FilesystemPrdRepository(),
    )
    try:
        staging_outcome = select_pending_use_case.execute(
            task_id,
            request_schema.relative_path,
        )
        task_obj = task_workflow_adapter.get_task_for_response(task_id)
    except PrdSourceError as prd_source_error:
        raise _to_http_exception(prd_source_error) from prd_source_error

    return _hydrate_prd_source_task_response(
        task_obj,
        is_task_running_override=staging_outcome.auto_started_implementation_bool,
    )


@router.post("/import", response_model=TaskResponseSchema)
def import_prd_file(
    task_id: str,
    background_tasks: BackgroundTasks,
    db_session: Annotated[Session, Depends(get_db)],
    uploaded_prd_file: UploadFile = File(...),
) -> Task:
    """Import an uploaded Markdown PRD into the task PRD root.

    Args:
        task_id: Task UUID string.
        background_tasks: FastAPI background task container.
        db_session: Database session.
        uploaded_prd_file: Uploaded Markdown PRD file.

    Returns:
        Task: Updated task object.
    """
    raw_prd_file_bytes = uploaded_prd_file.file.read(MAX_PRD_MARKDOWN_BYTES + 1)
    task_workflow_adapter = SqlAlchemyTaskWorkflowAdapter(db_session, background_tasks)
    import_prd_use_case = ImportPrdUseCase(
        task_workflow_port=task_workflow_adapter,
        prd_source_repository=FilesystemPrdRepository(),
    )
    try:
        staging_outcome = import_prd_use_case.execute(
            task_id_str=task_id,
            original_file_name_str=uploaded_prd_file.filename or "",
            raw_prd_file_bytes=raw_prd_file_bytes,
        )
        task_obj = task_workflow_adapter.get_task_for_response(task_id)
    except PrdSourceError as prd_source_error:
        raise _to_http_exception(prd_source_error) from prd_source_error

    return _hydrate_prd_source_task_response(
        task_obj,
        is_task_running_override=staging_outcome.auto_started_implementation_bool,
    )


@router.post("/import-text", response_model=TaskResponseSchema)
def import_pasted_prd_markdown(
    task_id: str,
    request_schema: ImportPastedPrdRequestSchema,
    background_tasks: BackgroundTasks,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """Import pasted Markdown PRD text into the task PRD root.

    Args:
        task_id: Task UUID string.
        request_schema: Pasted Markdown request payload.
        background_tasks: FastAPI background task container.
        db_session: Database session.

    Returns:
        Task: Updated task object.
    """
    task_workflow_adapter = SqlAlchemyTaskWorkflowAdapter(db_session, background_tasks)
    import_prd_use_case = ImportPrdUseCase(
        task_workflow_port=task_workflow_adapter,
        prd_source_repository=FilesystemPrdRepository(),
    )
    try:
        staging_outcome = import_prd_use_case.execute_pasted_markdown(
            task_id_str=task_id,
            original_file_name_str="pasted-prd.md",
            prd_markdown_text=request_schema.prd_markdown_text,
        )
        task_obj = task_workflow_adapter.get_task_for_response(task_id)
    except PrdSourceError as prd_source_error:
        raise _to_http_exception(prd_source_error) from prd_source_error

    return _hydrate_prd_source_task_response(
        task_obj,
        is_task_running_override=staging_outcome.auto_started_implementation_bool,
    )


def _to_http_exception(prd_source_error: PrdSourceError) -> HTTPException:
    """Map PRD source errors to HTTP exceptions."""
    if isinstance(prd_source_error, TaskNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(prd_source_error),
        )
    if isinstance(prd_source_error, PendingPrdNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(prd_source_error),
        )
    if isinstance(prd_source_error, PrdAlreadyExistsError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(prd_source_error),
        )
    if isinstance(prd_source_error, TaskAutomationRunningError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(prd_source_error),
        )
    if isinstance(
        prd_source_error,
        (InvalidPrdContentError, InvalidTaskStageError, UnsafePrdPathError),
    ):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(prd_source_error),
        )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=str(prd_source_error),
    )


def _hydrate_prd_source_task_response(
    task_obj: Task,
    *,
    is_task_running_override: bool,
) -> Task:
    """Attach computed response fields expected by TaskResponseSchema."""
    task_obj.branch_health = TaskService.build_task_branch_health(task_obj)
    task_obj.log_count = len(task_obj.dev_logs)
    task_obj.is_codex_task_running = (
        is_task_running_override
        if is_task_running_override
        else is_task_automation_running(task_obj.id)
    )
    task_obj.business_sync_status_note = None
    return task_obj
