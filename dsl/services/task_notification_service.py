"""统一任务通知服务.

负责封装任务邮件模板、发送审计、去重键和停滞提醒扫描逻辑.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from dsl.models.enums import TaskNotificationEventType, WorkflowStage
from dsl.models.task import Task
from dsl.models.task_notification import TaskNotification
from dsl.services.email_service import (
    load_email_settings_from_db,
    send_notification_email_via_settings,
)
from utils.database import SessionLocal
from utils.helpers import format_datetime_in_app_timezone, utc_now_naive
from utils.logger import logger

_WAITING_FOR_USER_STAGE_SET = {
    WorkflowStage.PRD_WAITING_CONFIRMATION,
    WorkflowStage.CHANGES_REQUESTED,
}
_DEFAULT_STALLED_TASK_THRESHOLD_MINUTES = 20
_WORKFLOW_STAGE_LABEL_MAP = {
    WorkflowStage.BACKLOG.value: "待办（backlog）",
    WorkflowStage.PRD_GENERATING.value: "PRD 生成中（prd_generating）",
    WorkflowStage.PRD_WAITING_CONFIRMATION.value: "PRD 等待确认（prd_waiting_confirmation）",
    WorkflowStage.IMPLEMENTATION_IN_PROGRESS.value: "编码执行中（implementation_in_progress）",
    WorkflowStage.SELF_REVIEW_IN_PROGRESS.value: "AI 自检中（self_review_in_progress）",
    WorkflowStage.TEST_IN_PROGRESS.value: "测试中（test_in_progress）",
    WorkflowStage.PR_PREPARING.value: "PR 整理中（pr_preparing）",
    WorkflowStage.ACCEPTANCE_IN_PROGRESS.value: "验收中（acceptance_in_progress）",
    WorkflowStage.CHANGES_REQUESTED.value: "待修改（changes_requested）",
    WorkflowStage.DONE.value: "已完成（done）",
}


class TaskNotificationService:
    """任务通知统一入口."""

    @staticmethod
    def _format_stage_label(workflow_stage_value_str: str) -> str:
        """返回工作流阶段的人类可读标签.

        Args:
            workflow_stage_value_str: 阶段枚举值字符串

        Returns:
            str: 阶段展示文本
        """
        return _WORKFLOW_STAGE_LABEL_MAP.get(
            workflow_stage_value_str,
            workflow_stage_value_str,
        )

    @staticmethod
    def _build_dedup_key(
        event_type: TaskNotificationEventType,
        task_id_str: str,
        workflow_stage_value_str: str,
        stage_updated_at: datetime | None,
    ) -> str:
        """构造通知去重键.

        Args:
            event_type: 通知事件类型
            task_id_str: 任务 ID
            workflow_stage_value_str: 当前阶段值
            stage_updated_at: 当前阶段进入时间

        Returns:
            str: 稳定的去重键
        """
        stage_window_marker_str = (
            stage_updated_at.isoformat() if stage_updated_at is not None else "unknown"
        )
        return (
            f"{event_type.value}:"
            f"{task_id_str}:"
            f"{workflow_stage_value_str}:"
            f"{stage_window_marker_str}"
        )

    @staticmethod
    def _reserve_notification_record(
        *,
        task_id_str: str,
        event_type: TaskNotificationEventType,
        workflow_stage_value_str: str,
        dedup_key_str: str,
        receiver_email_snapshot_str: str | None,
    ) -> TaskNotification | None:
        """写入通知审计占位记录，用于幂等去重.

        Args:
            task_id_str: 任务 ID
            event_type: 通知事件类型
            workflow_stage_value_str: 当前阶段值
            dedup_key_str: 去重键
            receiver_email_snapshot_str: 收件人快照

        Returns:
            TaskNotification | None: 预留成功时返回记录对象，重复时返回 None
        """
        db_session = SessionLocal()
        try:
            task_notification_obj = TaskNotification(
                task_id=task_id_str,
                event_type=event_type,
                workflow_stage_snapshot=workflow_stage_value_str,
                dedup_key=dedup_key_str,
                receiver_email_snapshot=receiver_email_snapshot_str,
                send_success=False,
                failure_message=None,
            )
            db_session.add(task_notification_obj)
            db_session.commit()
            db_session.refresh(task_notification_obj)
            db_session.expunge(task_notification_obj)
            return task_notification_obj
        except IntegrityError:
            db_session.rollback()
            return None
        finally:
            db_session.close()

    @staticmethod
    def _finalize_notification_record(
        notification_id_str: str,
        *,
        send_success_bool: bool,
        failure_message_str: str | None,
        receiver_email_snapshot_str: str | None,
    ) -> None:
        """回填通知发送结果.

        Args:
            notification_id_str: 审计记录 ID
            send_success_bool: 实际发送是否成功
            failure_message_str: 失败或跳过原因
            receiver_email_snapshot_str: 最新收件人快照
        """
        db_session = SessionLocal()
        try:
            task_notification_obj = (
                db_session.query(TaskNotification)
                .filter(TaskNotification.id == notification_id_str)
                .first()
            )
            if task_notification_obj is None:
                return

            task_notification_obj.send_success = send_success_bool
            task_notification_obj.failure_message = failure_message_str
            if receiver_email_snapshot_str is not None:
                task_notification_obj.receiver_email_snapshot = (
                    receiver_email_snapshot_str
                )
            db_session.commit()
        except Exception as notification_update_error:
            db_session.rollback()
            logger.error(
                "Failed to finalize notification record %s: %s",
                notification_id_str,
                notification_update_error,
            )
        finally:
            db_session.close()

    @staticmethod
    def _delete_notification_record(notification_id_str: str) -> None:
        """删除已预留但不应保留的通知审计记录.

        Args:
            notification_id_str: 审计记录 ID
        """
        db_session = SessionLocal()
        try:
            task_notification_obj = (
                db_session.query(TaskNotification)
                .filter(TaskNotification.id == notification_id_str)
                .first()
            )
            if task_notification_obj is None:
                return
            db_session.delete(task_notification_obj)
            db_session.commit()
        except Exception as notification_delete_error:
            db_session.rollback()
            logger.error(
                "Failed to delete notification record %s: %s",
                notification_id_str,
                notification_delete_error,
            )
        finally:
            db_session.close()

    @staticmethod
    def _is_notification_delivery_available(email_settings_obj) -> bool:
        """判断当前设置是否具备通知投递前置条件.

        Args:
            email_settings_obj: 邮件设置对象，可为 None

        Returns:
            bool: 当前是否具备尝试投递的必要配置
        """
        if email_settings_obj is None:
            return False
        if not getattr(email_settings_obj, "is_enabled", False):
            return False

        required_field_value_list = [
            getattr(email_settings_obj, "smtp_host", None),
            getattr(email_settings_obj, "smtp_username", None),
            getattr(email_settings_obj, "smtp_password", None),
            getattr(email_settings_obj, "receiver_email", None),
        ]
        return all(required_field_value_list)

    @staticmethod
    def _get_task_stage_snapshot(
        task_id_str: str,
        fallback_workflow_stage: WorkflowStage,
    ) -> tuple[str, datetime | None]:
        """读取任务当前阶段快照.

        Args:
            task_id_str: 任务 ID
            fallback_workflow_stage: 任务不存在时使用的阶段回退值

        Returns:
            tuple[str, datetime | None]: 当前阶段值和阶段进入时间
        """
        db_session = SessionLocal()
        try:
            task_obj = db_session.query(Task).filter(Task.id == task_id_str).first()
            if task_obj is None:
                return fallback_workflow_stage.value, None
            return task_obj.workflow_stage.value, task_obj.stage_updated_at
        finally:
            db_session.close()

    @staticmethod
    def _send_task_notification(
        *,
        task_id_str: str,
        task_title_str: str,
        event_type: TaskNotificationEventType,
        fallback_workflow_stage: WorkflowStage,
        subject_str: str,
        body_html_str: str,
        create_audit_when_delivery_unavailable_bool: bool = True,
    ) -> bool:
        """统一发送任务通知并写入审计记录.

        Args:
            task_id_str: 任务 ID
            task_title_str: 任务标题，仅用于日志上下文
            event_type: 通知事件类型
            fallback_workflow_stage: 任务不存在时使用的阶段回退值
            subject_str: 邮件主题
            body_html_str: HTML 邮件正文
            create_audit_when_delivery_unavailable_bool: 不可发送时是否仍写入审计记录

        Returns:
            bool: 实际发送成功时返回 True；重复去重或发送失败时返回 False
        """
        email_settings_obj = load_email_settings_from_db()
        receiver_email_snapshot_str = (
            email_settings_obj.receiver_email
            if email_settings_obj and email_settings_obj.receiver_email
            else None
        )
        workflow_stage_value_str, stage_updated_at = (
            TaskNotificationService._get_task_stage_snapshot(
                task_id_str=task_id_str,
                fallback_workflow_stage=fallback_workflow_stage,
            )
        )
        dedup_key_str = TaskNotificationService._build_dedup_key(
            event_type=event_type,
            task_id_str=task_id_str,
            workflow_stage_value_str=workflow_stage_value_str,
            stage_updated_at=stage_updated_at,
        )
        delivery_available_bool = (
            TaskNotificationService._is_notification_delivery_available(
                email_settings_obj
            )
        )

        if (
            not create_audit_when_delivery_unavailable_bool
            and not delivery_available_bool
        ):
            return False

        reserved_task_notification_obj = (
            TaskNotificationService._reserve_notification_record(
                task_id_str=task_id_str,
                event_type=event_type,
                workflow_stage_value_str=workflow_stage_value_str,
                dedup_key_str=dedup_key_str,
                receiver_email_snapshot_str=receiver_email_snapshot_str,
            )
        )
        if reserved_task_notification_obj is None:
            return False

        delivery_result = send_notification_email_via_settings(
            email_settings_obj=email_settings_obj,
            subject_str=subject_str,
            body_html_str=body_html_str,
        )
        if (
            not create_audit_when_delivery_unavailable_bool
            and not delivery_result.success
        ):
            TaskNotificationService._delete_notification_record(
                reserved_task_notification_obj.id
            )
            logger.warning(
                "Discarded notification audit after failed delivery: event=%s task=%s stage=%s title=%s failure=%s",
                event_type.value,
                task_id_str[:8],
                workflow_stage_value_str,
                task_title_str,
                delivery_result.failure_message,
            )
            return False

        TaskNotificationService._finalize_notification_record(
            reserved_task_notification_obj.id,
            send_success_bool=delivery_result.success,
            failure_message_str=delivery_result.failure_message,
            receiver_email_snapshot_str=delivery_result.receiver_email,
        )
        logger.info(
            "Task notification processed: event=%s task=%s stage=%s success=%s title=%s",
            event_type.value,
            task_id_str[:8],
            workflow_stage_value_str,
            delivery_result.success,
            task_title_str,
        )
        return delivery_result.success

    @staticmethod
    def send_prd_ready_notification(
        task_id_str: str,
        task_title_str: str,
    ) -> bool:
        """发送 PRD 已生成的通知邮件.

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
      <td style="padding: 4px 0;">{TaskNotificationService._format_stage_label(WorkflowStage.PRD_WAITING_CONFIRMATION.value)}</td>
    </tr>
  </table>
  <p style="color: #666; font-size: 12px;">此邮件由 Koda 自动发送，请勿回复。</p>
