"""邮件设置 Pydantic Schema 定义.

用于 API 请求/响应的数据验证和序列化.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from dsl.schemas.base import DSLResponseSchema


class EmailSettingsUpdate(BaseModel):
    """更新邮件设置的请求体.

    Attributes:
        smtp_host (str): SMTP 服务器地址
        smtp_port (int): SMTP 端口号（1-65535）
        smtp_username (str): SMTP 登录用户名
        smtp_password (str): SMTP 登录密码
        smtp_use_ssl (bool): 是否使用 SSL 加密
        receiver_email (str): 通知接收地址
        is_enabled (bool): 是否启用邮件通知
        stalled_task_threshold_minutes (int): 停滞提醒阈值（分钟）
    """

    smtp_host: str = Field(..., max_length=255, description="SMTP 服务器地址")
    smtp_port: int = Field(..., ge=1, le=65535, description="SMTP 端口号")
    smtp_username: str = Field(..., max_length=255, description="SMTP 用户名")
    smtp_password: str = Field(..., max_length=255, description="SMTP 密码")
    smtp_use_ssl: bool = Field(
        True, description="是否使用 SSL（True=465，False=587+STARTTLS）"
    )
    receiver_email: str = Field(..., max_length=255, description="通知接收邮件地址")
    is_enabled: bool = Field(True, description="是否启用邮件通知")
    stalled_task_threshold_minutes: int = Field(
        default=20,
        ge=1,
        le=1440,
        description="停滞提醒阈值（分钟）",
    )


class EmailSettingsResponse(DSLResponseSchema):
    """邮件设置的响应体（密码脱敏）.

    Attributes:
        id (int): 记录 ID
        smtp_host (str): SMTP 服务器地址
        smtp_port (int): SMTP 端口号
        smtp_username (str): SMTP 用户名
        smtp_password_masked (str): 已脱敏的密码（仅显示部分字符）
        smtp_use_ssl (bool): 是否使用 SSL
        receiver_email (str): 接收邮件地址
        is_enabled (bool): 是否启用
        stalled_task_threshold_minutes (int): 停滞提醒阈值（分钟）
        created_at (datetime): 创建时间
        updated_at (datetime): 更新时间
    """

    id: int
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password_masked: str
    smtp_use_ssl: bool
    receiver_email: str
    is_enabled: bool
    stalled_task_threshold_minutes: int
    created_at: datetime
    updated_at: datetime


class EmailTestRequest(BaseModel):
    """发送测试邮件的请求体.

    Attributes:
        subject (str): 邮件主题
        body (str): 邮件正文
    """

    subject: str = Field(default="Koda 测试邮件", max_length=200)
    body: str = Field(default="这是一封来自 Koda 的测试邮件，配置成功！")
