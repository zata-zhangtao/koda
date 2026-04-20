"""Tests for WebDAV backup messaging and business snapshot sync behavior."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

import backend.dsl.models  # noqa: F401
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.dsl.api.webdav_settings import upsert_webdav_settings
from backend.dsl.models.dev_log import DevLog
from backend.dsl.models.enums import (
    DevLogStateTag,
    TaskArtifactType,
    TaskLifecycleStatus,
    TaskQaContextScope,
    TaskQaGenerationStatus,
    TaskQaMessageRole,
    WorkflowStage,
)
from backend.dsl.models.project import Project
from backend.dsl.models.run_account import RunAccount
from backend.dsl.models.task import Task
from backend.dsl.models.task_artifact import TaskArtifact
from backend.dsl.models.task_qa_message import TaskQaMessage
from backend.dsl.models.task_reference_link import TaskReferenceLink
from backend.dsl.models.webdav_settings import WebDAVSettings
from backend.dsl.schemas.webdav_settings_schema import WebDAVSettingsUpdate
from backend.dsl.services import webdav_business_sync_service, webdav_service
from backend.dsl.services.task_service import TaskService
from utils.database import Base
from utils.helpers import utc_now_naive
from utils.settings import config


class _FakeSession:
    """Minimal session stub for WebDAV service tests."""

    def close(self) -> None:
        """Close the fake session."""


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


def _write_zip_archive(
    archive_file_path: Path,
    *,
    json_payload_dict: dict | None = None,
    archive_bytes_by_member_path: dict[str, bytes] | None = None,
) -> None:
    """Write a small ZIP archive for restore tests."""

    with ZipFile(archive_file_path, "w", compression=ZIP_DEFLATED) as archive_file_obj:
        if json_payload_dict is not None:
            archive_file_obj.writestr(
                "snapshot.json",
                json.dumps(json_payload_dict, ensure_ascii=False, indent=2),
            )
        for archive_member_path, archive_bytes in (
            archive_bytes_by_member_path or {}
        ).items():
            archive_file_obj.writestr(archive_member_path, archive_bytes)


def test_sync_database_to_webdav_appends_backup_scope_note(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Upload success should explain that WebDAV only stores DB records."""

    database_file_path = tmp_path / "dsl.db"
    database_file_path.write_text("placeholder", encoding="utf-8")

    monkeypatch.setattr(
        webdav_service,
        "_load_webdav_settings_from_db",
        lambda: SimpleNamespace(
            is_enabled=True,
            server_url="https://dav.example.com",
            username="tester",
            password="secret",
            remote_path="/koda-backup/",
        ),
    )
    monkeypatch.setattr(
        webdav_service.config,
        "DATABASE_URL",
        f"sqlite:///{database_file_path}",
    )
    monkeypatch.setattr(
        "utils.database.SessionLocal",
        lambda: _FakeSession(),
    )
    monkeypatch.setattr(
        "backend.dsl.services.project_service.ProjectService.refresh_project_repo_fingerprints",
        lambda db_session, only_missing: 0,
    )
    monkeypatch.setattr(
        webdav_service,
        "upload_file_to_webdav",
        lambda **_: (
            True,
            "Uploaded dsl.db (11 bytes)",
            "https://dav.example.com/koda-backup/dsl.db",
        ),
    )

    upload_success_bool, upload_message_str, remote_url_str = (
        webdav_service.sync_database_to_webdav()
    )

    assert upload_success_bool is True
    assert remote_url_str == "https://dav.example.com/koda-backup/dsl.db"
    assert "Uploaded dsl.db (11 bytes)" in upload_message_str
    assert "projects, requirement cards, logs, and settings" in upload_message_str
    assert "actual code completion progress are not included" in upload_message_str