</body>
</html>
"""
        return TaskNotificationService._send_task_notification(
            task_id_str=task_id_str,
            task_title_str=task_title_str,
            event_type=TaskNotificationEventType.PRD_READY,
            fallback_workflow_stage=WorkflowStage.PRD_WAITING_CONFIRMATION,
            subject_str=subject_str,
            body_html_str=body_html_str,
        )

    @staticmethod
    def send_changes_requested_notification(
        task_id_str: str,
        task_title_str: str,
        failure_reason_str: str = "",
    ) -> bool:
        """发送任务进入待修改阶段的通知邮件.

        Args:
            task_id_str: 任务 ID
            task_title_str: 任务标题
            failure_reason_str: 失败原因摘要

        Returns:
            bool: 发送成功返回 True
        """
        reason_block_html_str = (
            f"<p><strong>原因摘要：</strong>{failure_reason_str}</p>"
            if failure_reason_str
            else ""
        )
        subject_str = f"[Koda] 任务需要处理：{task_title_str}"
        body_html_str = f"""
<html>
<body style="font-family: sans-serif; color: #333; line-height: 1.6;">
  <h2 style="color: #dc2626;">⚠️ 任务需要您的介入</h2>
  <p>任务 <strong>{task_title_str}</strong> 已进入 <strong>待修改（changes_requested）</strong> 状态，表示当前自动化流程无法自行完成闭环，请前往 Koda 查看详情。</p>
  {reason_block_html_str}
  <table style="border-collapse: collapse; margin: 16px 0;">
    <tr>
      <td style="padding: 4px 12px 4px 0; color: #666;">任务 ID</td>
      <td style="padding: 4px 0;"><code>{task_id_str}</code></td>
    </tr>
    <tr>
      <td style="padding: 4px 12px 4px 0; color: #666;">当前阶段</td>
      <td style="padding: 4px 0; color: #dc2626;">{TaskNotificationService._format_stage_label(WorkflowStage.CHANGES_REQUESTED.value)}</td>
    </tr>
  </table>
  <p style="color: #666; font-size: 12px;">此邮件由 Koda 自动发送，请勿回复。</p>
