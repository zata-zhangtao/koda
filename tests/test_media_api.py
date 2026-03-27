"""Tests for media API multipart form binding."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Generator

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import dsl.models  # noqa: F401
from dsl.app import app
from dsl.models.enums import TaskLifecycleStatus
from dsl.models.run_account import RunAccount
from dsl.models.task import Task
from utils.database import Base, get_db
from utils.settings import config


def _build_png_image_bytes() -> bytes:
    """Build a tiny PNG image payload for upload tests.

    Returns:
        bytes: Encoded PNG image bytes.
    """
    image_buffer = io.BytesIO()
    image = Image.new("RGB", (8, 8), color=(120, 45, 200))
    image.save(image_buffer, format="PNG")
    return image_buffer.getvalue()


def _override_get_db(session_factory: sessionmaker) -> Generator[Session, None, None]:
    """Yield request-scoped SQLAlchemy sessions for API tests.

    Args:
        session_factory: Test session factory.

    Yields:
        Session: SQLAlchemy session for one request.
    """
    db_session = session_factory()
    try:
        yield db_session
    finally:
        db_session.close()


def _list_saved_media_file_path_list(media_root_path: Path) -> list[Path]:
    """List all stored media files beneath the configured media root.

    Args:
        media_root_path: Configured media root path.

    Returns:
        list[Path]: Stored media file paths.
    """
    if not media_root_path.exists():
        return []

    return sorted(path for path in media_root_path.rglob("*") if path.is_file())


def test_upload_attachment_uses_multipart_form_task_id_and_text(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Attachment uploads should bind `task_id` and `text_content` from form fields."""
    database_path = tmp_path / "media-api.db"
    database_engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=database_engine,
    )
    Base.metadata.create_all(bind=database_engine)

    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "MEDIA_STORAGE_PATH", tmp_path / "media")

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

        ignored_open_task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Should not receive attachment",
            lifecycle_status=TaskLifecycleStatus.OPEN,
        )
        target_pending_task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Target pending task",
            lifecycle_status=TaskLifecycleStatus.PENDING,
        )
        seed_session.add_all([ignored_open_task_obj, target_pending_task_obj])
        seed_session.commit()

        def _get_test_db() -> Generator[Session, None, None]:
            yield from _override_get_db(session_factory)

        app.dependency_overrides[get_db] = _get_test_db
        test_client = TestClient(app)
        try:
            response = test_client.post(
                "/api/media/upload-attachment",
                files={
                    "uploaded_file": ("demo.mp4", b"fake-video", "video/mp4"),
                },
                data={
                    "text_content": "video requirement context",
                    "task_id": target_pending_task_obj.id,
                },
            )
        finally:
            test_client.close()
            app.dependency_overrides.clear()
    finally:
        seed_session.close()

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["task_id"] == target_pending_task_obj.id
    assert "video requirement context" in response_json["text_content"]
    assert "[Attachment: demo.mp4]" in response_json["text_content"]


def test_upload_image_uses_multipart_form_task_id_and_text(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Image uploads should bind `task_id` and `text_content` from form fields."""
    database_path = tmp_path / "media-image-api.db"
    database_engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=database_engine,
    )
    Base.metadata.create_all(bind=database_engine)

    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "MEDIA_STORAGE_PATH", tmp_path / "media")

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

        target_pending_task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Target image task",
            lifecycle_status=TaskLifecycleStatus.PENDING,
        )
        seed_session.add(target_pending_task_obj)
        seed_session.commit()

        def _get_test_db() -> Generator[Session, None, None]:
            yield from _override_get_db(session_factory)

        app.dependency_overrides[get_db] = _get_test_db
        test_client = TestClient(app)
        try:
            response = test_client.post(
                "/api/media/upload",
                files={
                    "uploaded_image_file": (
                        "demo.png",
                        _build_png_image_bytes(),
                        "image/png",
                    ),
                },
                data={
                    "text_content": "image requirement context",
                    "task_id": target_pending_task_obj.id,
                },
            )
        finally:
            test_client.close()
            app.dependency_overrides.clear()
    finally:
        seed_session.close()

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["task_id"] == target_pending_task_obj.id
    assert response_json["text_content"] == "image requirement context"
    assert response_json["media_original_image_path"] is not None


def test_upload_image_rejects_archived_task_without_leaking_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Archived image uploads should roll back stored files when log creation fails."""
    database_path = tmp_path / "media-image-archived.db"
    database_engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=database_engine,
    )
    Base.metadata.create_all(bind=database_engine)

    media_root_path = tmp_path / "media"
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "MEDIA_STORAGE_PATH", media_root_path)

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

        archived_task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Archived image task",
            lifecycle_status=TaskLifecycleStatus.CLOSED,
        )
        seed_session.add(archived_task_obj)
        seed_session.commit()

        def _get_test_db() -> Generator[Session, None, None]:
            yield from _override_get_db(session_factory)

        app.dependency_overrides[get_db] = _get_test_db
        test_client = TestClient(app)
        try:
            response = test_client.post(
                "/api/media/upload",
                files={
                    "uploaded_image_file": (
                        "demo.png",
                        _build_png_image_bytes(),
                        "image/png",
                    ),
                },
                data={
                    "text_content": "should fail",
                    "task_id": archived_task_obj.id,
                },
            )
        finally:
            test_client.close()
            app.dependency_overrides.clear()
    finally:
        seed_session.close()

    assert response.status_code == 400
    assert "formal feedback" in response.json()["detail"].lower()
    assert _list_saved_media_file_path_list(media_root_path) == []


def test_upload_attachment_rejects_archived_task_without_leaking_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Archived attachment uploads should delete the saved file on rejection."""
    database_path = tmp_path / "media-attachment-archived.db"
    database_engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=database_engine,
    )
    Base.metadata.create_all(bind=database_engine)

    media_root_path = tmp_path / "media"
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "MEDIA_STORAGE_PATH", media_root_path)

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

        archived_task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Archived attachment task",
            lifecycle_status=TaskLifecycleStatus.DELETED,
        )
        seed_session.add(archived_task_obj)
        seed_session.commit()

        def _get_test_db() -> Generator[Session, None, None]:
            yield from _override_get_db(session_factory)

        app.dependency_overrides[get_db] = _get_test_db
        test_client = TestClient(app)
        try:
            response = test_client.post(
                "/api/media/upload-attachment",
                files={
                    "uploaded_file": ("demo.mp4", b"fake-video", "video/mp4"),
                },
                data={
                    "text_content": "should fail",
                    "task_id": archived_task_obj.id,
                },
            )
        finally:
            test_client.close()
            app.dependency_overrides.clear()
    finally:
        seed_session.close()

    assert response.status_code == 400
    assert "formal feedback" in response.json()["detail"].lower()
    assert _list_saved_media_file_path_list(media_root_path) == []
