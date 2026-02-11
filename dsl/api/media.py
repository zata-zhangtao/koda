"""Media API 路由.

提供图片上传、缩略图生成和文件服务功能.
"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from dsl.models.dev_log import DevLog
from dsl.models.enums import AIProcessingStatus
from dsl.schemas.dev_log_schema import DevLogResponseSchema
from dsl.services.log_service import LogService
from dsl.services.media_service import MediaService
from utils.database import get_db
from utils.logger import logger

router = APIRouter(prefix="/api/media", tags=["media"])


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


@router.post("/upload", response_model=DevLogResponseSchema)
async def upload_image(
    uploaded_image_file: UploadFile,
    text_content: str = "",
    db_session: Annotated[Session, Depends(get_db)] = None,
) -> DevLog:
    """上传图片并创建日志.

    上传图片后，会自动生成缩略图并创建一条包含图片的日志。
    在 Phase 2 中，会触发 AI 异步解析。

    Args:
        uploaded_image_file: 上传的图片文件
        text_content: 关联的文本内容（可选）
        db_session: 数据库会话

    Returns:
        DevLog: 新创建的日志（包含图片）

    Raises:
        HTTPException: 当上传失败时返回错误
    """
    run_account_id = _get_current_run_account_id(db_session)

    try:
        # 保存图片并生成缩略图
        original_path, thumbnail_path = await MediaService.save_image(uploaded_image_file)

        # 创建日志（Phase 1: AI 处理状态设为 PENDING，Phase 2 实现异步处理）
        from dsl.schemas.dev_log_schema import DevLogCreateSchema

        log_create = DevLogCreateSchema(
            text_content=text_content,
            media_original_image_path=original_path,
            media_thumbnail_path=thumbnail_path,
            # Phase 2: 启用 AI 处理
            # ai_processing_status=AIProcessingStatus.PENDING,
        )

        new_log = LogService.create_log(db_session, log_create, run_account_id)

        # Phase 2: 触发 AI 异步解析
        # await trigger_ai_analysis(new_log.id, original_path)

        new_log.task_title = new_log.task.task_title if new_log.task else ""

        logger.info(f"Created image log: {new_log.id[:8]}...")
        return new_log

    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error
    except Exception as error:
        logger.error(f"Failed to upload image: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process image: {error}",
        ) from error


@router.get("/{filename}")
def get_image(
    filename: str,
    thumbnail: bool = False,
) -> FileResponse:
    """获取图片文件.

    Args:
        filename: 文件名
        thumbnail: 是否返回缩略图

    Returns:
        FileResponse: 图片文件响应

    Raises:
        HTTPException: 当文件不存在时返回 404
    """
    file_path = MediaService.get_image_path(filename, thumbnail)

    if not file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Image {filename} not found",
        )

    # 根据文件扩展名确定 media_type
    media_type = "image/png"
    if file_path.suffix.lower() in (".jpg", ".jpeg"):
        media_type = "image/jpeg"
    elif file_path.suffix.lower() == ".gif":
        media_type = "image/gif"
    elif file_path.suffix.lower() == ".webp":
        media_type = "image/webp"

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename,
    )