</body>
</html>
"""
        return TaskNotificationService._send_task_notification(
            task_id_str=task_id_str,
            task_title_str=task_title_str,
            event_type=TaskNotificationEventType.CHANGES_REQUESTED,
            fallback_workflow_stage=WorkflowStage.CHANGES_REQUESTED,
            subject_str=subject_str,
            body_html_str=body_html_str,
        )

    @staticmethod
    def send_manual_interruption_notification(
        task_id_str: str,
        task_title_str: str,
        interrupted_stage_value_str: str | None = None,
    ) -> bool:
        """发送用户手动中断任务的通知邮件.

        Args:
            task_id_str: 任务 ID
            task_title_str: 任务标题
            interrupted_stage_value_str: 中断前的阶段值

        Returns:
            bool: 发送成功返回 True
        """
        interrupted_stage_html_str = ""
        if interrupted_stage_value_str:
            interrupted_stage_html_str = f"""
    <tr>
      <td style="padding: 4px 12px 4px 0; color: #666;">中断前阶段</td>
      <td style="padding: 4px 0;">{TaskNotificationService._format_stage_label(interrupted_stage_value_str)}</td>
    </tr>
"""

        subject_str = f"[Koda] 任务已手动中断：{task_title_str}"
        body_html_str = f"""
<html>
<body style="font-family: sans-serif; color: #333; line-height: 1.6;">
  <h2 style="color: #d97706;">🛑 任务已被手动中断</h2>
  <p>任务 <strong>{task_title_str}</strong> 被用户手动中断，系统已将其切换到 <strong>待修改（changes_requested）</strong> 状态，等待后续人工确认或重新执行。</p>
  <table style="border-collapse: collapse; margin: 16px 0;">
    <tr>
      <td style="padding: 4px 12px 4px 0; color: #666;">任务 ID</td>
      <td style="padding: 4px 0;"><code>{task_id_str}</code></td>
    </tr>
{interrupted_stage_html_str}
    <tr>
      <td style="padding: 4px 12px 4px 0; color: #666;">当前阶段</td>
      <td style="padding: 4px 0; color: #d97706;">{TaskNotificationService._format_stage_label(WorkflowStage.CHANGES_REQUESTED.value)}</td>
    </tr>
  </table>
  <p style="color: #666; font-size: 12px;">此邮件由 Koda 自动发送，请勿回复。</p>
