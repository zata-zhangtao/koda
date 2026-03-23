"""Tests for the unified task notification service."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import dsl.models  # noqa: F401
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dsl.models.enums import TaskNotificationEventType, WorkflowStage
from dsl.models.run_account import RunAccount
from dsl.models.task import Task
from dsl.models.task_notification import TaskNotification
from dsl.services import email_service
from dsl.services.task_notification_service import TaskNotificationService
from utils.database import Base
from utils.helpers import utc_now_naive


def _build_session_factory():
    """Build a shared in-memory session factory for cross-session service tests."""
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    return sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )


def test_send_stalled_task_notification_only_once_per_stage_window() -> None:
    """A stalled reminder should only be sent once for the same stage window."""
    session_factory = _build_session_factory()
    seed_session = session_factory()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        seed_session.add(run_account_obj)
        seed_session.commit()

        stalled_task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Awaiting PRD confirmation",
            workflow_stage=WorkflowStage.PRD_WAITING_CONFIRMATION,
            stage_updated_at=utc_now_naive() - timedelta(minutes=30),
        )
        seed_session.add(stalled_task_obj)
        seed_session.commit()

        original_session_local = (
            TaskNotificationService._reserve_notification_record.__globals__[
                "SessionLocal"
            ]
        )
        original_load_settings = (
            TaskNotificationService._send_task_notification.__globals__[
                "load_email_settings_from_db"
            ]
        )
        original_send_email = (
            TaskNotificationService._send_task_notification.__globals__[
                "send_notification_email_via_settings"
            ]
        )

        TaskNotificationService._reserve_notification_record.__globals__[
            "SessionLocal"
        ] = session_factory
        TaskNotificationService._finalize_notification_record.__globals__[
            "SessionLocal"
        ] = session_factory
        TaskNotificationService._get_task_stage_snapshot.__globals__["SessionLocal"] = (
            session_factory
        )
        TaskNotificationService.send_stalled_task_notification.__globals__[
            "SessionLocal"
        ] = session_factory
        TaskNotificationService.scan_and_send_stalled_task_notifications.__globals__[
            "SessionLocal"
        ] = session_factory
        TaskNotificationService._send_task_notification.__globals__[
            "load_email_settings_from_db"
        ] = lambda: SimpleNamespace(
            is_enabled=True,
            receiver_email="owner@example.com",
            stalled_task_threshold_minutes=20,
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_username="bot@example.com",
            smtp_password="secret",
            smtp_use_ssl=True,
        )
        TaskNotificationService.scan_and_send_stalled_task_notifications.__globals__[
            "load_email_settings_from_db"
        ] = TaskNotificationService._send_task_notification.__globals__[
            "load_email_settings_from_db"
        ]
        TaskNotificationService._send_task_notification.__globals__[
            "send_notification_email_via_settings"
        ] = (
            lambda email_settings_obj,
            subject_str,
            body_html_str: email_service.EmailDeliveryResult(
                success=True,
                receiver_email=email_settings_obj.receiver_email,
            )
        )

        try:
            first_send_result = TaskNotificationService.send_stalled_task_notification(
                task_id_str=stalled_task_obj.id,
                task_title_str=stalled_task_obj.task_title,
                threshold_minutes_int=20,
            )
            second_send_result = TaskNotificationService.send_stalled_task_notification(
                task_id_str=stalled_task_obj.id,
                task_title_str=stalled_task_obj.task_title,
                threshold_minutes_int=20,
            )
        finally:
            TaskNotificationService._reserve_notification_record.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService._finalize_notification_record.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService._get_task_stage_snapshot.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService.send_stalled_task_notification.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService.scan_and_send_stalled_task_notifications.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService._send_task_notification.__globals__[
                "load_email_settings_from_db"
            ] = original_load_settings
            TaskNotificationService.scan_and_send_stalled_task_notifications.__globals__[
                "load_email_settings_from_db"
            ] = original_load_settings
            TaskNotificationService._send_task_notification.__globals__[
                "send_notification_email_via_settings"
            ] = original_send_email

        verification_session = session_factory()
        try:
            notification_record_list = verification_session.query(
                TaskNotification
            ).all()
            assert first_send_result is True
            assert second_send_result is False
            assert len(notification_record_list) == 1
            assert (
                notification_record_list[0].event_type
                == TaskNotificationEventType.STALLED_REMINDER
            )
            assert notification_record_list[0].send_success is True
        finally:
            verification_session.close()
    finally:
        seed_session.close()


def test_send_stalled_task_notification_skips_audit_until_delivery_is_available() -> (
    None
):
    """A stalled reminder should not consume its window before delivery is possible."""
    session_factory = _build_session_factory()
    seed_session = session_factory()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        seed_session.add(run_account_obj)
        seed_session.commit()

        stalled_task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Awaiting SMTP configuration",
            workflow_stage=WorkflowStage.PRD_WAITING_CONFIRMATION,
            stage_updated_at=utc_now_naive() - timedelta(minutes=30),
        )
        seed_session.add(stalled_task_obj)
        seed_session.commit()

        original_session_local = (
            TaskNotificationService._reserve_notification_record.__globals__[
                "SessionLocal"
            ]
        )
        original_load_settings = (
            TaskNotificationService._send_task_notification.__globals__[
                "load_email_settings_from_db"
            ]
        )
        original_send_email = (
            TaskNotificationService._send_task_notification.__globals__[
                "send_notification_email_via_settings"
            ]
        )
        original_delete_session_local = (
            TaskNotificationService._delete_notification_record.__globals__[
                "SessionLocal"
            ]
        )

        TaskNotificationService._reserve_notification_record.__globals__[
            "SessionLocal"
        ] = session_factory
        TaskNotificationService._finalize_notification_record.__globals__[
            "SessionLocal"
        ] = session_factory
        TaskNotificationService._delete_notification_record.__globals__[
            "SessionLocal"
        ] = session_factory
        TaskNotificationService._get_task_stage_snapshot.__globals__["SessionLocal"] = (
            session_factory
        )
        TaskNotificationService.send_stalled_task_notification.__globals__[
            "SessionLocal"
        ] = session_factory
        TaskNotificationService._send_task_notification.__globals__[
            "load_email_settings_from_db"
        ] = lambda: SimpleNamespace(
            is_enabled=True,
            receiver_email="",
            stalled_task_threshold_minutes=20,
            smtp_host="",
            smtp_port=465,
            smtp_username="bot@example.com",
            smtp_password="secret",
            smtp_use_ssl=True,
        )
        TaskNotificationService._send_task_notification.__globals__[
            "send_notification_email_via_settings"
        ] = lambda email_settings_obj, subject_str, body_html_str: (
            _ for _ in ()
        ).throw(
            AssertionError(
                "delivery should not be attempted while email settings are incomplete"
            )
        )

        try:
            first_send_result = TaskNotificationService.send_stalled_task_notification(
                task_id_str=stalled_task_obj.id,
                task_title_str=stalled_task_obj.task_title,
                threshold_minutes_int=20,
            )

            intermediate_verification_session = session_factory()
            try:
                assert (
                    intermediate_verification_session.query(TaskNotification).count()
                    == 0
                )
            finally:
                intermediate_verification_session.close()

            TaskNotificationService._send_task_notification.__globals__[
                "load_email_settings_from_db"
            ] = lambda: SimpleNamespace(
                is_enabled=True,
                receiver_email="owner@example.com",
                stalled_task_threshold_minutes=20,
                smtp_host="smtp.example.com",
                smtp_port=465,
                smtp_username="bot@example.com",
                smtp_password="secret",
                smtp_use_ssl=True,
            )
            TaskNotificationService._send_task_notification.__globals__[
                "send_notification_email_via_settings"
            ] = (
                lambda email_settings_obj,
                subject_str,
                body_html_str: email_service.EmailDeliveryResult(
                    success=True,
                    receiver_email=email_settings_obj.receiver_email,
                )
            )
            second_send_result = TaskNotificationService.send_stalled_task_notification(
                task_id_str=stalled_task_obj.id,
                task_title_str=stalled_task_obj.task_title,
                threshold_minutes_int=20,
            )
        finally:
            TaskNotificationService._reserve_notification_record.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService._finalize_notification_record.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService._delete_notification_record.__globals__[
                "SessionLocal"
            ] = original_delete_session_local
            TaskNotificationService._get_task_stage_snapshot.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService.send_stalled_task_notification.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService._send_task_notification.__globals__[
                "load_email_settings_from_db"
            ] = original_load_settings
            TaskNotificationService._send_task_notification.__globals__[
                "send_notification_email_via_settings"
            ] = original_send_email

        verification_session = session_factory()
        try:
            notification_record_list = verification_session.query(
                TaskNotification
            ).all()
            assert first_send_result is False
            assert second_send_result is True
            assert len(notification_record_list) == 1
            assert notification_record_list[0].send_success is True
        finally:
            verification_session.close()
    finally:
        seed_session.close()


def test_send_stalled_task_notification_allows_retry_after_transient_delivery_failure() -> (
    None
):
    """A stalled reminder should not burn its stage window after a transient SMTP failure."""
    session_factory = _build_session_factory()
    seed_session = session_factory()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        seed_session.add(run_account_obj)
        seed_session.commit()

        stalled_task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Retry after SMTP recovery",
            workflow_stage=WorkflowStage.PRD_WAITING_CONFIRMATION,
            stage_updated_at=utc_now_naive() - timedelta(minutes=30),
        )
        seed_session.add(stalled_task_obj)
        seed_session.commit()

        original_session_local = (
            TaskNotificationService._reserve_notification_record.__globals__[
                "SessionLocal"
            ]
        )
        original_load_settings = (
            TaskNotificationService._send_task_notification.__globals__[
                "load_email_settings_from_db"
            ]
        )
        original_send_email = (
            TaskNotificationService._send_task_notification.__globals__[
                "send_notification_email_via_settings"
            ]
        )
        original_delete_session_local = (
            TaskNotificationService._delete_notification_record.__globals__[
                "SessionLocal"
            ]
        )

        TaskNotificationService._reserve_notification_record.__globals__[
            "SessionLocal"
        ] = session_factory
        TaskNotificationService._finalize_notification_record.__globals__[
            "SessionLocal"
        ] = session_factory
        TaskNotificationService._delete_notification_record.__globals__[
            "SessionLocal"
        ] = session_factory
        TaskNotificationService._get_task_stage_snapshot.__globals__["SessionLocal"] = (
            session_factory
        )
        TaskNotificationService.send_stalled_task_notification.__globals__[
            "SessionLocal"
        ] = session_factory
        TaskNotificationService._send_task_notification.__globals__[
            "load_email_settings_from_db"
        ] = lambda: SimpleNamespace(
            is_enabled=True,
            receiver_email="owner@example.com",
            stalled_task_threshold_minutes=20,
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_username="bot@example.com",
            smtp_password="secret",
            smtp_use_ssl=True,
        )

        try:
            TaskNotificationService._send_task_notification.__globals__[
                "send_notification_email_via_settings"
            ] = (
                lambda email_settings_obj,
                subject_str,
                body_html_str: email_service.EmailDeliveryResult(
                    success=False,
                    receiver_email=email_settings_obj.receiver_email,
                    failure_message="SMTP error when sending email: temporary outage",
                )
            )
            first_send_result = TaskNotificationService.send_stalled_task_notification(
                task_id_str=stalled_task_obj.id,
                task_title_str=stalled_task_obj.task_title,
                threshold_minutes_int=20,
            )

            intermediate_verification_session = session_factory()
            try:
                assert (
                    intermediate_verification_session.query(TaskNotification).count()
                    == 0
                )
            finally:
                intermediate_verification_session.close()

            TaskNotificationService._send_task_notification.__globals__[
                "send_notification_email_via_settings"
            ] = (
                lambda email_settings_obj,
                subject_str,
                body_html_str: email_service.EmailDeliveryResult(
                    success=True,
                    receiver_email=email_settings_obj.receiver_email,
                )
            )
            second_send_result = TaskNotificationService.send_stalled_task_notification(
                task_id_str=stalled_task_obj.id,
                task_title_str=stalled_task_obj.task_title,
                threshold_minutes_int=20,
            )
        finally:
            TaskNotificationService._reserve_notification_record.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService._finalize_notification_record.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService._delete_notification_record.__globals__[
                "SessionLocal"
            ] = original_delete_session_local
            TaskNotificationService._get_task_stage_snapshot.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService.send_stalled_task_notification.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService._send_task_notification.__globals__[
                "load_email_settings_from_db"
            ] = original_load_settings
            TaskNotificationService._send_task_notification.__globals__[
                "send_notification_email_via_settings"
            ] = original_send_email

        verification_session = session_factory()
        try:
            notification_record_list = verification_session.query(
                TaskNotification
            ).all()
            assert first_send_result is False
            assert second_send_result is True
            assert len(notification_record_list) == 1
            assert notification_record_list[0].send_success is True
        finally:
            verification_session.close()
    finally:
        seed_session.close()


def test_send_stalled_task_notification_allows_resend_after_reentering_stage() -> None:
    """Re-entering a waiting stage should create a new reminder window."""
    session_factory = _build_session_factory()
    seed_session = session_factory()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        seed_session.add(run_account_obj)
        seed_session.commit()

        stalled_task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Needs another reminder window",
            workflow_stage=WorkflowStage.PRD_WAITING_CONFIRMATION,
            stage_updated_at=utc_now_naive() - timedelta(minutes=30),
        )
        seed_session.add(stalled_task_obj)
        seed_session.commit()

        original_session_local = (
            TaskNotificationService._reserve_notification_record.__globals__[
                "SessionLocal"
            ]
        )
        original_load_settings = (
            TaskNotificationService._send_task_notification.__globals__[
                "load_email_settings_from_db"
            ]
        )
        original_send_email = (
            TaskNotificationService._send_task_notification.__globals__[
                "send_notification_email_via_settings"
            ]
        )

        TaskNotificationService._reserve_notification_record.__globals__[
            "SessionLocal"
        ] = session_factory
        TaskNotificationService._finalize_notification_record.__globals__[
            "SessionLocal"
        ] = session_factory
        TaskNotificationService._get_task_stage_snapshot.__globals__["SessionLocal"] = (
            session_factory
        )
        TaskNotificationService.send_stalled_task_notification.__globals__[
            "SessionLocal"
        ] = session_factory
        TaskNotificationService._send_task_notification.__globals__[
            "load_email_settings_from_db"
        ] = lambda: SimpleNamespace(
            is_enabled=True,
            receiver_email="owner@example.com",
            stalled_task_threshold_minutes=20,
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_username="bot@example.com",
            smtp_password="secret",
            smtp_use_ssl=True,
        )
        TaskNotificationService._send_task_notification.__globals__[
            "send_notification_email_via_settings"
        ] = (
            lambda email_settings_obj,
            subject_str,
            body_html_str: email_service.EmailDeliveryResult(
                success=True,
                receiver_email=email_settings_obj.receiver_email,
            )
        )

        try:
            first_send_result = TaskNotificationService.send_stalled_task_notification(
                task_id_str=stalled_task_obj.id,
                task_title_str=stalled_task_obj.task_title,
                threshold_minutes_int=20,
            )

            state_update_session = session_factory()
            try:
                reloaded_task_obj = (
                    state_update_session.query(Task)
                    .filter(Task.id == stalled_task_obj.id)
                    .first()
                )
                assert reloaded_task_obj is not None
                reloaded_task_obj.workflow_stage = (
                    WorkflowStage.IMPLEMENTATION_IN_PROGRESS
                )
                reloaded_task_obj.stage_updated_at = utc_now_naive()
                state_update_session.commit()
                reloaded_task_obj.workflow_stage = (
                    WorkflowStage.PRD_WAITING_CONFIRMATION
                )
                reloaded_task_obj.stage_updated_at = utc_now_naive() - timedelta(
                    minutes=25
                )
                state_update_session.commit()
            finally:
                state_update_session.close()

            second_send_result = TaskNotificationService.send_stalled_task_notification(
                task_id_str=stalled_task_obj.id,
                task_title_str=stalled_task_obj.task_title,
                threshold_minutes_int=20,
            )
        finally:
            TaskNotificationService._reserve_notification_record.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService._finalize_notification_record.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService._get_task_stage_snapshot.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService.send_stalled_task_notification.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService._send_task_notification.__globals__[
                "load_email_settings_from_db"
            ] = original_load_settings
            TaskNotificationService._send_task_notification.__globals__[
                "send_notification_email_via_settings"
            ] = original_send_email

        verification_session = session_factory()
        try:
            notification_record_list = (
                verification_session.query(TaskNotification)
                .order_by(TaskNotification.created_at.asc())
                .all()
            )
            assert first_send_result is True
            assert second_send_result is True
            assert len(notification_record_list) == 2
            assert (
                notification_record_list[0].dedup_key
                != notification_record_list[1].dedup_key
            )
        finally:
            verification_session.close()
    finally:
        seed_session.close()


def test_scan_and_send_stalled_task_notifications_filters_stage_and_threshold() -> None:
    """Only overdue waiting stages should be scanned into reminder notifications."""
    session_factory = _build_session_factory()
    seed_session = session_factory()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        seed_session.add(run_account_obj)
        seed_session.commit()

        seed_session.add_all(
            [
                Task(
                    run_account_id=run_account_obj.id,
                    task_title="Overdue confirmation",
                    workflow_stage=WorkflowStage.PRD_WAITING_CONFIRMATION,
                    stage_updated_at=utc_now_naive() - timedelta(minutes=30),
                ),
                Task(
                    run_account_id=run_account_obj.id,
                    task_title="Fresh changes requested",
                    workflow_stage=WorkflowStage.CHANGES_REQUESTED,
                    stage_updated_at=utc_now_naive() - timedelta(minutes=5),
                ),
                Task(
                    run_account_id=run_account_obj.id,
                    task_title="Wrong stage",
                    workflow_stage=WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
                    stage_updated_at=utc_now_naive() - timedelta(minutes=45),
                ),
            ]
        )
        seed_session.commit()

        original_session_local = (
            TaskNotificationService._reserve_notification_record.__globals__[
                "SessionLocal"
            ]
        )
        original_load_settings = (
            TaskNotificationService._send_task_notification.__globals__[
                "load_email_settings_from_db"
            ]
        )
        original_scan_load_settings = TaskNotificationService.scan_and_send_stalled_task_notifications.__globals__[
            "load_email_settings_from_db"
        ]
        original_send_email = (
            TaskNotificationService._send_task_notification.__globals__[
                "send_notification_email_via_settings"
            ]
        )

        TaskNotificationService._reserve_notification_record.__globals__[
            "SessionLocal"
        ] = session_factory
        TaskNotificationService._finalize_notification_record.__globals__[
            "SessionLocal"
        ] = session_factory
        TaskNotificationService._get_task_stage_snapshot.__globals__["SessionLocal"] = (
            session_factory
        )
        TaskNotificationService.send_stalled_task_notification.__globals__[
            "SessionLocal"
        ] = session_factory
        TaskNotificationService.scan_and_send_stalled_task_notifications.__globals__[
            "SessionLocal"
        ] = session_factory

        def configured_settings_factory() -> SimpleNamespace:
            return SimpleNamespace(
                is_enabled=True,
                receiver_email="owner@example.com",
                stalled_task_threshold_minutes=20,
                smtp_host="smtp.example.com",
                smtp_port=465,
                smtp_username="bot@example.com",
                smtp_password="secret",
                smtp_use_ssl=True,
            )

        TaskNotificationService._send_task_notification.__globals__[
            "load_email_settings_from_db"
        ] = configured_settings_factory
        TaskNotificationService.scan_and_send_stalled_task_notifications.__globals__[
            "load_email_settings_from_db"
        ] = configured_settings_factory
        TaskNotificationService._send_task_notification.__globals__[
            "send_notification_email_via_settings"
        ] = (
            lambda email_settings_obj,
            subject_str,
            body_html_str: email_service.EmailDeliveryResult(
                success=True,
                receiver_email=email_settings_obj.receiver_email,
            )
        )

        try:
            processed_notification_count_int = (
                TaskNotificationService.scan_and_send_stalled_task_notifications()
            )
        finally:
            TaskNotificationService._reserve_notification_record.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService._finalize_notification_record.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService._get_task_stage_snapshot.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService.send_stalled_task_notification.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService.scan_and_send_stalled_task_notifications.__globals__[
                "SessionLocal"
            ] = original_session_local
            TaskNotificationService._send_task_notification.__globals__[
                "load_email_settings_from_db"
            ] = original_load_settings
            TaskNotificationService.scan_and_send_stalled_task_notifications.__globals__[
                "load_email_settings_from_db"
            ] = original_scan_load_settings
            TaskNotificationService._send_task_notification.__globals__[
                "send_notification_email_via_settings"
            ] = original_send_email

        verification_session = session_factory()
        try:
            notification_record_list = verification_session.query(
                TaskNotification
            ).all()
            assert processed_notification_count_int == 1
            assert len(notification_record_list) == 1
            assert (
                notification_record_list[0].workflow_stage_snapshot
                == WorkflowStage.PRD_WAITING_CONFIRMATION.value
            )
        finally:
            verification_session.close()
    finally:
        seed_session.close()
