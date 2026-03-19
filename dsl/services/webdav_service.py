"""WebDAV 同步服务模块.

使用 Python 标准库 urllib 实现 WebDAV 文件上传/下载和连接测试，
无需额外依赖。支持 Basic Auth，兼容 Nextcloud、坚果云、ownCloud 等主流 WebDAV 服务.
"""

import base64
import shutil
import urllib.error
import urllib.request
from pathlib import Path

from utils.logger import logger
from utils.settings import config


def _build_basic_auth_header(username_str: str, password_str: str) -> str:
    """生成 HTTP Basic Auth 请求头值.

    Args:
        username_str: 用户名
        password_str: 密码

    Returns:
        str: 形如 'Basic <base64编码>' 的字符串
    """
    credentials_bytes = f"{username_str}:{password_str}".encode("utf-8")
    encoded_credentials_str = base64.b64encode(credentials_bytes).decode("ascii")
    return f"Basic {encoded_credentials_str}"


def _normalize_remote_dir_url(server_url_str: str, remote_path_str: str) -> str:
    """拼接服务器 URL 和远端目录路径，确保末尾有斜杠.

    Args:
        server_url_str: WebDAV 服务器基础 URL
        remote_path_str: 远端目录路径

    Returns:
        str: 完整的远端目录 URL
    """
    base_url_str = server_url_str.rstrip("/")
    clean_remote_path_str = remote_path_str.strip("/")
    if clean_remote_path_str:
        return f"{base_url_str}/{clean_remote_path_str}/"
    return f"{base_url_str}/"


def _load_webdav_settings_from_db():
    """从数据库读取 WebDAV 设置（同步）.

    Returns:
        WebDAVSettings | None: WebDAV 设置对象，若未配置返回 None
    """
    from dsl.models.webdav_settings import WebDAVSettings
    from utils.database import SessionLocal

    db_session = SessionLocal()
    try:
        webdav_settings_obj = (
            db_session.query(WebDAVSettings).filter(WebDAVSettings.id == 1).first()
        )
        return webdav_settings_obj
    except Exception as db_load_error:
        logger.error(f"Failed to load WebDAV settings: {db_load_error}")
        return None
    finally:
        db_session.close()


def _build_repo_relink_hint_message() -> str:
    """生成 WebDAV 恢复后的项目路径修复提示.

    Returns:
        str: 追加到同步结果后的提示语；若无需提示则返回空字符串
    """
    from dsl.models.project import Project
    from dsl.services.project_service import ProjectService
    from utils.database import SessionLocal

    db_session = SessionLocal()
    try:
        project_list = db_session.query(Project).all()
        invalid_project_count_int = 0
        head_mismatch_project_count_int = 0
        for project_obj in project_list:
            if not ProjectService.is_repo_path_valid(project_obj.repo_path):
                invalid_project_count_int += 1
                continue

            consistency_snapshot = ProjectService.build_project_consistency_snapshot(
                project_obj
            )
            if consistency_snapshot.is_repo_head_consistent is False:
                head_mismatch_project_count_int += 1
    except Exception as relink_hint_error:
        logger.error(
            f"Failed to inspect project repo paths after WebDAV restore: {relink_hint_error}"
        )
        return ""
    finally:
        db_session.close()

    if invalid_project_count_int == 0 and head_mismatch_project_count_int == 0:
        return ""

    hint_message_part_list: list[str] = []
    if invalid_project_count_int > 0:
        project_label_str = "project" if invalid_project_count_int == 1 else "projects"
        hint_message_part_list.append(
            f"{invalid_project_count_int} synced {project_label_str} still point to "
            "paths from another machine and should be relinked in Project settings"
        )
    if head_mismatch_project_count_int > 0:
        project_label_str = (
            "project" if head_mismatch_project_count_int == 1 else "projects"
        )
        hint_message_part_list.append(
            f"{head_mismatch_project_count_int} {project_label_str} already match the repo "
            "path but are on a different HEAD commit than the synced fingerprint"
        )

    return " " + "; ".join(hint_message_part_list) + "."


def test_webdav_connection(
    server_url_str: str,
    username_str: str,
    password_str: str,
    remote_path_str: str,
) -> tuple[bool, str]:
    """测试 WebDAV 服务器连接（PROPFIND 请求）.

    Args:
        server_url_str: WebDAV 服务器 URL
        username_str: 用户名
        password_str: 密码
        remote_path_str: 远端路径

    Returns:
        tuple[bool, str]: (是否成功, 描述信息)
    """
    remote_dir_url_str = _normalize_remote_dir_url(server_url_str, remote_path_str)
    auth_header_str = _build_basic_auth_header(username_str, password_str)

    propfind_request_obj = urllib.request.Request(
        url=remote_dir_url_str,
        method="PROPFIND",
        headers={
            "Authorization": auth_header_str,
            "Depth": "0",
            "Content-Type": "application/xml",
        },
        data=b'<?xml version="1.0" encoding="utf-8"?><propfind xmlns="DAV:"><prop/></propfind>',
    )

    try:
        with urllib.request.urlopen(
            propfind_request_obj, timeout=10
        ) as http_response_obj:
            status_code_int = http_response_obj.status
            if status_code_int in (207, 200):
                return True, f"Connected successfully (HTTP {status_code_int})"
            return False, f"Unexpected status: HTTP {status_code_int}"
    except urllib.error.HTTPError as http_error:
        if http_error.code == 404:
            # 路径不存在时尝试创建
            mkcol_success_bool, mkcol_message_str = _ensure_remote_directory(
                remote_dir_url_str, auth_header_str
            )
            if mkcol_success_bool:
                return True, "Remote directory created and connection verified."
            return (
                False,
                f"Remote path not found and could not create: {mkcol_message_str}",
            )
        if http_error.code == 401:
            return False, "Authentication failed (HTTP 401). Check username/password."
        return False, f"HTTP error: {http_error.code} {http_error.reason}"
    except urllib.error.URLError as url_error:
        return False, f"Connection failed: {url_error.reason}"
    except Exception as unexpected_error:
        return False, f"Unexpected error: {unexpected_error}"