</body>
</html>
"""
        return TaskNotificationService._send_task_notification(
            task_id_str=task_id_str,
            task_title_str=task_title_str,
            event_type=TaskNotificationEventType.MANUAL_INTERRUPTION,
            fallback_workflow_stage=WorkflowStage.CHANGES_REQUESTED,
            subject_str=subject_str,
            body_html_str=body_html_str,
        )

    @staticmethod
    def send_stalled_task_notification(
        task_id_str: str,
        task_title_str: str,
        threshold_minutes_int: int,
    ) -> bool:
        """发送任务停滞提醒邮件.

        Args:
            task_id_str: 任务 ID
            task_title_str: 任务标题
            threshold_minutes_int: 当前启用的停滞提醒阈值（分钟）

        Returns:
            bool: 发送成功返回 True
        """
        db_session = SessionLocal()
        try:
            task_obj = db_session.query(Task).filter(Task.id == task_id_str).first()
            if task_obj is None:
                return False
            if task_obj.workflow_stage not in _WAITING_FOR_USER_STAGE_SET:
                return False

            stage_entered_at = task_obj.stage_updated_at
            now_utc_datetime = utc_now_naive()
            stalled_minutes_int = threshold_minutes_int
            if stage_entered_at is not None:
                stalled_minutes_int = max(
                    threshold_minutes_int,
                    int((now_utc_datetime - stage_entered_at).total_seconds() // 60),
                )

            stage_entered_at_text_str = (
                format_datetime_in_app_timezone(stage_entered_at)
                if stage_entered_at is not None
                else "未知"
            )
            subject_str = f"[Koda] 任务等待您处理：{task_title_str}"
            body_html_str = f"""
