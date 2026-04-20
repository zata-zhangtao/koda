"""Task API 路由.

提供任务的创建、查询、状态更新、工作流阶段管理和执行触发功能.
"""

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.dsl.models.dev_log import DevLog
from backend.dsl.models.enums import DevLogStateTag, TaskLifecycleStatus, WorkflowStage
from backend.dsl.models.task import TASK_REQUIREMENT_BRIEF_MAX_LENGTH, Task
from backend.dsl.models.task_reference_link import TaskReferenceLink
from backend.dsl.schemas.dev_log_schema import DevLogCreateSchema
from backend.dsl.schemas.task_schema import (
    TaskBranchHealthSchema,
    TaskCreateSchema,
    TaskCardMetadataSchema,
    TaskDestroySchema,
    TaskReferenceCreateSchema,
    TaskReferenceResponseSchema,
    TaskResponseSchema,
    TaskStageUpdateSchema,
    TaskStatusUpdateSchema,
    TaskUpdateSchema,
)
from backend.dsl.services.automation_runner import (
    cancel_task_automation,
    clear_task_background_activity,
    get_task_log_path,
    is_task_automation_running,
    register_task_background_activity,
    run_task_completion,
    run_task_implementation,
    run_task_post_review_lint_resume,
    run_task_prd,
    run_task_review,
    run_task_self_review_resume,
)
from backend.dsl.services.log_service import LogService
from backend.dsl.services.path_opener import (
    PathOpenCommandError,
    PathOpenTargetNotFoundError,
    open_path_in_editor,
)
from backend.dsl.services.prd_file_service import (
    find_task_prd_file_path,
    repair_invalid_task_prd_file_for_read,
)
from backend.dsl.services.terminal_launcher import TerminalLaunchError, open_log_tail_terminal
from backend.dsl.services.task_service import TaskService
from utils.database import get_db
from utils.logger import logger
from utils.settings import config

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# Backward-compatible aliases for internal references/tests while
# route orchestration now uses runner-agnostic entrypoints.
is_codex_task_running = is_task_automation_running
run_codex_prd = run_task_prd
run_codex_task = run_task_implementation
run_codex_review_only = run_task_review
run_codex_review_resume = run_task_self_review_resume
run_post_review_lint_resume = run_task_post_review_lint_resume
run_codex_completion = run_task_completion
cancel_codex_task = cancel_task_automation

_SELF_REVIEW_PASSED_LOG_MARKER_LIST = [
    "AI 自检闭环完成",
    "AI 自检完成，未发现阻塞性问题",
]
_SELF_REVIEW_STARTED_LOG_MARKER_LIST = [
    "开始第 1 轮代码评审",
    "开始执行代码评审",
    "开始重新执行 AI 自检",
]
_POST_REVIEW_LINT_PASSED_LOG_MARKER_LIST = [
    "post-review lint 闭环完成：pre-commit 已通过",
]
_POST_REVIEW_LINT_STARTED_LOG_MARKER_LIST = [
    "已进入自动化验证阶段，开始执行 post-review lint：",
    "post-review lint 未通过，开始第 ",
    "轮 AI lint 定向修复完成，开始重新执行 pre-commit lint。",
]
_SELF_REVIEW_SUMMARY_LINE_PREFIX = "摘要："
_COMMIT_INFORMATION_SOURCE_AI_SUMMARY = "ai_summary"
_COMMIT_INFORMATION_SOURCE_REQUIREMENT_BRIEF = "requirement_brief"
_COMMIT_INFORMATION_SOURCE_TASK_TITLE = "task_title"
_ATTACHMENT_MARKDOWN_LINK_PATTERN = re.compile(r"\(/api/media/(?P<filename>[^)\s?#]+)")
_WAITING_USER_DISPLAY_STAGE_KEY = "waiting_user"
_WAITING_USER_DISPLAY_STAGE_LABEL = "等待用户"
_BRANCH_MISSING_DISPLAY_STAGE_KEY = "branch_missing"
_BRANCH_MISSING_DISPLAY_STAGE_LABEL = "缺失分支待确认"
_REQUIREMENT_UPDATE_MARKER = "<!-- requirement-change:update -->"
_REQUIREMENT_BRIEF_APPENDIX_HEADER = "## Referenced Requirement Context"
_REQUIREMENT_BRIEF_APPENDIX_SEPARATOR = "\n\n---\n\n"
_REQUIREMENT_BRIEF_COMPACT_APPENDIX_NOTE = (
    "Full reference summary moved to the structured reference log because the "
    "target requirement brief is near its size limit."
)
_WORKFLOW_STAGE_LABEL_MAP: dict[WorkflowStage, str] = {
    WorkflowStage.BACKLOG: "Backlog",
    WorkflowStage.PRD_GENERATING: "Drafting PRD",
    WorkflowStage.PRD_WAITING_CONFIRMATION: "PRD Ready",
    WorkflowStage.IMPLEMENTATION_IN_PROGRESS: "Coding",
    WorkflowStage.SELF_REVIEW_IN_PROGRESS: "Self Review",
    WorkflowStage.TEST_IN_PROGRESS: "Testing",
    WorkflowStage.PR_PREPARING: "PR Prep",
    WorkflowStage.ACCEPTANCE_IN_PROGRESS: "Acceptance",
    WorkflowStage.CHANGES_REQUESTED: "Changes Requested",
    WorkflowStage.DONE: "Done",
}
_REQUIREMENT_DELETE_MARKER = "<!-- requirement-change:delete -->"


@dataclass(frozen=True)
class CompletionCommitInformationResolution:
    """描述 Complete 阶段解析出的 commit information.

    Attributes:
        commit_information_text: 传给完成链路的原始 commit information 文本
        commit_information_source: commit information 的来源标签
    """

    commit_information_text: str
    commit_information_source: str


@dataclass(frozen=True)
class RequirementChangeSnapshot:
    """Describe the latest requirement-change log found for a task.

    Attributes:
        change_kind: Whether the log captured an update or delete event.
        summary_text: Human-readable summary extracted from the marker body.
    """

    change_kind: str
    summary_text: str | None


def _get_current_run_account_id(db_session: Session) -> str:
    """获取当前活跃账户 ID.

    Args:
        db_session: 数据库会话

    Returns:
        str: 当前活跃账户 ID

    Raises:
        HTTPException: 当没有活跃账户时返回 400
    """
    from backend.dsl.models.run_account import RunAccount

    active_account = db_session.query(RunAccount).filter(RunAccount.is_active).first()
    if not active_account:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active run account. Please create a run account first.",
        )
    return active_account.id


def _get_ordered_task_dev_logs(task_obj: Task) -> list[DevLog]:
    """返回按创建时间排序的任务日志列表.

    Args:
        task_obj: 任务对象

    Returns:
        list[DevLog]: 按 `(created_at, id)` 升序排列的日志列表
    """
    return sorted(
        task_obj.dev_logs,
        key=lambda dev_log_item: (dev_log_item.created_at, dev_log_item.id),
    )


def _get_ordered_task_dev_logs_by_task_id(
    db_session: Session,
    task_id_list: list[str],
) -> dict[str, list[DevLog]]:
    """批量返回按时间排序的任务日志列表.

    Args:
        db_session: 数据库会话
        task_id_list: 需要查询日志的任务 ID 列表

    Returns:
        dict[str, list[DevLog]]: `task_id -> ordered dev logs` 映射
    """
    ordered_task_dev_logs_by_task_id: dict[str, list[DevLog]] = {
        task_id_str: [] for task_id_str in task_id_list
    }
    if not task_id_list:
        return ordered_task_dev_logs_by_task_id

    ordered_dev_log_list = (
        db_session.query(DevLog)
        .filter(DevLog.task_id.in_(task_id_list))
        .order_by(DevLog.task_id.asc(), DevLog.created_at.asc(), DevLog.id.asc())
        .all()
    )
    for dev_log_item in ordered_dev_log_list:
        ordered_task_dev_logs_by_task_id.setdefault(dev_log_item.task_id, []).append(
            dev_log_item
        )
    return ordered_task_dev_logs_by_task_id


def _clean_markdown_preview(raw_markdown_text: str) -> str:
    """Normalize marker bodies into the short plain-text summary used by cards.

    Args:
        raw_markdown_text: Raw Markdown section content.

    Returns:
        str: Collapsed preview text suitable for task cards.
    """
    normalized_preview_text = re.sub(r"<!--[\s\S]*?-->", " ", raw_markdown_text)
    normalized_preview_text = re.sub(r"^/[a-z-]+\s+", "", normalized_preview_text)
    normalized_preview_text = re.sub(
        r"```[\s\S]*?```",
        " code block ",
        normalized_preview_text,
    )
    normalized_preview_text = normalized_preview_text.replace("`", "")
    normalized_preview_text = re.sub(
        r"[#!>*_[\]()\-+]+",
        " ",
        normalized_preview_text,
    )
    normalized_preview_text = re.sub(r"\s+", " ", normalized_preview_text)
    return normalized_preview_text.strip()


def _extract_marker_body(
    raw_markdown_text: str,
    section_label: str,
) -> str | None:
    """Extract the body text after a marker section heading.

    Args:
        raw_markdown_text: Full Markdown log body.
        section_label: Section heading to locate.

    Returns:
        str | None: Trimmed body text or `None` when the section is absent.
    """
    section_pattern = re.compile(rf"{re.escape(section_label)}\n([\s\S]*)$")
    section_match = section_pattern.search(raw_markdown_text)
    return (section_match.group(1).strip() if section_match else None) or None


def _parse_requirement_change_log(
    raw_markdown_text: str,
) -> RequirementChangeSnapshot | None:
    """Parse a requirement-update/delete audit log into card-friendly fields.

    Args:
        raw_markdown_text: Full log Markdown body.

    Returns:
        RequirementChangeSnapshot | None: Parsed change snapshot or `None`.
    """
    has_requirement_update_marker = _REQUIREMENT_UPDATE_MARKER in raw_markdown_text
    has_requirement_delete_marker = _REQUIREMENT_DELETE_MARKER in raw_markdown_text
    if not has_requirement_update_marker and not has_requirement_delete_marker:
        return None

    change_kind = "update" if has_requirement_update_marker else "delete"
    summary_section_label = "Summary:" if change_kind == "update" else "Final Summary:"
    raw_summary_body = (
        _extract_marker_body(raw_markdown_text, summary_section_label) or ""
    )
    normalized_summary_text = _clean_markdown_preview(raw_summary_body)
    return RequirementChangeSnapshot(
        change_kind=change_kind,
        summary_text=normalized_summary_text or None,
    )


def _get_latest_requirement_change_snapshot(
    ordered_task_dev_log_list: list[DevLog],
) -> RequirementChangeSnapshot | None:
    """Find the most recent requirement-change audit log for a task.

    Args:
        ordered_task_dev_log_list: Task logs ordered by time ascending.

    Returns:
        RequirementChangeSnapshot | None: Latest parsed requirement-change snapshot.
    """
    for dev_log_item in reversed(ordered_task_dev_log_list):
        requirement_change_snapshot = _parse_requirement_change_log(
            dev_log_item.text_content
        )
        if requirement_change_snapshot is not None:
            return requirement_change_snapshot
    return None


