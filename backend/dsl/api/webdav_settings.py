"""WebDAV 存储设置 API 路由.

提供 WebDAV 配置的读取、保存、连接测试，以及手动触发数据库备份/恢复
与业务快照同步功能.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.dsl.models.webdav_settings import WebDAVSettings
from backend.dsl.schemas.webdav_settings_schema import (
    WebDAVSettingsResponse,
    WebDAVSettingsUpdate,
    WebDAVSyncResult,
)
from backend.dsl.services.webdav_business_sync_service import (
    restore_business_snapshot_from_webdav,
    sync_business_snapshot_to_webdav,
)
from backend.dsl.services.webdav_service import (
    restore_database_from_webdav,
    sync_database_to_webdav,
    test_webdav_connection,
)
from utils.database import get_db
from utils.helpers import utc_now_naive
from utils.logger import logger

router = APIRouter(prefix="/api/webdav-settings", tags=["webdav-settings"])


def _mask_password(raw_password_str: str) -> str:
    """对密码进行脱敏处理.

    Args:
        raw_password_str: 原始密码

    Returns:
        str: 脱敏后的密码字符串
    """
    if len(raw_password_str) <= 2:
        return "*" * len(raw_password_str)
    return (
        raw_password_str[0] + "*" * (len(raw_password_str) - 2) + raw_password_str[-1]
    )


def _to_response(webdav_settings_obj: WebDAVSettings) -> WebDAVSettingsResponse:
    """将 ORM 模型转换为响应 Schema（密码脱敏）.

    Args:
        webdav_settings_obj: WebDAVSettings ORM 实例

    Returns:
        WebDAVSettingsResponse: 脱敏后的响应对象
    """
    return WebDAVSettingsResponse(
        id=webdav_settings_obj.id,
        server_url=webdav_settings_obj.server_url,
        username=webdav_settings_obj.username,
        password_masked=_mask_password(webdav_settings_obj.password or ""),
        remote_path=webdav_settings_obj.remote_path,
        is_enabled=webdav_settings_obj.is_enabled,
        created_at=webdav_settings_obj.created_at,
        updated_at=webdav_settings_obj.updated_at,
    )


@router.get("", response_model=WebDAVSettingsResponse)
def get_webdav_settings(db: Session = Depends(get_db)) -> WebDAVSettingsResponse:
    """获取当前 WebDAV 存储设置.

    Args:
        db: 数据库会话

    Returns:
        WebDAVSettingsResponse: 当前 WebDAV 配置（密码脱敏）

    Raises:
        HTTPException: 404 若尚未配置
    """
    webdav_settings_obj = (
        db.query(WebDAVSettings).filter(WebDAVSettings.id == 1).first()
    )
    if not webdav_settings_obj:
        raise HTTPException(
            status_code=404, detail="WebDAV settings not configured yet."
        )
    return _to_response(webdav_settings_obj)


@router.put("", response_model=WebDAVSettingsResponse)
def upsert_webdav_settings(
    update_payload: WebDAVSettingsUpdate,
    db: Session = Depends(get_db),
) -> WebDAVSettingsResponse:
    """创建或更新 WebDAV 存储设置（单例，id=1）.

    Args:
        update_payload: 更新数据
        db: 数据库会话

    Returns:
        WebDAVSettingsResponse: 保存后的配置（密码脱敏）
    """
    existing_webdav_settings_obj = (
        db.query(WebDAVSettings).filter(WebDAVSettings.id == 1).first()
    )

    if existing_webdav_settings_obj:
        password_str = (
            update_payload.password
            if update_payload.password
            else existing_webdav_settings_obj.password
        )
        existing_webdav_settings_obj.server_url = update_payload.server_url
        existing_webdav_settings_obj.username = update_payload.username
        existing_webdav_settings_obj.password = password_str
        existing_webdav_settings_obj.remote_path = update_payload.remote_path
        existing_webdav_settings_obj.is_enabled = update_payload.is_enabled
        existing_webdav_settings_obj.updated_at = utc_now_naive()
        saved_webdav_settings_obj = existing_webdav_settings_obj
    else:
        new_webdav_settings_obj = WebDAVSettings(
            id=1,
            server_url=update_payload.server_url,
            username=update_payload.username,
            password=update_payload.password,
            remote_path=update_payload.remote_path,
            is_enabled=update_payload.is_enabled,
        )
        db.add(new_webdav_settings_obj)
        saved_webdav_settings_obj = new_webdav_settings_obj

    db.commit()
    db.refresh(saved_webdav_settings_obj)
    logger.info(
        f"WebDAV settings saved: url={update_payload.server_url}, "
        f"remote_path={update_payload.remote_path}, enabled={update_payload.is_enabled}"
    )
    return _to_response(saved_webdav_settings_obj)


@router.post("/test", response_model=WebDAVSyncResult)
def test_webdav(db: Session = Depends(get_db)) -> WebDAVSyncResult:
    """使用已保存的配置测试 WebDAV 连接（PROPFIND）.

    Args:
        db: 数据库会话

    Returns:
        WebDAVSyncResult: 连接测试结果

    Raises:
        HTTPException: 404 若尚未配置
    """
    webdav_settings_obj = (
        db.query(WebDAVSettings).filter(WebDAVSettings.id == 1).first()
    )
    if not webdav_settings_obj:
        raise HTTPException(
            status_code=404, detail="WebDAV settings not configured yet."
        )

    if not all([webdav_settings_obj.server_url, webdav_settings_obj.username]):
        raise HTTPException(status_code=422, detail="WebDAV settings are incomplete.")

    connection_success_bool, connection_message_str = test_webdav_connection(
        server_url_str=webdav_settings_obj.server_url,
        username_str=webdav_settings_obj.username,
        password_str=webdav_settings_obj.password,
        remote_path_str=webdav_settings_obj.remote_path,
    )
    return WebDAVSyncResult(
        success=connection_success_bool, message=connection_message_str
    )


@router.post("/sync/upload", response_model=WebDAVSyncResult)
def upload_database(db: Session = Depends(get_db)) -> WebDAVSyncResult:
    """将本地 SQLite 数据库备份上传到 WebDAV 服务器.

    Args:
        db: 数据库会话

    Returns:
        WebDAVSyncResult: 上传结果

    Raises:
        HTTPException: 500 若上传失败
    """
    upload_success_bool, upload_message_str, remote_url_str = sync_database_to_webdav()
    if not upload_success_bool:
        raise HTTPException(status_code=500, detail=upload_message_str)
    return WebDAVSyncResult(
        success=True,
        message=upload_message_str,
        remote_url=remote_url_str,
    )


@router.post("/sync/download", response_model=WebDAVSyncResult)
def download_database(db: Session = Depends(get_db)) -> WebDAVSyncResult:
    """从 WebDAV 服务器恢复数据库并覆盖本地（危险操作，需用户确认）.

    Args:
        db: 数据库会话

    Returns:
        WebDAVSyncResult: 下载结果

    Raises:
        HTTPException: 500 若下载失败
    """
    download_success_bool, download_message_str = restore_database_from_webdav()
    if not download_success_bool:
        raise HTTPException(status_code=500, detail=download_message_str)
    return WebDAVSyncResult(success=True, message=download_message_str)


@router.post("/sync/business/upload", response_model=WebDAVSyncResult)
def upload_business_snapshot(db: Session = Depends(get_db)) -> WebDAVSyncResult:
    """将业务状态快照上传到 WebDAV 服务器.

    Args:
        db: 数据库会话

    Returns:
        WebDAVSyncResult: 上传结果

    Raises:
        HTTPException: 500 若上传失败
    """

    upload_success_bool, upload_message_str, remote_url_str = (
        sync_business_snapshot_to_webdav()
    )
    if not upload_success_bool:
        raise HTTPException(status_code=500, detail=upload_message_str)
    return WebDAVSyncResult(
        success=True,
        message=upload_message_str,
        remote_url=remote_url_str,
    )


@router.post("/sync/business/download", response_model=WebDAVSyncResult)
def download_business_snapshot(db: Session = Depends(get_db)) -> WebDAVSyncResult:
    """从 WebDAV 服务器导入业务状态快照.

    Args:
        db: 数据库会话

    Returns:
        WebDAVSyncResult: 导入结果

    Raises:
        HTTPException: 500 若导入失败
    """

    download_success_bool, download_message_str = (
        restore_business_snapshot_from_webdav()
    )
    if not download_success_bool:
        raise HTTPException(status_code=500, detail=download_message_str)
    return WebDAVSyncResult(success=True, message=download_message_str)
