"""邮件发送底座服务.

负责加载 SMTP 配置并发送 HTML 通知邮件，供统一任务通知服务复用.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from utils.logger import logger


@dataclass(frozen=True)
class EmailDeliveryResult:
    """邮件投递结果.

    Attributes:
        success (bool): 是否发送成功
        receiver_email (str | None): 发送时使用的收件人地址
        failure_message (str | None): 失败或跳过原因
    """

    success: bool
    receiver_email: str | None
    failure_message: str | None = None


def _mask_password(raw_password_str: str) -> str:
    """对密码进行脱敏处理，仅保留首尾各 1 个字符.

    Args:
        raw_password_str: 原始密码字符串

    Returns:
        str: 脱敏后的密码字符串
    """
    if len(raw_password_str) <= 2:
        return "*" * len(raw_password_str)
    return (
        raw_password_str[0] + "*" * (len(raw_password_str) - 2) + raw_password_str[-1]
    )


def load_email_settings_from_db():
    """从数据库加载邮件设置（同步）.

    Returns:
        EmailSettings | None: 邮件设置对象，若未配置则返回 None
    """
    from dsl.models.email_settings import EmailSettings
    from utils.database import SessionLocal

    db_session = SessionLocal()
    try:
        email_settings_obj = (
            db_session.query(EmailSettings).filter(EmailSettings.id == 1).first()
        )
        if email_settings_obj is not None:
            db_session.expunge(email_settings_obj)
        return email_settings_obj
    except Exception as db_load_error:
        logger.error(f"Failed to load email settings: {db_load_error}")
        return None
    finally:
        db_session.close()


def send_notification_email_via_settings(
    email_settings_obj,
    subject_str: str,
    body_html_str: str,
) -> EmailDeliveryResult:
    """使用指定的邮件设置发送 HTML 格式通知邮件.

    Args:
        email_settings_obj: EmailSettings ORM 对象，可为 None
        subject_str: 邮件主题
        body_html_str: 邮件正文（HTML 格式）

    Returns:
        EmailDeliveryResult: 结构化发送结果
    """
    if not email_settings_obj:
        logger.debug("Email settings not found, skipping notification.")
        return EmailDeliveryResult(
            success=False,
            receiver_email=None,
            failure_message="Email settings not configured.",
        )

    receiver_email_str = email_settings_obj.receiver_email or None
    if not email_settings_obj.is_enabled:
        logger.debug("Email notifications disabled, skipping.")
        return EmailDeliveryResult(
            success=False,
            receiver_email=receiver_email_str,
            failure_message="Email notifications are disabled.",
        )

    required_fields_list = [
        email_settings_obj.smtp_host,
        email_settings_obj.smtp_username,
        email_settings_obj.smtp_password,
        email_settings_obj.receiver_email,
    ]
    if not all(required_fields_list):
        logger.warning("Email settings incomplete, skipping notification.")
        return EmailDeliveryResult(
            success=False,
            receiver_email=receiver_email_str,
            failure_message="Email settings are incomplete.",
        )

    smtp_host_str = email_settings_obj.smtp_host
    smtp_port_int = email_settings_obj.smtp_port
    smtp_username_str = email_settings_obj.smtp_username
    smtp_password_str = email_settings_obj.smtp_password
    smtp_use_ssl_bool = email_settings_obj.smtp_use_ssl

    mime_message_obj = MIMEMultipart("alternative")
    mime_message_obj["Subject"] = subject_str
    mime_message_obj["From"] = smtp_username_str
    mime_message_obj["To"] = email_settings_obj.receiver_email

    html_part_obj = MIMEText(body_html_str, "html", "utf-8")
    mime_message_obj.attach(html_part_obj)

    try:
        if smtp_use_ssl_bool:
            smtp_client = smtplib.SMTP_SSL(smtp_host_str, smtp_port_int, timeout=15)
        else:
            smtp_client = smtplib.SMTP(smtp_host_str, smtp_port_int, timeout=15)
            smtp_client.starttls()

        smtp_client.login(smtp_username_str, smtp_password_str)
        smtp_client.sendmail(
            smtp_username_str,
            email_settings_obj.receiver_email,
            mime_message_obj.as_string(),
        )
        smtp_client.quit()

        logger.info(f"Email sent to {email_settings_obj.receiver_email}: {subject_str}")
        return EmailDeliveryResult(
            success=True,
            receiver_email=email_settings_obj.receiver_email,
        )

    except smtplib.SMTPAuthenticationError as auth_error:
        logger.error(f"SMTP authentication failed: {auth_error}")
        return EmailDeliveryResult(
            success=False,
            receiver_email=email_settings_obj.receiver_email,
            failure_message=f"SMTP authentication failed: {auth_error}",
        )
    except smtplib.SMTPException as smtp_error:
        logger.error(f"SMTP error when sending email: {smtp_error}")
        return EmailDeliveryResult(
            success=False,
            receiver_email=email_settings_obj.receiver_email,
            failure_message=f"SMTP error when sending email: {smtp_error}",
        )
    except OSError as conn_error:
        logger.error(f"Network error when connecting to SMTP: {conn_error}")
        return EmailDeliveryResult(
            success=False,
            receiver_email=email_settings_obj.receiver_email,
            failure_message=f"Network error when connecting to SMTP: {conn_error}",
        )


def send_notification_email(subject_str: str, body_html_str: str) -> bool:
    """发送 HTML 格式的通知邮件.

    若邮件通知未启用或配置不完整，则静默跳过（不抛异常）。

    Args:
        subject_str: 邮件主题
        body_html_str: 邮件正文（HTML 格式）

    Returns:
        bool: 发送成功返回 True，否则返回 False
    """
    email_settings_obj = load_email_settings_from_db()
    delivery_result = send_notification_email_via_settings(
        email_settings_obj=email_settings_obj,
        subject_str=subject_str,
        body_html_str=body_html_str,
    )
    return delivery_result.success


def send_prd_ready_notification(
    task_id_str: str,
    task_title_str: str,
) -> bool:
    """发送 PRD 已生成、等待用户确认的通知邮件.

    Args:
        task_id_str: 任务 ID
        task_title_str: 任务标题

    Returns:
        bool: 发送成功返回 True
    """
    from dsl.services.task_notification_service import TaskNotificationService

    return TaskNotificationService.send_prd_ready_notification(
        task_id_str=task_id_str,
        task_title_str=task_title_str,
    )


def send_task_failed_notification(
    task_id_str: str,
    task_title_str: str,
    failure_reason_str: str = "",
) -> bool:
    """发送任务执行失败/需要人工介入的通知邮件.

    Args:
        task_id_str: 任务 ID
        task_title_str: 任务标题
        failure_reason_str: 失败原因摘要（可选）

    Returns:
        bool: 发送成功返回 True
    """
    from dsl.services.task_notification_service import TaskNotificationService

    return TaskNotificationService.send_changes_requested_notification(
        task_id_str=task_id_str,
        task_title_str=task_title_str,
        failure_reason_str=failure_reason_str,
    )


def send_manual_interruption_notification(
    task_id_str: str,
    task_title_str: str,
    interrupted_stage_value_str: str | None = None,
) -> bool:
    """发送任务被用户手动中断的通知邮件.

    Args:
        task_id_str: 任务 ID
        task_title_str: 任务标题
        interrupted_stage_value_str: 中断动作发生前的阶段值

    Returns:
        bool: 发送成功返回 True
    """
    from dsl.services.task_notification_service import TaskNotificationService

    return TaskNotificationService.send_manual_interruption_notification(
        task_id_str=task_id_str,
        task_title_str=task_title_str,
        interrupted_stage_value_str=interrupted_stage_value_str,
    )
