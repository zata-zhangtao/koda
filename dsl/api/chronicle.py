"""Chronicle API 路由.

提供 Timeline 视图、Task 视图和 Markdown 导出功能.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from dsl.models.enums import TaskLifecycleStatus
from dsl.schemas.chronicle_schema import (
    ProjectTimelineEntrySchema,
    ProjectTimelineSummaryRequestSchema,
    ProjectTimelineSummaryResponseSchema,
    ProjectTimelineTaskDetailSchema,
)
from dsl.services.chronicle_service import ChronicleService
from utils.database import get_db
from utils.helpers import app_aware_to_utc_naive, app_now_aware

router = APIRouter(prefix="/api/chronicle", tags=["chronicle"])


def _get_current_run_account_id(db_session: Session) -> str:
    """获取当前活跃账户 ID.

    Args:
        db_session: 数据库会话

    Returns:
        str: 当前活跃账户 ID

    Raises:
        HTTPException: 当没有活跃账户时返回 400
    """
    from dsl.models.run_account import RunAccount

    account = db_session.query(RunAccount).filter(RunAccount.is_active).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active run account. Please create a run account first.",
        )
    return account.id


@router.get("/timeline")
def get_timeline(
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = 100,
    db_session: Annotated[Session, Depends(get_db)] = None,
) -> list[dict[str, Any]]:
    """获取时间线视图.

    Args:
        start_date: 开始日期过滤（可选）
        end_date: 结束日期过滤（可选）
        limit: 返回数量限制
        db_session: 数据库会话

    Returns:
        list[dict[str, Any]]: 时间线数据列表
    """
    run_account_id = _get_current_run_account_id(db_session)
    normalized_start_date = app_aware_to_utc_naive(start_date) if start_date else None
    normalized_end_date = app_aware_to_utc_naive(end_date) if end_date else None
    return ChronicleService.get_timeline(
        db_session,
        run_account_id,
        normalized_start_date,
        normalized_end_date,
        limit,
    )


@router.get("/task/{task_id}")
def get_task_chronicle(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """获取任务编年史.

    Args:
        task_id: 任务 ID
        db_session: 数据库会话

    Returns:
        dict[str, Any]: 任务编年史数据

    Raises:
        HTTPException: 当任务不存在时返回 404
    """
    chronicle = ChronicleService.get_task_chronicle(db_session, task_id)
    if not chronicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )
    return chronicle


@router.get(
    "/project-timeline",
    response_model=list[ProjectTimelineEntrySchema],
)
def get_project_timeline(
    project_id: str | None = None,
    project_category: str | None = None,
    lifecycle_status: list[TaskLifecycleStatus] | None = Query(default=None),
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
    db_session: Annotated[Session, Depends(get_db)] = None,
) -> list[dict[str, Any]]:
    """获取项目维度时间线.

    Args:
        project_id: 项目 ID（可选）
        project_category: 项目类别（可选）
        lifecycle_status: 生命周期过滤条件（可选）
        start_date: 开始时间（可选）
        end_date: 结束时间（可选）
        limit: 返回数量限制
        offset: 分页偏移
        db_session: 数据库会话

    Returns:
        list[dict[str, Any]]: 项目时间线条目
    """
    run_account_id = _get_current_run_account_id(db_session)
    normalized_start_date = app_aware_to_utc_naive(start_date) if start_date else None
    normalized_end_date = app_aware_to_utc_naive(end_date) if end_date else None
    return ChronicleService.get_project_timeline(
        db_session=db_session,
        run_account_id=run_account_id,
        project_id=project_id,
        project_category=project_category,
        lifecycle_status_list=lifecycle_status,
        start_date=normalized_start_date,
        end_date=normalized_end_date,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/project-timeline/{task_id}",
    response_model=ProjectTimelineTaskDetailSchema,
)
def get_project_timeline_task_detail(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """获取项目时间线中的单任务详情.

    Args:
        task_id: 任务 ID
        db_session: 数据库会话

    Returns:
        dict[str, Any]: 任务详情

    Raises:
        HTTPException: 当任务不存在或无权限时返回 404
    """
    run_account_id = _get_current_run_account_id(db_session)
    task_detail = ChronicleService.get_project_timeline_task_detail(
        db_session=db_session,
        run_account_id=run_account_id,
        task_id=task_id,
    )
    if task_detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )
    return task_detail


@router.post(
    "/project-timeline/summary",
    response_model=ProjectTimelineSummaryResponseSchema,
)
def summarize_project_timeline(
    summary_request: ProjectTimelineSummaryRequestSchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """生成项目时间线摘要.

    Args:
        summary_request: 摘要请求参数
        db_session: 数据库会话

    Returns:
        dict[str, Any]: 结构化摘要
    """
    run_account_id = _get_current_run_account_id(db_session)
    normalized_start_date = (
        app_aware_to_utc_naive(summary_request.start_date)
        if summary_request.start_date
        else None
    )
    normalized_end_date = (
        app_aware_to_utc_naive(summary_request.end_date)
        if summary_request.end_date
        else None
    )
    return ChronicleService.summarize_project_timeline(
        db_session=db_session,
        run_account_id=run_account_id,
        project_id=summary_request.project_id,
        project_category=summary_request.project_category,
        lifecycle_status_list=summary_request.lifecycle_status_list,
        start_date=normalized_start_date,
        end_date=normalized_end_date,
        summary_focus=summary_request.summary_focus,
    )


@router.get("/export")
def export_chronicle(
    format: str = "markdown",
    task_id: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    db_session: Annotated[Session, Depends(get_db)] = None,
) -> PlainTextResponse:
    """导出编年史文档.

    Args:
        format: 导出格式（目前仅支持 markdown）
        task_id: 按任务过滤（可选）
        start_date: 开始日期过滤（可选）
        end_date: 结束日期过滤（可选）
        db_session: 数据库会话

    Returns:
        PlainTextResponse: Markdown 文档响应

    Raises:
        HTTPException: 当格式不支持时返回 400
    """
    if format.lower() != "markdown":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format: {format}. Only 'markdown' is supported.",
        )

    run_account_id = _get_current_run_account_id(db_session)
    normalized_start_date = app_aware_to_utc_naive(start_date) if start_date else None
    normalized_end_date = app_aware_to_utc_naive(end_date) if end_date else None
    markdown_content = ChronicleService.export_markdown(
        db_session,
        run_account_id,
        task_id,
        normalized_start_date,
        normalized_end_date,
    )

    export_date_str = app_now_aware().strftime("%Y%m%d")
    if task_id:
        filename = f"chronicle-task-{task_id[:8]}-{export_date_str}.md"
    else:
        filename = f"chronicle-{export_date_str}.md"

    return PlainTextResponse(
        content=markdown_content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