def _ensure_remote_directory(
    remote_dir_url_str: str, auth_header_str: str
) -> tuple[bool, str]:
    """通过 MKCOL 在 WebDAV 服务器上创建目录.

    Args:
        remote_dir_url_str: 完整的远端目录 URL
        auth_header_str: Authorization 请求头值

    Returns:
        tuple[bool, str]: (是否成功, 描述信息)
    """
    mkcol_request_obj = urllib.request.Request(
        url=remote_dir_url_str,
        method="MKCOL",
        headers={"Authorization": auth_header_str},
    )
    try:
        with urllib.request.urlopen(
            mkcol_request_obj, timeout=10
        ) as mkcol_response_obj:
            if mkcol_response_obj.status in (201, 200, 405):
                # 405 = already exists, 201 = created
                return True, "Directory ready."
        return False, "MKCOL returned unexpected status."
    except urllib.error.HTTPError as mkcol_http_error:
        if mkcol_http_error.code == 405:
            # Already exists — that's fine
            return True, "Directory already exists."
        return False, f"MKCOL failed: HTTP {mkcol_http_error.code}"
    except Exception as mkcol_unexpected_error:
        return False, f"MKCOL failed: {mkcol_unexpected_error}"


def upload_file_to_webdav(
    local_file_path: Path,
    server_url_str: str,
    username_str: str,
    password_str: str,
    remote_path_str: str,
) -> tuple[bool, str, str | None]:
    """将本地文件上传到 WebDAV 服务器.

    Args:
        local_file_path: 本地文件路径
        server_url_str: WebDAV 服务器 URL
        username_str: 用户名
        password_str: 密码
        remote_path_str: 远端目录路径

    Returns:
        tuple[bool, str, str | None]: (是否成功, 描述信息, 远端文件 URL)
    """
    if not local_file_path.exists():
        return False, f"Local file not found: {local_file_path}", None

    auth_header_str = _build_basic_auth_header(username_str, password_str)
    remote_dir_url_str = _normalize_remote_dir_url(server_url_str, remote_path_str)

    # 确保远端目录存在
    _ensure_remote_directory(remote_dir_url_str, auth_header_str)

    remote_file_url_str = f"{remote_dir_url_str}{local_file_path.name}"

    with open(local_file_path, "rb") as local_file_obj:
        file_bytes_data = local_file_obj.read()

    put_request_obj = urllib.request.Request(
        url=remote_file_url_str,
        data=file_bytes_data,
        method="PUT",
        headers={
            "Authorization": auth_header_str,
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(file_bytes_data)),
        },
    )

    try:
        with urllib.request.urlopen(put_request_obj, timeout=30) as put_response_obj:
            status_code_int = put_response_obj.status
            if status_code_int in (200, 201, 204):
                logger.info(
                    f"WebDAV upload success: {local_file_path.name} → {remote_file_url_str}"
                )
                return (
                    True,
                    f"Uploaded {local_file_path.name} ({len(file_bytes_data)} bytes)",
                    remote_file_url_str,
                )
            return False, f"Unexpected status: HTTP {status_code_int}", None
    except urllib.error.HTTPError as http_error:
        error_message_str = f"HTTP {http_error.code}: {http_error.reason}"
        logger.error(f"WebDAV upload failed: {error_message_str}")
        return False, error_message_str, None
    except urllib.error.URLError as url_error:
        error_message_str = f"Connection error: {url_error.reason}"
        logger.error(f"WebDAV upload failed: {error_message_str}")
        return False, error_message_str, None
    except Exception as unexpected_error:
        logger.error(f"WebDAV upload unexpected error: {unexpected_error}")
        return False, str(unexpected_error), None


