"""任务服务模块.

提供 Task 的 CRUD 操作和生命周期管理功能.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from dsl.models.enums import TaskLifecycleStatus
from dsl.models.task import Task
from dsl.schemas.task_schema import TaskCreateSchema, TaskStatusUpdateSchema
from utils.logger import logger


class TaskService:
    """任务服务类.

    处理任务的创建、查询、状态更新等业务逻辑.
    """

    @staticmethod
    def create_task(
        db_session: Session,
        task_create_schema: TaskCreateSchema,
        run_account_id: str,
    ) -> Task:
        """创建新任务.

        Args:
            db_session: 数据库会话
            task_create_schema: 任务创建数据
            run_account_id: 当前运行账户 ID

        Returns:
            Task: 新创建的任务对象
        """
        new_task = Task(
            run_account_id=run_account_id,
            task_title=task_create_schema.task_title,
            lifecycle_status=TaskLifecycleStatus.OPEN,
        )

        db_session.add(new_task)
        db_session.commit()
        db_session.refresh(new_task)

        logger.info(f"Created Task: {new_task.id[:8]}... - {new_task.task_title}")
        return new_task

    @staticmethod
    def get_tasks(
        db_session: Session,
        run_account_id: str,
        status: TaskLifecycleStatus | None = None,
    ) -> list[Task]:
        """获取任务列表.

        Args:
            db_session: 数据库会话
            run_account_id: 运行账户 ID
            status: 按状态过滤（可选）

        Returns:
            list[Task]: 任务对象列表
        """
        query = db_session.query(Task).filter(Task.run_account_id == run_account_id)

        if status:
            query = query.filter(Task.lifecycle_status == status)

        return query.order_by(Task.created_at.desc()).all()

    @staticmethod
    def get_task_by_id(db_session: Session, task_id: str) -> Task | None:
        """通过 ID 获取任务.

        Args:
            db_session: 数据库会话
            task_id: 任务 ID

        Returns:
            Task | None: 任务对象或 None
        """
        return db_session.query(Task).filter(Task.id == task_id).first()

    @staticmethod
    def update_task_status(
        db_session: Session,
        task_id: str,
        status_update: TaskStatusUpdateSchema,
    ) -> Task | None:
        """更新任务状态.

        Args:
            db_session: 数据库会话
            task_id: 任务 ID
            status_update: 状态更新数据

        Returns:
            Task | None: 更新后的任务对象或 None
        """
        task = TaskService.get_task_by_id(db_session, task_id)
        if not task:
            return None

        task.lifecycle_status = status_update.lifecycle_status

        # 如果关闭任务，记录关闭时间
        if status_update.lifecycle_status == TaskLifecycleStatus.CLOSED:
            task.closed_at = datetime.utcnow()
        else:
            task.closed_at = None

        db_session.commit()
        db_session.refresh(task)

        logger.info(f"Updated Task {task_id[:8]}... status to {task.lifecycle_status.value}")
        return task

    @staticmethod
    def get_active_task(db_session: Session, run_account_id: str) -> Task | None:
        """获取当前活跃任务（最新的 OPEN 状态任务）.

        Args:
            db_session: 数据库会话
            run_account_id: 运行账户 ID

        Returns:
            Task | None: 活跃任务或 None
        """
        return (
            db_session.query(Task)
            .filter(
                Task.run_account_id == run_account_id,
                Task.lifecycle_status == TaskLifecycleStatus.OPEN,
            )
            .order_by(Task.created_at.desc())
            .first()
        )