def _get_latest_requirement_change_snapshot_map_by_task_id(
    db_session: Session,
    task_id_list: list[str],
) -> dict[str, RequirementChangeSnapshot]:
    """批量返回任务最近一条需求变更快照.

    `card-metadata` 只需要需求变更摘要，不应该把任务的全部时间线都读入内存。
    这里仅查询带有 requirement-change marker 的日志，并按时间倒序为每个任务保留
    第一条匹配记录。

    Args:
        db_session: 数据库会话
        task_id_list: 任务 ID 列表

    Returns:
        dict[str, RequirementChangeSnapshot]: `task_id -> latest requirement-change`
            映射；无匹配日志的任务不会出现在结果中
    """
    if not task_id_list:
        return {}

    relevant_requirement_change_filter = or_(
        DevLog.text_content.contains(_REQUIREMENT_UPDATE_MARKER),
        DevLog.text_content.contains(_REQUIREMENT_DELETE_MARKER),
    )
    relevant_requirement_change_row_list = (
        db_session.query(
            DevLog.task_id,
            DevLog.text_content,
        )
        .filter(
            DevLog.task_id.in_(task_id_list),
            relevant_requirement_change_filter,
        )
        .order_by(DevLog.task_id.asc(), DevLog.created_at.desc(), DevLog.id.desc())
        .all()
    )

    latest_requirement_change_snapshot_map_by_task_id: dict[
        str, RequirementChangeSnapshot
    ] = {}
    for task_id_str, log_text in relevant_requirement_change_row_list:
        if task_id_str in latest_requirement_change_snapshot_map_by_task_id:
            continue
        requirement_change_snapshot = _parse_requirement_change_log(log_text)
        if requirement_change_snapshot is not None:
            latest_requirement_change_snapshot_map_by_task_id[task_id_str] = (
                requirement_change_snapshot
            )

    return latest_requirement_change_snapshot_map_by_task_id


def _get_latest_waiting_user_signal_map_by_task_id(
    db_session: Session,
    task_id_list: list[str],
) -> dict[str, dict[str, bool | None]]:
    """批量返回任务最近一轮 review/lint 的通过信号.

    该接口只为任务卡片元数据服务，因此不需要把整条任务日志历史全部载入内存。
    我们只查询与“等待用户点击 Complete”判断有关的少量标记日志，并按时间倒序
    为每个任务提取最近一次相关结论。

    Args:
        db_session: 数据库会话
        task_id_list: 任务 ID 列表

    Returns:
        dict[str, dict[str, bool | None]]: `task_id -> signal map`
    """
    latest_signal_map_by_task_id: dict[str, dict[str, bool | None]] = {
        task_id_str: {
            "self_review_passed": None,
            "post_review_lint_passed": None,
        }
        for task_id_str in task_id_list
    }
    if not task_id_list:
        return latest_signal_map_by_task_id

    relevant_marker_text_list = [
        *_SELF_REVIEW_PASSED_LOG_MARKER_LIST,
        *_SELF_REVIEW_STARTED_LOG_MARKER_LIST,
        *_POST_REVIEW_LINT_PASSED_LOG_MARKER_LIST,
        *_POST_REVIEW_LINT_STARTED_LOG_MARKER_LIST,
    ]
    relevant_marker_filter = or_(
        *(
            DevLog.text_content.contains(marker_text)
            for marker_text in relevant_marker_text_list
        )
    )
    relevant_log_row_list = (
        db_session.query(
            DevLog.task_id,
            DevLog.text_content,
        )
        .filter(
            DevLog.task_id.in_(task_id_list),
            relevant_marker_filter,
        )
        .order_by(DevLog.task_id.asc(), DevLog.created_at.desc(), DevLog.id.desc())
        .all()
    )

    for task_id_str, log_text in relevant_log_row_list:
        task_signal_map = latest_signal_map_by_task_id.setdefault(
            task_id_str,
            {
                "self_review_passed": None,
                "post_review_lint_passed": None,
            },
        )

        if task_signal_map["self_review_passed"] is None:
            if any(
                marker_text in log_text
                for marker_text in _SELF_REVIEW_PASSED_LOG_MARKER_LIST
            ):
                task_signal_map["self_review_passed"] = True
            elif any(
                marker_text in log_text
                for marker_text in _SELF_REVIEW_STARTED_LOG_MARKER_LIST
            ):
                task_signal_map["self_review_passed"] = False

        if task_signal_map["post_review_lint_passed"] is None:
            if any(
                marker_text in log_text
                for marker_text in _POST_REVIEW_LINT_PASSED_LOG_MARKER_LIST
            ):
                task_signal_map["post_review_lint_passed"] = True
            elif any(
                marker_text in log_text
                for marker_text in _POST_REVIEW_LINT_STARTED_LOG_MARKER_LIST
            ):
                task_signal_map["post_review_lint_passed"] = False

    return latest_signal_map_by_task_id


def _resolve_task_effective_work_dir_path(
    db_session: Session,
    task_obj: Task,
) -> Path:
    """解析任务的 Codex 工作目录.

    优先级：task worktree > 关联项目仓库根 > Koda 仓库根目录。

    Args:
        db_session: 数据库会话
        task_obj: 任务对象

    Returns:
        Path: 可用于 Codex 执行的工作目录
    """
    effective_work_dir_path = config.BASE_DIR
    if task_obj.worktree_path:
        worktree_dir_path = Path(task_obj.worktree_path)
        if worktree_dir_path.exists():
            return worktree_dir_path

    if task_obj.project_id:
        from backend.dsl.models.project import Project

        project_obj = (
            db_session.query(Project).filter(Project.id == task_obj.project_id).first()
        )
        if project_obj:
            project_repo_path = Path(project_obj.repo_path)
            if project_repo_path.exists():
                return project_repo_path

    return effective_work_dir_path


def _resolve_task_review_work_dir_path(
    db_session: Session,
    task_obj: Task,
) -> Path:
    """Resolve the working directory for standalone review-only automation.

    独立评审必须指向真实的 task worktree 或绑定项目仓库，不能回退到 Koda 自身仓库。

    Args:
        db_session: 数据库会话
        task_obj: 任务对象

    Returns:
        Path: review-only 执行目录

    Raises:
        HTTPException: 当任务没有可用的 worktree / 项目仓库时抛出 422
    """
    if task_obj.worktree_path:
        worktree_dir_path = Path(task_obj.worktree_path)
        if worktree_dir_path.exists():
            return worktree_dir_path

    if task_obj.project_id:
        from backend.dsl.models.project import Project

        project_obj = (
            db_session.query(Project).filter(Project.id == task_obj.project_id).first()
        )
        if project_obj:
            project_repo_path = Path(project_obj.repo_path)
            if project_repo_path.exists():
                return project_repo_path

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=(
            "Standalone review requires an existing task worktree or linked project "
            "repository on this machine."
        ),
    )


def _extract_attachment_absolute_path_list(raw_log_text_str: str) -> list[str]:
    """从日志 Markdown 中提取附件对应的本地绝对路径.

    Args:
        raw_log_text_str: 日志文本

    Returns:
        list[str]: 附件绝对路径列表，按出现顺序去重
    """
    attachment_absolute_path_list: list[str] = []
    seen_attachment_path_set: set[str] = set()

    for markdown_match in _ATTACHMENT_MARKDOWN_LINK_PATTERN.finditer(raw_log_text_str):
        attachment_filename_str = markdown_match.group("filename").strip()
        if not attachment_filename_str:
            continue
        attachment_absolute_path = (
            Path(config.MEDIA_STORAGE_PATH) / "original" / attachment_filename_str
        ).resolve()
        attachment_absolute_path_str = str(attachment_absolute_path)
        if attachment_absolute_path_str in seen_attachment_path_set:
            continue
        seen_attachment_path_set.add(attachment_absolute_path_str)
        attachment_absolute_path_list.append(attachment_absolute_path_str)

    return attachment_absolute_path_list


def _build_task_context_entry(dev_log_item: DevLog) -> str:
    """把一条 DevLog 转成适合下游 Prompt 的上下文块.

    当日志包含图片或附件时，除了原始文本，还会附带本地文件路径合同，
    让 Codex 在需要时显式检查这些文件，而不是只看到一段普通文字。

    Args:
        dev_log_item: 单条任务日志

    Returns:
        str: 序列化后的上下文块；若该日志没有有效内容则返回空字符串
    """
    raw_text_content_str = dev_log_item.text_content.strip()
    context_line_list: list[str] = []
    if raw_text_content_str:
        context_line_list.append(raw_text_content_str)

    local_media_absolute_path_list: list[str] = []
    seen_media_path_set: set[str] = set()

    if dev_log_item.media_original_image_path:
        raw_media_path = Path(dev_log_item.media_original_image_path)
        resolved_media_path = (
            raw_media_path
            if raw_media_path.is_absolute()
            else (config.BASE_DIR / raw_media_path).resolve()
        )
        resolved_media_path_str = str(resolved_media_path)
        seen_media_path_set.add(resolved_media_path_str)
        local_media_absolute_path_list.append(resolved_media_path_str)

    for attachment_absolute_path_str in _extract_attachment_absolute_path_list(
        raw_text_content_str
    ):
        if attachment_absolute_path_str in seen_media_path_set:
            continue
        seen_media_path_set.add(attachment_absolute_path_str)
        local_media_absolute_path_list.append(attachment_absolute_path_str)

    if local_media_absolute_path_list:
        if context_line_list:
            context_line_list.append("")
        context_line_list.append("Attached local files:")
        for local_media_absolute_path_str in local_media_absolute_path_list:
            context_line_list.append(f"- `{local_media_absolute_path_str}`")
        context_line_list.append(
            "If these files help clarify the requirement, inspect them directly. "
            "For non-text binary files that cannot be parsed in this environment, "
            "do not ignore them silently; at minimum account for their filenames and existence."
        )

    return "\n".join(context_line_list).strip()


def _build_task_context_snapshot_list(task_dev_log_list: list[DevLog]) -> list[str]:
    """构建任务最近上下文快照.

    Args:
        task_dev_log_list: 任务日志列表

    Returns:
        list[str]: 序列化后的日志上下文列表
    """
    task_context_snapshot_list: list[str] = []
    for dev_log_item in task_dev_log_list:
        serialized_context_entry = _build_task_context_entry(dev_log_item)
        if serialized_context_entry:
            task_context_snapshot_list.append(serialized_context_entry)
    return task_context_snapshot_list


def _create_internal_archive_audit_log(
    db_session: Session,
    task_obj: Task,
    *,
    log_text_content: str,
    log_state_tag: DevLogStateTag,
) -> None:
    """Persist an internal archive-transition audit log for a task.

    Args:
        db_session: 数据库会话
        task_obj: 已完成状态迁移的任务
        log_text_content: 留痕日志正文
        log_state_tag: 留痕状态标签
    """
    LogService.create_internal_log(
        db_session,
        DevLogCreateSchema(
            task_id=task_obj.id,
            text_content=log_text_content,
            state_tag=log_state_tag,
        ),
        task_obj.run_account_id,
    )


def _build_requirement_delete_audit_log(task_obj: Task) -> str:
    """Build the system log body used when a requirement is archived as deleted.

    Args:
        task_obj: 已删除归档的任务对象

    Returns:
        str: 删除留痕日志正文
    """
    final_requirement_summary = (
        task_obj.requirement_brief
        or "No requirement summary was captured before deletion."
    )
    return "\n".join(
        [
            _REQUIREMENT_DELETE_MARKER,
            "## Requirement Deleted",
            "",
            f"Title: {task_obj.task_title}",
            "",
            "Final Summary:",
            final_requirement_summary,
        ]
    )


def _build_task_reference_log_markdown(
    source_task_obj: Task,
    target_task_obj: Task,
    reference_note_text: str | None,
) -> str:
    """构建“引用历史任务”结构化日志.

    Args:
        source_task_obj: 来源任务
        target_task_obj: 目标任务
        reference_note_text: 引用备注

    Returns:
        str: 用于持久化到 DevLog 的 Markdown 文本
    """
    source_requirement_summary_text = (
        source_task_obj.requirement_brief or "No requirement brief captured."
    )
    log_line_list = [
        "<!-- requirement-reference:add -->",
        "## Requirement Reference Added",
        "",
        f"Source Task ID: {source_task_obj.id}",
        f"Source Task Title: {source_task_obj.task_title}",
        f"Source Task Status: {source_task_obj.lifecycle_status.value}",
        f"Target Task ID: {target_task_obj.id}",
        f"Target Task Title: {target_task_obj.task_title}",
        "",
        "Source Requirement:",
        source_requirement_summary_text,
    ]
    if reference_note_text:
        log_line_list.extend(
            [
                "",
                "Reference Note:",
                reference_note_text,
            ]
        )
    return "\n".join(log_line_list)


