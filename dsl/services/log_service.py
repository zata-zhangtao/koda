"""日志服务模块.

提供 DevLog 的 CRUD 操作、状态转换和命令解析功能.
"""

from datetime import UTC, datetime
import re
from typing import TYPE_CHECKING

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from dsl.models.dev_log import DevLog
from dsl.models.enums import AIProcessingStatus, DevLogStateTag
from dsl.schemas.dev_log_schema import CommandParseResultSchema, DevLogCreateSchema
from utils.logger import logger

if TYPE_CHECKING:
    pass


class LogService:
    """日志服务类.

    处理 DevLog 的创建、查询、命令解析等业务逻辑.
    """

    # 命令映射表
    COMMAND_TO_STATE_TAG: dict[str, DevLogStateTag] = {
        "bug": DevLogStateTag.BUG,
        "fix": DevLogStateTag.FIXED,
        "opt": DevLogStateTag.OPTIMIZATION,
        "transfer": DevLogStateTag.TRANSFERRED,
    }

    @staticmethod
    def parse_command(input_text: str) -> CommandParseResultSchema:
        """解析用户输入的命令.

        支持的命令:
        - /bug <text>: 标记为 Bug
        - /fix <text>: 标记为已修复
        - /opt <text>: 标记为优化建议
        - /transfer <text>: 标记为已转移
        - /task <title>: 创建或切换任务

        Args:
            input_text: 用户输入的原始文本

        Returns:
            CommandParseResultSchema: 解析结果，包含命令类型、状态标记和内容

        Examples:
            >>> result = LogService.parse_command("/bug 发现了内存泄漏")
            >>> result.is_command
            True
            >>> result.state_tag
            <DevLogStateTag.BUG>
            >>> result.content
            "发现了内存泄漏"
        """
        stripped_input_text = input_text.strip()

        # 检查是否以 / 开头
        if not stripped_input_text.startswith("/"):
            return CommandParseResultSchema(
                is_command=False,
                content=stripped_input_text,
            )

        # 匹配命令格式: /<command> [content]
        command_pattern = r"^/([a-zA-Z]+)(?:\s+(.*))?$"
        command_match_result = re.match(command_pattern, stripped_input_text)

        if not command_match_result:
            return CommandParseResultSchema(
                is_command=False,
                content=stripped_input_text,
            )

        command_type_str = command_match_result.group(1).lower()
        content_after_command = (command_match_result.group(2) or "").strip()

        # 处理 task 命令
        if command_type_str == "task":
            return CommandParseResultSchema(
                is_command=True,
                command_type="task",
                content=content_after_command,
                task_title=content_after_command if content_after_command else None,
            )

        # 处理状态标记命令
        if command_type_str in LogService.COMMAND_TO_STATE_TAG:
            state_tag = LogService.COMMAND_TO_STATE_TAG[command_type_str]
            return CommandParseResultSchema(
                is_command=True,
                command_type=command_type_str,
                state_tag=state_tag,
                content=content_after_command,
            )

        # 未知命令，视为普通文本
        return CommandParseResultSchema(
            is_command=False,
            content=stripped_input_text,
        )

    @staticmethod
    def create_log(
        db_session: Session,
        log_create_schema: DevLogCreateSchema,
        run_account_id: str,
    ) -> DevLog:
        """创建新的开发日志.

        Args:
            db_session: 数据库会话
            log_create_schema: 日志创建数据
            run_account_id: 当前运行账户 ID

        Returns:
            DevLog: 新创建的日志对象

        Raises:
            ValueError: 当任务不存在时
        """
        from dsl.models.task import Task

        # 如果未指定 task_id，使用当前活跃账户的最新活跃任务
        task_id = log_create_schema.task_id
        if not task_id:
            latest_open_task: Task | None = (
                db_session.query(Task)
                .filter(
                    Task.run_account_id == run_account_id,
                    Task.lifecycle_status == "OPEN",
                )
                .order_by(Task.created_at.desc())
                .first()
            )
            if latest_open_task:
                task_id = latest_open_task.id
            else:
                raise ValueError("No active task found. Please create a task first.")

        # 验证任务存在
        task_exists = (
            db_session.query(Task).filter(Task.id == task_id).first() is not None
        )
        if not task_exists:
            raise ValueError(f"Task with id {task_id} not found")

        new_dev_log = DevLog(
            task_id=task_id,
            run_account_id=run_account_id,
            text_content=log_create_schema.text_content,
            state_tag=log_create_schema.state_tag,
            media_original_image_path=log_create_schema.media_original_image_path,
            media_thumbnail_path=log_create_schema.media_thumbnail_path,
        )

        db_session.add(new_dev_log)
        db_session.commit()
        db_session.refresh(new_dev_log)

        logger.info(
            f"Created DevLog: {new_dev_log.id[:8]}... with state {new_dev_log.state_tag.value}"
        )
        return new_dev_log

    @staticmethod
    def get_logs(
        db_session: Session,
        task_id: str | None = None,
        run_account_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
        created_after: datetime | None = None,
    ) -> list[DevLog]:
        """获取日志列表.

        Args:
            db_session: 数据库会话
            task_id: 按任务过滤（可选）
            run_account_id: 按运行账户过滤（可选）
            limit: 返回数量限制
            offset: 分页偏移量
            created_after: 仅返回该时间之后的新日志（可选）

        Returns:
            list[DevLog]: 日志对象列表
        """
        from dsl.models.task import Task

        query = db_session.query(DevLog).options(
            selectinload(DevLog.task).load_only(Task.id, Task.task_title)
        )

        if task_id:
            query = query.filter(DevLog.task_id == task_id)
        if run_account_id:
            query = query.filter(DevLog.run_account_id == run_account_id)
        if created_after is not None:
            normalized_created_after = (
                created_after.replace(tzinfo=None)
                if created_after.tzinfo is None
                else created_after.astimezone(UTC).replace(tzinfo=None)
            )
            query = query.filter(DevLog.created_at > normalized_created_after)

        ordered_query = (
            query.order_by(DevLog.created_at.asc())
            if created_after is not None
            else query.order_by(DevLog.created_at.desc())
        )

        return ordered_query.offset(offset).limit(limit).all()

    @staticmethod
    def get_log_by_id(db_session: Session, log_id: str) -> DevLog | None:
        """通过 ID 获取日志.

        Args:
            db_session: 数据库会话
            log_id: 日志 ID

        Returns:
            DevLog | None: 日志对象或 None
        """
        return db_session.query(DevLog).filter(DevLog.id == log_id).first()

    @staticmethod
    def get_review_queue(
        db_session: Session,
        run_account_id: str | None = None,
    ) -> list[DevLog]:
        """获取待校正的日志队列.

        Args:
            db_session: 数据库会话
            run_account_id: 按运行账户过滤（可选）

        Returns:
            list[DevLog]: 待校正的日志列表
        """
        query = db_session.query(DevLog).filter(
            DevLog.ai_processing_status == AIProcessingStatus.WAITING_REVIEW
        )

        if run_account_id:
            query = query.filter(DevLog.run_account_id == run_account_id)

        return query.order_by(DevLog.created_at.desc()).all()

    @staticmethod
    def update_ai_review(
        db_session: Session,
        log_id: str,
        action: str,
        ai_generated_title: str | None = None,
        ai_analysis_text: str | None = None,
        ai_extracted_code: str | None = None,
    ) -> DevLog | None:
        """更新 AI 校正结果.

        Args:
            db_session: 数据库会话
            log_id: 日志 ID
            action: 操作类型 (accept, edit)
            ai_generated_title: 编辑后的标题（edit 操作）
            ai_analysis_text: 编辑后的分析文本（edit 操作）
            ai_extracted_code: 编辑后的代码块（edit 操作）

        Returns:
            DevLog | None: 更新后的日志对象或 None
        """
        dev_log = LogService.get_log_by_id(db_session, log_id)
        if not dev_log:
            return None

        if action in ("accept", "edit"):
            dev_log.ai_processing_status = AIProcessingStatus.CONFIRMED

            if action == "edit":
                if ai_generated_title is not None:
                    dev_log.ai_generated_title = ai_generated_title
                if ai_analysis_text is not None:
                    dev_log.ai_analysis_text = ai_analysis_text
                if ai_extracted_code is not None:
                    dev_log.ai_extracted_code = ai_extracted_code

            db_session.commit()
            db_session.refresh(dev_log)
            logger.info(f"Updated AI review for DevLog: {log_id[:8]}...")

        return dev_log

    @staticmethod
    def count_logs_by_state(
        db_session: Session,
        task_id: str,
        state_tag: DevLogStateTag,
    ) -> int:
        """统计任务中指定状态的日志数量.

        Args:
            db_session: 数据库会话
            task_id: 任务 ID
            state_tag: 状态标记

        Returns:
            int: 日志数量
        """
        return (
            db_session.query(func.count(DevLog.id))
            .filter(
                DevLog.task_id == task_id,
                DevLog.state_tag == state_tag,
            )
            .scalar()
            or 0
        )
