"""任务服务模块.

提供 Task 的 CRUD 操作、生命周期管理和工作流阶段推进功能.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from dsl.models.enums import TaskLifecycleStatus, WorkflowStage
from dsl.models.task import Task
from dsl.schemas.task_schema import (
    TaskCreateSchema,
    TaskStageUpdateSchema,
    TaskStatusUpdateSchema,
    TaskUpdateSchema,
)
from utils.logger import logger


class TaskService:
    """任务服务类.

    处理任务的创建、查询、状态更新和工作流阶段推进等业务逻辑.
    """

    @staticmethod
    def create_task(
        db_session: Session,
        task_create_schema: TaskCreateSchema,
        run_account_id: str,
    ) -> Task:
        """创建新任务，工作流阶段默认为 backlog.

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
            lifecycle_status=TaskLifecycleStatus.PENDING,
            workflow_stage=WorkflowStage.BACKLOG,
            project_id=task_create_schema.project_id,
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
            status: 按生命周期状态过滤（可选）

        Returns:
            list[Task]: 任务对象列表，按创建时间倒序排列
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
        """更新任务生命周期状态.

        Args:
            db_session: 数据库会话
            task_id: 任务 ID
            status_update: 状态更新数据

        Returns:
            Task | None: 更新后的任务对象或 None
        """
        task_obj = TaskService.get_task_by_id(db_session, task_id)
        if not task_obj:
            return None

        task_obj.lifecycle_status = status_update.lifecycle_status

        # 如果关闭任务，记录关闭时间并同步 workflow_stage
        if status_update.lifecycle_status == TaskLifecycleStatus.CLOSED:
            task_obj.closed_at = datetime.utcnow()
            task_obj.workflow_stage = WorkflowStage.DONE
        else:
            task_obj.closed_at = None

        db_session.commit()
        db_session.refresh(task_obj)

        logger.info(
            f"Updated Task {task_id[:8]}... status to {task_obj.lifecycle_status.value}"
        )
        return task_obj

    @staticmethod
    def update_workflow_stage(
        db_session: Session,
        task_id: str,
        stage_update: TaskStageUpdateSchema,
    ) -> Task | None:
        """更新任务工作流阶段.

        当阶段变更为 DONE 时，同步将 lifecycle_status 更新为 CLOSED.

        Args:
            db_session: 数据库会话
            task_id: 任务 ID
            stage_update: 阶段更新数据

        Returns:
            Task | None: 更新后的任务对象或 None
        """
        task_obj = TaskService.get_task_by_id(db_session, task_id)
        if not task_obj:
            return None

        previous_stage_value: str = task_obj.workflow_stage.value
        task_obj.workflow_stage = stage_update.workflow_stage

        # 阶段为 DONE 时同步关闭任务
        if stage_update.workflow_stage == WorkflowStage.DONE:
            task_obj.lifecycle_status = TaskLifecycleStatus.CLOSED
            task_obj.closed_at = datetime.utcnow()
        # 阶段非终态且任务处于 PENDING，推进为 OPEN
        elif task_obj.lifecycle_status == TaskLifecycleStatus.PENDING:
            task_obj.lifecycle_status = TaskLifecycleStatus.OPEN

        db_session.commit()
        db_session.refresh(task_obj)

        logger.info(
            f"Task {task_id[:8]}... stage: {previous_stage_value} → {task_obj.workflow_stage.value}"
        )
        return task_obj

    @staticmethod
    def start_task(
        db_session: Session,
        task_id: str,
    ) -> Task | None:
        """启动任务：创建 git worktree（若关联了 Project）并进入 PRD_GENERATING 阶段.

        Args:
            db_session: 数据库会话
            task_id: 任务 ID

        Returns:
            Task | None: 更新后的任务对象，若任务不存在则返回 None

        Raises:
            ValueError: 任务不在 BACKLOG 阶段，或 worktree 创建失败
        """
        import subprocess
        from pathlib import Path

        task_obj = TaskService.get_task_by_id(db_session, task_id)
        if not task_obj:
            return None

        if task_obj.workflow_stage != WorkflowStage.BACKLOG:
            raise ValueError(
                f"Task {task_id[:8]}... cannot start from stage "
                f"'{task_obj.workflow_stage.value}'. Only backlog tasks can be started."
            )

        task_obj.workflow_stage = WorkflowStage.PRD_GENERATING
        task_obj.lifecycle_status = TaskLifecycleStatus.OPEN

        # 若关联了 Project，立即创建 git worktree
        if task_obj.project_id and not task_obj.worktree_path:
            from dsl.models.project import Project

            project_obj = db_session.query(Project).filter(
                Project.id == task_obj.project_id
            ).first()

            if project_obj:
                repo_path_obj = Path(project_obj.repo_path)
                task_short_id_str = task_id[:8]
                branch_name_str = f"task/{task_short_id_str}"
                worktree_path_str = str(
                    repo_path_obj.parent / f"{repo_path_obj.name}-wt-{task_short_id_str}"
                )

                # 优先查找项目内的 worktree 创建脚本
                worktree_script_candidates = [
                    repo_path_obj / "scripts" / "new-worktree.sh",
                    repo_path_obj / "scripts" / "create-worktree.sh",
                    repo_path_obj / "new-worktree.sh",
                ]
                worktree_script_path = next(
                    (p for p in worktree_script_candidates if p.exists()), None
                )

                try:
                    if worktree_script_path:
                        subprocess.run(
                            [str(worktree_script_path), worktree_path_str, branch_name_str],
                            cwd=str(repo_path_obj),
                            check=True,
                            capture_output=True,
                        )
                    else:
                        subprocess.run(
                            ["git", "worktree", "add", worktree_path_str, "-b", branch_name_str],
                            cwd=str(repo_path_obj),
                            check=True,
                            capture_output=True,
                        )
                    task_obj.worktree_path = worktree_path_str
                    logger.info(
                        f"Task {task_id[:8]}... worktree created: {worktree_path_str} "
                        f"(branch: {branch_name_str})"
                    )
                except subprocess.CalledProcessError as git_error:
                    stderr_text = git_error.stderr.decode("utf-8", errors="replace").strip()
                    raise ValueError(
                        f"创建 git worktree 失败：{stderr_text}"
                    ) from git_error

        db_session.commit()
        db_session.refresh(task_obj)

        logger.info(f"Task {task_id[:8]}... started → prd_generating")
        return task_obj

    @staticmethod
    def execute_task(
        db_session: Session,
        task_id: str,
    ) -> Task | None:
        """触发任务进入执行阶段（implementation_in_progress），并预设 worktree_path.

        原子操作：
        1. 将 workflow_stage 更新为 IMPLEMENTATION_IN_PROGRESS
        2. 将 lifecycle_status 更新为 OPEN（若当前为 PENDING）
        3. 若任务关联了 Project，计算并预设 worktree_path

        Args:
            db_session: 数据库会话
            task_id: 任务 ID

        Returns:
            Task | None: 更新后的任务对象，若任务不存在则返回 None

        Raises:
            ValueError: 当任务当前阶段不允许执行时
        """
        from pathlib import Path

        task_obj = TaskService.get_task_by_id(db_session, task_id)
        if not task_obj:
            return None

        # 仅允许从 prd_waiting_confirmation 或 changes_requested 发起执行
        allowed_source_stages = {
            WorkflowStage.PRD_WAITING_CONFIRMATION,
            WorkflowStage.CHANGES_REQUESTED,
        }
        if task_obj.workflow_stage not in allowed_source_stages:
            raise ValueError(
                f"Task {task_id[:8]}... cannot execute from stage "
                f"'{task_obj.workflow_stage.value}'. "
                f"Allowed: {[s.value for s in allowed_source_stages]}"
            )

        task_obj.workflow_stage = WorkflowStage.IMPLEMENTATION_IN_PROGRESS
        task_obj.lifecycle_status = TaskLifecycleStatus.OPEN

        db_session.commit()
        db_session.refresh(task_obj)

        logger.info(
            f"Task {task_id[:8]}... execution started → implementation_in_progress"
            + (f", worktree={task_obj.worktree_path}" if task_obj.worktree_path else "")
        )
        return task_obj

    @staticmethod
    def update_task_title(
        db_session: Session,
        task_id: str,
        task_update_schema: TaskUpdateSchema,
    ) -> Task | None:
        """更新任务标题.

        Args:
            db_session: 数据库会话
            task_id: 任务 ID
            task_update_schema: 更新后的任务数据

        Returns:
            Task | None: 更新后的任务对象或 None
        """
        task_obj = TaskService.get_task_by_id(db_session, task_id)
        if not task_obj:
            return None

        task_obj.task_title = task_update_schema.task_title
        db_session.commit()
        db_session.refresh(task_obj)

        logger.info(f"Updated Task {task_id[:8]}... title to {task_obj.task_title}")
        return task_obj

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
