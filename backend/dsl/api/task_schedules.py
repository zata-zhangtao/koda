"""Task schedule API 路由.

提供任务级调度规则的增删改查、立即触发与执行历史查询能力.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.dsl.models.task import Task
from backend.dsl.models.task_schedule import TaskSchedule
from backend.dsl.models.task_schedule_run import TaskScheduleRun
from backend.dsl.schemas.task_schedule_schema import (
    TaskScheduleCreateSchema,
    TaskScheduleResponseSchema,
    TaskScheduleRunResponseSchema,
    TaskScheduleUpdateSchema,
)
from backend.dsl.services.task_schedule_service import TaskScheduleService
from backend.dsl.services.task_scheduler_dispatcher import TaskSchedulerDispatcher
from backend.dsl.services.task_service import TaskService
from utils.database import get_db

router = APIRouter(prefix="/api/tasks/{task_id}/schedules", tags=["task-schedules"])


def _get_task_or_404(db_session: Session, task_id: str) -> Task:
    """加载任务对象，不存在则抛出 404.

    Args:
        db_session: 数据库会话
        task_id: 任务 ID

    Returns:
        Task: 任务对象

    Raises:
        HTTPException: 任务不存在时抛出 404
    """
    task_obj = TaskService.get_task_by_id(db_session, task_id)
    if task_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )
    return task_obj


def _get_task_schedule_or_404(
    db_session: Session,
    task_id: str,
    schedule_id: str,
) -> TaskSchedule:
    """加载任务调度规则，不存在则抛出 404.

    Args:
        db_session: 数据库会话
        task_id: 任务 ID
        schedule_id: 调度规则 ID

    Returns:
        TaskSchedule: 调度规则对象

    Raises:
        HTTPException: 规则不存在时抛出 404
    """
    task_schedule_obj = TaskScheduleService.get_task_schedule_by_id(
        db_session,
        task_id,
        schedule_id,
    )
    if task_schedule_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Task schedule with id {schedule_id} not found under task {task_id}"
            ),
        )
    return task_schedule_obj


@router.get("", response_model=list[TaskScheduleResponseSchema])
def list_task_schedules(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> list[TaskSchedule]:
    """列出指定任务下的调度规则.

    Args:
        task_id: 任务 ID
        db_session: 数据库会话

    Returns:
        list[TaskSchedule]: 调度规则列表
    """
    _get_task_or_404(db_session, task_id)
    return TaskScheduleService.list_task_schedules(db_session, task_id)


@router.post(
    "", response_model=TaskScheduleResponseSchema, status_code=status.HTTP_201_CREATED
)
def create_task_schedule(
    task_id: str,
    task_schedule_create_schema: TaskScheduleCreateSchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> TaskSchedule:
    """创建任务调度规则.

    Args:
        task_id: 任务 ID
        task_schedule_create_schema: 创建请求
        db_session: 数据库会话

    Returns:
        TaskSchedule: 新创建规则

    Raises:
        HTTPException: 参数不合法时抛出 422
    """
    task_obj = _get_task_or_404(db_session, task_id)
    try:
        return TaskScheduleService.create_task_schedule(
            db_session,
            task_obj,
            task_schedule_create_schema,
        )
    except ValueError as validation_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(validation_error),
        ) from validation_error


@router.get("/runs", response_model=list[TaskScheduleRunResponseSchema])
def list_task_schedule_runs(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
) -> list[TaskScheduleRun]:
    """查询任务调度执行历史.

    Args:
        task_id: 任务 ID
        db_session: 数据库会话
        limit: 返回条数上限

    Returns:
        list[TaskScheduleRun]: 执行记录列表
    """
    _get_task_or_404(db_session, task_id)
    return TaskScheduleService.list_task_schedule_runs(
        db_session,
        task_id,
        limit_int=limit,
    )


@router.post("/{schedule_id}/run-now", response_model=TaskScheduleRunResponseSchema)
def run_task_schedule_now(
    task_id: str,
    schedule_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> TaskScheduleRun:
    """立即触发一次调度规则.

    Args:
        task_id: 任务 ID
        schedule_id: 调度规则 ID
        db_session: 数据库会话

    Returns:
        TaskScheduleRun: 本次触发执行记录

    Raises:
        HTTPException: 当触发窗口冲突时抛出 409
    """
    _get_task_or_404(db_session, task_id)
    task_schedule_obj = _get_task_schedule_or_404(db_session, task_id, schedule_id)
    try:
        return TaskSchedulerDispatcher.dispatch_schedule_run_now(
            db_session,
            task_schedule_obj=task_schedule_obj,
        )
    except ValueError as dispatch_error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(dispatch_error),
        ) from dispatch_error


@router.patch("/{schedule_id}", response_model=TaskScheduleResponseSchema)
def update_task_schedule(
    task_id: str,
    schedule_id: str,
    task_schedule_update_schema: TaskScheduleUpdateSchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> TaskSchedule:
    """更新任务调度规则.

    Args:
        task_id: 任务 ID
        schedule_id: 调度规则 ID
        task_schedule_update_schema: 更新请求
        db_session: 数据库会话

    Returns:
        TaskSchedule: 更新后规则

    Raises:
        HTTPException: 参数不合法时抛出 422
    """
    _get_task_or_404(db_session, task_id)
    task_schedule_obj = _get_task_schedule_or_404(db_session, task_id, schedule_id)
    try:
        return TaskScheduleService.update_task_schedule(
            db_session,
            task_schedule_obj,
            task_schedule_update_schema,
        )
    except ValueError as validation_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(validation_error),
        ) from validation_error


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task_schedule(
    task_id: str,
    schedule_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> None:
    """删除任务调度规则.

    Args:
        task_id: 任务 ID
        schedule_id: 调度规则 ID
        db_session: 数据库会话
    """
    _get_task_or_404(db_session, task_id)
    task_schedule_obj = _get_task_schedule_or_404(db_session, task_id, schedule_id)
    TaskScheduleService.delete_task_schedule(db_session, task_schedule_obj)