<html>
<body style="font-family: sans-serif; color: #333; line-height: 1.6;">
  <h2 style="color: #7c3aed;">⏰ 任务等待时间已超过阈值</h2>
  <p>任务 <strong>{task_title_str}</strong> 已在 <strong>{TaskNotificationService._format_stage_label(task_obj.workflow_stage.value)}</strong> 停留至少 <strong>{stalled_minutes_int} 分钟</strong>，请前往 Koda 确认下一步操作。</p>
  <table style="border-collapse: collapse; margin: 16px 0;">
    <tr>
      <td style="padding: 4px 12px 4px 0; color: #666;">任务 ID</td>
      <td style="padding: 4px 0;"><code>{task_id_str}</code></td>
    </tr>
    <tr>
      <td style="padding: 4px 12px 4px 0; color: #666;">当前阶段</td>
      <td style="padding: 4px 0;">{TaskNotificationService._format_stage_label(task_obj.workflow_stage.value)}</td>
    </tr>
    <tr>
      <td style="padding: 4px 12px 4px 0; color: #666;">阶段进入时间</td>
      <td style="padding: 4px 0;">{stage_entered_at_text_str}</td>
    </tr>
    <tr>
      <td style="padding: 4px 12px 4px 0; color: #666;">提醒阈值</td>
      <td style="padding: 4px 0;">{threshold_minutes_int} 分钟</td>
    </tr>
  </table>
  <p style="color: #666; font-size: 12px;">此邮件由 Koda 自动发送，请勿回复。</p>
</body>
</html>
"""
        finally:
            db_session.close()

        return TaskNotificationService._send_task_notification(
            task_id_str=task_id_str,
            task_title_str=task_title_str,
            event_type=TaskNotificationEventType.STALLED_REMINDER,
            fallback_workflow_stage=WorkflowStage.PRD_WAITING_CONFIRMATION,
            subject_str=subject_str,
            body_html_str=body_html_str,
            create_audit_when_delivery_unavailable_bool=False,
        )

    @staticmethod
    def scan_and_send_stalled_task_notifications() -> int:
        """扫描并发送人工等待超时提醒.

        Returns:
            int: 本轮成功或尝试处理的停滞提醒数量
        """
        email_settings_obj = load_email_settings_from_db()
        if email_settings_obj is None or not email_settings_obj.is_enabled:
            return 0

        threshold_minutes_int = max(
            int(
                getattr(
                    email_settings_obj,
                    "stalled_task_threshold_minutes",
                    _DEFAULT_STALLED_TASK_THRESHOLD_MINUTES,
                )
                or _DEFAULT_STALLED_TASK_THRESHOLD_MINUTES
            ),
            1,
        )
        deadline_datetime = utc_now_naive() - timedelta(minutes=threshold_minutes_int)

        db_session = SessionLocal()
        try:
            stalled_task_list = (
                db_session.query(Task)
                .filter(
                    Task.workflow_stage.in_(
                        [
                            workflow_stage.value
                            for workflow_stage in _WAITING_FOR_USER_STAGE_SET
                        ]
                    ),
                    Task.stage_updated_at <= deadline_datetime,
                )
                .all()
            )
        finally:
            db_session.close()

        processed_notification_count_int = 0
        for stalled_task_obj in stalled_task_list:
            if TaskNotificationService.send_stalled_task_notification(
                task_id_str=stalled_task_obj.id,
                task_title_str=stalled_task_obj.task_title,
                threshold_minutes_int=threshold_minutes_int,
            ):
                processed_notification_count_int += 1

        return processed_notification_count_int