def _build_reference_appendix_for_requirement_brief(
    source_task_obj: Task,
    reference_note_text: str | None,
) -> str:
    """构建追加到 requirement_brief 的引用附录.

    Args:
        source_task_obj: 来源任务
        reference_note_text: 引用备注

    Returns:
        str: 结构化引用附录
    """
    source_requirement_summary_text = (
        source_task_obj.requirement_brief or "No requirement brief captured."
    )
    appendix_line_list = [
        _REQUIREMENT_BRIEF_APPENDIX_HEADER,
        "",
        f"- Source Task: {source_task_obj.task_title}",
        f"- Source Task ID: {source_task_obj.id}",
        f"- Source Task Status: {source_task_obj.lifecycle_status.value}",
        "",
        source_requirement_summary_text,
    ]
    if reference_note_text:
        appendix_line_list.extend(
            [
                "",
                f"Note: {reference_note_text}",
            ]
        )
    return "\n".join(appendix_line_list)


def _build_compact_reference_appendix_for_requirement_brief(
    source_task_obj: Task,
) -> str:
    """构建紧凑版 requirement_brief 引用附录.

    当完整来源摘要无法放入目标任务 `requirement_brief` 时，退化为仅保留
    审计锚点和提示文案的紧凑版本，避免数据库长度溢出。

    Args:
        source_task_obj: 来源任务

    Returns:
        str: 紧凑版结构化引用附录
    """
    compact_appendix_line_list = [
        _REQUIREMENT_BRIEF_APPENDIX_HEADER,
        "",
        f"- Source Task ID: {source_task_obj.id}",
        "",
        _REQUIREMENT_BRIEF_COMPACT_APPENDIX_NOTE,
    ]
    return "\n".join(compact_appendix_line_list)


def _build_bounded_requirement_brief_with_reference_appendix(
    existing_requirement_brief_text: str,
    source_task_obj: Task,
    reference_note_text: str | None,
) -> str:
    """构建受字段长度保护的 requirement_brief 更新文本.

    优先尝试写入完整引用附录；若超出 `Task.requirement_brief` 列上限，
    则退化为紧凑版引用附录；若连紧凑版都无法容纳，则直接返回 422，
    避免数据库层抛出 500。

    Args:
        existing_requirement_brief_text: 目标任务当前 requirement_brief
        source_task_obj: 来源任务
        reference_note_text: 引用备注

    Returns:
        str: 可安全持久化的新 requirement_brief 文本

    Raises:
        HTTPException: 当目标字段没有足够空间容纳最小引用附录时抛出 422
    """
    appendix_separator_text = (
        _REQUIREMENT_BRIEF_APPENDIX_SEPARATOR if existing_requirement_brief_text else ""
    )
    appendix_candidate_list = [
        _build_reference_appendix_for_requirement_brief(
            source_task_obj=source_task_obj,
            reference_note_text=reference_note_text,
        ),
        _build_compact_reference_appendix_for_requirement_brief(
            source_task_obj=source_task_obj,
        ),
    ]
    for requirement_appendix_markdown in appendix_candidate_list:
        bounded_requirement_brief_text = (
            f"{existing_requirement_brief_text}"
            f"{appendix_separator_text}"
            f"{requirement_appendix_markdown}"
        )
        if len(bounded_requirement_brief_text) <= TASK_REQUIREMENT_BRIEF_MAX_LENGTH:
            return bounded_requirement_brief_text
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=(
            "Referenced requirement context cannot fit in target "
            f"requirement_brief because the field is limited to "
            f"{TASK_REQUIREMENT_BRIEF_MAX_LENGTH} characters."
        ),
    )


def _requirement_brief_contains_reference(
    target_task_obj: Task,
    source_task_id: str,
) -> bool:
    """判断目标任务 requirement_brief 是否已包含指定来源任务的引用附录.

    Args:
        target_task_obj: 目标任务
        source_task_id: 来源任务 ID

    Returns:
        bool: 若已存在该来源任务的引用附录则返回 True
    """
    requirement_brief_text = target_task_obj.requirement_brief or ""
    return (
        _REQUIREMENT_BRIEF_APPENDIX_HEADER in requirement_brief_text
        and f"- Source Task ID: {source_task_id}" in requirement_brief_text
    )


def _find_existing_task_reference_log(
    db_session: Session,
    source_task_id: str,
    target_task_id: str,
) -> DevLog | None:
    """按结构化内容查找已存在的任务引用日志.

    Args:
        db_session: 数据库会话
        source_task_id: 来源任务 ID
        target_task_id: 目标任务 ID

    Returns:
        DevLog | None: 已存在的结构化引用日志；不存在时返回 None
    """
    required_marker_text_list = [
        "<!-- requirement-reference:add -->",
        f"Source Task ID: {source_task_id}",
        f"Target Task ID: {target_task_id}",
    ]
    candidate_reference_log_list = (
        db_session.query(DevLog)
        .filter(
            DevLog.task_id == target_task_id,
            DevLog.state_tag == DevLogStateTag.TRANSFERRED,
        )
        .order_by(DevLog.created_at.asc(), DevLog.id.asc())
        .all()
    )
    for reference_log_obj in candidate_reference_log_list:
        if all(
            marker_text in reference_log_obj.text_content
            for marker_text in required_marker_text_list
        ):
            return reference_log_obj
    return None


def _schedule_prd_generation(
    task_obj: Task,
    background_tasks: BackgroundTasks,
    db_session: Session,
) -> Task:
    """调度后台 PRD 生成任务并返回带运行态的任务响应.

    Args:
        task_obj: 已切换到 `prd_generating` 的任务对象
        background_tasks: FastAPI 后台任务容器
        db_session: 数据库会话

    Returns:
        Task: 带运行态计算字段的任务对象
    """
    ordered_task_dev_log_list = _get_ordered_task_dev_logs(task_obj)
    dev_log_text_snapshot_list = _build_task_context_snapshot_list(
        ordered_task_dev_log_list
    )
    effective_work_dir_path = _resolve_task_effective_work_dir_path(
        db_session,
        task_obj,
    )

    task_log_path = get_task_log_path(task_obj.id)
    if not task_log_path.exists():
        task_log_path.write_text(
            (
                f"=== Koda queued-prd | task {task_obj.id[:8]} ===\n"
                "已收到 PRD 生成请求，等待后台执行器开始写入详细日志。\n"
            ),
            encoding="utf-8",
        )

    register_task_background_activity(task_obj.id)
    background_tasks.add_task(
        run_codex_prd,
        task_id_str=task_obj.id,
        run_account_id_str=task_obj.run_account_id,
        task_title_str=task_obj.task_title,
        dev_log_text_list=dev_log_text_snapshot_list,
        work_dir_path=effective_work_dir_path,
        worktree_path_str=task_obj.worktree_path,
        auto_confirm_prd_and_execute_bool=task_obj.auto_confirm_prd_and_execute,
    )
    return _hydrate_task_response(
        task_obj,
        db_session=db_session,
        is_task_running_override=True,
    )


def _has_latest_self_review_cycle_passed(task_dev_log_list: list[DevLog]) -> bool:
    """判断最近一轮 self-review 是否已经出现通过标记.

    Args:
        task_dev_log_list: 已按时间正序排列的任务日志列表

    Returns:
        bool: 若最近一轮 self-review 已出现通过标记则返回 True，否则返回 False
    """
    for dev_log_item in reversed(task_dev_log_list):
        log_text = dev_log_item.text_content
        if any(
            marker_text in log_text
            for marker_text in _SELF_REVIEW_PASSED_LOG_MARKER_LIST
        ):
            return True
        if any(
            marker_text in log_text
            for marker_text in _SELF_REVIEW_STARTED_LOG_MARKER_LIST
        ):
            return False

    return False


def _extract_self_review_summary_from_log_text(log_text_str: str) -> str | None:
    """从单条 self-review 日志中提取摘要正文.

    Args:
        log_text_str: 日志文本

    Returns:
        str | None: 若存在 `摘要：...` 行则返回正文，否则返回 None
    """
    for raw_log_line_str in log_text_str.splitlines():
        stripped_log_line_str = raw_log_line_str.strip()
        if not stripped_log_line_str.startswith(_SELF_REVIEW_SUMMARY_LINE_PREFIX):
            continue

        extracted_summary_str = stripped_log_line_str.removeprefix(
            _SELF_REVIEW_SUMMARY_LINE_PREFIX
        ).strip()
        return extracted_summary_str or None

    return None


def _extract_latest_passed_self_review_summary(
    task_dev_log_list: list[DevLog],
) -> str | None:
    """提取最近一轮通过的 self-review 摘要.

    逆序扫描日志；若先遇到新一轮 self-review 开始标记但尚未通过，
    则不会继续误用更旧轮次的通过摘要。

    Args:
        task_dev_log_list: 已按时间正序排列的任务日志列表

    Returns:
        str | None: 最近一轮通过的 self-review 摘要；若不存在则返回 None
    """
    for dev_log_item in reversed(task_dev_log_list):
        log_text = dev_log_item.text_content
        if any(
            marker_text in log_text
            for marker_text in _SELF_REVIEW_PASSED_LOG_MARKER_LIST
        ):
            return _extract_self_review_summary_from_log_text(log_text)
        if any(
            marker_text in log_text
            for marker_text in _SELF_REVIEW_STARTED_LOG_MARKER_LIST
        ):
            return None

    return None


def _resolve_completion_commit_information(
    task_obj: Task,
    ordered_task_dev_log_list: list[DevLog],
) -> CompletionCommitInformationResolution:
    """解析 Complete 阶段使用的 commit information 与来源.

    优先级固定为：最近一轮通过的 self-review AI summary ->
    `Task.requirement_brief` -> `Task.task_title`。

    Args:
        task_obj: 任务对象
        ordered_task_dev_log_list: 已按时间正序排列的任务日志列表

    Returns:
        CompletionCommitInformationResolution: 已解析的 commit information 结果
    """
    latest_self_review_summary_str = _extract_latest_passed_self_review_summary(
        ordered_task_dev_log_list
    )
    if latest_self_review_summary_str:
        return CompletionCommitInformationResolution(
            commit_information_text=latest_self_review_summary_str,
            commit_information_source=_COMMIT_INFORMATION_SOURCE_AI_SUMMARY,
        )

    requirement_brief_text = (task_obj.requirement_brief or "").strip()
    if requirement_brief_text:
        return CompletionCommitInformationResolution(
            commit_information_text=requirement_brief_text,
            commit_information_source=_COMMIT_INFORMATION_SOURCE_REQUIREMENT_BRIEF,
        )

    return CompletionCommitInformationResolution(
        commit_information_text=task_obj.task_title,
        commit_information_source=_COMMIT_INFORMATION_SOURCE_TASK_TITLE,
    )


def _build_completion_commit_information_source_log_text(
    commit_information_source_str: str,
) -> str:
    """构造 Complete 阶段 commit information 来源留痕文本.

    Args:
        commit_information_source_str: commit information 来源标签

    Returns:
        str: 可写入 DevLog 的来源说明文本
    """
    if commit_information_source_str == _COMMIT_INFORMATION_SOURCE_AI_SUMMARY:
        return "📝 已解析 Complete 阶段的 commit information 来源：最近一轮通过的 AI summary。"
    if commit_information_source_str == _COMMIT_INFORMATION_SOURCE_REQUIREMENT_BRIEF:
        return (
            "📝 已解析 Complete 阶段的 commit information 来源：requirement summary fallback。"
            "\n当前没有可用的最近一轮通过 AI summary，系统将回退使用 `requirement_brief`。"
        )
    return (
        "📝 已解析 Complete 阶段的 commit information 来源：task title fallback。"
        "\n当前没有可用的最近一轮通过 AI summary，也没有 requirement summary，系统将回退使用 `task_title`。"
    )


