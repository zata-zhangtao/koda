"""WebDAV 同步设置数据模型.

存储 WebDAV 服务器连接配置，用于数据库备份/同步功能.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from utils.database import Base
from utils.helpers import utc_now_naive


class WebDAVSettings(Base):
    """WebDAV 同步设置模型.

    全局唯一一条记录（id=1），存储 WebDAV 服务器地址和认证信息.

    Attributes:
        id (int): 主键，固定为 1（单例模式）
        server_url (str): WebDAV 服务器基础 URL（如 https://dav.example.com/remote.php/dav/files/user/）
        username (str): WebDAV 登录用户名
        password (str): WebDAV 登录密码
        remote_path (str): 远程存储路径（如 /koda-backup/）
        is_enabled (bool): 是否启用 WebDAV 同步
        created_at (datetime): 创建时间
        updated_at (datetime): 最后更新时间
    """

    __tablename__ = "webdav_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    server_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    username: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    password: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    remote_path: Mapped[str] = mapped_column(
        String(512), nullable=False, default="/koda-backup/"
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive
    )
