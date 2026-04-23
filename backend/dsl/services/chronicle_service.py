"""编年史服务模块.

提供 Timeline 视图、Task 视图、项目时间线聚合和 Markdown 导出功能.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend.dsl.models.dev_log import DevLog
from backend.dsl.models.enums import (
    DevLogStateTag,
    TaskArtifactType,
    TaskLifecycleStatus,
)
from backend.dsl.models.project import Project
from backend.dsl.models.task import Task
from backend.dsl.models.task_artifact import TaskArtifact
from backend.dsl.services.prd_file_service import find_task_readable_prd_file_path
from backend.dsl.services.task_service import TaskService
from utils.helpers import (
    format_date_in_app_timezone,
    format_datetime_in_app_timezone,
    format_time_in_app_timezone,
    get_app_timezone_display_label,
    get_app_timezone_offset_label,
    parse_iso_datetime_text,
    serialize_datetime_for_api,
)


class ChronicleService:
    """编年史服务类.

    处理日志的时间线渲染、任务视图、项目维度聚合与 Markdown 导出.
    """

    # 状态标记到图标的映射
    STATE_TAG_ICONS: dict[DevLogStateTag, str] = {
        DevLogStateTag.NONE: "",
        DevLogStateTag.BUG: "🐛",
        DevLogStateTag.OPTIMIZATION: "💡",
        DevLogStateTag.FIXED: "✅",
        DevLogStateTag.TRANSFERRED: "⏭️",
    }

    # 状态标记到颜色的映射 (用于 Markdown)
    STATE_TAG_COLORS: dict[DevLogStateTag, str] = {
        DevLogStateTag.NONE: "",
        DevLogStateTag.BUG: "🔴",
        DevLogStateTag.OPTIMIZATION: "🟡",
        DevLogStateTag.FIXED: "🟢",
        DevLogStateTag.TRANSFERRED: "🔵",
    }

    _PLANNING_WITH_FILES_PATTERN = re.compile(
        r"(planning with files|planing with files)",
        re.IGNORECASE,
    )
    _CANDIDATE_PATH_IN_BACKTICKS_PATTERN = re.compile(r"`([^`\n]+)`")
    _CANDIDATE_PATH_IN_LIST_PATTERN = re.compile(
        r"^\s*[-*]\s+([A-Za-z0-9_./\\-]+\.[A-Za-z0-9._-]+)\s*$",
        re.MULTILINE,
    )
    _ACTIVE_PLANNING_RELATIVE_PATH_TUPLE = (
        ".claude/planning/current/task_plan.md",
        ".claude/planning/current/findings.md",
        ".claude/planning/current/progress.md",
    )
    _LEGACY_PLANNING_RELATIVE_PATH_TUPLE = (
        "task_plan.md",
        "findings.md",
        "progress.md",
    )

    @staticmethod
    def _normalize_project_category_scope(
        raw_project_category_str: str | None,
    ) -> str | None:
        """标准化项目类别筛选值.

        Args:
            raw_project_category_str: 原始项目类别筛选值

        Returns:
            str | None: 去首尾空白后的类别值；空字符串返回 None
        """
        if raw_project_category_str is None:
            return None
        normalized_project_category_str = raw_project_category_str.strip()
        return normalized_project_category_str or None

    @staticmethod
    def _is_datetime_in_project_timeline_scope(
        candidate_datetime: datetime | None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> bool:
        """判断时间点是否落在项目时间线筛选窗口内.

        Args:
            candidate_datetime: 待判断时间点
            start_date: 起始时间（可选）
            end_date: 截止时间（可选）

        Returns:
            bool: 是否属于当前筛选窗口
        """
        if candidate_datetime is None:
            return False
        if start_date is not None and candidate_datetime < start_date:
            return False
        if end_date is not None and candidate_datetime > end_date:
            return False
        return True

    @staticmethod
    def get_timeline(
        db_session: Session,
        run_account_id: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """获取时间线视图数据.

        Args:
            db_session: 数据库会话
            run_account_id: 运行账户 ID
            start_date: 开始日期过滤（可选）
            end_date: 结束日期过滤（可选）
            limit: 返回数量限制

        Returns:
            list[dict[str, Any]]: 时间线数据列表
        """
        query = db_session.query(DevLog).filter(DevLog.run_account_id == run_account_id)

        if start_date:
            query = query.filter(DevLog.created_at >= start_date)
        if end_date:
            query = query.filter(DevLog.created_at <= end_date)

        logs = query.order_by(DevLog.created_at.desc()).limit(limit).all()

        return [ChronicleService._format_log_for_timeline(log) for log in logs]

    @staticmethod
    def get_task_chronicle(
        db_session: Session,
        task_id: str,
    ) -> dict[str, Any] | None:
        """获取任务编年史数据.

        Args:
            db_session: 数据库会话
            task_id: 任务 ID

        Returns:
            dict[str, Any] | None: 任务编年史数据或 None
        """
        task = TaskService.get_task_by_id(db_session, task_id)
        if not task:
            return None

        logs = (
            db_session.query(DevLog)
            .filter(DevLog.task_id == task_id)
            .order_by(DevLog.created_at.asc(), DevLog.id.asc())
            .all()
        )
        formatted_log_list = [
            ChronicleService._format_log_for_timeline(log) for log in logs
        ]

        return {
            "task": {
                "id": task.id,
                "title": task.task_title,
                "status": task.lifecycle_status.value,
                "created_at": serialize_datetime_for_api(task.created_at),
                "closed_at": serialize_datetime_for_api(task.closed_at),
            },
            "logs": formatted_log_list,
            "transcript_blocks": ChronicleService._build_task_transcript_block_list(
                formatted_log_list
            ),
            "stats": {
                "total_logs": len(logs),
                "bug_count": sum(
                    1 for log in logs if log.state_tag == DevLogStateTag.BUG
                ),
                "fix_count": sum(
                    1 for log in logs if log.state_tag == DevLogStateTag.FIXED
                ),
            },
        }

    @staticmethod
    def get_project_timeline(
        db_session: Session,
        run_account_id: str,
        project_id: str | None = None,
        project_category: str | None = None,
        lifecycle_status_list: list[TaskLifecycleStatus] | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """按项目聚合时间线.

        日期筛选采用“窗口内活动”语义：任务在范围内任一创建/阶段变更/关闭/日志
        活动命中时都会保留；`total_logs`/`bug_count`/`fix_count` 仅统计同一时间
        窗口内的日志。

        Args:
            db_session: 数据库会话
            run_account_id: 运行账户 ID
            project_id: 项目 ID（可选）
            project_category: 项目类别（可选）
            lifecycle_status_list: 生命周期过滤列表（可选）
            start_date: 开始时间（可选）
            end_date: 结束时间（可选）
            limit: 返回数量限制
            offset: 分页偏移

        Returns:
            list[dict[str, Any]]: 项目时间线条目
        """
        normalized_project_category = (
            ChronicleService._normalize_project_category_scope(project_category)
        )
        task_query = (
            db_session.query(Task, Project)
            .outerjoin(Project, Task.project_id == Project.id)
            .filter(
                Task.run_account_id == run_account_id,
                Task.project_id.isnot(None),
            )
        )
        if project_id:
            task_query = task_query.filter(Task.project_id == project_id)
        if normalized_project_category is not None:
            task_query = task_query.filter(
                Project.project_category == normalized_project_category
            )
        if lifecycle_status_list:
            task_query = task_query.filter(
                Task.lifecycle_status.in_(lifecycle_status_list)
            )

        matched_task_row_list = task_query.order_by(Task.created_at.desc()).all()
        if not matched_task_row_list:
            return []

        matched_task_list = [
            task_obj for task_obj, _project_obj in matched_task_row_list
        ]
        task_id_list = [task_item.id for task_item in matched_task_list]
        task_project_metadata_by_task_id: dict[str, tuple[str | None, str | None]] = {
            task_obj.id: (
                project_obj.display_name if project_obj is not None else None,
                project_obj.project_category if project_obj is not None else None,
            )
            for task_obj, project_obj in matched_task_row_list
        }
        task_log_stats_query = db_session.query(
            DevLog.task_id,
            func.count(DevLog.id),
            func.sum(
                case(
                    (DevLog.state_tag == DevLogStateTag.BUG, 1),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (DevLog.state_tag == DevLogStateTag.FIXED, 1),
                    else_=0,
                )
            ),
            func.max(DevLog.created_at),
        ).filter(DevLog.task_id.in_(task_id_list))
        if start_date is not None:
            task_log_stats_query = task_log_stats_query.filter(
                DevLog.created_at >= start_date
            )
        if end_date is not None:
            task_log_stats_query = task_log_stats_query.filter(
                DevLog.created_at <= end_date
            )
        task_log_stats_row_list = task_log_stats_query.group_by(DevLog.task_id).all()

        task_log_stats_by_task_id: dict[str, tuple[int, int, int, datetime | None]] = {
            task_id_str: (
                int(total_log_count_int or 0),
                int(bug_log_count_int or 0),
                int(fix_log_count_int or 0),
                last_log_created_at_datetime,
            )
            for (
                task_id_str,
                total_log_count_int,
                bug_log_count_int,
                fix_log_count_int,
                last_log_created_at_datetime,
            ) in task_log_stats_row_list
        }

        artifact_presence_row_list = (
            db_session.query(TaskArtifact.task_id, TaskArtifact.artifact_type)
            .filter(TaskArtifact.task_id.in_(task_id_list))
            .distinct()
            .all()
        )
        artifact_presence_by_task_id: dict[str, set[TaskArtifactType]] = {}
        for task_id_str, artifact_type in artifact_presence_row_list:
            artifact_presence_by_task_id.setdefault(task_id_str, set()).add(
                artifact_type
            )

        project_timeline_entry_list: list[dict[str, Any]] = []
        for task_item in matched_task_list:
            (
                total_logs,
                bug_count,
                fix_count,
                last_log_created_at,
            ) = task_log_stats_by_task_id.get(task_item.id, (0, 0, 0, None))

            scoped_activity_candidate_list = [
                candidate_datetime
                for candidate_datetime in (
                    task_item.created_at,
                    task_item.closed_at,
                    task_item.stage_updated_at,
                    last_log_created_at,
                )
                if ChronicleService._is_datetime_in_project_timeline_scope(
                    candidate_datetime,
                    start_date,
                    end_date,
                )
            ]
            if not scoped_activity_candidate_list:
                continue
            last_activity_at = max(scoped_activity_candidate_list)

            task_artifact_type_set = artifact_presence_by_task_id.get(
                task_item.id, set()
            )
            project_display_name, project_category_value = (
                task_project_metadata_by_task_id.get(task_item.id, (None, None))
            )
            project_timeline_entry_list.append(
                {
                    "task_id": task_item.id,
                    "project_id": task_item.project_id,
                    "project_display_name": project_display_name,
                    "project_category": project_category_value,
                    "task_title": task_item.task_title,
                    "lifecycle_status": task_item.lifecycle_status.value,
                    "workflow_stage": task_item.workflow_stage.value,
                    "created_at": serialize_datetime_for_api(task_item.created_at),
                    "closed_at": serialize_datetime_for_api(task_item.closed_at),
                    "closed_at_in_scope": (
                        ChronicleService._is_datetime_in_project_timeline_scope(
                            task_item.closed_at,
                            start_date,
                            end_date,
                        )
                    ),
                    "last_activity_at": serialize_datetime_for_api(last_activity_at),
                    "total_logs": total_logs,
                    "bug_count": bug_count,
                    "fix_count": fix_count,
                    "has_prd_artifact": TaskArtifactType.PRD in task_artifact_type_set,
                    "has_planning_artifact": (
                        TaskArtifactType.PLANNING_WITH_FILES in task_artifact_type_set
                    ),
                }
            )

        project_timeline_entry_list.sort(
            key=lambda timeline_entry: timeline_entry["last_activity_at"] or "",
            reverse=True,
        )

        normalized_offset = max(offset, 0)
        normalized_limit = max(limit, 1)
        return project_timeline_entry_list[
            normalized_offset : normalized_offset + normalized_limit
        ]

    @staticmethod
    def get_project_timeline_task_detail(
        db_session: Session,
        run_account_id: str,
        task_id: str,
        log_limit: int = 200,
    ) -> dict[str, Any] | None:
        """获取项目时间线中的任务详情.

        Args:
            db_session: 数据库会话
            run_account_id: 运行账户 ID
            task_id: 任务 ID
            log_limit: 返回的日志数量上限

        Returns:
            dict[str, Any] | None: 详情数据；无权限或不存在时返回 None
        """
        task_obj = TaskService.get_task_by_id(db_session, task_id)
        if task_obj is None or task_obj.run_account_id != run_account_id:
            return None

        ordered_task_dev_log_list = (
            db_session.query(DevLog)
            .filter(DevLog.task_id == task_obj.id)
            .order_by(DevLog.created_at.asc(), DevLog.id.asc())
            .all()
        )
        limited_task_dev_log_list = (
            ordered_task_dev_log_list[-log_limit:]
            if log_limit > 0 and len(ordered_task_dev_log_list) > log_limit
            else ordered_task_dev_log_list
        )

        prd_task_artifact_obj = ChronicleService._ensure_prd_task_artifact_snapshot(
            db_session=db_session,
            task_obj=task_obj,
        )
        planning_task_artifact_obj = (
            ChronicleService._ensure_planning_with_files_task_artifact_snapshot(
                db_session=db_session,
                task_obj=task_obj,
                ordered_task_dev_log_list=ordered_task_dev_log_list,
            )
        )

        bug_log_count = sum(
            1
            for dev_log_item in ordered_task_dev_log_list
            if dev_log_item.state_tag == DevLogStateTag.BUG
        )
        fix_log_count = sum(
            1
            for dev_log_item in ordered_task_dev_log_list
            if dev_log_item.state_tag == DevLogStateTag.FIXED
        )

        return {
            "task": {
                "id": task_obj.id,
                "project_id": task_obj.project_id,
                "project_display_name": (
                    task_obj.project.display_name
                    if task_obj.project is not None
                    else None
                ),
                "project_category": (
                    task_obj.project.project_category
                    if task_obj.project is not None
                    else None
                ),
                "title": task_obj.task_title,
                "lifecycle_status": task_obj.lifecycle_status.value,
                "workflow_stage": task_obj.workflow_stage.value,
                "created_at": serialize_datetime_for_api(task_obj.created_at),
                "closed_at": serialize_datetime_for_api(task_obj.closed_at),
            },
            "requirement_snapshot": task_obj.requirement_brief,
            "prd_snapshot": ChronicleService._serialize_task_artifact_snapshot(
                prd_task_artifact_obj
            ),
            "planning_snapshot": ChronicleService._serialize_task_artifact_snapshot(
                planning_task_artifact_obj
            ),
            "logs": [
                ChronicleService._format_log_for_timeline(dev_log_item)
                for dev_log_item in limited_task_dev_log_list
            ],
            "stats": {
                "total_logs": len(ordered_task_dev_log_list),
                "bug_count": bug_log_count,
                "fix_count": fix_log_count,
            },
        }

    @staticmethod
    def summarize_project_timeline(
        db_session: Session,
        run_account_id: str,
        project_id: str | None = None,
        project_category: str | None = None,
        lifecycle_status_list: list[TaskLifecycleStatus] | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        summary_focus: str = "progress",
    ) -> dict[str, Any]:
        """生成项目时间线摘要.

        当前采用规则引擎方式提炼 milestones/risks/next_actions，输出结构化摘要，
        便于前端后续接入更重的 LLM 总结实现。

        Args:
            db_session: 数据库会话
            run_account_id: 运行账户 ID
            project_id: 项目 ID（可选）
            project_category: 项目类别（可选）
            lifecycle_status_list: 生命周期筛选列表（可选）
            start_date: 开始时间（可选）
            end_date: 结束时间（可选）
            summary_focus: 关注点（progress/risk/decision）

        Returns:
            dict[str, Any]: 结构化摘要结果
        """
        project_timeline_entry_list = ChronicleService.get_project_timeline(
            db_session=db_session,
            run_account_id=run_account_id,
            project_id=project_id,
            project_category=project_category,
            lifecycle_status_list=lifecycle_status_list,
            start_date=start_date,
            end_date=end_date,
            limit=500,
            offset=0,
        )
        if not project_timeline_entry_list:
            return {
                "summary_text": "当前筛选条件下暂无可总结的项目时间线数据。",
                "milestones": [],
                "risks": [],
                "next_actions": [],
                "source_task_ids": [],
            }

        source_task_id_list = [
            timeline_entry["task_id"] for timeline_entry in project_timeline_entry_list
        ]

        milestone_text_list: list[str] = []
        risk_text_list: list[str] = []
        next_action_text_list: list[str] = []

        for timeline_entry in project_timeline_entry_list:
            task_title = timeline_entry["task_title"]
            lifecycle_status = timeline_entry["lifecycle_status"]
            total_logs = int(timeline_entry["total_logs"])
            bug_count = int(timeline_entry["bug_count"])
            fix_count = int(timeline_entry["fix_count"])
            closed_at_in_scope = bool(timeline_entry.get("closed_at_in_scope"))

            if (
                lifecycle_status == TaskLifecycleStatus.CLOSED.value
                and closed_at_in_scope
            ):
                closed_at_label = (
                    ChronicleService._format_markdown_datetime_label(
                        timeline_entry["closed_at"]
                    )
                    if timeline_entry["closed_at"]
                    else ChronicleService._format_markdown_datetime_label(
                        timeline_entry["last_activity_at"]
                    )
                )
                milestone_text_list.append(
                    f"《{task_title}》已完成（{closed_at_label}）"
                )
                continue

            if (
                lifecycle_status == TaskLifecycleStatus.CLOSED.value
                and bug_count <= fix_count
            ):
                continue

            if lifecycle_status == TaskLifecycleStatus.ABANDONED.value:
                risk_text_list.append(
                    f"《{task_title}》已废弃，需确认是否有未迁移上下文。"
                )
                continue

            if lifecycle_status == TaskLifecycleStatus.DELETED.value:
                risk_text_list.append(
                    f"《{task_title}》已删除，需核查是否影响关联需求。"
                )
                continue

            if bug_count > fix_count:
                risk_text_list.append(
                    f"《{task_title}》仍有未闭合问题（bug {bug_count} / fix {fix_count}）。"
                )
                next_action_text_list.append(
                    f"优先推进《{task_title}》的阻塞修复并补齐验证。"
                )
            elif total_logs == 0:
                next_action_text_list.append(
                    f"《{task_title}》尚无执行日志，建议尽快启动。"
                )
            else:
                next_action_text_list.append(f"继续推进《{task_title}》到可验收阶段。")

        if not milestone_text_list:
            milestone_text_list.append("当前筛选范围内暂无已完成里程碑。")
        if not risk_text_list:
            risk_text_list.append("当前筛选范围内未发现显著风险。")
        if not next_action_text_list:
            next_action_text_list.append("保持当前推进节奏，并持续更新时间线证据。")

        milestone_text_list = milestone_text_list[:5]
        risk_text_list = risk_text_list[:5]
        next_action_text_list = next_action_text_list[:5]

        if summary_focus == "risk":
            summary_text = (
                f"项目在当前筛选范围内共涉及 {len(project_timeline_entry_list)} 个任务，"
                f"主要风险集中在 {len(risk_text_list)} 个事项。"
            )
        elif summary_focus == "decision":
            summary_text = (
                f"项目当前可用于决策的任务样本为 {len(project_timeline_entry_list)} 个，"
                "建议优先根据风险与下一步建议安排资源。"
            )
        else:
            summary_text = (
                f"项目当前筛选范围包含 {len(project_timeline_entry_list)} 个任务，"
                f"已识别 {len(milestone_text_list)} 个里程碑与 {len(risk_text_list)} 个风险点。"
            )

        return {
            "summary_text": summary_text,
            "milestones": milestone_text_list,
            "risks": risk_text_list,
            "next_actions": next_action_text_list,
            "source_task_ids": source_task_id_list[:30],
        }

    @staticmethod
    def _get_latest_task_artifact(
        db_session: Session,
        task_id: str,
        artifact_type: TaskArtifactType,
    ) -> TaskArtifact | None:
        """获取任务指定类型的最新工件快照."""
        return (
            db_session.query(TaskArtifact)
            .filter(
                TaskArtifact.task_id == task_id,
                TaskArtifact.artifact_type == artifact_type,
            )
            .order_by(TaskArtifact.captured_at.desc())
            .first()
        )

    @staticmethod
    def _serialize_task_artifact_snapshot(
        task_artifact_obj: TaskArtifact | None,
    ) -> dict[str, Any] | None:
        """序列化任务工件快照."""
        if task_artifact_obj is None:
            return None

        file_manifest_list: list[str] = []
        if task_artifact_obj.file_manifest_json:
            try:
                loaded_file_manifest = json.loads(task_artifact_obj.file_manifest_json)
                if isinstance(loaded_file_manifest, list):
                    file_manifest_list = [
                        str(file_path_item)
                        for file_path_item in loaded_file_manifest
                        if isinstance(file_path_item, str)
                    ]
            except json.JSONDecodeError:
                file_manifest_list = []

        return {
            "artifact_type": task_artifact_obj.artifact_type.value,
            "source_path": task_artifact_obj.source_path,
            "content_markdown": task_artifact_obj.content_markdown,
            "file_manifest": file_manifest_list,
            "captured_at": serialize_datetime_for_api(task_artifact_obj.captured_at),
        }

    @staticmethod
    def _create_or_reuse_task_artifact_snapshot(
        db_session: Session,
        task_id: str,
        artifact_type: TaskArtifactType,
        source_path: str | None,
        content_markdown: str,
        file_manifest_list: list[str] | None = None,
    ) -> TaskArtifact:
        """创建或复用任务工件快照.

        如果最新同类型快照内容与来源均一致，则直接复用，避免重复落库。
        """
        normalized_file_manifest_json = json.dumps(
            file_manifest_list or [],
            ensure_ascii=False,
        )
        latest_task_artifact_obj = ChronicleService._get_latest_task_artifact(
            db_session=db_session,
            task_id=task_id,
            artifact_type=artifact_type,
        )
        if (
            latest_task_artifact_obj is not None
            and latest_task_artifact_obj.source_path == source_path
            and latest_task_artifact_obj.content_markdown == content_markdown
            and (latest_task_artifact_obj.file_manifest_json or "[]")
            == normalized_file_manifest_json
        ):
            return latest_task_artifact_obj

        created_task_artifact_obj = TaskArtifact(
            task_id=task_id,
            artifact_type=artifact_type,
            source_path=source_path,
            content_markdown=content_markdown,
            file_manifest_json=normalized_file_manifest_json,
        )
        db_session.add(created_task_artifact_obj)
        db_session.commit()
        db_session.refresh(created_task_artifact_obj)
        return created_task_artifact_obj

    @staticmethod
    def _ensure_prd_task_artifact_snapshot(
        db_session: Session,
        task_obj: Task,
    ) -> TaskArtifact | None:
        """确保任务存在 PRD 快照."""
        if task_obj.worktree_path:
            worktree_dir_path = Path(task_obj.worktree_path)
            if worktree_dir_path.exists():
                captured_prd_task_artifact_obj = (
                    ChronicleService.capture_prd_artifact_snapshot(
                        db_session=db_session,
                        task_id=task_obj.id,
                        worktree_dir_path=worktree_dir_path,
                    )
                )
                if captured_prd_task_artifact_obj is not None:
                    return captured_prd_task_artifact_obj

        return ChronicleService._get_latest_task_artifact(
            db_session=db_session,
            task_id=task_obj.id,
            artifact_type=TaskArtifactType.PRD,
        )

    @staticmethod
    def _ensure_planning_with_files_task_artifact_snapshot(
        db_session: Session,
        task_obj: Task,
        ordered_task_dev_log_list: list[DevLog],
    ) -> TaskArtifact | None:
        """确保任务存在 planning with files 快照."""
        if task_obj.worktree_path:
            worktree_dir_path = Path(task_obj.worktree_path)
            if worktree_dir_path.exists():
                captured_planning_task_artifact_obj = (
                    ChronicleService.capture_planning_artifact_snapshot(
                        db_session=db_session,
                        task_id=task_obj.id,
                        worktree_dir_path=worktree_dir_path,
                    )
                )
                if captured_planning_task_artifact_obj is not None:
                    return captured_planning_task_artifact_obj

        latest_planning_task_artifact_obj = ChronicleService._get_latest_task_artifact(
            db_session=db_session,
            task_id=task_obj.id,
            artifact_type=TaskArtifactType.PLANNING_WITH_FILES,
        )
        if latest_planning_task_artifact_obj is not None:
            return latest_planning_task_artifact_obj

        latest_planning_dev_log_item = None
        for dev_log_item in reversed(ordered_task_dev_log_list):
            if ChronicleService._PLANNING_WITH_FILES_PATTERN.search(
                dev_log_item.text_content
            ):
                latest_planning_dev_log_item = dev_log_item
                break

        if latest_planning_dev_log_item is None:
            return None

        extracted_file_manifest_list = (
            ChronicleService._extract_candidate_file_path_list(
                latest_planning_dev_log_item.text_content
            )
        )
        return ChronicleService._create_or_reuse_task_artifact_snapshot(
            db_session=db_session,
            task_id=task_obj.id,
            artifact_type=TaskArtifactType.PLANNING_WITH_FILES,
            source_path=f"dev_log:{latest_planning_dev_log_item.id}",
            content_markdown=latest_planning_dev_log_item.text_content,
            file_manifest_list=extracted_file_manifest_list,
        )

    @staticmethod
    def _resolve_planning_file_path_list(worktree_dir_path: Path) -> list[Path]:
        """解析当前任务可用的 planning 文件列表.

        Args:
            worktree_dir_path: 任务 worktree 根目录

        Returns:
            list[Path]: 已存在的 planning 文件路径列表
        """
        active_planning_file_path_list = [
            worktree_dir_path / relative_path
            for relative_path in ChronicleService._ACTIVE_PLANNING_RELATIVE_PATH_TUPLE
            if (worktree_dir_path / relative_path).is_file()
        ]
        if active_planning_file_path_list:
            return active_planning_file_path_list

        return [
            worktree_dir_path / relative_path
            for relative_path in ChronicleService._LEGACY_PLANNING_RELATIVE_PATH_TUPLE
            if (worktree_dir_path / relative_path).is_file()
        ]

    @staticmethod
    def _build_planning_artifact_payload(
        worktree_dir_path: Path,
        planning_file_path_list: list[Path],
    ) -> tuple[str, list[str], str]:
        """构建 planning 工件快照内容和文件清单.

        Args:
            worktree_dir_path: 任务 worktree 根目录
            planning_file_path_list: 已存在的 planning 文件列表

        Returns:
            tuple[str, list[str], str]: 快照正文、文件清单、来源路径
        """
        normalized_file_manifest_list: list[str] = []
        planning_content_section_list: list[str] = []

        for planning_file_path in planning_file_path_list:
            relative_planning_file_path = planning_file_path.relative_to(
                worktree_dir_path
            ).as_posix()
            planning_file_content_markdown = planning_file_path.read_text(
                encoding="utf-8"
            )
            normalized_file_manifest_list.append(relative_planning_file_path)
            planning_content_section_list.append(
                "\n".join(
                    [
                        f"## {relative_planning_file_path}",
                        "",
                        planning_file_content_markdown.strip(),
                    ]
                ).strip()
            )

        if not normalized_file_manifest_list:
            return "", [], str(worktree_dir_path)

        if normalized_file_manifest_list[0].startswith(".claude/planning/current/"):
            source_path = str(worktree_dir_path / ".claude/planning/current")
        else:
            source_path = str(worktree_dir_path)

        planning_content_markdown = "\n\n---\n\n".join(planning_content_section_list)
        return planning_content_markdown, normalized_file_manifest_list, source_path

    @staticmethod
    def _extract_candidate_file_path_list(raw_text_content: str) -> list[str]:
        """从 planning 文本中提取候选文件路径列表."""
        normalized_text_content = raw_text_content.strip()
        if not normalized_text_content:
            return []

        extracted_candidate_path_list: list[str] = []
        seen_path_text_set: set[str] = set()

        for (
            pattern_match
        ) in ChronicleService._CANDIDATE_PATH_IN_BACKTICKS_PATTERN.finditer(
            normalized_text_content
        ):
            raw_candidate_path_text = pattern_match.group(1).strip()
            if not ChronicleService._looks_like_path(raw_candidate_path_text):
                continue
            normalized_candidate_path_text = raw_candidate_path_text.replace("\\", "/")
            if normalized_candidate_path_text in seen_path_text_set:
                continue
            seen_path_text_set.add(normalized_candidate_path_text)
            extracted_candidate_path_list.append(normalized_candidate_path_text)

        for pattern_match in ChronicleService._CANDIDATE_PATH_IN_LIST_PATTERN.finditer(
            normalized_text_content
        ):
            raw_candidate_path_text = pattern_match.group(1).strip()
            if not ChronicleService._looks_like_path(raw_candidate_path_text):
                continue
            normalized_candidate_path_text = raw_candidate_path_text.replace("\\", "/")
            if normalized_candidate_path_text in seen_path_text_set:
                continue
            seen_path_text_set.add(normalized_candidate_path_text)
            extracted_candidate_path_list.append(normalized_candidate_path_text)

        return extracted_candidate_path_list[:50]

    @staticmethod
    def _looks_like_path(raw_candidate_path_text: str) -> bool:
        """判断文本是否看起来像文件路径."""
        if not raw_candidate_path_text:
            return False
        if " " in raw_candidate_path_text:
            return False
        return (
            "/" in raw_candidate_path_text
            or "\\" in raw_candidate_path_text
            or raw_candidate_path_text.startswith(".")
        )

    @staticmethod
    def capture_prd_artifact_snapshot(
        db_session: Session,
        task_id: str,
        worktree_dir_path: Path,
    ) -> TaskArtifact | None:
        """从任务 worktree 捕获并持久化 PRD 快照.

        Args:
            db_session: 数据库会话
            task_id: 任务 ID
            worktree_dir_path: 任务 worktree 根目录

        Returns:
            TaskArtifact | None: 新建或复用的 PRD 快照对象
        """
        task_obj = TaskService.get_task_by_id(db_session, task_id)
        if task_obj is None:
            return None
        if not worktree_dir_path.exists():
            return None

        prd_file_path = find_task_readable_prd_file_path(
            worktree_dir_path,
            task_id,
        )
        if prd_file_path is None:
            return None

        try:
            prd_content_markdown = prd_file_path.read_text(encoding="utf-8")
        except OSError:
            return None

        return ChronicleService._create_or_reuse_task_artifact_snapshot(
            db_session=db_session,
            task_id=task_id,
            artifact_type=TaskArtifactType.PRD,
            source_path=str(prd_file_path),
            content_markdown=prd_content_markdown,
            file_manifest_list=[],
        )

    @staticmethod
    def capture_planning_artifact_snapshot(
        db_session: Session,
        task_id: str,
        worktree_dir_path: Path,
    ) -> TaskArtifact | None:
        """从任务 worktree 捕获并持久化 planning with files 快照.

        优先读取 `.claude/planning/current/*.md`，若不存在则回退到旧的
        根目录 `task_plan.md` / `findings.md` / `progress.md`。

        Args:
            db_session: 数据库会话
            task_id: 任务 ID
            worktree_dir_path: 任务 worktree 根目录

        Returns:
            TaskArtifact | None: 新建或复用的 planning 快照对象
        """
        task_obj = TaskService.get_task_by_id(db_session, task_id)
        if task_obj is None:
            return None
        if not worktree_dir_path.exists():
            return None

        planning_file_path_list = ChronicleService._resolve_planning_file_path_list(
            worktree_dir_path
        )
        if not planning_file_path_list:
            return None

        try:
            (
                planning_content_markdown,
                planning_file_manifest_list,
                source_path,
            ) = ChronicleService._build_planning_artifact_payload(
                worktree_dir_path=worktree_dir_path,
                planning_file_path_list=planning_file_path_list,
            )
        except OSError:
            return None

        return ChronicleService._create_or_reuse_task_artifact_snapshot(
            db_session=db_session,
            task_id=task_id,
            artifact_type=TaskArtifactType.PLANNING_WITH_FILES,
            source_path=source_path,
            content_markdown=planning_content_markdown,
            file_manifest_list=planning_file_manifest_list,
        )

    @staticmethod
    def export_markdown(
        db_session: Session,
        run_account_id: str,
        task_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> str:
        """导出 Markdown 文档.

        Args:
            db_session: 数据库会话
            run_account_id: 运行账户 ID
            task_id: 按任务过滤（可选）
            start_date: 开始日期过滤（可选）
            end_date: 结束日期过滤（可选）

        Returns:
            str: Markdown 格式文档
        """
        if task_id:
            return ChronicleService._export_task_markdown(db_session, task_id)
        else:
            return ChronicleService._export_timeline_markdown(
                db_session, run_account_id, start_date, end_date
            )

    @staticmethod
    def _format_log_for_timeline(log: DevLog) -> dict[str, Any]:
        """格式化日志为时间线条目.

        Args:
            log: DevLog 对象

        Returns:
            dict[str, Any]: 格式化后的时间线数据
        """
        return {
            "id": log.id,
            "created_at": serialize_datetime_for_api(log.created_at),
            "text_content": log.text_content,
            "state_tag": log.state_tag.value,
            "state_icon": ChronicleService.STATE_TAG_ICONS.get(log.state_tag, ""),
            "task_id": log.task_id,
            "task_title": log.task.task_title if log.task else "",
            "has_media": log.media_original_image_path is not None,
            "media_original_path": log.media_original_image_path,
            "media_thumbnail_path": log.media_thumbnail_path,
            # Phase 2: AI fields
            "ai_processing_status": (
                log.ai_processing_status.value if log.ai_processing_status else None
            ),
            "ai_generated_title": log.ai_generated_title,
            "ai_analysis_text": log.ai_analysis_text,
            "ai_extracted_code": log.ai_extracted_code,
            "automation_session_id": log.automation_session_id,
            "automation_sequence_index": log.automation_sequence_index,
            "automation_phase_label": log.automation_phase_label,
            "automation_runner_kind": log.automation_runner_kind,
        }

    @staticmethod
    def _build_task_transcript_block_list(
        log_entry_list: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build task-level export blocks from contiguous raw log entries.

        Args:
            log_entry_list: Chronological task log entries.

        Returns:
            list[dict[str, Any]]: Raw-log blocks plus grouped automation transcript blocks.
        """
        transcript_block_list: list[dict[str, Any]] = []
        pending_transcript_log_list: list[dict[str, Any]] = []
        active_session_id_str: str | None = None

        def flush_pending_transcript_block() -> None:
            nonlocal active_session_id_str
            if not pending_transcript_log_list:
                return
            transcript_block_list.append(
                ChronicleService._build_automation_transcript_block(
                    pending_transcript_log_list
                )
            )
            pending_transcript_log_list.clear()
            active_session_id_str = None

        for log_entry in log_entry_list:
            log_session_id = log_entry.get("automation_session_id")
            if not log_session_id:
                flush_pending_transcript_block()
                transcript_block_list.append(
                    {
                        "kind": "log",
                        "log": log_entry,
                    }
                )
                continue

            if active_session_id_str is None or active_session_id_str != log_session_id:
                flush_pending_transcript_block()
                active_session_id_str = log_session_id

            pending_transcript_log_list.append(log_entry)

        flush_pending_transcript_block()
        return transcript_block_list

    @staticmethod
    def _build_automation_transcript_block(
        transcript_chunk_log_list: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Merge one contiguous automation transcript chunk sequence.

        Args:
            transcript_chunk_log_list: Contiguous log entries sharing one session ID.

        Returns:
            dict[str, Any]: Grouped transcript block metadata and merged text.
        """
        chronological_chunk_log_list = sorted(
            transcript_chunk_log_list,
            key=lambda log_entry: (log_entry["created_at"], log_entry["id"]),
        )
        ordered_chunk_log_list = sorted(
            transcript_chunk_log_list,
            key=lambda log_entry: (
                log_entry.get("automation_sequence_index") is None,
                log_entry.get("automation_sequence_index") or 0,
                log_entry["created_at"],
                log_entry["id"],
            ),
        )
        merged_text_content = "\n".join(
            log_entry["text_content"]
            for log_entry in ordered_chunk_log_list
            if log_entry.get("text_content")
        )
        first_chunk_log_entry = chronological_chunk_log_list[0]
        last_chunk_log_entry = chronological_chunk_log_list[-1]
        phase_label_str = next(
            (
                log_entry.get("automation_phase_label")
                for log_entry in ordered_chunk_log_list
                if log_entry.get("automation_phase_label")
            ),
            None,
        )
        runner_kind_str = next(
            (
                log_entry.get("automation_runner_kind")
                for log_entry in ordered_chunk_log_list
                if log_entry.get("automation_runner_kind")
            ),
            None,
        )

        return {
            "kind": "automation_transcript",
            "id": first_chunk_log_entry["id"],
            "task_id": first_chunk_log_entry["task_id"],
            "task_title": first_chunk_log_entry["task_title"],
            "automation_session_id": first_chunk_log_entry["automation_session_id"],
            "automation_phase_label": phase_label_str,
            "automation_runner_kind": runner_kind_str,
            "chunk_count": len(ordered_chunk_log_list),
            "start_created_at": first_chunk_log_entry["created_at"],
            "end_created_at": last_chunk_log_entry["created_at"],
            "text_content": merged_text_content,
        }

    @staticmethod
    def _export_task_markdown(db_session: Session, task_id: str) -> str:
        """导出单个任务的 Markdown.

        Args:
            db_session: 数据库会话
            task_id: 任务 ID

        Returns:
            str: Markdown 文档
        """
        chronicle_data = ChronicleService.get_task_chronicle(db_session, task_id)
        if not chronicle_data:
            return "# Error\n\nTask not found."

        task = chronicle_data["task"]
        transcript_block_list = chronicle_data["transcript_blocks"]
        logs = chronicle_data["logs"]

        lines: list[str] = [
            f"# {task['title']}",
            "",
            f"**Status:** {task['status']}",
            f"**Created:** {ChronicleService._format_markdown_datetime_label(task['created_at'])}",
            f"**Timezone:** {ChronicleService._get_markdown_timezone_note()}",
            f"**Total Logs:** {len(logs)}",
            "",
            "---",
            "",
        ]

        if task["closed_at"]:
            lines.insert(
                4,
                f"**Closed:** {ChronicleService._format_markdown_datetime_label(task['closed_at'])}",
            )

        for transcript_block in transcript_block_list:
            if transcript_block["kind"] == "automation_transcript":
                ChronicleService._append_automation_transcript_markdown_block(
                    lines,
                    transcript_block,
                )
                continue

            ChronicleService._append_single_log_markdown_block(
                lines,
                transcript_block["log"],
            )

        return "\n".join(lines)

    @staticmethod
    def _export_timeline_markdown(
        db_session: Session,
        run_account_id: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> str:
        """导出时间线的 Markdown.

        Args:
            db_session: 数据库会话
            run_account_id: 运行账户 ID
            start_date: 开始日期过滤（可选）
            end_date: 结束日期过滤（可选）

        Returns:
            str: Markdown 文档
        """
        timeline = ChronicleService.get_timeline(
            db_session, run_account_id, start_date, end_date
        )

        lines: list[str] = [
            "# Development Chronicle",
            "",
            f"**Period:** {ChronicleService._format_markdown_period(start_date, end_date)}",
            f"**Timezone:** {ChronicleService._get_markdown_timezone_note()}",
            f"**Total Logs:** {len(timeline)}",
            "",
            "---",
            "",
        ]

        # 按日期分组
        current_date: str | None = None
        for log in timeline:
            log_created_at = parse_iso_datetime_text(log["created_at"])
            log_date = format_date_in_app_timezone(log_created_at)
            if log_date != current_date:
                current_date = log_date
                lines.append(f"# {log_date}")
                lines.append("")

            timestamp = ChronicleService._format_markdown_time_label(log["created_at"])
            icon = ChronicleService.STATE_TAG_ICONS.get(
                DevLogStateTag(log["state_tag"]), ""
            )

            lines.append(f"## {icon} [{timestamp}] {log['task_title']}")
            lines.append("")

            if log["text_content"]:
                lines.append(log["text_content"])
                lines.append("")

            if log["has_media"] and log["media_original_path"]:
                lines.append(f"![Screenshot]({log['media_original_path']})")
                lines.append("")

            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _format_markdown_datetime_label(raw_datetime_text: str | None) -> str:
        """格式化 Markdown 用的完整时间标签.

        Args:
            raw_datetime_text: API 时间字符串

        Returns:
            str: 形如 `2026-03-19 08:36:23 UTC+08:00` 的标签
        """
        parsed_datetime = parse_iso_datetime_text(raw_datetime_text)
        if parsed_datetime is None:
            return "N/A"
        formatted_datetime = format_datetime_in_app_timezone(parsed_datetime)
        timezone_label = get_app_timezone_offset_label(parsed_datetime)
        return f"{formatted_datetime} {timezone_label}"

    @staticmethod
    def _format_markdown_time_label(raw_datetime_text: str | None) -> str:
        """格式化 Markdown 用的时间标签.

        Args:
            raw_datetime_text: API 时间字符串

        Returns:
            str: 形如 `08:36:23 UTC+08:00` 的标签
        """
        parsed_datetime = parse_iso_datetime_text(raw_datetime_text)
        if parsed_datetime is None:
            return "N/A"
        formatted_time = format_time_in_app_timezone(parsed_datetime)
        timezone_label = get_app_timezone_offset_label(parsed_datetime)
        return f"{formatted_time} {timezone_label}"

    @staticmethod
    def _format_markdown_period(
        start_date: datetime | None,
        end_date: datetime | None,
    ) -> str:
        """格式化导出文档中的时间区间.

        Args:
            start_date: 开始时间
            end_date: 结束时间

        Returns:
            str: 形如 `2026-03-18 - 2026-03-19` 的区间描述
        """
        start_label = (
            format_date_in_app_timezone(start_date) if start_date else "All time"
        )
        end_label = format_date_in_app_timezone(end_date) if end_date else "Now"
        return f"{start_label} - {end_label}"

    @staticmethod
    def _get_markdown_timezone_note() -> str:
        """返回 Markdown 导出的时区说明.

        Returns:
            str: 人类可读的时区说明
        """
        return get_app_timezone_display_label()

    @staticmethod
    def _format_markdown_datetime_range_label(
        start_datetime_text: str | None,
        end_datetime_text: str | None,
    ) -> str:
        """Format a task transcript time range for Markdown headings.

        Args:
            start_datetime_text: Transcript start time in API format.
            end_datetime_text: Transcript end time in API format.

        Returns:
            str: One timestamp or a start/end range label.
        """
        start_label = ChronicleService._format_markdown_datetime_label(
            start_datetime_text
        )
        end_label = ChronicleService._format_markdown_datetime_label(end_datetime_text)
        if start_label == end_label:
            return start_label
        return f"{start_label} - {end_label}"

    @staticmethod
    def _append_single_log_markdown_block(
        markdown_line_list: list[str],
        log_entry: dict[str, Any],
    ) -> None:
        """Append one raw task log block to the Markdown export.

        Args:
            markdown_line_list: Mutable Markdown line buffer.
            log_entry: One formatted task log entry.
        """
        timestamp = ChronicleService._format_markdown_datetime_label(
            log_entry["created_at"]
        )
        icon = ChronicleService.STATE_TAG_ICONS.get(
            DevLogStateTag(log_entry["state_tag"]), ""
        )

        markdown_line_list.append(f"## {icon} [{timestamp}] {log_entry['task_title']}")
        markdown_line_list.append("")

        if log_entry["text_content"]:
            markdown_line_list.append(log_entry["text_content"])
            markdown_line_list.append("")

        if log_entry["has_media"] and log_entry["media_original_path"]:
            markdown_line_list.append(
                f"![Screenshot]({log_entry['media_original_path']})"
            )
            markdown_line_list.append("")

        if log_entry["ai_generated_title"]:
            markdown_line_list.append(
                "> **AI Analysis:** " + log_entry["ai_generated_title"]
            )
            markdown_line_list.append("")
            if log_entry["ai_analysis_text"]:
                markdown_line_list.append(f"> {log_entry['ai_analysis_text']}")
                markdown_line_list.append("")

        markdown_line_list.append("---")
        markdown_line_list.append("")

    @staticmethod
    def _append_automation_transcript_markdown_block(
        markdown_line_list: list[str],
        transcript_block: dict[str, Any],
    ) -> None:
        """Append one grouped automation transcript block to the Markdown export.

        Args:
            markdown_line_list: Mutable Markdown line buffer.
            transcript_block: Grouped transcript metadata and merged body.
        """
        transcript_time_range_label = (
            ChronicleService._format_markdown_datetime_range_label(
                transcript_block.get("start_created_at"),
                transcript_block.get("end_created_at"),
            )
        )
        transcript_phase_label = transcript_block.get("automation_phase_label")
        transcript_heading_label = transcript_phase_label or "automation-transcript"
        metadata_part_list: list[str] = []
        if transcript_block.get("automation_runner_kind"):
            metadata_part_list.append(
                f"runner={transcript_block['automation_runner_kind']}"
            )
        metadata_part_list.append(f"chunks={transcript_block['chunk_count']}")

        markdown_line_list.append(
            f"## 🤖 [{transcript_time_range_label}] {transcript_heading_label}"
        )
        markdown_line_list.append("")
        markdown_line_list.append("> " + " · ".join(metadata_part_list))
        markdown_line_list.append("")
        if transcript_block.get("text_content"):
            markdown_line_list.append(transcript_block["text_content"])
            markdown_line_list.append("")
        markdown_line_list.append("---")
        markdown_line_list.append("")