def download_file_from_webdav(
    remote_filename_str: str,
    local_dest_path: Path,
    server_url_str: str,
    username_str: str,
    password_str: str,
    remote_path_str: str,
) -> tuple[bool, str]:
    """从 WebDAV 服务器下载文件到本地.

    Args:
        remote_filename_str: 远端文件名（不含路径）
        local_dest_path: 本地目标文件路径
        server_url_str: WebDAV 服务器 URL
        username_str: 用户名
        password_str: 密码
        remote_path_str: 远端目录路径

    Returns:
        tuple[bool, str]: (是否成功, 描述信息)
    """
    auth_header_str = _build_basic_auth_header(username_str, password_str)
    remote_dir_url_str = _normalize_remote_dir_url(server_url_str, remote_path_str)
    remote_file_url_str = f"{remote_dir_url_str}{remote_filename_str}"

    get_request_obj = urllib.request.Request(
        url=remote_file_url_str,
        method="GET",
        headers={"Authorization": auth_header_str},
    )

    try:
        with urllib.request.urlopen(get_request_obj, timeout=30) as get_response_obj:
            local_dest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_dest_path, "wb") as local_file_obj:
                shutil.copyfileobj(get_response_obj, local_file_obj)

        downloaded_size_bytes = local_dest_path.stat().st_size
        logger.info(
            f"WebDAV download success: {remote_filename_str} → {local_dest_path} "
            f"({downloaded_size_bytes} bytes)"
        )
        return True, f"Downloaded {remote_filename_str} ({downloaded_size_bytes} bytes)"
    except urllib.error.HTTPError as http_error:
        error_message_str = f"HTTP {http_error.code}: {http_error.reason}"
        logger.error(f"WebDAV download failed: {error_message_str}")
        return False, error_message_str
    except urllib.error.URLError as url_error:
        error_message_str = f"Connection error: {url_error.reason}"
        logger.error(f"WebDAV download failed: {error_message_str}")
        return False, error_message_str
    except Exception as unexpected_error:
        logger.error(f"WebDAV download unexpected error: {unexpected_error}")
        return False, str(unexpected_error)


def sync_database_to_webdav() -> tuple[bool, str, str | None]:
    """将当前 SQLite 数据库备份并上传到 WebDAV（同步，供 asyncio.to_thread 使用）.

    Returns:
        tuple[bool, str, str | None]: (是否成功, 描述信息, 远端 URL)
    """
    webdav_settings_obj = _load_webdav_settings_from_db()

    if not webdav_settings_obj:
        return False, "WebDAV settings not configured.", None

    if not webdav_settings_obj.is_enabled:
        return False, "WebDAV sync is disabled.", None

    required_fields_list = [
        webdav_settings_obj.server_url,
        webdav_settings_obj.username,
        webdav_settings_obj.password,
    ]
    if not all(required_fields_list):
        return False, "WebDAV settings are incomplete.", None

    from dsl.services.project_service import ProjectService
    from utils.database import SessionLocal

    db_session = SessionLocal()
    try:
        refreshed_project_count_int = ProjectService.refresh_project_repo_fingerprints(
            db_session,
            only_missing=False,
        )
        if refreshed_project_count_int > 0:
            logger.info(
                "Refreshed repo fingerprints for %s projects before WebDAV upload",
                refreshed_project_count_int,
            )
    finally:
        db_session.close()

    db_url_str = config.DATABASE_URL
    # 仅处理 SQLite 本地文件
    if not db_url_str.startswith("sqlite:///"):
        return False, "Only SQLite databases are supported for WebDAV sync.", None

    db_file_path = Path(db_url_str.replace("sqlite:///", ""))
    if not db_file_path.is_absolute():
        db_file_path = config.BASE_DIR / db_file_path

    upload_success_bool, upload_message_str, remote_url_str = upload_file_to_webdav(
        local_file_path=db_file_path,
        server_url_str=webdav_settings_obj.server_url,
        username_str=webdav_settings_obj.username,
        password_str=webdav_settings_obj.password,
        remote_path_str=webdav_settings_obj.remote_path,
    )
    return upload_success_bool, upload_message_str, remote_url_str


def restore_database_from_webdav() -> tuple[bool, str]:
    """从 WebDAV 下载数据库备份并覆盖本地（同步，供 asyncio.to_thread 使用）.

    **警告**：此操作会覆盖本地数据库，调用前请确保用户已确认。

    Returns:
        tuple[bool, str]: (是否成功, 描述信息)
    """
    webdav_settings_obj = _load_webdav_settings_from_db()

    if not webdav_settings_obj:
        return False, "WebDAV settings not configured."

    if not webdav_settings_obj.is_enabled:
        return False, "WebDAV sync is disabled."

    db_url_str = config.DATABASE_URL
    if not db_url_str.startswith("sqlite:///"):
        return False, "Only SQLite databases are supported for WebDAV sync."

    db_file_path = Path(db_url_str.replace("sqlite:///", ""))
    if not db_file_path.is_absolute():
        db_file_path = config.BASE_DIR / db_file_path

    download_success_bool, download_message_str = download_file_from_webdav(
        remote_filename_str=db_file_path.name,
        local_dest_path=db_file_path,
        server_url_str=webdav_settings_obj.server_url,
        username_str=webdav_settings_obj.username,
        password_str=webdav_settings_obj.password,
        remote_path_str=webdav_settings_obj.remote_path,
    )
    if not download_success_bool:
        return False, download_message_str

    relink_hint_message_str = _build_repo_relink_hint_message()
    return True, f"{download_message_str}{relink_hint_message_str}"