def test_restore_database_from_webdav_appends_restore_scope_note(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Restore success should warn that repo/worktree progress is not restored."""

    database_file_path = tmp_path / "dsl.db"

    monkeypatch.setattr(
        webdav_service,
        "_load_webdav_settings_from_db",
        lambda: SimpleNamespace(
            is_enabled=True,
            server_url="https://dav.example.com",
            username="tester",
            password="secret",
            remote_path="/koda-backup/",
        ),
    )
    monkeypatch.setattr(
        webdav_service.config,
        "DATABASE_URL",
        f"sqlite:///{database_file_path}",
    )
    monkeypatch.setattr(
        webdav_service,
        "download_file_from_webdav",
        lambda **_: (True, "Downloaded dsl.db (11 bytes)"),
    )
    monkeypatch.setattr(
        webdav_service,
        "_build_repo_relink_hint_message",
        lambda: "2 synced projects still point to paths from another machine.",
    )

    download_success_bool, download_message_str = (
        webdav_service.restore_database_from_webdav()
    )

    assert download_success_bool is True
    assert "Downloaded dsl.db (11 bytes)" in download_message_str
    assert "database snapshots only" in download_message_str
    assert "2 synced projects still point to paths from another machine." in (
        download_message_str
    )


def test_build_business_sync_snapshot_payload_collects_media_and_sidecars(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Business snapshot export should include media, artifacts, QA, and references."""

    db_session = _build_db_session()
    media_root_path = tmp_path / "data" / "media"
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "MEDIA_STORAGE_PATH", media_root_path)
    try:
        active_run_account_obj = RunAccount(
            account_display_name="Active",
            user_name="active",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        inactive_run_account_obj = RunAccount(
            account_display_name="Inactive",
            user_name="inactive",
            environment_os="Linux",
            git_branch_name=None,
            is_active=False,
        )
        project_one_obj = Project(
            display_name="Demo Project",
            project_category="agent",
            repo_path=str(tmp_path / "repo-one"),
            repo_remote_url="https://example.com/demo.git",
            repo_head_commit_hash="abc123",
            description="Primary synced project",
        )
        project_two_obj = Project(
            display_name="Support Project",
            project_category="tooling",
            repo_path=str(tmp_path / "repo-two"),
            repo_remote_url="https://example.com/support.git",
            repo_head_commit_hash="def456",
            description="Secondary synced project",
        )
        db_session.add_all(
            [
                active_run_account_obj,
                inactive_run_account_obj,
                project_one_obj,
                project_two_obj,
            ]
        )
        db_session.commit()

        task_one_obj = Task(
            run_account_id=active_run_account_obj.id,
            project_id=project_one_obj.id,
            task_title="Sync me",
            lifecycle_status=TaskLifecycleStatus.OPEN,
            workflow_stage=WorkflowStage.CHANGES_REQUESTED,
            requirement_brief="Primary requirement",
        )
        task_two_obj = Task(
            run_account_id=active_run_account_obj.id,
            project_id=project_two_obj.id,
            task_title="Referenced task",
            lifecycle_status=TaskLifecycleStatus.PENDING,
            workflow_stage=WorkflowStage.BACKLOG,
            requirement_brief="Secondary requirement",
        )
        ignored_task_obj = Task(
            run_account_id=inactive_run_account_obj.id,
            project_id=project_one_obj.id,
            task_title="Ignore me",
            lifecycle_status=TaskLifecycleStatus.OPEN,
            workflow_stage=WorkflowStage.BACKLOG,
            requirement_brief="Should not export",
        )
        db_session.add_all([task_one_obj, task_two_obj, ignored_task_obj])
        db_session.commit()

        original_image_path = media_root_path / "original" / "shot.png"
        thumbnail_image_path = media_root_path / "thumbnail" / "shot.png"
        attachment_path = media_root_path / "original" / "spec.txt"
        original_image_path.parent.mkdir(parents=True, exist_ok=True)
        thumbnail_image_path.parent.mkdir(parents=True, exist_ok=True)
        original_image_path.write_bytes(b"original-image")
        thumbnail_image_path.write_bytes(b"thumbnail-image")
        attachment_path.write_text("attachment", encoding="utf-8")

        dev_log_obj = DevLog(
            task_id=task_one_obj.id,
            run_account_id=active_run_account_obj.id,
            text_content="See [Attachment: spec](/api/media/spec.txt)",
            state_tag=DevLogStateTag.FIXED,
            media_original_image_path=str(original_image_path.relative_to(tmp_path)),
            media_thumbnail_path=str(thumbnail_image_path.relative_to(tmp_path)),
        )
        task_artifact_obj = TaskArtifact(
            task_id=task_one_obj.id,
            artifact_type=TaskArtifactType.PRD,
            source_path="/tmp/prd.md",
            content_markdown="# PRD",
            file_manifest_json="[]",
        )
        task_qa_message_obj = TaskQaMessage(
            task_id=task_one_obj.id,
            run_account_id=active_run_account_obj.id,
            role=TaskQaMessageRole.USER,
            context_scope=TaskQaContextScope.IMPLEMENTATION,
            generation_status=TaskQaGenerationStatus.COMPLETED,
            content_markdown="What changed?",
        )
        db_session.add_all([dev_log_obj, task_artifact_obj, task_qa_message_obj])
        db_session.commit()

        task_reference_link_obj = TaskReferenceLink(
            run_account_id=active_run_account_obj.id,
            source_task_id=task_one_obj.id,
            target_task_id=task_two_obj.id,
            reference_log_id=dev_log_obj.id,
            requirement_brief_appended=True,
        )
        db_session.add(task_reference_link_obj)
        db_session.commit()

        snapshot_payload_dict, snapshot_summary = (
            webdav_business_sync_service._build_business_sync_snapshot_payload(
                db_session,
                active_run_account_obj,
            )
        )

        exported_task_id_set = {
            task_snapshot_dict["id"]
            for task_snapshot_dict in snapshot_payload_dict["tasks"]
        }
        exported_media_relative_path_set = {
            media_file_entry["relative_path"]
            for media_file_entry in snapshot_payload_dict["media_files"]
        }

        assert exported_task_id_set == {task_one_obj.id, task_two_obj.id}
        assert len(snapshot_payload_dict["projects"]) == 2
        assert len(snapshot_payload_dict["dev_logs"]) == 1
        assert len(snapshot_payload_dict["task_artifacts"]) == 1
        assert len(snapshot_payload_dict["task_qa_messages"]) == 1
        assert len(snapshot_payload_dict["task_reference_links"]) == 1
        assert exported_media_relative_path_set == {
            "data/media/original/shot.png",
            "data/media/thumbnail/shot.png",
            "data/media/original/spec.txt",
        }
        assert snapshot_summary.task_count_int == 2
        assert snapshot_summary.media_file_count_int == 3
    finally:
        db_session.close()


def test_restore_business_sync_snapshot_sanitizes_state_and_restores_media(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Business snapshot restore should downgrade machine-local stages and import sidecars."""

    db_session = _build_db_session()
    media_root_path = tmp_path / "data" / "media"
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "MEDIA_STORAGE_PATH", media_root_path)
    try:
        active_run_account_obj = RunAccount(
            account_display_name="Current Machine",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        existing_project_obj = Project(
            id="project-1",
            display_name="Local Project",
            project_category="agent",
            repo_path=str(tmp_path / "local-repo"),
            repo_remote_url="https://old.example.com/repo.git",
            repo_head_commit_hash="old-head",
            description="Existing local binding",
        )
        db_session.add_all([active_run_account_obj, existing_project_obj])
        db_session.commit()

        current_timestamp = utc_now_naive()
        snapshot_payload_dict = {
            "snapshot_kind": "business_sync",
            "schema_version": 1,
            "exported_at": current_timestamp.isoformat(),
            "projects": [
                {
                    "id": "project-1",
                    "display_name": "Remote Project",
                    "project_category": "agent",
                    "repo_remote_url": "https://example.com/repo.git",
                    "repo_head_commit_hash": "remote-head",
                    "description": "Synced description",
                    "created_at": current_timestamp.isoformat(),
                }
            ],
            "tasks": [
                {
                    "id": "task-1",
                    "project_id": "project-1",
                    "task_title": "Continue implementation elsewhere",
                    "lifecycle_status": TaskLifecycleStatus.OPEN.value,
                    "workflow_stage": WorkflowStage.IMPLEMENTATION_IN_PROGRESS.value,
                    "stage_updated_at": current_timestamp.isoformat(),
                    "last_ai_activity_at": current_timestamp.isoformat(),
                    "requirement_brief": "Implementation in progress",
                    "auto_confirm_prd_and_execute": False,
                    "business_sync_original_workflow_stage": None,
                    "business_sync_original_lifecycle_status": None,
                    "business_sync_restored_at": None,
                    "destroy_reason": None,
                    "destroyed_at": None,
                    "created_at": current_timestamp.isoformat(),
                    "closed_at": None,
                },
                {
                    "id": "task-2",
                    "project_id": "project-1",
                    "task_title": "PRD was generating remotely",
                    "lifecycle_status": TaskLifecycleStatus.PENDING.value,
                    "workflow_stage": WorkflowStage.PRD_GENERATING.value,
                    "stage_updated_at": current_timestamp.isoformat(),
                    "last_ai_activity_at": current_timestamp.isoformat(),
                    "requirement_brief": "PRD should reopen locally",
                    "auto_confirm_prd_and_execute": False,
                    "business_sync_original_workflow_stage": None,
                    "business_sync_original_lifecycle_status": None,
                    "business_sync_restored_at": None,
                    "destroy_reason": None,
                    "destroyed_at": None,
                    "created_at": current_timestamp.isoformat(),
                    "closed_at": None,
                },
            ],
            "dev_logs": [
                {
                    "id": "log-1",
                    "task_id": "task-1",
                    "created_at": current_timestamp.isoformat(),
                    "text_content": "Imported log",
                    "state_tag": DevLogStateTag.FIXED.value,
                    "media_original_image_path": "data/media/original/imported.png",
                    "media_thumbnail_path": "data/media/thumbnail/imported.png",
                    "ai_processing_status": None,
                    "ai_generated_title": None,
                    "ai_analysis_text": None,
                    "ai_extracted_code": None,
                    "ai_confidence_score": None,
                    "automation_session_id": None,
                    "automation_sequence_index": None,
                    "automation_phase_label": None,
                    "automation_runner_kind": None,
                }
            ],
            "task_artifacts": [
                {
                    "id": "artifact-1",
                    "task_id": "task-2",
                    "artifact_type": TaskArtifactType.PRD.value,
                    "source_path": "/tmp/prd.md",
                    "content_markdown": "# Restored PRD",
                    "file_manifest_json": "[]",
                    "captured_at": current_timestamp.isoformat(),
                }
            ],
            "task_qa_messages": [
                {
                    "id": "qa-1",
                    "task_id": "task-1",
                    "role": TaskQaMessageRole.USER.value,
                    "context_scope": TaskQaContextScope.IMPLEMENTATION.value,
                    "generation_status": TaskQaGenerationStatus.COMPLETED.value,
                    "reply_to_message_id": None,
                    "model_name": None,
                    "content_markdown": "Need more tests?",
                    "error_text": None,
                    "created_at": current_timestamp.isoformat(),
                    "updated_at": current_timestamp.isoformat(),
                }
            ],
            "task_reference_links": [
                {
                    "id": "ref-1",
                    "source_task_id": "task-1",
                    "target_task_id": "task-2",
                    "reference_log_id": "log-1",
                    "requirement_brief_appended": True,
                    "created_at": current_timestamp.isoformat(),
                }
            ],
            "media_files": [
                {
                    "relative_path": "data/media/original/imported.png",
                    "archive_path": "assets/data/media/original/imported.png",
                    "sha256_hex": "unused",
                },
                {
                    "relative_path": "data/media/thumbnail/imported.png",
                    "archive_path": "assets/data/media/thumbnail/imported.png",
                    "sha256_hex": "unused",
                },
            ],
        }

        archive_file_path = tmp_path / "business-sync.zip"
        _write_zip_archive(
            archive_file_path,
            archive_bytes_by_member_path={
                "assets/data/media/original/imported.png": b"original-imported",
                "assets/data/media/thumbnail/imported.png": b"thumbnail-imported",
            },
        )

        with ZipFile(archive_file_path, "r") as snapshot_archive_file_obj:
            snapshot_summary = (
                webdav_business_sync_service._restore_business_sync_snapshot_payload(
                    db_session,
                    active_run_account_obj,
                    snapshot_payload_dict,
                    snapshot_archive_file_obj,
                )
            )

        restored_task_one_obj = (
            db_session.query(Task).filter(Task.id == "task-1").first()
        )
        restored_task_two_obj = (
            db_session.query(Task).filter(Task.id == "task-2").first()
        )
        restored_project_obj = (
            db_session.query(Project).filter(Project.id == "project-1").first()
        )
        restored_dev_log_count_int = (
            db_session.query(DevLog).filter(DevLog.task_id == "task-1").count()
        )
        restored_task_qa_count_int = (
            db_session.query(TaskQaMessage)
            .filter(TaskQaMessage.task_id == "task-1")
            .count()
        )
        restored_reference_count_int = db_session.query(TaskReferenceLink).count()

        assert restored_task_one_obj is not None
        assert restored_task_two_obj is not None
        assert restored_project_obj is not None
        assert restored_task_one_obj.run_account_id == active_run_account_obj.id
        assert restored_task_one_obj.workflow_stage == WorkflowStage.CHANGES_REQUESTED
        assert restored_task_one_obj.lifecycle_status == TaskLifecycleStatus.OPEN
        assert (
            restored_task_one_obj.business_sync_original_workflow_stage
            == WorkflowStage.IMPLEMENTATION_IN_PROGRESS.value
        )
        assert (
            restored_task_one_obj.business_sync_original_lifecycle_status
            == TaskLifecycleStatus.OPEN.value
        )
        assert restored_task_one_obj.business_sync_restored_at is not None
        assert restored_task_one_obj.worktree_path is None
        assert TaskService.can_rebind_project(restored_task_one_obj) is True
        assert (
            restored_task_two_obj.workflow_stage
            == WorkflowStage.PRD_WAITING_CONFIRMATION
        )
        assert restored_task_two_obj.lifecycle_status == TaskLifecycleStatus.OPEN
        assert restored_project_obj.repo_path == str(tmp_path / "local-repo")
        assert restored_project_obj.repo_remote_url == "https://example.com/repo.git"
        assert restored_project_obj.repo_head_commit_hash == "remote-head"
        assert restored_dev_log_count_int == 1
        assert restored_task_qa_count_int == 1
        assert restored_reference_count_int == 1
        assert (
            tmp_path / "data" / "media" / "original" / "imported.png"
        ).read_bytes() == b"original-imported"
        assert (
            tmp_path / "data" / "media" / "thumbnail" / "imported.png"
        ).read_bytes() == b"thumbnail-imported"
        assert snapshot_summary.sanitized_task_count_int == 2
        assert snapshot_summary.media_file_count_int == 2
    finally:
        db_session.close()


def test_upsert_webdav_settings_preserves_existing_password_on_blank_update() -> None:
    """Saving a blank WebDAV password should keep the previously stored password."""

    db_session = _build_db_session()
    try:
        upsert_webdav_settings(
            WebDAVSettingsUpdate(
                server_url="https://dav.example.com",
                username="tester",
                password="original-secret",
                remote_path="/koda-sync/",
                is_enabled=True,
            ),
            db_session,
        )

        upsert_webdav_settings(
            WebDAVSettingsUpdate(
                server_url="https://dav.example.com",
                username="tester",
                password="",
                remote_path="/koda-next/",
                is_enabled=False,
            ),
            db_session,
        )

        stored_webdav_settings_obj = (
            db_session.query(WebDAVSettings).filter(WebDAVSettings.id == 1).first()
        )

        assert stored_webdav_settings_obj is not None
        assert stored_webdav_settings_obj.password == "original-secret"
        assert stored_webdav_settings_obj.remote_path == "/koda-next/"
        assert stored_webdav_settings_obj.is_enabled is False
    finally:
        db_session.close()