def _create_completion_commit_information_source_log(
    db_session: Session,
    task_obj: Task,
    commit_information_resolution: CompletionCommitInformationResolution,
) -> str:
    """写入 Complete 阶段 commit information 来源留痕.

    Args:
        db_session: 数据库会话
        task_obj: 任务对象
        commit_information_resolution: 已解析的 commit information 结果

    Returns:
        str: 已写入的日志文本
    """
    commit_information_source_log_text = (
        _build_completion_commit_information_source_log_text(
            commit_information_resolution.commit_information_source
        )
    )
    LogService.create_log(
        db_session,
        DevLogCreateSchema(
            task_id=task_obj.id,
            text_content=commit_information_source_log_text,
            state_tag=DevLogStateTag.OPTIMIZATION,
        ),
        task_obj.run_account_id,
    )
    return commit_information_source_log_text


def _has_latest_post_review_lint_cycle_passed(task_dev_log_list: list[DevLog]) -> bool:
    """判断最近一轮 post-review lint 是否已经出现通过标记.

    Args:
        task_dev_log_list: 已按时间正序排列的任务日志列表

    Returns:
        bool: 若最近一轮 lint 已出现通过标记则返回 True，否则返回 False
    """
    for dev_log_item in reversed(task_dev_log_list):
        log_text = dev_log_item.text_content
        if any(
            marker_text in log_text
            for marker_text in _POST_REVIEW_LINT_PASSED_LOG_MARKER_LIST
        ):
            return True
        if any(
            marker_text in log_text
            for marker_text in _POST_REVIEW_LINT_STARTED_LOG_MARKER_LIST
        ):
            return False

    return False


def _create_manual_completion_override_log_if_needed(
    db_session: Session,
    task_obj: Task,
    source_workflow_stage: WorkflowStage | None,
    ordered_task_dev_log_list: list[DevLog],
) -> str | None:
    """在人工提前触发完成时写入留痕日志.

    只有当任务仍停留在 `self_review_in_progress`，且最近一轮 self-review
    尚未出现通过标记时，才视为一次需要显式记录的人工接管。

    Args:
        db_session: 数据库会话
        task_obj: 任务对象
        source_workflow_stage: 进入完成链路前的原始阶段
        ordered_task_dev_log_list: 已按时间正序排列的任务日志列表

    Returns:
        str | None: 若写入了人工接管日志则返回日志文本，否则返回 None
    """
    if source_workflow_stage != WorkflowStage.SELF_REVIEW_IN_PROGRESS:
        return None

    if _has_latest_self_review_cycle_passed(ordered_task_dev_log_list):
        return None

    manual_override_log_text = (
        "📝 已记录人工接管：用户在 AI 自检尚未形成“通过”结论时手动触发了 `Complete`。\n"
        "系统将直接从 `self_review_in_progress` 进入 Git 收尾阶段（pr_preparing）。"
    )
    LogService.create_log(
        db_session,
        DevLogCreateSchema(
            task_id=task_obj.id,
            text_content=manual_override_log_text,
            state_tag=DevLogStateTag.OPTIMIZATION,
        ),
        task_obj.run_account_id,
    )
    return manual_override_log_text


def _format_workflow_stage_label(workflow_stage: WorkflowStage) -> str:
    """格式化真实 workflow_stage 的默认展示文案.

    Args:
        workflow_stage: 真实工作流阶段

    Returns:
        str: 前端默认使用的阶段文案
    """
    return _WORKFLOW_STAGE_LABEL_MAP.get(
        workflow_stage,
        workflow_stage.value.replace("_", " "),
    )


def _resolve_project_display_name(
    db_session: Session,
    project_id: str | None,
) -> str:
    """Resolve a user-facing project label for task audit logs.

    Args:
        db_session: 数据库会话
        project_id: 关联项目 ID，可为空

    Returns:
        str: 适合写入日志的项目展示名称
    """
    if not project_id:
        return "未关联项目"

    from backend.dsl.models.project import Project

    project_obj = db_session.query(Project).filter(Project.id == project_id).first()
    if project_obj and project_obj.display_name.strip():
        return project_obj.display_name.strip()
    return f"未知项目（{project_id[:8]}...）"


def _build_task_project_rebind_log_text(
    *,
    previous_project_label_str: str,
    next_project_label_str: str,
) -> str:
    """Build the audit log for backlog project rebinding.

    Args:
        previous_project_label_str: 修改前项目名称
        next_project_label_str: 修改后项目名称

    Returns:
        str: 标准化日志正文
    """
    return "\n".join(
        [
            "## Project Binding Updated",
            "",
            f"- Previous project: {previous_project_label_str}",
            f"- Current project: {next_project_label_str}",
            (
                "- Note: project rebinding is only allowed while the task "
                "stays in backlog and has no worktree yet."
            ),
        ]
    )


def _build_task_destroy_log_text(
    *,
    task_title_str: str,
    destroyed_stage_label_str: str,
    project_label_str: str,
    destroy_reason_str: str,
    requirement_summary_str: str,
    worktree_path_snapshot_str: str | None,
    cleanup_summary_str: str,
) -> str:
    """Build the audit log for started-task destroy.

    Args:
        task_title_str: 任务标题
        destroyed_stage_label_str: 销毁前阶段文案
        project_label_str: 当前项目展示名称
        destroy_reason_str: 销毁原因
        requirement_summary_str: 销毁前持久化需求摘要
        worktree_path_snapshot_str: 销毁前 worktree 路径快照
        cleanup_summary_str: 清理结果摘要

    Returns:
        str: 标准化日志正文
    """
    audit_line_list = [
        "## Requirement Destroyed",
        "",
        f"- Task title: {task_title_str}",
        f"- Stage before destroy: {destroyed_stage_label_str}",
        f"- Linked project: {project_label_str}",
        f"- Destroy reason: {destroy_reason_str}",
        f"- Cleanup: {cleanup_summary_str}",
        "",
        "Final Summary:",
        requirement_summary_str,
    ]
    if worktree_path_snapshot_str:
        audit_line_list.append(f"- Worktree snapshot: `{worktree_path_snapshot_str}`")
    return "\n".join(audit_line_list)


def _build_destroy_cleanup_failure_reason(
    *,
    worktree_removed: bool,
    branch_deleted: bool,
) -> str:
    """Build a stable destroy-cleanup failure message.

    Args:
        worktree_removed: worktree 目录是否已被移除
        branch_deleted: 任务分支是否已被删除

    Returns:
        str: 标准化清理失败文案
    """
    cleanup_gap_list: list[str] = []
    if not worktree_removed:
        cleanup_gap_list.append("task worktree directory still exists")
    if not branch_deleted:
        cleanup_gap_list.append("task branch still exists locally")
    return "Destroy cleanup did not finish completely: " + "; ".join(cleanup_gap_list)


def _build_business_sync_status_note(task_obj: Task) -> str | None:
    """Build a UI-facing note for tasks restored from business sync snapshots.

    Args:
        task_obj: 任务对象

    Returns:
        str | None: 面向 UI 的说明文案；若任务并非业务同步恢复则返回 None
    """
    if not task_obj.business_sync_restored_at:
        return None

    original_stage_value_str = task_obj.business_sync_original_workflow_stage
    if original_stage_value_str:
        try:
            original_workflow_stage = WorkflowStage(original_stage_value_str)
            original_stage_label_str = _format_workflow_stage_label(
                original_workflow_stage
            )
        except ValueError:
            original_stage_label_str = original_stage_value_str.replace("_", " ")
    else:
        original_stage_label_str = "Unknown"

    if task_obj.workflow_stage.value != original_stage_value_str:
        return (
            f"Synced progress was {original_stage_label_str}. Koda reopened this task "
            f"as {_format_workflow_stage_label(task_obj.workflow_stage)} on this machine "
            "because repo/worktree execution state is machine-local."
        )

    return (
        f"Restored from a WebDAV business snapshot. Current progress reflects the "
        f"synced card state ({original_stage_label_str}), but local repo/worktree "
        "state still needs to be rebuilt on this machine."
    )


def _build_task_card_metadata(
    task_obj: Task,
    task_branch_health: TaskBranchHealthSchema | None,
    *,
    ordered_task_dev_log_list: list[DevLog] | None = None,
    latest_requirement_change_snapshot: RequirementChangeSnapshot | None = None,
    is_task_running: bool,
    latest_self_review_passed: bool = False,
    latest_post_review_lint_passed: bool = False,
) -> TaskCardMetadataSchema:
    """构建单个任务的卡片展示元数据.

    Args:
        task_obj: 任务对象
        is_task_running: 当前后台自动化是否仍在运行

    Returns:
        TaskCardMetadataSchema: 供左侧卡片和详情头部共用的展示元数据
    """
    resolved_latest_requirement_change_snapshot = latest_requirement_change_snapshot
    if resolved_latest_requirement_change_snapshot is None:
        resolved_ordered_task_dev_log_list = (
            ordered_task_dev_log_list
            if ordered_task_dev_log_list is not None
            else _get_ordered_task_dev_logs(task_obj)
        )
        resolved_latest_requirement_change_snapshot = (
            _get_latest_requirement_change_snapshot(resolved_ordered_task_dev_log_list)
        )
    if task_branch_health and task_branch_health.manual_completion_candidate:
        return TaskCardMetadataSchema(
            task_id=task_obj.id,
            display_stage_key=_BRANCH_MISSING_DISPLAY_STAGE_KEY,
            display_stage_label=_BRANCH_MISSING_DISPLAY_STAGE_LABEL,
            is_waiting_for_user=False,
            last_ai_activity_at=task_obj.last_ai_activity_at,
            requirement_change_kind=(
                resolved_latest_requirement_change_snapshot.change_kind
                if resolved_latest_requirement_change_snapshot is not None
                else None
            ),
            requirement_summary=(
                resolved_latest_requirement_change_snapshot.summary_text
                if resolved_latest_requirement_change_snapshot is not None
                else None
            ),
            business_sync_restored_at=task_obj.business_sync_restored_at,
            business_sync_status_note=_build_business_sync_status_note(task_obj),
            branch_health=task_branch_health,
        )
    waiting_for_user_after_self_review = (
        task_obj.workflow_stage == WorkflowStage.SELF_REVIEW_IN_PROGRESS
        and not is_task_running
        and latest_self_review_passed
    )
    waiting_for_user_after_post_review_lint = (
        task_obj.workflow_stage == WorkflowStage.TEST_IN_PROGRESS
        and not is_task_running
        and latest_post_review_lint_passed
    )
    is_waiting_for_user = (
        waiting_for_user_after_self_review or waiting_for_user_after_post_review_lint
    )
    display_stage_key = (
        _WAITING_USER_DISPLAY_STAGE_KEY
        if is_waiting_for_user
        else task_obj.workflow_stage.value
    )
    display_stage_label = (
        _WAITING_USER_DISPLAY_STAGE_LABEL
        if is_waiting_for_user
        else _format_workflow_stage_label(task_obj.workflow_stage)
    )
    return TaskCardMetadataSchema(
        task_id=task_obj.id,
        display_stage_key=display_stage_key,
        display_stage_label=display_stage_label,
        is_waiting_for_user=is_waiting_for_user,
        last_ai_activity_at=task_obj.last_ai_activity_at,
        requirement_change_kind=(
            resolved_latest_requirement_change_snapshot.change_kind
            if resolved_latest_requirement_change_snapshot is not None
            else None
        ),
        requirement_summary=(
            resolved_latest_requirement_change_snapshot.summary_text
            if resolved_latest_requirement_change_snapshot is not None
            else None
        ),
        business_sync_restored_at=task_obj.business_sync_restored_at,
        business_sync_status_note=_build_business_sync_status_note(task_obj),
        branch_health=task_branch_health,
    )


