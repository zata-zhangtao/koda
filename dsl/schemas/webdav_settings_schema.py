"""WebDAV 设置 Pydantic Schema 定义.

用于 API 请求/响应的数据验证和序列化.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from dsl.schemas.base import DSLResponseSchema


class WebDAVSettingsUpdate(BaseModel):
    """更新 WebDAV 设置的请求体.

    Attributes:
        server_url (str): WebDAV 服务器 URL
        username (str): 登录用户名
        password (str): 登录密码
        remote_path (str): 远端存储路径
        is_enabled (bool): 是否启用
    """

    server_url: str = Field(..., max_length=512, description="WebDAV 服务器 URL")
    username: str = Field(..., max_length=255, description="用户名")
    password: str = Field(..., max_length=255, description="密码")
    remote_path: str = Field("/koda-backup/", max_length=512, description="远端路径")
    is_enabled: bool = Field(True, description="是否启用 WebDAV 同步")


class WebDAVSettingsResponse(DSLResponseSchema):
    """WebDAV 设置响应体（密码脱敏）.

    Attributes:
        id (int): 记录 ID
        server_url (str): WebDAV 服务器 URL
        username (str): 用户名
        password_masked (str): 已脱敏的密码
        remote_path (str): 远端路径
        is_enabled (bool): 是否启用
        created_at (datetime): 创建时间
        updated_at (datetime): 更新时间
    """

    id: int
    server_url: str
    username: str
    password_masked: str
    remote_path: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime

class WebDAVSyncResult(BaseModel):
    """WebDAV 同步操作结果.

    Attributes:
        success (bool): 是否成功
        message (str): 结果描述
        remote_url (str | None): 已上传文件的远端 URL
    """

    success: bool
    message: str
    remote_url: str | None = None
