"""邮件通知设置数据模型.

存储 SMTP 配置和接收邮件地址，用于任务状态变更通知.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from utils.database import Base
from utils.helpers import utc_now_naive


class EmailSettings(Base):
    """邮件通知设置模型.

    全局唯一一条记录（id=1），存储 SMTP 连接参数和收件人地址.

    Attributes:
        id (int): 主键，固定为 1（单例模式）
        smtp_host (str): SMTP 服务器地址
        smtp_port (int): SMTP 服务器端口（默认 465/587）
        smtp_username (str): SMTP 登录用户名
        smtp_password (str): SMTP 登录密码（明文存储于本地 SQLite）
        smtp_use_ssl (bool): 是否使用 SSL（True=465，False=587+STARTTLS）
        receiver_email (str): 通知接收邮件地址
        is_enabled (bool): 是否启用邮件通知
        created_at (datetime): 创建时间
        updated_at (datetime): 最后更新时间
    """

    __tablename__ = "email_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    smtp_host: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=465)
    smtp_username: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    smtp_password: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    smtp_use_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    receiver_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive
    )