def _hydrate_task_response(
    task_obj: Task,
    *,
    db_session: Session | None = None,
    branch_health_override: TaskBranchHealthSchema | None = None,
    is_task_running_override: bool | None = None,
    log_count_override: int | None = None,
) -> Task:
    """补齐任务响应中的计算字段.

    Args:
        task_obj: 任务对象
        db_session: 可选数据库会话；传入时会在缺少 override 的情况下计算分支健康状态
        branch_health_override: 可选的分支健康覆盖值
        is_task_running_override: 可选的运行态覆盖值
        log_count_override: 可选的日志数量覆盖值

    Returns:
        Task: 填充了 `log_count`、`is_codex_task_running` 与 `branch_health` 的任务对象
    """
    resolved_branch_health = branch_health_override
    if resolved_branch_health is None and db_session is not None:
        resolved_branch_health = TaskService.build_task_branch_health(task_obj)

    task_obj.branch_health = resolved_branch_health
    resolved_log_count = log_count_override
    if resolved_log_count is None:
        existing_log_count = getattr(task_obj, "log_count", None)
        resolved_log_count = (
            int(existing_log_count)
            if existing_log_count is not None
            else len(task_obj.dev_logs)
        )

    task_obj.log_count = resolved_log_count
    task_obj.is_codex_task_running = (
        is_codex_task_running(task_obj.id)
        if is_task_running_override is None
        else is_task_running_override
    )
    task_obj.business_sync_status_note = _build_business_sync_status_note(task_obj)
    return task_obj


def _build_manual_branch_missing_completion_log_text(
    task_branch_health: TaskBranchHealthSchema,
) -> str:
    """Build the audit log text for a missing-branch manual completion.

    Args:
        task_branch_health: 当前任务的分支健康快照

    Returns:
        str: 人工完成审计日志文本
    """
    expected_branch_name_str = task_branch_health.expected_branch_name
    worktree_status_hint_str = (
        "当前 worktree 目录仍保留，可继续作为人工核对入口。"
        if task_branch_health.worktree_exists
        else "当前 worktree 目录已不存在。"
    )
    return (
        "✅ 已记录人工确认完成：系统检测到任务分支 "
        f"`{expected_branch_name_str}` 缺失，用户在查看时间线/代码后确认该需求已人工完成。\n"
        "系统将直接把任务收敛到 `done / CLOSED`，不会重复执行普通 Git 收尾链路。\n"
        f"{worktree_status_hint_str}"
    )


def _validate_task_project_filter(
    project_id: str | None,
    unlinked_only: bool,
) -> tuple[str | None, bool]:
    """规范化任务列表的项目筛选参数.

    Args:
        project_id: 请求中的项目 ID 过滤值
        unlinked_only: 是否只返回未关联项目任务

    Returns:
        tuple[str | None, bool]: 规范化后的 `(project_id, unlinked_only)`

    Raises:
        HTTPException: 当 `project_id` 与 `unlinked_only=true` 同时出现时抛出
    """
    normalized_project_id = project_id.strip() if project_id else None
    normalized_project_id = normalized_project_id or None
    if normalized_project_id and unlinked_only:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="project_id and unlinked_only cannot be used together.",
        )
    return normalized_project_id, unlinked_only


@router.get("", response_model=list[TaskResponseSchema])
def list_tasks(
    db_session: Annotated[Session, Depends(get_db)],
    project_id: Annotated[
        str | None,
        Query(
            description="Only return tasks bound to the specified project ID.",
        ),
    ] = None,
    unlinked_only: Annotated[
        bool,
        Query(
            description="When true, only return tasks without a bound project.",
        ),
    ] = False,
) -> list[Task]:
    """列出当前账户的任务.

    Args:
        project_id: 关联项目 ID 过滤（可选）
        unlinked_only: 是否只返回未关联项目任务
        db_session: 数据库会话

    Returns:
        list[Task]: 任务列表，按创建时间倒序排列
    """
    run_account_id = _get_current_run_account_id(db_session)
    normalized_project_id, normalized_unlinked_only = _validate_task_project_filter(
        project_id,
        unlinked_only,
    )
    task_list = TaskService.get_tasks(
        db_session,
        run_account_id,
        project_id=normalized_project_id,
        unlinked_only=normalized_unlinked_only,
    )
    task_log_count_map = TaskService.get_task_log_count_map(
        db_session,
        [task_item.id for task_item in task_list],
    )
    task_branch_health_map = TaskService.build_task_branch_health_map(
        db_session,
        task_list,
    )
    return [
        _hydrate_task_response(
            task_item,
            branch_health_override=task_branch_health_map.get(task_item.id),
            log_count_override=task_log_count_map.get(task_item.id, 0),
        )
        for task_item in task_list
    ]


@router.get("/card-metadata", response_model=list[TaskCardMetadataSchema])
def list_task_card_metadata(
    db_session: Annotated[Session, Depends(get_db)],
    project_id: Annotated[
        str | None,
        Query(
            description="Only return task card metadata for the specified project ID.",
        ),
    ] = None,
    unlinked_only: Annotated[
        bool,
        Query(
            description="When true, only return metadata for tasks without a bound project.",
        ),
    ] = False,
) -> list[TaskCardMetadataSchema]:
    """列出任务卡片展示元数据.

    该接口只返回 UI 展示层需要的派生信息，其中 `waiting_user`
    仅表示“等待用户点击 Complete”的覆盖态，不代表新增了真实
    `workflow_stage`。

    Args:
        project_id: 关联项目 ID 过滤（可选）
        unlinked_only: 是否只返回未关联项目任务
        db_session: 数据库会话

    Returns:
        list[TaskCardMetadataSchema]: 当前账户下全部任务的卡片展示元数据
    """
    run_account_id = _get_current_run_account_id(db_session)
    normalized_project_id, normalized_unlinked_only = _validate_task_project_filter(
        project_id,
        unlinked_only,
    )
    task_list = TaskService.get_tasks(
        db_session,
        run_account_id,
        project_id=normalized_project_id,
        unlinked_only=normalized_unlinked_only,
    )
    task_id_list = [task_item.id for task_item in task_list]
    waiting_user_candidate_task_id_list = [
        task_item.id
        for task_item in task_list
        if task_item.lifecycle_status
        not in {
            TaskLifecycleStatus.CLOSED,
            TaskLifecycleStatus.DELETED,
        }
        and task_item.workflow_stage
        in {
            WorkflowStage.SELF_REVIEW_IN_PROGRESS,
            WorkflowStage.TEST_IN_PROGRESS,
        }
    ]
    latest_requirement_change_snapshot_map_by_task_id = (
        _get_latest_requirement_change_snapshot_map_by_task_id(
            db_session,
            task_id_list,
        )
    )
    latest_waiting_user_signal_map_by_task_id = (
        _get_latest_waiting_user_signal_map_by_task_id(
            db_session,
            waiting_user_candidate_task_id_list,
        )
    )
    task_branch_health_map = TaskService.build_task_branch_health_map(
        db_session,
        task_list,
    )

    task_card_metadata_list: list[TaskCardMetadataSchema] = []
    for task_item in task_list:
        waiting_user_signal_map = latest_waiting_user_signal_map_by_task_id.get(
            task_item.id,
            {
                "self_review_passed": None,
                "post_review_lint_passed": None,
            },
        )
        task_card_metadata_list.append(
            _build_task_card_metadata(
                task_item,
                task_branch_health_map.get(task_item.id),
                latest_requirement_change_snapshot=(
                    latest_requirement_change_snapshot_map_by_task_id.get(task_item.id)
                ),
                is_task_running=is_codex_task_running(task_item.id),
                latest_self_review_passed=bool(
                    waiting_user_signal_map["self_review_passed"]
                ),
                latest_post_review_lint_passed=bool(
                    waiting_user_signal_map["post_review_lint_passed"]
                ),
            )
        )

    return task_card_metadata_list


@router.post("", response_model=TaskResponseSchema, status_code=status.HTTP_201_CREATED)
def create_task(
    task_create_schema: TaskCreateSchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """创建新任务.

    新任务默认 lifecycle_status=PENDING，workflow_stage=backlog.

    Args:
        task_create_schema: 任务创建数据
        db_session: 数据库会话

    Returns:
        Task: 新创建的任务

    Raises:
        HTTPException: 当关联的 Project 不存在时返回 422
    """
    run_account_id = _get_current_run_account_id(db_session)
    try:
        new_task = TaskService.create_task(
            db_session, task_create_schema, run_account_id
        )
    except ValueError as validation_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(validation_error),
        ) from validation_error
    return _hydrate_task_response(new_task, db_session=db_session)


@router.put("/{task_id}/status", response_model=TaskResponseSchema)
def update_task_status(
    task_id: str,
    status_update: TaskStatusUpdateSchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """更新任务生命周期状态.

    Args:
        task_id: 任务 ID
        status_update: 状态更新数据
        db_session: 数据库会话

    Returns:
        Task: 更新后的任务

    Raises:
        HTTPException: 当任务不存在时返回 404；状态变更不合法时返回 422
    """
    existing_task_obj = TaskService.get_task_by_id(db_session, task_id)
    if not existing_task_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    previous_lifecycle_status = existing_task_obj.lifecycle_status
    try:
        updated_task = TaskService.update_task_status(
            db_session, task_id, status_update
        )
    except ValueError as validation_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(validation_error),
        ) from validation_error
    if not updated_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )
    if (
        status_update.lifecycle_status == TaskLifecycleStatus.CLOSED
        and previous_lifecycle_status != TaskLifecycleStatus.CLOSED
    ):
        _create_internal_archive_audit_log(
            db_session,
            updated_task,
            log_text_content="Requirement completed and moved into the completed archive.",
            log_state_tag=DevLogStateTag.FIXED,
        )
    elif (
        status_update.lifecycle_status == TaskLifecycleStatus.DELETED
        and previous_lifecycle_status != TaskLifecycleStatus.DELETED
    ):
        _create_internal_archive_audit_log(
            db_session,
            updated_task,
            log_text_content=_build_requirement_delete_audit_log(updated_task),
            log_state_tag=DevLogStateTag.NONE,
        )
    return _hydrate_task_response(updated_task, db_session=db_session)


@router.put("/{task_id}/stage", response_model=TaskResponseSchema)
def update_task_stage(
    task_id: str,
    stage_update: TaskStageUpdateSchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """更新任务工作流阶段.

    通用阶段更新接口，供各阶段按钮（如「确认 PRD」、「验收通过」等）使用.
    当阶段更新为 done 时，自动将 lifecycle_status 设为 CLOSED.

    Args:
        task_id: 任务 ID
        stage_update: 阶段更新数据
        db_session: 数据库会话

    Returns:
        Task: 更新后的任务

    Raises:
        HTTPException: 当任务不存在时返回 404
    """
    existing_task_obj = TaskService.get_task_by_id(db_session, task_id)
    if not existing_task_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    previous_workflow_stage = existing_task_obj.workflow_stage
    updated_task = TaskService.update_workflow_stage(db_session, task_id, stage_update)
    if not updated_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )
    if (
        stage_update.workflow_stage == WorkflowStage.DONE
        and previous_workflow_stage != WorkflowStage.DONE
    ):
        _create_internal_archive_audit_log(
            db_session,
            updated_task,
            log_text_content="需求验收通过，已标记为完成。",
            log_state_tag=DevLogStateTag.FIXED,
        )
    return _hydrate_task_response(updated_task, db_session=db_session)


@router.post("/{task_id}/start", response_model=TaskResponseSchema)
def start_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """启动任务：创建 git worktree 并进入 PRD_GENERATING 阶段.

    仅允许从 backlog 阶段触发。若任务关联了 Project，将立即在项目仓库中创建
    git worktree（默认分支名：`task/<task_id[:8]>-<semantic-slug>`；
    AI 命名不可用时自动回退）。

    Args:
        task_id: 任务 ID
        db_session: 数据库会话

    Returns:
        Task: 已更新为 prd_generating 的任务对象

    Raises:
        HTTPException: 任务不存在（404）、阶段不合法（422）或 worktree 创建失败（422）
    """
    if is_codex_task_running(task_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task automation is already running for this task.",
        )

    try:
        started_task = TaskService.start_task(db_session, task_id)
    except ValueError as start_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(start_error),
        ) from start_error

    if not started_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    return _schedule_prd_generation(
        task_obj=started_task,
        background_tasks=background_tasks,
        db_session=db_session,
    )


