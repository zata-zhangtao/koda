"""DevLog API 路由.

提供日志的创建、查询和 AI 校正功能.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from dsl.models.dev_log import DevLog
from dsl.models.run_account import RunAccount
from dsl.schemas.dev_log_schema import (
    AIReviewUpdateSchema,
    CommandParseResultSchema,
    DevLogCreateSchema,
    DevLogResponseSchema,
    DevLogWithAIRSchema,
)
from dsl.services.log_service import LogService
from dsl.services.task_service import TaskService
from utils.database import get_db
from utils.helpers import parse_iso_datetime_text
from utils.logger import logger

router = APIRouter(prefix="/api/logs", tags=["logs"])


def _get_current_run_account_id(db_session: Session) -> str:
    """获取当前活跃账户 ID.

    Args:
        db_session: 数据库会话

    Returns:
        str: 当前活跃账户 ID

    Raises:
        HTTPException: 当没有活跃账户时返回 400
    """
    account = db_session.query(RunAccount).filter(RunAccount.is_active).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active run account. Please create a run account first.",
        )
    return account.id


@router.get("", response_model=list[DevLogResponseSchema])
def list_logs(
    task_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    created_after: str | None = None,
    db_session: Session = Depends(get_db),
) -> list[DevLog]:
    """获取日志列表.

    Args:
        task_id: 按任务过滤（可选）
        limit: 返回数量限制
        offset: 分页偏移量
        created_after: 仅返回该时间之后的新日志；支持带偏移的 ISO 8601 字符串
        db_session: 数据库会话

    Returns:
        list[DevLog]: 日志列表
    """
    run_account_id = _get_current_run_account_id(db_session)
    created_after_datetime: datetime | None = None
    if created_after is not None:
        created_after_datetime = parse_iso_datetime_text(created_after)
        if created_after_datetime is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Invalid created_after timestamp. Expected an ISO 8601 datetime.",
            )

    logs = LogService.get_logs(
        db_session,
        task_id,
        run_account_id,
        limit,
        offset,
        created_after_datetime,
    )

    # 填充 task_title
    for log in logs:
        log.task_title = log.task.task_title if log.task else ""

    return logs


@router.post(
    "", response_model=DevLogResponseSchema, status_code=status.HTTP_201_CREATED
)
def create_log(
    log_create_schema: DevLogCreateSchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> DevLog:
    """创建新日志.

    Args:
        log_create_schema: 日志创建数据
        db_session: 数据库会话

    Returns:
        DevLog: 新创建的日志

    Raises:
        HTTPException: 当任务不存在或创建失败时返回错误
    """
    run_account_id = _get_current_run_account_id(db_session)

    try:
        new_log = LogService.create_log(db_session, log_create_schema, run_account_id)
        new_log.task_title = new_log.task.task_title if new_log.task else ""
        return new_log
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error


@router.post("/parse-command", response_model=CommandParseResultSchema)
def parse_command(
    text: str,
) -> CommandParseResultSchema:
    """解析输入文本中的命令.

    Args:
        text: 用户输入的原始文本

    Returns:
        CommandParseResultSchema: 命令解析结果
    """
    return LogService.parse_command(text)


@router.post("/create-with-command", response_model=DevLogResponseSchema)
def create_log_with_command(
    text: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> DevLog:
    """解析命令并创建日志.

    如果解析到 /task 命令，会先创建/切换任务，然后创建日志。

    Args:
        text: 用户输入的原始文本（可能包含命令）
        db_session: 数据库会话

    Returns:
        DevLog: 新创建的日志
    """
    run_account_id = _get_current_run_account_id(db_session)

    # 解析命令
    command_result = LogService.parse_command(text)

    # 处理 /task 命令
    if command_result.is_command and command_result.command_type == "task":
        if command_result.task_title:
            # 创建新任务
            from dsl.schemas.task_schema import TaskCreateSchema

            task_create = TaskCreateSchema(task_title=command_result.task_title)
            TaskService.create_task(db_session, task_create, run_account_id)
            logger.info(f"Created task from command: {command_result.task_title}")
        # 返回空，表示任务创建成功但没有日志
        raise HTTPException(
            status_code=status.HTTP_200_OK,
            detail="Task created/switched successfully",
        )

    # 创建日志
    log_create = DevLogCreateSchema(
        text_content=command_result.content,
        state_tag=command_result.state_tag,
    )

    try:
        new_log = LogService.create_log(db_session, log_create, run_account_id)

        # 检查是否为 /fix 命令，如果是，检查是否需要关闭任务
        if command_result.is_command and command_result.command_type == "fix":
            _check_and_suggest_close_task(db_session, new_log.task_id)

        new_log.task_title = new_log.task.task_title if new_log.task else ""
        return new_log
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error


def _check_and_suggest_close_task(db_session: Session, task_id: str) -> None:
    """检查任务是否所有 Bug 都已修复，如果是则提示关闭任务.

    Args:
        db_session: 数据库会话
        task_id: 任务 ID
    """
    from dsl.models.enums import DevLogStateTag

    bug_count = LogService.count_logs_by_state(db_session, task_id, DevLogStateTag.BUG)
    fix_count = LogService.count_logs_by_state(
        db_session, task_id, DevLogStateTag.FIXED
    )

    if bug_count > 0 and fix_count >= bug_count:
        logger.info(
            f"Task {task_id[:8]}... has {bug_count} bugs and {fix_count} fixes. "
            "Suggest closing the task."
        )


@router.get("/review-queue", response_model=list[DevLogWithAIRSchema])
def get_review_queue(
    db_session: Annotated[Session, Depends(get_db)],
) -> list[DevLog]:
    """获取待校正的日志队列.

    Args:
        db_session: 数据库会话

    Returns:
        list[DevLog]: 待校正的日志列表
    """
    run_account_id = _get_current_run_account_id(db_session)
    logs = LogService.get_review_queue(db_session, run_account_id)

    for log in logs:
        log.task_title = log.task.task_title if log.task else ""

    return logs


@router.put("/{log_id}/ai-review", response_model=DevLogWithAIRSchema)
def update_ai_review(
    log_id: str,
    review_update: AIReviewUpdateSchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> DevLog:
    """更新 AI 校正结果.

    Args:
        log_id: 日志 ID
        review_update: 校正更新数据
        db_session: 数据库会话

    Returns:
        DevLog: 更新后的日志

    Raises:
        HTTPException: 当日志不存在时返回 404
    """
    log = LogService.update_ai_review(
        db_session,
        log_id,
        review_update.action,
        review_update.ai_generated_title,
        review_update.ai_analysis_text,
        review_update.ai_extracted_code,
    )

    if not log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Log with id {log_id} not found",
        )

    log.task_title = log.task.task_title if log.task else ""
    return log
