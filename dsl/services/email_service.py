"""邮件通知服务模块.

负责从数据库读取 SMTP 配置，并发送任务状态变更通知邮件.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from utils.logger import logger


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


def _load_email_settings_from_db():
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
        return email_settings_obj
    except Exception as db_load_error:
        logger.error(f"Failed to load email settings: {db_load_error}")
        return None
    finally:
        db_session.close()


def send_notification_email(subject_str: str, body_html_str: str) -> bool:
    """发送 HTML 格式的通知邮件.

    若邮件通知未启用或配置不完整，则静默跳过（不抛异常）。

    Args:
        subject_str: 邮件主题
        body_html_str: 邮件正文（HTML 格式）

    Returns:
        bool: 发送成功返回 True，否则返回 False
    """
    email_settings_obj = _load_email_settings_from_db()

    if not email_settings_obj:
        logger.debug("Email settings not found, skipping notification.")
        return False

    if not email_settings_obj.is_enabled:
        logger.debug("Email notifications disabled, skipping.")
        return False

    required_fields_list = [
        email_settings_obj.smtp_host,
        email_settings_obj.smtp_username,
        email_settings_obj.smtp_password,
        email_settings_obj.receiver_email,
    ]
    if not all(required_fields_list):
        logger.warning("Email settings incomplete, skipping notification.")
        return False

    smtp_host_str = email_settings_obj.smtp_host
    smtp_port_int = email_settings_obj.smtp_port
    smtp_username_str = email_settings_obj.smtp_username
    smtp_password_str = email_settings_obj.smtp_password
    smtp_use_ssl_bool = email_settings_obj.smtp_use_ssl
    receiver_email_str = email_settings_obj.receiver_email

    mime_message_obj = MIMEMultipart("alternative")
    mime_message_obj["Subject"] = subject_str
    mime_message_obj["From"] = smtp_username_str
    mime_message_obj["To"] = receiver_email_str

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
            receiver_email_str,
            mime_message_obj.as_string(),
        )
        smtp_client.quit()

        logger.info(f"Email sent to {receiver_email_str}: {subject_str}")
        return True

    except smtplib.SMTPAuthenticationError as auth_error:
        logger.error(f"SMTP authentication failed: {auth_error}")
        return False
    except smtplib.SMTPException as smtp_error:
        logger.error(f"SMTP error when sending email: {smtp_error}")
        return False
    except OSError as conn_error:
        logger.error(f"Network error when connecting to SMTP: {conn_error}")
        return False


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
    subject_str = f"[Koda] PRD 已生成，待确认：{task_title_str}"
    body_html_str = f"""
<html>
<body style="font-family: sans-serif; color: #333; line-height: 1.6;">
  <h2 style="color: #2563eb;">📋 PRD 已生成，等待您确认</h2>
  <p>任务 <strong>{task_title_str}</strong> 的 PRD 文档已由 AI 生成完毕，请前往 Koda 查看并决定是否进入执行阶段。</p>
  <table style="border-collapse: collapse; margin: 16px 0;">
    <tr>
      <td style="padding: 4px 12px 4px 0; color: #666;">任务 ID</td>
      <td style="padding: 4px 0;"><code>{task_id_str}</code></td>
    </tr>
    <tr>
      <td style="padding: 4px 12px 4px 0; color: #666;">当前阶段</td>
      <td style="padding: 4px 0;">PRD 等待确认（prd_waiting_confirmation）</td>
    </tr>
  </table>
  <p style="color: #666; font-size: 12px;">此邮件由 Koda 自动发送，请勿回复。</p>
</body>
</html>
"""
    return send_notification_email(subject_str, body_html_str)


def send_task_failed_notification(
    task_id_str: str,
    task_title_str: str,
    failure_reason_str: str = "",
) -> bool:
    """发送任务执行失败/需要修改的通知邮件.

    Args:
        task_id_str: 任务 ID
        task_title_str: 任务标题
        failure_reason_str: 失败原因摘要（可选）

    Returns:
        bool: 发送成功返回 True
    """
    subject_str = f"[Koda] 任务需要处理：{task_title_str}"
    reason_block_html_str = (
        f"<p><strong>原因摘要：</strong>{failure_reason_str}</p>"
        if failure_reason_str
        else ""
    )
    body_html_str = f"""
<html>
<body style="font-family: sans-serif; color: #333; line-height: 1.6;">
  <h2 style="color: #dc2626;">⚠️ 任务需要您的介入</h2>
  <p>任务 <strong>{task_title_str}</strong> 已进入 <strong>待修改（changes_requested）</strong> 状态，请前往 Koda 查看详情。</p>
  {reason_block_html_str}
  <table style="border-collapse: collapse; margin: 16px 0;">
    <tr>
      <td style="padding: 4px 12px 4px 0; color: #666;">任务 ID</td>
      <td style="padding: 4px 0;"><code>{task_id_str}</code></td>
    </tr>
    <tr>
      <td style="padding: 4px 12px 4px 0; color: #666;">当前阶段</td>
      <td style="padding: 4px 0; color: #dc2626;">待修改（changes_requested）</td>
    </tr>
  </table>
  <p style="color: #666; font-size: 12px;">此邮件由 Koda 自动发送，请勿回复。</p>
</body>
</html>
"""
    return send_notification_email(subject_str, body_html_str)