@router.post("/{task_id}/regenerate-prd", response_model=TaskResponseSchema)
def regenerate_task_prd(
    task_id: str,
    background_tasks: BackgroundTasks,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """重新生成指定任务的 PRD.

    该接口用于用户在查看 PRD 后修改需求、补充反馈、上传图片/附件后，
    把任务重新推进回 `prd_generating`，并在后台重新调用 Codex 生成 PRD。

    Args:
        task_id: 任务 ID
        background_tasks: FastAPI 后台任务容器
        db_session: 数据库会话

    Returns:
        Task: 已切换回 `prd_generating` 且后台任务已启动的任务对象

    Raises:
        HTTPException: 当任务不存在、阶段非法，或当前已有自动化运行时返回错误
    """
    if is_codex_task_running(task_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task automation is already running for this task.",
        )

    try:
        regenerated_task = TaskService.request_prd_regeneration(db_session, task_id)
    except ValueError as regeneration_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(regeneration_error),
        ) from regeneration_error

    if not regenerated_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    LogService.create_log(
        db_session,
        DevLogCreateSchema(
            task_id=task_id,
            text_content=(
                "🔄 已收到 PRD 重新生成请求。"
                "系统会基于当前需求内容、最新反馈以及已上传的图片/附件生成新的 PRD 草案。"
            ),
            state_tag=DevLogStateTag.OPTIMIZATION,
        ),
        regenerated_task.run_account_id,
    )

    refreshed_task = TaskService.get_task_by_id(db_session, task_id)
    if refreshed_task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    return _schedule_prd_generation(
        task_obj=refreshed_task,
        background_tasks=background_tasks,
        db_session=db_session,
    )


@router.post("/{task_id}/execute", response_model=TaskResponseSchema)
def execute_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """触发任务进入执行阶段并启动 codex exec 后台任务.

    原子操作：
    1. 将 workflow_stage 更新为 implementation_in_progress
    2. 在后台异步启动 codex exec，输出实时写入 DevLog 时间线
    3. 实现完成后自动推进至 self_review_in_progress，并立即执行 AI 自检 / 代码评审
    4. 若自检发现阻塞问题，优先进入自动回改并重新评审；仅在闭环失败或执行失败时回退至 changes_requested
    5. 若自检通过，任务自动推进到 test_in_progress，并执行 `uv run pre-commit run --all-files`
    6. 若 lint 在自动重跑后仍失败，系统会继续进入有上限的 AI lint 定向修复闭环；仅在 lint 闭环失败时回退至 changes_requested

    仅允许从 prd_waiting_confirmation 或 changes_requested 阶段触发.

    Args:
        task_id: 任务 ID
        background_tasks: FastAPI 后台任务注入
        db_session: 数据库会话

    Returns:
        Task: 已更新为 implementation_in_progress 的任务对象

    Raises:
        HTTPException: 当任务不存在时返回 404；阶段不合法时返回 422
    """
    try:
        executed_task = TaskService.execute_task(db_session, task_id)
    except ValueError as stage_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(stage_error),
        ) from stage_error

    if not executed_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    ordered_task_dev_log_list = _get_ordered_task_dev_logs(executed_task)
    dev_log_text_snapshot_list = _build_task_context_snapshot_list(
        ordered_task_dev_log_list
    )
    effective_work_dir_path = _resolve_task_effective_work_dir_path(
        db_session,
        executed_task,
    )

    # 在后台异步运行实现阶段；成功后会继续进入真实的 self-review 阶段
    register_task_background_activity(task_id)
    background_tasks.add_task(
        run_codex_task,
        task_id_str=task_id,
        run_account_id_str=executed_task.run_account_id,
        task_title_str=executed_task.task_title,
        dev_log_text_list=dev_log_text_snapshot_list,
        work_dir_path=effective_work_dir_path,
        worktree_path_str=executed_task.worktree_path,
    )

    return _hydrate_task_response(
        executed_task,
        db_session=db_session,
        is_task_running_override=True,
    )


@router.post("/{task_id}/review", response_model=TaskResponseSchema)
def review_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """触发一次独立的 review-only 代码评审.

    该入口不会修改 `workflow_stage`，也不会在评审通过后自动继续 lint / Complete。
    它只会把评审 transcript 与结论写回 `DevLog`，适合手动 run-now 或定时调度。

    Args:
        task_id: 任务 ID
        background_tasks: FastAPI 后台任务注入
        db_session: 数据库会话

    Returns:
        Task: 当前任务对象，带运行态字段

    Raises:
        HTTPException: 当任务不存在、生命周期不允许评审、缺少可用 review 目录，
            或当前已有自动化运行时返回错误
    """
    if is_codex_task_running(task_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task automation is already running for this task.",
        )

    try:
        reviewable_task = TaskService.prepare_task_review(db_session, task_id)
    except ValueError as review_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(review_error),
        ) from review_error

    if not reviewable_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    ordered_task_dev_log_list = _get_ordered_task_dev_logs(reviewable_task)
    dev_log_text_snapshot_list = _build_task_context_snapshot_list(
        ordered_task_dev_log_list
    )
    review_work_dir_path = _resolve_task_review_work_dir_path(
        db_session,
        reviewable_task,
    )

    register_task_background_activity(task_id)
    background_tasks.add_task(
        run_codex_review_only,
        task_id_str=task_id,
        run_account_id_str=reviewable_task.run_account_id,
        task_title_str=reviewable_task.task_title,
        dev_log_text_list=dev_log_text_snapshot_list,
        work_dir_path=review_work_dir_path,
        worktree_path_str=reviewable_task.worktree_path,
    )

    return _hydrate_task_response(
        reviewable_task,
        db_session=db_session,
        is_task_running_override=True,
    )


@router.post("/{task_id}/resume", response_model=TaskResponseSchema)
def resume_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """Resume interrupted automation from the task's persisted workflow stage.

    支持从以下阶段恢复：
    - `prd_generating`
    - `implementation_in_progress`
    - `self_review_in_progress`
    - `test_in_progress`
    - `pr_preparing`

    其中 `self_review_in_progress` 与 `test_in_progress` 只有在最近一轮
    self-review / lint 尚未停在“等待用户点击 Complete”时才允许恢复。

    Args:
        task_id: 任务 ID
        background_tasks: FastAPI 后台任务注入
        db_session: 数据库会话

    Returns:
        Task: 标记为后台恢复执行中的任务对象

    Raises:
        HTTPException: 当任务不存在时返回 404；仍在运行时返回 409；阶段不允许恢复时返回 422
    """
    if is_codex_task_running(task_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task automation is already running for this task.",
        )

    try:
        resumable_task = TaskService.prepare_task_resume(db_session, task_id)
    except ValueError as resume_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(resume_error),
        ) from resume_error

    if not resumable_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    ordered_task_dev_log_list = _get_ordered_task_dev_logs(resumable_task)
    if (
        resumable_task.workflow_stage == WorkflowStage.SELF_REVIEW_IN_PROGRESS
        and _has_latest_self_review_cycle_passed(ordered_task_dev_log_list)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Self-review already passed. Use Complete instead of Resume.",
        )
    if (
        resumable_task.workflow_stage == WorkflowStage.TEST_IN_PROGRESS
        and _has_latest_post_review_lint_cycle_passed(ordered_task_dev_log_list)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Post-review lint already passed. Use Complete instead of Resume.",
        )

    dev_log_text_snapshot_list = _build_task_context_snapshot_list(
        ordered_task_dev_log_list
    )
    effective_work_dir_path = _resolve_task_effective_work_dir_path(
        db_session,
        resumable_task,
    )

    if resumable_task.workflow_stage == WorkflowStage.PRD_GENERATING:
        register_task_background_activity(task_id)
        background_tasks.add_task(
            run_codex_prd,
            task_id_str=task_id,
            run_account_id_str=resumable_task.run_account_id,
            task_title_str=resumable_task.task_title,
            dev_log_text_list=dev_log_text_snapshot_list,
            work_dir_path=effective_work_dir_path,
            worktree_path_str=resumable_task.worktree_path,
            auto_confirm_prd_and_execute_bool=(
                resumable_task.auto_confirm_prd_and_execute
            ),
        )
    elif resumable_task.workflow_stage == WorkflowStage.IMPLEMENTATION_IN_PROGRESS:
        register_task_background_activity(task_id)
        background_tasks.add_task(
            run_codex_task,
            task_id_str=task_id,
            run_account_id_str=resumable_task.run_account_id,
            task_title_str=resumable_task.task_title,
            dev_log_text_list=dev_log_text_snapshot_list,
            work_dir_path=effective_work_dir_path,
            worktree_path_str=resumable_task.worktree_path,
        )
    elif resumable_task.workflow_stage == WorkflowStage.SELF_REVIEW_IN_PROGRESS:
        register_task_background_activity(task_id)
        background_tasks.add_task(
            run_codex_review_resume,
            task_id_str=task_id,
            run_account_id_str=resumable_task.run_account_id,
            task_title_str=resumable_task.task_title,
            dev_log_text_list=dev_log_text_snapshot_list,
            work_dir_path=effective_work_dir_path,
            worktree_path_str=resumable_task.worktree_path,
        )
    elif resumable_task.workflow_stage == WorkflowStage.TEST_IN_PROGRESS:
        register_task_background_activity(task_id)
        background_tasks.add_task(
            run_post_review_lint_resume,
            task_id_str=task_id,
            run_account_id_str=resumable_task.run_account_id,
            task_title_str=resumable_task.task_title,
            dev_log_text_list=dev_log_text_snapshot_list,
            work_dir_path=effective_work_dir_path,
            worktree_path_str=resumable_task.worktree_path,
        )
    else:
        if not resumable_task.worktree_path:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Task has no worktree_path. Completion resume requires a worktree.",
            )
        worktree_dir_path = Path(resumable_task.worktree_path)
        if not worktree_dir_path.exists():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Worktree directory does not exist yet: {worktree_dir_path}",
            )
        commit_information_resolution = _resolve_completion_commit_information(
            task_obj=resumable_task,
            ordered_task_dev_log_list=ordered_task_dev_log_list,
        )

        register_task_background_activity(task_id)
        background_tasks.add_task(
            run_codex_completion,
            task_id_str=task_id,
            run_account_id_str=resumable_task.run_account_id,
            task_title_str=resumable_task.task_title,
            commit_information_text_str=(
                commit_information_resolution.commit_information_text
            ),
            commit_information_source_str=(
                commit_information_resolution.commit_information_source
            ),
            dev_log_text_list=dev_log_text_snapshot_list,
            work_dir_path=worktree_dir_path,
            worktree_path_str=resumable_task.worktree_path,
        )

    return _hydrate_task_response(
        resumable_task,
        db_session=db_session,
        is_task_running_override=True,
    )


