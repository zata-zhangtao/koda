"""邮件通知设置 API 路由.

提供邮件 SMTP 配置的读取、保存和测试发送功能.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from dsl.models.email_settings import EmailSettings
from dsl.schemas.email_settings_schema import (
    EmailSettingsResponse,
    EmailSettingsUpdate,
    EmailTestRequest,
)
from dsl.services.email_service import send_notification_email
from utils.database import get_db
from utils.helpers import utc_now_naive
from utils.logger import logger

router = APIRouter(prefix="/api/email-settings", tags=["email-settings"])


def _to_response(email_settings_obj: EmailSettings) -> EmailSettingsResponse:
    """将 ORM 模型转换为响应 Schema，并对密码进行脱敏处理.

    Args:
        email_settings_obj: EmailSettings ORM 实例

    Returns:
        EmailSettingsResponse: 脱敏后的响应对象
    """
    raw_password_str = email_settings_obj.smtp_password or ""
    if len(raw_password_str) <= 2:
        masked_password_str = "*" * len(raw_password_str)
    else:
        masked_password_str = (
            raw_password_str[0] + "*" * (len(raw_password_str) - 2) + raw_password_str[-1]
        )

    return EmailSettingsResponse(
        id=email_settings_obj.id,
        smtp_host=email_settings_obj.smtp_host,
        smtp_port=email_settings_obj.smtp_port,
        smtp_username=email_settings_obj.smtp_username,
        smtp_password_masked=masked_password_str,
        smtp_use_ssl=email_settings_obj.smtp_use_ssl,
        receiver_email=email_settings_obj.receiver_email,
        is_enabled=email_settings_obj.is_enabled,
        created_at=email_settings_obj.created_at,
        updated_at=email_settings_obj.updated_at,
    )


@router.get("", response_model=EmailSettingsResponse)
def get_email_settings(db: Session = Depends(get_db)) -> EmailSettingsResponse:
    """获取当前邮件通知设置.

    若尚未配置，返回 404.

    Args:
        db: 数据库会话

    Returns:
        EmailSettingsResponse: 当前邮件设置（密码脱敏）

    Raises:
        HTTPException: 404 若尚未配置
    """
    email_settings_obj = db.query(EmailSettings).filter(EmailSettings.id == 1).first()
    if not email_settings_obj:
        raise HTTPException(status_code=404, detail="Email settings not configured yet.")
    return _to_response(email_settings_obj)


@router.put("", response_model=EmailSettingsResponse)
def upsert_email_settings(
    update_payload: EmailSettingsUpdate,
    db: Session = Depends(get_db),
) -> EmailSettingsResponse:
    """创建或更新邮件通知设置（单例，id=1）.

    Args:
        update_payload: 更新数据
        db: 数据库会话

    Returns:
        EmailSettingsResponse: 保存后的邮件设置（密码脱敏）
    """
    existing_email_settings_obj = db.query(EmailSettings).filter(EmailSettings.id == 1).first()

    if existing_email_settings_obj:
        existing_email_settings_obj.smtp_host = update_payload.smtp_host
        existing_email_settings_obj.smtp_port = update_payload.smtp_port
        existing_email_settings_obj.smtp_username = update_payload.smtp_username
        existing_email_settings_obj.smtp_password = update_payload.smtp_password
        existing_email_settings_obj.smtp_use_ssl = update_payload.smtp_use_ssl
        existing_email_settings_obj.receiver_email = update_payload.receiver_email
        existing_email_settings_obj.is_enabled = update_payload.is_enabled
        existing_email_settings_obj.updated_at = utc_now_naive()
        saved_email_settings_obj = existing_email_settings_obj
    else:
        new_email_settings_obj = EmailSettings(
            id=1,
            smtp_host=update_payload.smtp_host,
            smtp_port=update_payload.smtp_port,
            smtp_username=update_payload.smtp_username,
            smtp_password=update_payload.smtp_password,
            smtp_use_ssl=update_payload.smtp_use_ssl,
            receiver_email=update_payload.receiver_email,
            is_enabled=update_payload.is_enabled,
        )
        db.add(new_email_settings_obj)
        saved_email_settings_obj = new_email_settings_obj

    db.commit()
    db.refresh(saved_email_settings_obj)
    logger.info(
        f"Email settings saved: host={update_payload.smtp_host}, "
        f"receiver={update_payload.receiver_email}, enabled={update_payload.is_enabled}"
    )
    return _to_response(saved_email_settings_obj)


@router.post("/test")
def test_email_settings(
    test_request: EmailTestRequest,
    db: Session = Depends(get_db),
) -> dict:
    """使用当前 SMTP 配置发送一封测试邮件.

    Args:
        test_request: 测试邮件主题和正文
        db: 数据库会话

    Returns:
        dict: 发送结果

    Raises:
        HTTPException: 404 若尚未配置，422 若配置不完整
    """
    email_settings_obj = db.query(EmailSettings).filter(EmailSettings.id == 1).first()
    if not email_settings_obj:
        raise HTTPException(status_code=404, detail="Email settings not configured yet.")

    if not email_settings_obj.is_enabled:
        raise HTTPException(status_code=422, detail="Email notifications are disabled. Please enable them first.")

    required_fields_list = [
        email_settings_obj.smtp_host,
        email_settings_obj.smtp_username,
        email_settings_obj.smtp_password,
        email_settings_obj.receiver_email,
    ]
    if not all(required_fields_list):
        raise HTTPException(status_code=422, detail="Email settings are incomplete.")

    body_html_str = f"""
<html>
<body style="font-family: sans-serif; color: #333; line-height: 1.6;">
  <h2 style="color: #16a34a;">✅ Koda 邮件配置测试</h2>
  <p>{test_request.body}</p>
  <p style="color: #666; font-size: 12px;">此邮件由 Koda 自动发送，请勿回复。</p>
</body>
</html>
"""
    send_success_bool = send_notification_email(test_request.subject, body_html_str)

    if send_success_bool:
        return {"success": True, "message": f"Test email sent to {email_settings_obj.receiver_email}"}
    else:
        raise HTTPException(
            status_code=500,
            detail="Failed to send test email. Please check SMTP configuration and logs.",
        )
