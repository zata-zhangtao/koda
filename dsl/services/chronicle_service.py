"""编年史服务模块.

提供 Timeline 视图、Task 视图和 Markdown 导出功能.
"""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from dsl.models.dev_log import DevLog
from dsl.models.enums import DevLogStateTag
from dsl.services.task_service import TaskService
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

    处理日志的时间线渲染、任务视图和 Markdown 导出.
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
