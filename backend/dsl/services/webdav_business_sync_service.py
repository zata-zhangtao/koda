"""WebDAV 业务状态同步服务.

该模块在保留原始 SQLite 数据库备份/恢复能力之外，提供一条更安全的
“业务状态快照”同步链路：

- 同步项目、需求卡片、日志、PRD/planning 快照、附件/图片等业务事实
- 不同步 `repo_path`、`worktree_path`、本机 Git 分支存在性、运行中状态等机器事实
- 对依赖本机代码上下文的执行阶段做安全降级，避免在另一台机器上出现假可恢复状态
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
from tempfile import TemporaryDirectory
from typing import Any
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.dsl.models.dev_log import DevLog
from backend.dsl.models.enums import (
    AIProcessingStatus,
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
from backend.dsl.models.task_notification import TaskNotification
from backend.dsl.models.task_qa_message import TaskQaMessage
from backend.dsl.models.task_reference_link import TaskReferenceLink
from backend.dsl.models.task_schedule import TaskSchedule
from backend.dsl.models.task_schedule_run import TaskScheduleRun
from backend.dsl.services.chronicle_service import ChronicleService
from backend.dsl.services.webdav_service import (
    _build_repo_relink_hint_message,
    _compose_result_message,
    _load_webdav_settings_from_db,
    download_file_from_webdav,
    upload_file_to_webdav,
)
from utils.database import SessionLocal
from utils.helpers import (
    app_aware_to_utc_naive,
    parse_iso_datetime_text,
    serialize_datetime_for_api,
    utc_now_naive,
)
from utils.logger import logger
from utils.settings import config

_WEBDAV_BUSINESS_SNAPSHOT_FILENAME = "koda-business-sync.zip"
_WEBDAV_BUSINESS_SNAPSHOT_SCHEMA_VERSION = 1
_WEBDAV_SNAPSHOT_KIND = "business_sync"
_SNAPSHOT_JSON_FILENAME = "snapshot.json"
_SNAPSHOT_ASSET_PREFIX = "assets/"
_ATTACHMENT_MARKDOWN_LINK_PATTERN = re.compile(r"\(/api/media/(?P<filename>[^)\s?#]+)")
_WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"^[A-Za-z]:/")
_MACHINE_CONTEXT_DEPENDENT_STAGE_SET: set[WorkflowStage] = {
    WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
    WorkflowStage.SELF_REVIEW_IN_PROGRESS,
    WorkflowStage.TEST_IN_PROGRESS,
    WorkflowStage.PR_PREPARING,
    WorkflowStage.ACCEPTANCE_IN_PROGRESS,
}


@dataclass(frozen=True)
class BusinessSyncSummary:
    """Summary of one business-sync export or restore operation.

    Attributes:
        project_count_int: Number of project records.
        task_count_int: Number of task records.
        dev_log_count_int: Number of dev logs.
        task_artifact_count_int: Number of task artifacts.
        task_qa_message_count_int: Number of task-sidecar messages.
        task_reference_link_count_int: Number of task reference links.
        media_file_count_int: Number of packaged media files.
        sanitized_task_count_int: Number of tasks whose runtime stage was safely downgraded.
    """

    project_count_int: int
    task_count_int: int
    dev_log_count_int: int
    task_artifact_count_int: int
    task_qa_message_count_int: int
    task_reference_link_count_int: int
    media_file_count_int: int
    sanitized_task_count_int: int = 0


def _resolve_media_storage_root_path() -> Path:
    """Return the absolute media storage root path."""

    configured_media_storage_path = Path(config.MEDIA_STORAGE_PATH)
    if configured_media_storage_path.is_absolute():
        return configured_media_storage_path.resolve()
    return (config.BASE_DIR / configured_media_storage_path).resolve()


def _is_path_within_directory(candidate_path: Path, directory_path: Path) -> bool:
    """Return whether the candidate path is located under the directory path."""

    try:
        candidate_path.resolve().relative_to(directory_path.resolve())
        return True
    except ValueError:
        return False


def _normalize_snapshot_relative_path(raw_relative_path_str: str) -> str | None:
    """Normalize and validate one base-relative snapshot path.

    Args:
        raw_relative_path_str: 原始相对路径文本

    Returns:
        str | None: 标准化后的相对路径；非法时返回 None
    """

    normalized_input_path_str = raw_relative_path_str.strip().replace("\\", "/")
    if not normalized_input_path_str:
        return None
    if _WINDOWS_ABSOLUTE_PATH_PATTERN.match(normalized_input_path_str):
        return None

    normalized_relative_path = PurePosixPath(normalized_input_path_str)
    if normalized_relative_path.is_absolute():
        return None

    normalized_relative_path_str = normalized_relative_path.as_posix().lstrip("/")
    if not normalized_relative_path_str or normalized_relative_path_str == ".":
        return None

    normalized_path_part_tuple = PurePosixPath(normalized_relative_path_str).parts
    if any(
        path_part_str in {"", ".", ".."} for path_part_str in normalized_path_part_tuple
    ):
        return None

    return normalized_relative_path_str


def _resolve_base_relative_path(raw_candidate_path_str: str) -> str | None:
    """Convert one stored relative/absolute path into a safe BASE_DIR-relative path.

    Args:
        raw_candidate_path_str: 原始路径文本

    Returns:
        str | None: `config.BASE_DIR` 相对路径；无法安全归一化时返回 None
    """

    normalized_input_path_str = raw_candidate_path_str.strip().replace("\\", "/")
    if not normalized_input_path_str:
        return None

    candidate_path = Path(normalized_input_path_str)
    if candidate_path.is_absolute():
        absolute_candidate_path = candidate_path.resolve()
        if not _is_path_within_directory(absolute_candidate_path, config.BASE_DIR):
            return None
        return _normalize_snapshot_relative_path(
            absolute_candidate_path.relative_to(config.BASE_DIR).as_posix()
        )

    return _normalize_snapshot_relative_path(normalized_input_path_str)


def _resolve_exportable_media_absolute_path(
    raw_media_path_str: str,
) -> tuple[str, Path] | None:
    """Resolve one stored media path into a safe exportable absolute path.

    Args:
        raw_media_path_str: 数据库中的媒体路径

    Returns:
        tuple[str, Path] | None: (`BASE_DIR` 相对路径, 绝对路径)；非法时返回 None
    """

    normalized_relative_path_str = _resolve_base_relative_path(raw_media_path_str)
    if normalized_relative_path_str is None:
        return None

    absolute_media_path = (config.BASE_DIR / normalized_relative_path_str).resolve()
    if not _is_path_within_directory(
        absolute_media_path,
        _resolve_media_storage_root_path(),
    ):
        return None

    return normalized_relative_path_str, absolute_media_path


def _resolve_restore_media_destination_path(raw_media_relative_path_str: str) -> Path:
    """Resolve one snapshot media path into a safe local destination path.

    Args:
        raw_media_relative_path_str: 快照中的媒体相对路径

    Returns:
        Path: 当前机器上的绝对落盘路径

    Raises:
        ValueError: 当路径非法或越过媒体目录边界时抛出
    """

    normalized_relative_path_str = _normalize_snapshot_relative_path(
        raw_media_relative_path_str
    )
    if normalized_relative_path_str is None:
        raise ValueError("Snapshot contains an invalid media relative path.")

    destination_media_file_path = (
        config.BASE_DIR / normalized_relative_path_str
    ).resolve()
    if not _is_path_within_directory(
        destination_media_file_path,
        _resolve_media_storage_root_path(),
    ):
        raise ValueError("Snapshot media path escapes the local media storage root.")

    return destination_media_file_path


def _normalize_archive_member_path(raw_member_path_str: str) -> str:
    """Normalize and validate one ZIP member path.

    Args:
        raw_member_path_str: ZIP 内部成员路径

    Returns:
        str: 标准化后的 ZIP 成员路径

    Raises:
        ValueError: 当成员路径非法时抛出
    """

    normalized_member_path_str = _normalize_snapshot_relative_path(raw_member_path_str)
    if normalized_member_path_str is None:
        raise ValueError("Snapshot archive contains an invalid member path.")
    return normalized_member_path_str


def _require_active_run_account(db_session: Session) -> RunAccount:
    """Return the current active run account for business sync.

    Args:
        db_session: 数据库会话

    Returns:
        RunAccount: 当前活跃运行账户

    Raises:
        ValueError: 当前不存在活跃运行账户
    """

    active_run_account_obj = (
        db_session.query(RunAccount).filter(RunAccount.is_active).first()
    )
    if active_run_account_obj is None:
        raise ValueError("No active run account. Please create or activate one first.")
    return active_run_account_obj


def _extract_attachment_filename_list(raw_log_text_str: str) -> list[str]:
    """Extract attachment filenames referenced from log markdown.

    Args:
        raw_log_text_str: 日志 Markdown 文本

    Returns:
        list[str]: 去重后的附件文件名列表
    """

    attachment_filename_list: list[str] = []
    seen_attachment_filename_set: set[str] = set()
    for markdown_match in _ATTACHMENT_MARKDOWN_LINK_PATTERN.finditer(raw_log_text_str):
        attachment_filename_str = markdown_match.group("filename").strip()
        if (
            not attachment_filename_str
            or attachment_filename_str in seen_attachment_filename_set
        ):
            continue
        seen_attachment_filename_set.add(attachment_filename_str)
        attachment_filename_list.append(attachment_filename_str)
    return attachment_filename_list


def _compute_file_sha256_hex(file_path: Path) -> str:
    """Compute the SHA-256 digest for one file.

    Args:
        file_path: 文件路径

    Returns:
        str: SHA-256 十六进制摘要
    """

    file_hasher = hashlib.sha256()
    with open(file_path, "rb") as file_obj:
        for file_chunk_bytes in iter(lambda: file_obj.read(65536), b""):
            file_hasher.update(file_chunk_bytes)
    return file_hasher.hexdigest()


def _parse_snapshot_datetime_to_utc_naive(
    raw_datetime_text: str | None,
) -> datetime | None:
    """Parse snapshot ISO text into UTC-naive datetime for SQLAlchemy fields.

    Args:
        raw_datetime_text: Snapshot datetime text

    Returns:
        datetime | None: Parsed UTC-naive datetime or None
    """

    parsed_datetime = parse_iso_datetime_text(raw_datetime_text)
    if parsed_datetime is None:
        return None
    return app_aware_to_utc_naive(parsed_datetime)


def _ensure_latest_task_artifact_snapshots_for_export(
    db_session: Session,
    task_obj_list: list[Task],
) -> None:
    """Capture the latest PRD/planning snapshots before building export payload.

    Args:
        db_session: 数据库会话
        task_obj_list: 需要导出的任务列表
    """

    for task_obj in task_obj_list:
        if not task_obj.worktree_path:
            continue
        worktree_dir_path = Path(task_obj.worktree_path)
        if not worktree_dir_path.exists():
            continue
        ChronicleService.capture_prd_artifact_snapshot(
            db_session,
            task_obj.id,
            worktree_dir_path,
        )
        ChronicleService.capture_planning_artifact_snapshot(
            db_session,
            task_obj.id,
            worktree_dir_path,
        )


def _collect_media_file_entry_list(
    dev_log_obj_list: list[DevLog],
) -> list[dict[str, str]]:
    """Collect physical media payloads referenced by dev logs.

    Args:
        dev_log_obj_list: 需要导出的日志列表

    Returns:
        list[dict[str, str]]: 媒体文件清单
    """

    media_entry_list: list[dict[str, str]] = []
    seen_relative_media_path_set: set[str] = set()

    for dev_log_obj in dev_log_obj_list:
        candidate_media_path_list: list[str] = []
        if dev_log_obj.media_original_image_path:
            candidate_media_path_list.append(dev_log_obj.media_original_image_path)
        if dev_log_obj.media_thumbnail_path:
            candidate_media_path_list.append(dev_log_obj.media_thumbnail_path)

        for attachment_filename_str in _extract_attachment_filename_list(
            dev_log_obj.text_content
        ):
            candidate_media_path_list.append(
                str(
                    Path(config.MEDIA_STORAGE_PATH)
                    / "original"
                    / attachment_filename_str
                )
            )

        for candidate_media_path_str in candidate_media_path_list:
            resolved_media_path = _resolve_exportable_media_absolute_path(
                candidate_media_path_str
            )
            if resolved_media_path is None:
                continue

            normalized_relative_media_path_str, absolute_media_path = (
                resolved_media_path
            )
            if normalized_relative_media_path_str in seen_relative_media_path_set:
                continue
            if not absolute_media_path.exists():
                continue

            seen_relative_media_path_set.add(normalized_relative_media_path_str)
            media_entry_list.append(
                {
                    "relative_path": normalized_relative_media_path_str,
                    "archive_path": (
                        f"{_SNAPSHOT_ASSET_PREFIX}{normalized_relative_media_path_str}"
                    ),
                    "sha256_hex": _compute_file_sha256_hex(absolute_media_path),
                }
            )

    return media_entry_list


def _build_business_sync_snapshot_payload(
    db_session: Session,
    active_run_account_obj: RunAccount,
) -> tuple[dict[str, Any], BusinessSyncSummary]:
    """Build the JSON payload that represents the business-sync snapshot.

    Args:
        db_session: 数据库会话
        active_run_account_obj: 当前活跃运行账户

    Returns:
        tuple[dict[str, Any], BusinessSyncSummary]: Snapshot payload and summary
    """

    task_obj_list = (
        db_session.query(Task)
        .filter(Task.run_account_id == active_run_account_obj.id)
        .order_by(Task.created_at.asc(), Task.id.asc())
        .all()
    )
    _ensure_latest_task_artifact_snapshots_for_export(db_session, task_obj_list)

    task_id_list = [task_obj.id for task_obj in task_obj_list]
    task_id_set = set(task_id_list)

    dev_log_obj_list = (
        db_session.query(DevLog)
        .filter(DevLog.task_id.in_(task_id_list))
        .order_by(DevLog.created_at.asc(), DevLog.id.asc())
        .all()
        if task_id_list
        else []
    )
    task_artifact_obj_list = (
        db_session.query(TaskArtifact)
        .filter(TaskArtifact.task_id.in_(task_id_list))
        .order_by(TaskArtifact.captured_at.asc(), TaskArtifact.id.asc())
        .all()
        if task_id_list
        else []
    )
    task_qa_message_obj_list = (
        db_session.query(TaskQaMessage)
        .filter(TaskQaMessage.task_id.in_(task_id_list))
        .order_by(TaskQaMessage.created_at.asc(), TaskQaMessage.id.asc())
        .all()
        if task_id_list
        else []
    )
    task_reference_link_obj_list = (
        db_session.query(TaskReferenceLink)
        .filter(
            TaskReferenceLink.source_task_id.in_(task_id_list),
            TaskReferenceLink.target_task_id.in_(task_id_list),
        )
        .order_by(TaskReferenceLink.created_at.asc(), TaskReferenceLink.id.asc())
        .all()
        if task_id_list
        else []
    )
    project_obj_list = (
        db_session.query(Project)
        .order_by(Project.created_at.asc(), Project.id.asc())
        .all()
    )
    media_file_entry_list = _collect_media_file_entry_list(dev_log_obj_list)

    snapshot_payload_dict: dict[str, Any] = {
        "snapshot_kind": _WEBDAV_SNAPSHOT_KIND,
        "schema_version": _WEBDAV_BUSINESS_SNAPSHOT_SCHEMA_VERSION,
        "exported_at": serialize_datetime_for_api(utc_now_naive()),
        "active_run_account": {
            "id": active_run_account_obj.id,
            "account_display_name": active_run_account_obj.account_display_name,
        },
        "projects": [
            {
                "id": project_obj.id,
                "display_name": project_obj.display_name,
                "project_category": project_obj.project_category,
                "repo_remote_url": project_obj.repo_remote_url,
                "repo_head_commit_hash": project_obj.repo_head_commit_hash,
                "description": project_obj.description,
                "created_at": serialize_datetime_for_api(project_obj.created_at),
            }
            for project_obj in project_obj_list
        ],
        "tasks": [
            {
                "id": task_obj.id,
                "project_id": task_obj.project_id,
                "task_title": task_obj.task_title,
                "lifecycle_status": task_obj.lifecycle_status.value,
                "workflow_stage": task_obj.workflow_stage.value,
                "stage_updated_at": serialize_datetime_for_api(
                    task_obj.stage_updated_at
                ),
                "last_ai_activity_at": serialize_datetime_for_api(
                    task_obj.last_ai_activity_at
                ),
                "requirement_brief": task_obj.requirement_brief,
                "auto_confirm_prd_and_execute": (task_obj.auto_confirm_prd_and_execute),
                "business_sync_original_workflow_stage": (
                    task_obj.business_sync_original_workflow_stage
                ),
                "business_sync_original_lifecycle_status": (
                    task_obj.business_sync_original_lifecycle_status
                ),
                "business_sync_restored_at": serialize_datetime_for_api(
                    task_obj.business_sync_restored_at
                ),
                "destroy_reason": task_obj.destroy_reason,
                "destroyed_at": serialize_datetime_for_api(task_obj.destroyed_at),
                "created_at": serialize_datetime_for_api(task_obj.created_at),
                "closed_at": serialize_datetime_for_api(task_obj.closed_at),
            }
            for task_obj in task_obj_list
        ],
        "dev_logs": [
            {
                "id": dev_log_obj.id,
                "task_id": dev_log_obj.task_id,
                "created_at": serialize_datetime_for_api(dev_log_obj.created_at),
                "text_content": dev_log_obj.text_content,
                "state_tag": dev_log_obj.state_tag.value,
                "media_original_image_path": dev_log_obj.media_original_image_path,
                "media_thumbnail_path": dev_log_obj.media_thumbnail_path,
                "ai_processing_status": (
                    dev_log_obj.ai_processing_status.value
                    if dev_log_obj.ai_processing_status
                    else None
                ),
                "ai_generated_title": dev_log_obj.ai_generated_title,
                "ai_analysis_text": dev_log_obj.ai_analysis_text,
                "ai_extracted_code": dev_log_obj.ai_extracted_code,
                "ai_confidence_score": dev_log_obj.ai_confidence_score,
                "automation_session_id": dev_log_obj.automation_session_id,
                "automation_sequence_index": dev_log_obj.automation_sequence_index,
                "automation_phase_label": dev_log_obj.automation_phase_label,
                "automation_runner_kind": dev_log_obj.automation_runner_kind,
            }
            for dev_log_obj in dev_log_obj_list
        ],
        "task_artifacts": [
            {
                "id": task_artifact_obj.id,
                "task_id": task_artifact_obj.task_id,
                "artifact_type": task_artifact_obj.artifact_type.value,
                "source_path": task_artifact_obj.source_path,
                "content_markdown": task_artifact_obj.content_markdown,
                "file_manifest_json": task_artifact_obj.file_manifest_json,
                "captured_at": serialize_datetime_for_api(
                    task_artifact_obj.captured_at
                ),
            }
            for task_artifact_obj in task_artifact_obj_list
        ],
        "task_qa_messages": [
            {
                "id": task_qa_message_obj.id,
                "task_id": task_qa_message_obj.task_id,
                "role": task_qa_message_obj.role.value,
                "context_scope": task_qa_message_obj.context_scope.value,
                "generation_status": task_qa_message_obj.generation_status.value,
                "reply_to_message_id": task_qa_message_obj.reply_to_message_id,
                "model_name": task_qa_message_obj.model_name,
                "content_markdown": task_qa_message_obj.content_markdown,
                "error_text": task_qa_message_obj.error_text,
                "created_at": serialize_datetime_for_api(
                    task_qa_message_obj.created_at
                ),
                "updated_at": serialize_datetime_for_api(
                    task_qa_message_obj.updated_at
                ),
            }
            for task_qa_message_obj in task_qa_message_obj_list
        ],
        "task_reference_links": [
            {
                "id": task_reference_link_obj.id,
                "source_task_id": task_reference_link_obj.source_task_id,
                "target_task_id": task_reference_link_obj.target_task_id,
                "reference_log_id": task_reference_link_obj.reference_log_id,
                "requirement_brief_appended": (
                    task_reference_link_obj.requirement_brief_appended
                ),
                "created_at": serialize_datetime_for_api(
                    task_reference_link_obj.created_at
                ),
            }
            for task_reference_link_obj in task_reference_link_obj_list
            if (
                task_reference_link_obj.source_task_id in task_id_set
                and task_reference_link_obj.target_task_id in task_id_set
            )
        ],
        "media_files": media_file_entry_list,
    }

    snapshot_summary = BusinessSyncSummary(
        project_count_int=len(project_obj_list),
        task_count_int=len(task_obj_list),
        dev_log_count_int=len(dev_log_obj_list),
        task_artifact_count_int=len(task_artifact_obj_list),
        task_qa_message_count_int=len(task_qa_message_obj_list),
        task_reference_link_count_int=len(task_reference_link_obj_list),
        media_file_count_int=len(media_file_entry_list),
    )
    return snapshot_payload_dict, snapshot_summary


def _write_business_sync_archive(
    archive_file_path: Path,
    snapshot_payload_dict: dict[str, Any],
) -> BusinessSyncSummary:
    """Write the snapshot payload and media assets into a ZIP archive.

    Args:
        archive_file_path: 目标 ZIP 路径
        snapshot_payload_dict: 业务快照 JSON 载荷

    Returns:
        BusinessSyncSummary: 构建出的摘要
    """

    media_file_entry_list = snapshot_payload_dict.get("media_files", [])
    with ZipFile(archive_file_path, "w", compression=ZIP_DEFLATED) as archive_file_obj:
        archive_file_obj.writestr(
            _SNAPSHOT_JSON_FILENAME,
            json.dumps(snapshot_payload_dict, ensure_ascii=False, indent=2),
        )
        for media_file_entry in media_file_entry_list:
            relative_media_path_str = media_file_entry["relative_path"]
            resolved_media_path = _resolve_exportable_media_absolute_path(
                relative_media_path_str
            )
            if resolved_media_path is None:
                continue

            _, absolute_media_path = resolved_media_path
            if not absolute_media_path.exists():
                continue

            archive_file_obj.write(
                absolute_media_path,
                arcname=_normalize_archive_member_path(
                    media_file_entry["archive_path"]
                ),
            )

    return BusinessSyncSummary(
        project_count_int=len(snapshot_payload_dict.get("projects", [])),
        task_count_int=len(snapshot_payload_dict.get("tasks", [])),
        dev_log_count_int=len(snapshot_payload_dict.get("dev_logs", [])),
        task_artifact_count_int=len(snapshot_payload_dict.get("task_artifacts", [])),
        task_qa_message_count_int=len(
            snapshot_payload_dict.get("task_qa_messages", [])
        ),
        task_reference_link_count_int=len(
            snapshot_payload_dict.get("task_reference_links", [])
        ),
        media_file_count_int=len(media_file_entry_list),
    )


def _sanitize_restored_task_stage(
    original_workflow_stage: WorkflowStage,
    original_lifecycle_status: TaskLifecycleStatus,
    *,
    has_prd_artifact_bool: bool,
) -> tuple[WorkflowStage, TaskLifecycleStatus]:
    """Map one imported task into a safe local operational stage.

    Args:
        original_workflow_stage: 远端快照中的原始阶段
        original_lifecycle_status: 远端快照中的原始生命周期
        has_prd_artifact_bool: 是否存在可恢复的 PRD 快照

    Returns:
        tuple[WorkflowStage, TaskLifecycleStatus]: 当前机器上应落库的安全阶段与生命周期
    """

    if original_lifecycle_status in {
        TaskLifecycleStatus.CLOSED,
        TaskLifecycleStatus.DELETED,
        TaskLifecycleStatus.ABANDONED,
    }:
        return original_workflow_stage, original_lifecycle_status

    if original_workflow_stage == WorkflowStage.PRD_GENERATING:
        if has_prd_artifact_bool:
            return WorkflowStage.PRD_WAITING_CONFIRMATION, TaskLifecycleStatus.OPEN
        return WorkflowStage.BACKLOG, TaskLifecycleStatus.PENDING

    if original_workflow_stage in _MACHINE_CONTEXT_DEPENDENT_STAGE_SET:
        return WorkflowStage.CHANGES_REQUESTED, TaskLifecycleStatus.OPEN

    return original_workflow_stage, original_lifecycle_status


def _copy_media_files_from_snapshot_archive(
    snapshot_archive_file_obj: ZipFile,
    media_file_entry_list: list[dict[str, str]],
) -> None:
    """Restore packaged media files into local storage.

    Args:
        snapshot_archive_file_obj: 已打开的 ZIP 快照对象
        media_file_entry_list: 媒体清单
    """

    for media_file_entry in media_file_entry_list:
        archive_member_path_str = _normalize_archive_member_path(
            media_file_entry["archive_path"]
        )
        destination_media_file_path = _resolve_restore_media_destination_path(
            media_file_entry["relative_path"]
        )
        destination_media_file_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with snapshot_archive_file_obj.open(
                archive_member_path_str, "r"
            ) as source_file_obj:
                with open(destination_media_file_path, "wb") as destination_file_obj:
                    shutil.copyfileobj(source_file_obj, destination_file_obj)
        except KeyError:
            continue


def _delete_existing_machine_local_children_for_imported_tasks(
    db_session: Session,
    imported_task_id_list: list[str],
) -> None:
    """Remove machine-local child records before rehydrating imported tasks.

    Args:
        db_session: 数据库会话
        imported_task_id_list: 参与导入的任务 ID 列表
    """

    if not imported_task_id_list:
        return

    db_session.query(TaskReferenceLink).filter(
        or_(
            TaskReferenceLink.source_task_id.in_(imported_task_id_list),
            TaskReferenceLink.target_task_id.in_(imported_task_id_list),
        )
    ).delete(synchronize_session=False)
    db_session.query(TaskScheduleRun).filter(
        TaskScheduleRun.task_id.in_(imported_task_id_list)
    ).delete(synchronize_session=False)
    db_session.query(TaskSchedule).filter(
        TaskSchedule.task_id.in_(imported_task_id_list)
    ).delete(synchronize_session=False)
    db_session.query(TaskNotification).filter(
        TaskNotification.task_id.in_(imported_task_id_list)
    ).delete(synchronize_session=False)
    db_session.query(TaskQaMessage).filter(
        TaskQaMessage.task_id.in_(imported_task_id_list)
    ).delete(synchronize_session=False)
    db_session.query(TaskArtifact).filter(
        TaskArtifact.task_id.in_(imported_task_id_list)
    ).delete(synchronize_session=False)
    db_session.query(DevLog).filter(DevLog.task_id.in_(imported_task_id_list)).delete(
        synchronize_session=False
    )


def _restore_business_sync_snapshot_payload(
    db_session: Session,
    active_run_account_obj: RunAccount,
    snapshot_payload_dict: dict[str, Any],
    snapshot_archive_file_obj: ZipFile,
) -> BusinessSyncSummary:
    """Apply one business snapshot payload into the current database.

    Args:
        db_session: 数据库会话
        active_run_account_obj: 当前活跃运行账户
        snapshot_payload_dict: 解压后的快照载荷
        snapshot_archive_file_obj: 已打开的 ZIP 快照对象

    Returns:
        BusinessSyncSummary: 恢复摘要

    Raises:
        ValueError: 当快照格式非法时抛出
    """

    if snapshot_payload_dict.get("snapshot_kind") != _WEBDAV_SNAPSHOT_KIND:
        raise ValueError("Unsupported WebDAV business snapshot kind.")
    if (
        snapshot_payload_dict.get("schema_version")
        != _WEBDAV_BUSINESS_SNAPSHOT_SCHEMA_VERSION
    ):
        raise ValueError("Unsupported WebDAV business snapshot schema version.")

    restore_started_at = utc_now_naive()
    project_snapshot_list: list[dict[str, Any]] = snapshot_payload_dict.get(
        "projects", []
    )
    task_snapshot_list: list[dict[str, Any]] = snapshot_payload_dict.get("tasks", [])
    dev_log_snapshot_list: list[dict[str, Any]] = snapshot_payload_dict.get(
        "dev_logs", []
    )
    task_artifact_snapshot_list: list[dict[str, Any]] = snapshot_payload_dict.get(
        "task_artifacts",
        [],
    )
    task_qa_snapshot_list: list[dict[str, Any]] = snapshot_payload_dict.get(
        "task_qa_messages",
        [],
    )
    task_reference_link_snapshot_list: list[dict[str, Any]] = snapshot_payload_dict.get(
        "task_reference_links",
        [],
    )
    media_file_entry_list: list[dict[str, str]] = snapshot_payload_dict.get(
        "media_files",
        [],
    )

    imported_project_id_set: set[str] = set()
    for project_snapshot_dict in project_snapshot_list:
        imported_project_id_set.add(project_snapshot_dict["id"])
        existing_project_obj = (
            db_session.query(Project)
            .filter(Project.id == project_snapshot_dict["id"])
            .first()
        )
        if existing_project_obj is None:
            existing_project_obj = Project(
                id=project_snapshot_dict["id"],
                display_name=project_snapshot_dict["display_name"],
                project_category=project_snapshot_dict.get("project_category"),
                repo_path="",
                repo_remote_url=project_snapshot_dict.get("repo_remote_url"),
                repo_head_commit_hash=project_snapshot_dict.get(
                    "repo_head_commit_hash"
                ),
                description=project_snapshot_dict.get("description"),
                created_at=_parse_snapshot_datetime_to_utc_naive(
                    project_snapshot_dict.get("created_at")
                )
                or restore_started_at,
            )
            db_session.add(existing_project_obj)
            continue

        existing_project_obj.display_name = project_snapshot_dict["display_name"]
        existing_project_obj.project_category = project_snapshot_dict.get(
            "project_category"
        )
        existing_project_obj.repo_remote_url = project_snapshot_dict.get(
            "repo_remote_url"
        )
        existing_project_obj.repo_head_commit_hash = project_snapshot_dict.get(
            "repo_head_commit_hash"
        )
        existing_project_obj.description = project_snapshot_dict.get("description")

    imported_task_id_list = [
        task_snapshot_dict["id"] for task_snapshot_dict in task_snapshot_list
    ]
    imported_task_id_set = set(imported_task_id_list)
    task_artifact_type_set_by_task_id: dict[str, set[str]] = {}
    for task_artifact_snapshot_dict in task_artifact_snapshot_list:
        task_artifact_type_set_by_task_id.setdefault(
            task_artifact_snapshot_dict["task_id"],
            set(),
        ).add(task_artifact_snapshot_dict["artifact_type"])

    sanitized_task_count_int = 0
    for task_snapshot_dict in task_snapshot_list:
        original_workflow_stage_value_str = (
            task_snapshot_dict.get("business_sync_original_workflow_stage")
            or task_snapshot_dict["workflow_stage"]
        )
        original_lifecycle_status_value_str = (
            task_snapshot_dict.get("business_sync_original_lifecycle_status")
            or task_snapshot_dict["lifecycle_status"]
        )
        original_workflow_stage = WorkflowStage(original_workflow_stage_value_str)
        original_lifecycle_status = TaskLifecycleStatus(
            original_lifecycle_status_value_str
        )
        has_prd_artifact_bool = (
            TaskArtifactType.PRD.value
            in task_artifact_type_set_by_task_id.get(task_snapshot_dict["id"], set())
        )
        sanitized_workflow_stage, sanitized_lifecycle_status = (
            _sanitize_restored_task_stage(
                original_workflow_stage,
                original_lifecycle_status,
                has_prd_artifact_bool=has_prd_artifact_bool,
            )
        )
        if (
            sanitized_workflow_stage != original_workflow_stage
            or sanitized_lifecycle_status != original_lifecycle_status
        ):
            sanitized_task_count_int += 1

        resolved_project_id: str | None = task_snapshot_dict.get("project_id")
        if resolved_project_id not in imported_project_id_set:
            resolved_project_id = None

        existing_task_obj = (
            db_session.query(Task).filter(Task.id == task_snapshot_dict["id"]).first()
        )
        if existing_task_obj is None:
            existing_task_obj = Task(
                id=task_snapshot_dict["id"],
                run_account_id=active_run_account_obj.id,
                project_id=resolved_project_id,
                task_title=task_snapshot_dict["task_title"],
                lifecycle_status=sanitized_lifecycle_status,
                workflow_stage=sanitized_workflow_stage,
                stage_updated_at=restore_started_at,
                last_ai_activity_at=_parse_snapshot_datetime_to_utc_naive(
                    task_snapshot_dict.get("last_ai_activity_at")
                ),
                worktree_path=None,
                requirement_brief=task_snapshot_dict.get("requirement_brief"),
                auto_confirm_prd_and_execute=bool(
                    task_snapshot_dict.get("auto_confirm_prd_and_execute", False)
                ),
                business_sync_original_workflow_stage=original_workflow_stage.value,
                business_sync_original_lifecycle_status=(
                    original_lifecycle_status.value
                ),
                business_sync_restored_at=restore_started_at,
                destroy_reason=task_snapshot_dict.get("destroy_reason"),
                destroyed_at=_parse_snapshot_datetime_to_utc_naive(
                    task_snapshot_dict.get("destroyed_at")
                ),
                created_at=_parse_snapshot_datetime_to_utc_naive(
                    task_snapshot_dict.get("created_at")
                )
                or restore_started_at,
                closed_at=_parse_snapshot_datetime_to_utc_naive(
                    task_snapshot_dict.get("closed_at")
                ),
            )
            db_session.add(existing_task_obj)
            continue

        existing_task_obj.run_account_id = active_run_account_obj.id
        existing_task_obj.project_id = resolved_project_id
        existing_task_obj.task_title = task_snapshot_dict["task_title"]
        existing_task_obj.lifecycle_status = sanitized_lifecycle_status
        existing_task_obj.workflow_stage = sanitized_workflow_stage
        existing_task_obj.stage_updated_at = restore_started_at
        existing_task_obj.last_ai_activity_at = _parse_snapshot_datetime_to_utc_naive(
            task_snapshot_dict.get("last_ai_activity_at")
        )
        existing_task_obj.worktree_path = None
        existing_task_obj.requirement_brief = task_snapshot_dict.get(
            "requirement_brief"
        )
        existing_task_obj.auto_confirm_prd_and_execute = bool(
            task_snapshot_dict.get("auto_confirm_prd_and_execute", False)
        )
        existing_task_obj.business_sync_original_workflow_stage = (
            original_workflow_stage.value
        )
        existing_task_obj.business_sync_original_lifecycle_status = (
            original_lifecycle_status.value
        )
        existing_task_obj.business_sync_restored_at = restore_started_at
        existing_task_obj.destroy_reason = task_snapshot_dict.get("destroy_reason")
        existing_task_obj.destroyed_at = _parse_snapshot_datetime_to_utc_naive(
            task_snapshot_dict.get("destroyed_at")
        )
        existing_task_obj.created_at = (
            _parse_snapshot_datetime_to_utc_naive(task_snapshot_dict.get("created_at"))
            or existing_task_obj.created_at
        )
        existing_task_obj.closed_at = _parse_snapshot_datetime_to_utc_naive(
            task_snapshot_dict.get("closed_at")
        )

    db_session.flush()
    _delete_existing_machine_local_children_for_imported_tasks(
        db_session,
        imported_task_id_list,
    )
    _copy_media_files_from_snapshot_archive(
        snapshot_archive_file_obj,
        media_file_entry_list,
    )

    filtered_dev_log_snapshot_list = [
        dev_log_snapshot_dict
        for dev_log_snapshot_dict in dev_log_snapshot_list
        if dev_log_snapshot_dict["task_id"] in imported_task_id_set
    ]
    imported_dev_log_id_set = {
        dev_log_snapshot_dict["id"]
        for dev_log_snapshot_dict in filtered_dev_log_snapshot_list
    }
    for dev_log_snapshot_dict in filtered_dev_log_snapshot_list:
        db_session.add(
            DevLog(
                id=dev_log_snapshot_dict["id"],
                task_id=dev_log_snapshot_dict["task_id"],
                run_account_id=active_run_account_obj.id,
                created_at=_parse_snapshot_datetime_to_utc_naive(
                    dev_log_snapshot_dict.get("created_at")
                )
                or restore_started_at,
                text_content=dev_log_snapshot_dict.get("text_content", ""),
                state_tag=DevLogStateTag(dev_log_snapshot_dict["state_tag"]),
                media_original_image_path=dev_log_snapshot_dict.get(
                    "media_original_image_path"
                ),
                media_thumbnail_path=dev_log_snapshot_dict.get("media_thumbnail_path"),
                ai_processing_status=(
                    AIProcessingStatus(dev_log_snapshot_dict["ai_processing_status"])
                    if dev_log_snapshot_dict.get("ai_processing_status")
                    else None
                ),
                ai_generated_title=dev_log_snapshot_dict.get("ai_generated_title"),
                ai_analysis_text=dev_log_snapshot_dict.get("ai_analysis_text"),
                ai_extracted_code=dev_log_snapshot_dict.get("ai_extracted_code"),
                ai_confidence_score=dev_log_snapshot_dict.get("ai_confidence_score"),
                automation_session_id=dev_log_snapshot_dict.get(
                    "automation_session_id"
                ),
                automation_sequence_index=dev_log_snapshot_dict.get(
                    "automation_sequence_index"
                ),
                automation_phase_label=dev_log_snapshot_dict.get(
                    "automation_phase_label"
                ),
                automation_runner_kind=dev_log_snapshot_dict.get(
                    "automation_runner_kind"
                ),
            )
        )

    filtered_task_artifact_snapshot_list = [
        task_artifact_snapshot_dict
        for task_artifact_snapshot_dict in task_artifact_snapshot_list
        if task_artifact_snapshot_dict["task_id"] in imported_task_id_set
    ]
    for task_artifact_snapshot_dict in filtered_task_artifact_snapshot_list:
        db_session.add(
            TaskArtifact(
                id=task_artifact_snapshot_dict["id"],
                task_id=task_artifact_snapshot_dict["task_id"],
                artifact_type=TaskArtifactType(
                    task_artifact_snapshot_dict["artifact_type"]
                ),
                source_path=task_artifact_snapshot_dict.get("source_path"),
                content_markdown=task_artifact_snapshot_dict.get(
                    "content_markdown", ""
                ),
                file_manifest_json=task_artifact_snapshot_dict.get(
                    "file_manifest_json"
                ),
                captured_at=_parse_snapshot_datetime_to_utc_naive(
                    task_artifact_snapshot_dict.get("captured_at")
                )
                or restore_started_at,
            )
        )

    filtered_task_qa_snapshot_list = [
        task_qa_snapshot_dict
        for task_qa_snapshot_dict in task_qa_snapshot_list
        if task_qa_snapshot_dict["task_id"] in imported_task_id_set
    ]
    imported_task_qa_message_id_set = {
        task_qa_snapshot_dict["id"]
        for task_qa_snapshot_dict in filtered_task_qa_snapshot_list
    }
    sorted_task_qa_snapshot_list = sorted(
        filtered_task_qa_snapshot_list,
        key=lambda task_qa_snapshot_dict: (
            task_qa_snapshot_dict.get("reply_to_message_id") is not None,
            task_qa_snapshot_dict.get("created_at") or "",
            task_qa_snapshot_dict["id"],
        ),
    )
    for task_qa_snapshot_dict in sorted_task_qa_snapshot_list:
        reply_to_message_id = task_qa_snapshot_dict.get("reply_to_message_id")
        resolved_reply_to_message_id = (
            reply_to_message_id
            if reply_to_message_id in imported_task_qa_message_id_set
            else None
        )
        db_session.add(
            TaskQaMessage(
                id=task_qa_snapshot_dict["id"],
                task_id=task_qa_snapshot_dict["task_id"],
                run_account_id=active_run_account_obj.id,
                role=TaskQaMessageRole(task_qa_snapshot_dict["role"]),
                context_scope=TaskQaContextScope(
                    task_qa_snapshot_dict["context_scope"]
                ),
                generation_status=TaskQaGenerationStatus(
                    task_qa_snapshot_dict["generation_status"]
                ),
                reply_to_message_id=resolved_reply_to_message_id,
                model_name=task_qa_snapshot_dict.get("model_name"),
                content_markdown=task_qa_snapshot_dict.get("content_markdown", ""),
                error_text=task_qa_snapshot_dict.get("error_text"),
                created_at=_parse_snapshot_datetime_to_utc_naive(
                    task_qa_snapshot_dict.get("created_at")
                )
                or restore_started_at,
                updated_at=_parse_snapshot_datetime_to_utc_naive(
                    task_qa_snapshot_dict.get("updated_at")
                )
                or restore_started_at,
            )
        )

    filtered_task_reference_link_snapshot_list = [
        task_reference_link_snapshot_dict
        for task_reference_link_snapshot_dict in task_reference_link_snapshot_list
        if (
            task_reference_link_snapshot_dict["source_task_id"] in imported_task_id_set
            and task_reference_link_snapshot_dict["target_task_id"]
            in imported_task_id_set
        )
    ]
    for task_reference_link_snapshot_dict in filtered_task_reference_link_snapshot_list:
        reference_log_id = task_reference_link_snapshot_dict.get("reference_log_id")
        resolved_reference_log_id = (
            reference_log_id if reference_log_id in imported_dev_log_id_set else None
        )
        db_session.add(
            TaskReferenceLink(
                id=task_reference_link_snapshot_dict["id"],
                run_account_id=active_run_account_obj.id,
                source_task_id=task_reference_link_snapshot_dict["source_task_id"],
                target_task_id=task_reference_link_snapshot_dict["target_task_id"],
                reference_log_id=resolved_reference_log_id,
                requirement_brief_appended=bool(
                    task_reference_link_snapshot_dict.get(
                        "requirement_brief_appended", False
                    )
                ),
                created_at=_parse_snapshot_datetime_to_utc_naive(
                    task_reference_link_snapshot_dict.get("created_at")
                )
                or restore_started_at,
            )
        )

    db_session.commit()

    return BusinessSyncSummary(
        project_count_int=len(project_snapshot_list),
        task_count_int=len(task_snapshot_list),
        dev_log_count_int=len(filtered_dev_log_snapshot_list),
        task_artifact_count_int=len(filtered_task_artifact_snapshot_list),
        task_qa_message_count_int=len(filtered_task_qa_snapshot_list),
        task_reference_link_count_int=len(filtered_task_reference_link_snapshot_list),
        media_file_count_int=len(media_file_entry_list),
        sanitized_task_count_int=sanitized_task_count_int,
    )


def _read_snapshot_payload_from_archive(
    snapshot_archive_file_obj: ZipFile,
) -> dict[str, Any]:
    """Read and decode `snapshot.json` from the ZIP archive.

    Args:
        snapshot_archive_file_obj: 已打开的 ZIP 快照对象

    Returns:
        dict[str, Any]: 解析后的 JSON 载荷

    Raises:
        ValueError: 当归档缺少 `snapshot.json` 或 JSON 非法时抛出
    """

    try:
        snapshot_payload_bytes = snapshot_archive_file_obj.read(_SNAPSHOT_JSON_FILENAME)
    except KeyError as snapshot_missing_error:
        raise ValueError(
            "Downloaded business snapshot is missing snapshot.json."
        ) from snapshot_missing_error

    try:
        decoded_snapshot_text = snapshot_payload_bytes.decode("utf-8")
        parsed_snapshot_payload = json.loads(decoded_snapshot_text)
    except (UnicodeDecodeError, json.JSONDecodeError) as snapshot_error:
        raise ValueError(
            f"Failed to read business snapshot: {snapshot_error}"
        ) from snapshot_error

    if not isinstance(parsed_snapshot_payload, dict):
        raise ValueError("Business snapshot payload must be a JSON object.")

    return parsed_snapshot_payload


def _format_business_sync_summary_message(
    business_sync_summary: BusinessSyncSummary,
    *,
    operation_label_str: str,
) -> str:
    """Format one user-facing summary message for business sync.

    Args:
        business_sync_summary: 业务同步摘要
        operation_label_str: 操作标签，如 Uploaded/Restored

    Returns:
        str: 用户可读摘要
    """

    base_summary_text = (
        f"{operation_label_str} business snapshot: "
        f"{business_sync_summary.project_count_int} projects, "
        f"{business_sync_summary.task_count_int} tasks, "
        f"{business_sync_summary.dev_log_count_int} logs, "
        f"{business_sync_summary.task_artifact_count_int} artifacts, "
        f"{business_sync_summary.task_qa_message_count_int} sidecar Q&A messages, "
        f"{business_sync_summary.task_reference_link_count_int} task references, "
        f"{business_sync_summary.media_file_count_int} media files."
    )
    if business_sync_summary.sanitized_task_count_int > 0:
        return (
            f"{base_summary_text} "
            f"{business_sync_summary.sanitized_task_count_int} tasks were reopened into "
            "safe local stages because repo/worktree execution state is machine-local."
        )
    return base_summary_text


def sync_business_snapshot_to_webdav() -> tuple[bool, str, str | None]:
    """Build and upload a business-sync snapshot archive to WebDAV.

    Returns:
        tuple[bool, str, str | None]: (是否成功, 结果消息, 远端 URL)
    """

    webdav_settings_obj = _load_webdav_settings_from_db()
    if not webdav_settings_obj:
        return False, "WebDAV settings not configured.", None
    if not webdav_settings_obj.is_enabled:
        return False, "WebDAV backup and sync are disabled.", None
    if not all(
        [
            webdav_settings_obj.server_url,
            webdav_settings_obj.username,
            webdav_settings_obj.password,
        ]
    ):
        return False, "WebDAV settings are incomplete.", None

    with TemporaryDirectory(prefix="koda-webdav-business-sync-") as temporary_dir_str:
        temporary_dir_path = Path(temporary_dir_str)
        archive_file_path = temporary_dir_path / _WEBDAV_BUSINESS_SNAPSHOT_FILENAME

        db_session = SessionLocal()
        try:
            active_run_account_obj = _require_active_run_account(db_session)
            snapshot_payload_dict, business_sync_summary = (
                _build_business_sync_snapshot_payload(
                    db_session,
                    active_run_account_obj,
                )
            )
        except Exception as export_error:
            logger.error("Failed to build WebDAV business snapshot: %s", export_error)
            return False, str(export_error), None
        finally:
            db_session.close()

        try:
            _write_business_sync_archive(archive_file_path, snapshot_payload_dict)
        except (OSError, ValueError) as archive_error:
            logger.error(
                "Failed to write WebDAV business snapshot archive: %s", archive_error
            )
            return False, str(archive_error), None

        (
            upload_success_bool,
            upload_message_str,
            remote_url_str,
        ) = upload_file_to_webdav(
            local_file_path=archive_file_path,
            server_url_str=webdav_settings_obj.server_url,
            username_str=webdav_settings_obj.username,
            password_str=webdav_settings_obj.password,
            remote_path_str=webdav_settings_obj.remote_path,
        )
        if not upload_success_bool:
            return False, upload_message_str, remote_url_str

        return (
            True,
            _compose_result_message(
                upload_message_str,
                _format_business_sync_summary_message(
                    business_sync_summary,
                    operation_label_str="Uploaded",
                ),
                (
                    "Business sync keeps card/project facts and media, but excludes "
                    "machine-local repo/worktree execution state."
                ),
            ),
            remote_url_str,
        )


def restore_business_snapshot_from_webdav() -> tuple[bool, str]:
    """Download and apply a WebDAV business-sync snapshot archive.

    Returns:
        tuple[bool, str]: (是否成功, 结果消息)
    """

    webdav_settings_obj = _load_webdav_settings_from_db()
    if not webdav_settings_obj:
        return False, "WebDAV settings not configured."
    if not webdav_settings_obj.is_enabled:
        return False, "WebDAV backup and sync are disabled."
    if not all(
        [
            webdav_settings_obj.server_url,
            webdav_settings_obj.username,
            webdav_settings_obj.password,
        ]
    ):
        return False, "WebDAV settings are incomplete."

    with TemporaryDirectory(
        prefix="koda-webdav-business-restore-"
    ) as temporary_dir_str:
        temporary_dir_path = Path(temporary_dir_str)
        archive_file_path = temporary_dir_path / _WEBDAV_BUSINESS_SNAPSHOT_FILENAME
        (
            download_success_bool,
            download_message_str,
        ) = download_file_from_webdav(
            remote_filename_str=_WEBDAV_BUSINESS_SNAPSHOT_FILENAME,
            local_dest_path=archive_file_path,
            server_url_str=webdav_settings_obj.server_url,
            username_str=webdav_settings_obj.username,
            password_str=webdav_settings_obj.password,
            remote_path_str=webdav_settings_obj.remote_path,
        )
        if not download_success_bool:
            return False, download_message_str

        try:
            with ZipFile(archive_file_path, "r") as snapshot_archive_file_obj:
                snapshot_payload_dict = _read_snapshot_payload_from_archive(
                    snapshot_archive_file_obj
                )

                db_session = SessionLocal()
                try:
                    active_run_account_obj = _require_active_run_account(db_session)
                    business_sync_summary = _restore_business_sync_snapshot_payload(
                        db_session,
                        active_run_account_obj,
                        snapshot_payload_dict,
                        snapshot_archive_file_obj,
                    )
                except Exception as restore_error:
                    db_session.rollback()
                    logger.error(
                        "Failed to restore WebDAV business snapshot: %s",
                        restore_error,
                    )
                    return False, str(restore_error)
                finally:
                    db_session.close()
        except (BadZipFile, OSError, ValueError) as archive_error:
            return False, str(archive_error)

    relink_hint_message_str = _build_repo_relink_hint_message()
    return (
        True,
        _compose_result_message(
            download_message_str,
            _format_business_sync_summary_message(
                business_sync_summary,
                operation_label_str="Restored",
            ),
            (
                "Imported tasks keep synced card progress, but repo/worktree execution "
                "state must be rebuilt locally before continuing code work."
            ),
            relink_hint_message_str,
        ),
    )