@router.post("/{task_id}/complete", response_model=TaskResponseSchema)
def complete_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """触发任务进入完成收尾阶段，并执行确定性的 Git 收尾与合并动作.

    顺序固定为：
    1. 在任务 worktree 中执行 `git add .`
    2. 在任务 worktree 中执行 `git commit -m "<resolved commit information>"`
    3. 在任务 worktree 中执行 `git rebase main`
    4. 若 rebase 冲突，自动调用 Codex 修复冲突并继续 rebase
    5. 在当前持有 `main` 分支的工作区执行 `git merge <task branch>`
    6. 清理 task worktree 与本地任务分支

    若任务仍处于 `self_review_in_progress` 且尚未出现最近一轮通过标记，
    接口仍允许人工显式触发 `Complete`，并会先写入一条 DevLog 留痕。
    若在合并到 `main` 前失败，任务回退到 `changes_requested`。
    若已成功合并到 `main` 但清理失败，任务仍会进入 `done`，同时记录人工清理提示。

    Args:
        task_id: 任务 ID
        background_tasks: FastAPI 后台任务注入
        db_session: 数据库会话

    Returns:
        Task: 已更新为 `pr_preparing` 的任务对象

    Raises:
        HTTPException: 当任务不存在时返回 404；阶段不合法、worktree 缺失、任务已转入
            缺失分支人工确认路径或目录不存在时返回 422；若当前任务已存在运行中的
            后台执行则返回 409
    """
    if is_codex_task_running(task_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task automation is already running for this task.",
        )

    source_task = TaskService.get_task_by_id(db_session, task_id)
    source_workflow_stage = source_task.workflow_stage if source_task else None

    try:
        completion_task = TaskService.prepare_task_completion(db_session, task_id)
    except ValueError as completion_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(completion_error),
        ) from completion_error

    if not completion_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    if not completion_task.worktree_path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Task has no worktree_path. Complete is only available for worktree-backed tasks.",
        )

    from pathlib import Path as _Path

    worktree_dir_path = _Path(completion_task.worktree_path)
    if not worktree_dir_path.exists():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Worktree directory does not exist yet: {worktree_dir_path}",
        )

    ordered_task_dev_log_list = _get_ordered_task_dev_logs(completion_task)
    manual_override_log_text = _create_manual_completion_override_log_if_needed(
        db_session=db_session,
        task_obj=completion_task,
        source_workflow_stage=source_workflow_stage,
        ordered_task_dev_log_list=ordered_task_dev_log_list,
    )
    commit_information_resolution = _resolve_completion_commit_information(
        task_obj=completion_task,
        ordered_task_dev_log_list=ordered_task_dev_log_list,
    )
    commit_information_source_log_text = (
        _create_completion_commit_information_source_log(
            db_session=db_session,
            task_obj=completion_task,
            commit_information_resolution=commit_information_resolution,
        )
    )
    dev_log_text_snapshot_list: list[str] = [
        dev_log_item.text_content for dev_log_item in ordered_task_dev_log_list
    ]
    if manual_override_log_text:
        dev_log_text_snapshot_list.append(manual_override_log_text)
    dev_log_text_snapshot_list.append(commit_information_source_log_text)
    task_title_snapshot_str: str = completion_task.task_title
    commit_information_snapshot_str: str = (
        commit_information_resolution.commit_information_text
    )
    commit_information_source_snapshot_str: str = (
        commit_information_resolution.commit_information_source
    )
    run_account_id_snapshot_str: str = completion_task.run_account_id
    worktree_path_snapshot_str: str = completion_task.worktree_path

    register_task_background_activity(task_id)
    background_tasks.add_task(
        run_codex_completion,
        task_id_str=task_id,
        run_account_id_str=run_account_id_snapshot_str,
        task_title_str=task_title_snapshot_str,
        commit_information_text_str=commit_information_snapshot_str,
        commit_information_source_str=commit_information_source_snapshot_str,
        dev_log_text_list=dev_log_text_snapshot_list,
        work_dir_path=worktree_dir_path,
        worktree_path_str=worktree_path_snapshot_str,
    )

    completion_task.log_count = (
        len(ordered_task_dev_log_list) + (1 if manual_override_log_text else 0) + 1
    )
    completion_task.is_codex_task_running = True
    completion_task.branch_health = TaskService.build_task_branch_health(
        completion_task
    )
    return completion_task


@router.post("/{task_id}/manual-complete", response_model=TaskResponseSchema)
def manual_complete_task(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """Manually close a task after a missing-branch confirmation.

    This endpoint is reserved for the case where the resolved task branch has
    already been merged and deleted outside Koda, so rerunning the standard Git
    completion flow would no longer make sense.

    Args:
        task_id: 任务 ID
        db_session: 数据库会话

    Returns:
        Task: 已收敛到 `done / CLOSED` 的任务对象

    Raises:
        HTTPException: 当任务不存在时返回 404；当后台自动化仍在运行时返回 409；
            当任务不满足人工完成条件时返回 422
    """
    if is_codex_task_running(task_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task automation is already running for this task.",
        )

    task_obj = TaskService.get_task_by_id(db_session, task_id)
    if task_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    task_branch_health = TaskService.build_task_branch_health(task_obj)
    try:
        TaskService.validate_manual_completion_candidate(
            task_obj,
            task_branch_health,
        )
    except ValueError as manual_completion_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(manual_completion_error),
        ) from manual_completion_error

    db_session.add(
        DevLog(
            task_id=task_obj.id,
            run_account_id=task_obj.run_account_id,
            text_content=_build_manual_branch_missing_completion_log_text(
                task_branch_health
            ),
            state_tag=DevLogStateTag.FIXED,
        )
    )

    manually_completed_task = TaskService.close_task_after_manual_completion(
        db_session,
        task_obj,
    )
    return _hydrate_task_response(manually_completed_task, db_session=db_session)


@router.post("/{task_id}/cancel", response_model=TaskResponseSchema)
def cancel_task(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """中断正在运行的 codex 进程并将任务回退至 changes_requested 阶段.

    若该任务没有正在运行的 codex 进程，仍会将 workflow_stage 强制回退至
    changes_requested，确保 UI 可以解除阻塞。

    Args:
        task_id: 任务 ID
        db_session: 数据库会话

    Returns:
        Task: 已回退为 changes_requested 的任务对象

    Raises:
        HTTPException: 当任务不存在时返回 404
    """
    from backend.dsl.schemas.task_schema import TaskStageUpdateSchema
    from backend.dsl.models.enums import WorkflowStage

    task_obj = TaskService.get_task_by_id(db_session, task_id)
    if not task_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )
    previous_workflow_stage_value_str = task_obj.workflow_stage.value
    task_title_str = task_obj.task_title

    # 尝试终止正在运行的 codex 进程
    cancel_codex_task(task_id)
    clear_task_background_activity(task_id)

    # 强制将阶段回退至 changes_requested，解除 UI 阻塞
    stage_update_schema = TaskStageUpdateSchema(
        workflow_stage=WorkflowStage.CHANGES_REQUESTED
    )
    updated_task = TaskService.update_workflow_stage(
        db_session, task_id, stage_update_schema
    )
    if not updated_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    try:
        from backend.dsl.services.email_service import send_manual_interruption_notification

        send_manual_interruption_notification(
            task_id_str=task_id,
            task_title_str=task_title_str,
            interrupted_stage_value_str=previous_workflow_stage_value_str,
        )
    except Exception as email_error:
        logger.warning(
            "Failed to send manual interruption email for task %s...: %s",
            task_id[:8],
            email_error,
        )
    return _hydrate_task_response(
        updated_task,
        db_session=db_session,
        is_task_running_override=False,
    )


@router.post("/{task_id}/destroy", response_model=TaskResponseSchema)
def destroy_task(
    task_id: str,
    destroy_payload: TaskDestroySchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """销毁已启动任务，并记录原因与清理结果.

    销毁只适用于已经启动过的任务：系统会先停止后台自动化，再尝试清理
    worktree / 分支，最后把任务归档到 deleted history。

    Args:
        task_id: 任务 ID
        destroy_payload: 销毁原因请求体
        db_session: 数据库会话

    Returns:
        Task: 已写入销毁元数据的任务对象

    Raises:
        HTTPException: 当任务不存在、尚未启动或清理失败时抛出
    """
    task_obj = TaskService.get_task_by_id(db_session, task_id)
    if not task_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    if task_obj.lifecycle_status == TaskLifecycleStatus.CLOSED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Closed tasks cannot be destroyed.",
        )
    if task_obj.lifecycle_status == TaskLifecycleStatus.DELETED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Task is already deleted.",
        )

    if not TaskService.has_task_started(task_obj):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Task destroy is only available after the task has started. "
                "Use Delete for backlog tasks."
            ),
        )

    destroyed_stage_label_str = _format_workflow_stage_label(task_obj.workflow_stage)
    project_label_str = _resolve_project_display_name(db_session, task_obj.project_id)
    worktree_path_snapshot_str = task_obj.worktree_path
    cleanup_summary_str = (
        "background automation stopped; no worktree cleanup was needed."
    )

    cancel_codex_task(task_id)
    clear_task_background_activity(task_id)

    if worktree_path_snapshot_str:
        from backend.dsl.models.project import Project
        from backend.dsl.services.git_worktree_service import GitWorktreeService

        project_repo_path_obj: Path | None = None
        if task_obj.project_id:
            project_obj = (
                db_session.query(Project)
                .filter(Project.id == task_obj.project_id)
                .first()
            )
            if project_obj:
                project_repo_path_obj = Path(project_obj.repo_path)

        try:
            repo_root_path = GitWorktreeService.resolve_repo_root_path(
                project_repo_path=project_repo_path_obj,
                worktree_path=Path(worktree_path_snapshot_str),
            )
            cleanup_result = GitWorktreeService.destroy_task_worktree(
                repo_root_path=repo_root_path,
                task_id=task_id,
                worktree_path=Path(worktree_path_snapshot_str),
            )
        except ValueError as cleanup_error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(cleanup_error),
            ) from cleanup_error

        cleanup_completed_fully = (
            cleanup_result.cleanup_succeeded
            and cleanup_result.worktree_removed
            and cleanup_result.branch_deleted
        )
        if not cleanup_completed_fully:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=cleanup_result.failure_reason_text
                or _build_destroy_cleanup_failure_reason(
                    worktree_removed=cleanup_result.worktree_removed,
                    branch_deleted=cleanup_result.branch_deleted,
                ),
            )
        cleanup_summary_str = (
            "background automation stopped and task worktree cleanup completed."
        )

    try:
        updated_task = TaskService.destroy_task(
            db_session,
            task_id,
            destroy_payload.destroy_reason,
        )
    except ValueError as destroy_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(destroy_error),
        ) from destroy_error

    if not updated_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    LogService.create_internal_log(
        db_session,
        DevLogCreateSchema(
            task_id=task_id,
            text_content=_build_task_destroy_log_text(
                task_title_str=task_obj.task_title,
                destroyed_stage_label_str=destroyed_stage_label_str,
                project_label_str=project_label_str,
                destroy_reason_str=destroy_payload.destroy_reason,
                requirement_summary_str=(
                    task_obj.requirement_brief or "No requirement brief captured yet."
                ),
                worktree_path_snapshot_str=worktree_path_snapshot_str,
                cleanup_summary_str=cleanup_summary_str,
            ),
            state_tag=DevLogStateTag.TRANSFERRED,
        ),
        updated_task.run_account_id,
    )
    return _hydrate_task_response(updated_task, is_task_running_override=False)


