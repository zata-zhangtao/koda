"""Chronicle API 路由.

提供 Timeline 视图、Task 视图和 Markdown 导出功能.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from dsl.services.chronicle_service import ChronicleService
from utils.database import get_db

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

    account = (
        db_session.query(RunAccount).filter(RunAccount.is_active == True).first()
    )
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
    return ChronicleService.get_timeline(db_session, run_account_id, start_date, end_date, limit)


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
    markdown_content = ChronicleService.export_markdown(
        db_session, run_account_id, task_id, start_date, end_date
    )

    # 生成文件名
    from datetime import datetime as dt

    if task_id:
        filename = f"chronicle-task-{task_id[:8]}-{dt.now().strftime('%Y%m%d')}.md"
    else:
        filename = f"chronicle-{dt.now().strftime('%Y%m%d')}.md"

    return PlainTextResponse(
        content=markdown_content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
