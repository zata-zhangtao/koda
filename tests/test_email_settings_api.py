"""Tests for email settings API helpers."""

from __future__ import annotations

import backend.dsl.models  # noqa: F401
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.dsl.api.email_settings import get_email_settings, upsert_email_settings
from backend.dsl.schemas.email_settings_schema import EmailSettingsUpdate
from utils.database import Base


def _build_db_session() -> Session:
    """Build an isolated in-memory database session."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    test_session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )
    Base.metadata.create_all(bind=test_engine)
    return test_session_factory()


def test_upsert_email_settings_round_trips_stalled_threshold() -> None:
    """GET/PUT should expose the stalled reminder threshold field."""
    db_session = _build_db_session()
    try:
        response = upsert_email_settings(
            EmailSettingsUpdate(
                smtp_host="smtp.example.com",
                smtp_port=465,
                smtp_username="bot@example.com",
                smtp_password="app-password",
                smtp_use_ssl=True,
                receiver_email="owner@example.com",
                is_enabled=True,
                stalled_task_threshold_minutes=45,
            ),
            db_session,
        )

        fetched_response = get_email_settings(db_session)

        assert response.stalled_task_threshold_minutes == 45
        assert fetched_response.stalled_task_threshold_minutes == 45
        assert fetched_response.receiver_email == "owner@example.com"
    finally:
        db_session.close()


def test_upsert_email_settings_preserves_existing_password_on_blank_update() -> None:
    """Saving a blank password should keep the previously stored SMTP password."""
    from backend.dsl.models.email_settings import EmailSettings

    db_session = _build_db_session()
    try:
        upsert_email_settings(
            EmailSettingsUpdate(
                smtp_host="smtp.example.com",
                smtp_port=465,
                smtp_username="bot@example.com",
                smtp_password="original-secret",
                smtp_use_ssl=True,
                receiver_email="owner@example.com",
                is_enabled=True,
                stalled_task_threshold_minutes=20,
            ),
            db_session,
        )

        upsert_email_settings(
            EmailSettingsUpdate(
                smtp_host="smtp.example.com",
                smtp_port=587,
                smtp_username="bot@example.com",
                smtp_password="",
                smtp_use_ssl=False,
                receiver_email="owner@example.com",
                is_enabled=True,
                stalled_task_threshold_minutes=25,
            ),
            db_session,
        )

        stored_email_settings_obj = (
            db_session.query(EmailSettings).filter(EmailSettings.id == 1).first()
        )

        assert stored_email_settings_obj is not None
        assert stored_email_settings_obj.smtp_password == "original-secret"
        assert stored_email_settings_obj.stalled_task_threshold_minutes == 25
    finally:
        db_session.close()