@router.get("/{task_id}/prd-file")
def get_task_prd_file(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> dict:
    """读取任务 worktree 中该任务专属的 PRD 文件内容.

    后端会按当前任务的专属前缀 `tasks/prd-{task_id[:8]}*.md` 查找，
    优先读取带语义 slug 的新文件名，同时兼容旧的固定文件名。

    Args:
        task_id: 任务 ID
        db_session: 数据库会话

    Returns:
        dict: {"content": str, "path": str} 或 {"content": null, "path": null}
    """
    from pathlib import Path as _Path

    task_obj = TaskService.get_task_by_id(db_session, task_id)
    if not task_obj or not task_obj.worktree_path:
        return {"content": None, "path": None}

    worktree_dir = _Path(task_obj.worktree_path)
    if not worktree_dir.exists():
        return {"content": None, "path": None}

    prd_file_path = find_task_prd_file_path(worktree_dir, task_id)
    if prd_file_path is None:
        repair_result = repair_invalid_task_prd_file_for_read(
            worktree_dir_path=worktree_dir,
            task_id_str=task_id,
            task_title_str=task_obj.task_title,
        )
        prd_file_path = repair_result.resolved_file_path
    if prd_file_path is None:
        return {"content": None, "path": None}

    try:
        prd_content = prd_file_path.read_text(encoding="utf-8")
        return {"content": prd_content, "path": str(prd_file_path)}
    except OSError:
        return {"content": None, "path": None}


def _open_task_worktree_in_editor(
    task_id: str,
    db_session: Session,
) -> dict[str, str]:
    """使用配置的编辑器命令打开任务对应的 git worktree 目录.

    需要任务已有 worktree_path（即已触发过执行），且该路径在文件系统中存在。

    Args:
        task_id: 任务 ID
        db_session: 数据库会话

    Returns:
        dict: 包含打开路径的确认信息

    Raises:
        HTTPException: 任务不存在（404）、worktree 未设置（422）、目标路径不存在（422）
            或命令模板 / 可执行命令异常（500）
    """
    from pathlib import Path as _Path

    task_obj = TaskService.get_task_by_id(db_session, task_id)
    if not task_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    if not task_obj.worktree_path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Task has no worktree_path. Execute the task first.",
        )

    worktree_dir_path = _Path(task_obj.worktree_path)

    if not worktree_dir_path.exists():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Worktree directory does not exist yet: {worktree_dir_path}",
        )

    try:
        open_path_in_editor(
            target_path=worktree_dir_path,
            target_kind="worktree",
        )
    except PathOpenTargetNotFoundError as path_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(path_error),
        ) from path_error
    except PathOpenCommandError as path_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(path_error),
        ) from path_error

    return {"opened": str(worktree_dir_path)}


@router.post("/{task_id}/open-in-editor", status_code=status.HTTP_200_OK)
def open_task_in_editor(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    """使用配置的编辑器命令打开任务对应的 git worktree 目录.

    Args:
        task_id: 任务 ID
        db_session: 数据库会话

    Returns:
        dict[str, str]: 包含打开路径的确认信息
    """
    return _open_task_worktree_in_editor(task_id=task_id, db_session=db_session)


@router.post(
    "/{task_id}/open-in-trae",
    status_code=status.HTTP_200_OK,
    deprecated=True,
)
def open_task_in_trae(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    """兼容旧客户端的别名路由，内部复用 `open-in-editor` 逻辑.

    Args:
        task_id: 任务 ID
        db_session: 数据库会话

    Returns:
        dict[str, str]: 包含打开路径的确认信息
    """
    return _open_task_worktree_in_editor(task_id=task_id, db_session=db_session)


@router.post("/{task_id}/open-terminal", status_code=status.HTTP_200_OK)
def open_task_terminal(
    task_id: str,
) -> dict:
    """打开一个新的终端窗口，实时查看该任务的 codex 输出日志.

    默认支持 macOS、WSL 与常见 Linux 桌面终端；也可通过
    `KODA_OPEN_TERMINAL_COMMAND` 自定义启动命令。日志文件由
    codex_runner 在任务执行时自动写入 `/tmp/koda-{task_id[:8]}.log`。

    Args:
        task_id: 任务 ID

    Returns:
        dict: 包含日志文件路径的确认信息

    Raises:
        HTTPException: 日志文件不存在（404）或终端无法打开（500）
    """
    log_file_path = get_task_log_path(task_id)

    if not log_file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"尚无日志文件（{log_file_path}）。请先启动任务。",
        )

    try:
        open_log_tail_terminal(log_file_path)
    except TerminalLaunchError as launch_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(launch_error),
        ) from launch_error

    return {"log_file": str(log_file_path)}


@router.patch("/{task_id}", response_model=TaskResponseSchema)
def update_task(
    task_id: str,
    task_update_schema: TaskUpdateSchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """更新任务内容.

    Args:
        task_id: 任务 ID
        task_update_schema: 任务更新数据
        db_session: 数据库会话

    Returns:
        Task: 更新后的任务

    Raises:
        HTTPException: 当任务不存在时返回 404
    """
    existing_task = TaskService.get_task_by_id(db_session, task_id)
    if not existing_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    previous_project_id_str = existing_task.project_id
    previous_project_label_str = _resolve_project_display_name(
        db_session,
        previous_project_id_str,
    )

    try:
        updated_task = TaskService.update_task(db_session, task_id, task_update_schema)
    except ValueError as validation_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(validation_error),
        ) from validation_error

    if not updated_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )
    if previous_project_id_str != updated_task.project_id:
        next_project_label_str = _resolve_project_display_name(
            db_session,
            updated_task.project_id,
        )
        LogService.create_log(
            db_session,
            DevLogCreateSchema(
                task_id=task_id,
                text_content=_build_task_project_rebind_log_text(
                    previous_project_label_str=previous_project_label_str,
                    next_project_label_str=next_project_label_str,
                ),
                state_tag=DevLogStateTag.TRANSFERRED,
            ),
            updated_task.run_account_id,
        )
    return _hydrate_task_response(updated_task, db_session=db_session)


@router.post(
    "/{target_task_id}/references",
    response_model=TaskReferenceResponseSchema,
)
def create_task_reference(
    target_task_id: str,
    reference_create_schema: TaskReferenceCreateSchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> TaskReferenceResponseSchema:
    """把历史需求任务引用到当前需求卡片.

    该接口会创建结构化引用 DevLog，并可选把摘要追加到目标任务
    `requirement_brief`。当完整附录会超过字段上限时，会退化为紧凑版
    引用附录；若连紧凑版也放不下，则返回 422，而不是把错误拖到数据库层。

    Args:
        target_task_id: 目标任务 ID
        reference_create_schema: 引用创建参数
        db_session: 数据库会话

    Returns:
        TaskReferenceResponseSchema: 引用创建结果

    Raises:
        HTTPException: 当任务不存在、无权限或参数非法时返回 404/422
    """
    run_account_id = _get_current_run_account_id(db_session)
    target_task_obj = TaskService.get_task_by_id(db_session, target_task_id)
    source_task_obj = TaskService.get_task_by_id(
        db_session,
        reference_create_schema.source_task_id,
    )

    if target_task_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target task with id {target_task_id} not found",
        )
    if source_task_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Source task with id {reference_create_schema.source_task_id} "
                "not found"
            ),
        )
    if target_task_obj.run_account_id != run_account_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target task with id {target_task_id} not found",
        )
    if source_task_obj.run_account_id != run_account_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Source task with id {reference_create_schema.source_task_id} "
                "not found"
            ),
        )
    if source_task_obj.id == target_task_obj.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="source_task_id cannot be the same as target_task_id.",
        )
    if target_task_obj.lifecycle_status in {
        TaskLifecycleStatus.CLOSED,
        TaskLifecycleStatus.DELETED,
        TaskLifecycleStatus.ABANDONED,
    }:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Target task is not editable in lifecycle "
                f"'{target_task_obj.lifecycle_status.value}'."
            ),
        )

    normalized_reference_note = (
        reference_create_schema.reference_note.strip()
        if reference_create_schema.reference_note
        else None
    )
    task_reference_link_obj = (
        db_session.query(TaskReferenceLink)
        .filter(
            TaskReferenceLink.source_task_id == source_task_obj.id,
            TaskReferenceLink.target_task_id == target_task_obj.id,
        )
        .first()
    )
    requirement_brief_already_contains_reference = (
        _requirement_brief_contains_reference(
            target_task_obj=target_task_obj,
            source_task_id=source_task_obj.id,
        )
    )
    requirement_brief_reference_already_appended = (
        requirement_brief_already_contains_reference
        or (
            task_reference_link_obj.requirement_brief_appended
            if task_reference_link_obj is not None
            else False
        )
    )
    pending_requirement_brief_text: str | None = None

    if (
        reference_create_schema.append_to_requirement_brief
        and not requirement_brief_reference_already_appended
    ):
        pending_requirement_brief_text = (
            _build_bounded_requirement_brief_with_reference_appendix(
                existing_requirement_brief_text=target_task_obj.requirement_brief or "",
                source_task_obj=source_task_obj,
                reference_note_text=normalized_reference_note,
            )
        )

    if task_reference_link_obj is None:
        existing_reference_log_obj = _find_existing_task_reference_log(
            db_session=db_session,
            source_task_id=source_task_obj.id,
            target_task_id=target_task_obj.id,
        )
        reference_log_id = (
            existing_reference_log_obj.id if existing_reference_log_obj else None
        )
        if reference_log_id is None:
            reference_log_markdown = _build_task_reference_log_markdown(
                source_task_obj=source_task_obj,
                target_task_obj=target_task_obj,
                reference_note_text=normalized_reference_note,
            )
            created_reference_log_obj = LogService.create_log(
                db_session=db_session,
                log_create_schema=DevLogCreateSchema(
                    task_id=target_task_obj.id,
                    text_content=reference_log_markdown,
                    state_tag=DevLogStateTag.TRANSFERRED,
                ),
                run_account_id=run_account_id,
            )
            reference_log_id = created_reference_log_obj.id

        task_reference_link_obj = TaskReferenceLink(
            run_account_id=run_account_id,
            source_task_id=source_task_obj.id,
            target_task_id=target_task_obj.id,
            reference_log_id=reference_log_id,
            requirement_brief_appended=requirement_brief_already_contains_reference,
        )
        db_session.add(task_reference_link_obj)
        db_session.commit()
        db_session.refresh(task_reference_link_obj)
    elif (
        not task_reference_link_obj.requirement_brief_appended
        and _requirement_brief_contains_reference(
            target_task_obj=target_task_obj,
            source_task_id=source_task_obj.id,
        )
    ):
        task_reference_link_obj.requirement_brief_appended = True
        db_session.commit()
        db_session.refresh(task_reference_link_obj)

    if task_reference_link_obj.reference_log_id is None:
        existing_reference_log_obj = _find_existing_task_reference_log(
            db_session=db_session,
            source_task_id=source_task_obj.id,
            target_task_id=target_task_obj.id,
        )
        if existing_reference_log_obj is None:
            reference_log_markdown = _build_task_reference_log_markdown(
                source_task_obj=source_task_obj,
                target_task_obj=target_task_obj,
                reference_note_text=normalized_reference_note,
            )
            existing_reference_log_obj = LogService.create_log(
                db_session=db_session,
                log_create_schema=DevLogCreateSchema(
                    task_id=target_task_obj.id,
                    text_content=reference_log_markdown,
                    state_tag=DevLogStateTag.TRANSFERRED,
                ),
                run_account_id=run_account_id,
            )
        task_reference_link_obj.reference_log_id = existing_reference_log_obj.id
        db_session.commit()
        db_session.refresh(task_reference_link_obj)

    if (
        reference_create_schema.append_to_requirement_brief
        and not task_reference_link_obj.requirement_brief_appended
    ):
        target_task_obj.requirement_brief = pending_requirement_brief_text
        task_reference_link_obj.requirement_brief_appended = True
        db_session.commit()
        db_session.refresh(target_task_obj)
        db_session.refresh(task_reference_link_obj)

    return TaskReferenceResponseSchema(
        target_task_id=target_task_obj.id,
        source_task_id=source_task_obj.id,
        reference_log_id=task_reference_link_obj.reference_log_id,
        requirement_brief_appended=task_reference_link_obj.requirement_brief_appended,
    )


@router.get("/{task_id}", response_model=TaskResponseSchema)
def get_task(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """获取单个任务详情.

    Args:
        task_id: 任务 ID
        db_session: 数据库会话

    Returns:
        Task: 任务详情

    Raises:
        HTTPException: 当任务不存在时返回 404
    """
    task_obj = TaskService.get_task_by_id(db_session, task_id)
    if not task_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )
    task_log_count_map = TaskService.get_task_log_count_map(db_session, [task_obj.id])
    return _hydrate_task_response(
        task_obj,
        db_session=db_session,
        log_count_override=task_log_count_map.get(task_obj.id, 0),
    )
