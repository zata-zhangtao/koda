"""任务服务模块.

提供 Task 的 CRUD 操作、生命周期管理和工作流阶段推进功能.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.dsl.models.dev_log import DevLog
from backend.dsl.models.enums import TaskLifecycleStatus, WorkflowStage
from backend.dsl.models.task import Task
from backend.dsl.schemas.task_schema import (
    TaskBranchHealthSchema,
    TaskCreateSchema,
    TaskStageUpdateSchema,
    TaskStatusUpdateSchema,
    TaskUpdateSchema,
)
from utils.helpers import utc_now_naive
from utils.logger import logger

if TYPE_CHECKING:
    from backend.dsl.models.project import Project


class TaskService:
    """任务服务类.

    处理任务的创建、查询、状态更新和工作流阶段推进等业务逻辑.
    """

    @staticmethod
    def _select_display_task_branch_name(
        canonical_task_branch_name_str: str,
        matching_task_branch_name_list: list[str],
    ) -> str:
        """Select the branch name that should be shown in branch-health UI.

        Args:
            canonical_task_branch_name_str: Legacy canonical branch name
            matching_task_branch_name_list: All locally matched branch names

        Returns:
            str: Preferred branch name for display and messaging
        """
        if canonical_task_branch_name_str in matching_task_branch_name_list:
            return canonical_task_branch_name_str

        sorted_matching_task_branch_name_list = sorted(
            matching_task_branch_name_list,
            key=lambda branch_name_str: (len(branch_name_str), branch_name_str),
        )
        return sorted_matching_task_branch_name_list[0]

    @staticmethod
    def _clear_business_sync_restore_markers(task_obj: Task) -> None:
        """Clear snapshot-only restore markers once local execution resumes.

        Args:
            task_obj: 待清理标记的任务对象
        """
        task_obj.business_sync_original_workflow_stage = None
        task_obj.business_sync_original_lifecycle_status = None
        task_obj.business_sync_restored_at = None

    @staticmethod
    def _ensure_task_worktree_if_needed(
        db_session: Session,
        task_obj: Task,
    ) -> None:
        """为关联项目的任务创建或复用 worktree.

        Args:
            db_session: 数据库会话
            task_obj: 待检查的任务对象

        Raises:
            ValueError: 当关联仓库路径无效或 worktree 创建失败时
        """
        if not task_obj.project_id or task_obj.worktree_path:
            return

        from pathlib import Path

        from backend.dsl.models.project import Project
        from backend.dsl.services.project_service import ProjectService

        project_obj = (
            db_session.query(Project).filter(Project.id == task_obj.project_id).first()
        )
        if project_obj is None:
            return

        repo_path_obj = Path(project_obj.repo_path)
        project_consistency_snapshot = (
            ProjectService.build_project_consistency_snapshot(project_obj)
        )
        if not repo_path_obj.exists():
            raise ValueError(
                "关联项目的仓库路径在当前机器上不存在："
                f"{repo_path_obj}。请先更新项目路径。"
            )
        if not (repo_path_obj / ".git").exists():
            raise ValueError(
                "关联项目的仓库路径不是有效 Git 仓库："
                f"{repo_path_obj}。请先更新项目路径。"
            )
        if project_consistency_snapshot.is_repo_remote_consistent is False:
            raise ValueError(
                "关联项目当前绑定到错误的代码仓库。"
                "请先把项目重绑到与已同步指纹一致的 Git remote。"
            )

        from backend.dsl.services.git_worktree_service import GitWorktreeService
        from backend.dsl.services.worktree_branch_naming_service import (
            WorktreeBranchNamingService,
        )

        recent_log_row_list: list[tuple[str]] = (
            db_session.query(DevLog.text_content)
            .filter(DevLog.task_id == task_obj.id)
            .order_by(DevLog.created_at.desc())
            .limit(3)
            .all()
        )
        recent_log_text_list = [
            recent_log_text_str
            for (recent_log_text_str,) in recent_log_row_list
            if recent_log_text_str
        ]
        branch_naming_result_obj = (
            WorktreeBranchNamingService.build_task_branch_naming_result(
                task_id_str=task_obj.id,
                task_title_str=task_obj.task_title,
                requirement_brief_str=task_obj.requirement_brief,
                recent_context_text_list=recent_log_text_list,
            )
        )
        created_worktree_path = GitWorktreeService.create_task_worktree(
            repo_root_path=repo_path_obj,
            task_id=task_obj.id,
            task_branch_name_str=branch_naming_result_obj.branch_name_str,
        )
        task_obj.worktree_path = str(created_worktree_path)
        logger.info(
            f"Task {task_obj.id[:8]}... worktree created: {created_worktree_path} "
            f"(branch: {branch_naming_result_obj.branch_name_str}, "
            f"branch_naming_source: {branch_naming_result_obj.naming_source_str})"
        )

    @staticmethod
    def _build_project_map_for_task_list(
        db_session: Session,
        task_list: list[Task],
    ) -> dict[str, "Project"]:
        """Build a `project_id -> Project` lookup table for the provided tasks.

        Args:
            db_session: 数据库会话
            task_list: 任务列表

        Returns:
            dict[str, Project]: 项目映射表
        """
        project_id_list = sorted(
            {
                task_item.project_id
                for task_item in task_list
                if task_item.project_id is not None
            }
        )
        if not project_id_list:
            return {}

        from backend.dsl.models.project import Project

        project_obj_list = (
            db_session.query(Project).filter(Project.id.in_(project_id_list)).all()
        )
        return {project_obj.id: project_obj for project_obj in project_obj_list}

    @staticmethod
    def _resolve_branch_probe_working_tree_path(
        task_obj: Task,
        linked_project_obj: "Project | None",
    ) -> Path | None:
        """Resolve the best local Git working tree for branch-health probing.

        Args:
            task_obj: 任务对象
            linked_project_obj: 当前任务关联的项目对象（可选）

        Returns:
            Path | None: 可用于执行 Git 分支探针的工作树路径；无法定位时返回 None
        """
        from backend.dsl.services.git_worktree_service import GitWorktreeService

        candidate_working_tree_path_list: list[Path] = []
        if task_obj.worktree_path:
            candidate_working_tree_path_list.append(
                Path(task_obj.worktree_path).expanduser()
            )
        if linked_project_obj is not None:
            candidate_working_tree_path_list.append(
                Path(linked_project_obj.repo_path).expanduser()
            )

        for candidate_working_tree_path in candidate_working_tree_path_list:
            resolved_working_tree_path = (
                GitWorktreeService.resolve_git_working_tree_path(
                    candidate_working_tree_path
                )
            )
            if resolved_working_tree_path is not None:
                return resolved_working_tree_path

        return None

    @staticmethod
    def _has_task_entered_worktree_backed_git_flow(task_obj: Task) -> bool:
        """Return whether the task has durable evidence of entering Git flow.

        Args:
            task_obj: 任务对象

        Returns:
            bool: 是否已经持久化过任务 worktree 路径
        """
        return bool(task_obj.worktree_path)

    @staticmethod
    def build_task_branch_health(
        task_obj: Task,
        linked_project_obj: "Project | None" = None,
    ) -> TaskBranchHealthSchema:
        """Build the derived branch-health snapshot for one task.

        Args:
            task_obj: 任务对象
            linked_project_obj: 当前任务关联的项目对象（可选）

        Returns:
            TaskBranchHealthSchema: 分支健康快照
        """
        from backend.dsl.services.git_worktree_service import GitWorktreeService

        resolved_linked_project_obj = linked_project_obj or task_obj.project
        canonical_task_branch_name_str = GitWorktreeService.build_task_branch_name(
            task_obj.id
        )
        expected_branch_name_str = canonical_task_branch_name_str
        has_entered_worktree_backed_git_flow_bool = (
            TaskService._has_task_entered_worktree_backed_git_flow(task_obj)
        )
        task_worktree_exists_bool = False
        if task_obj.worktree_path:
            task_worktree_exists_bool = (
                Path(task_obj.worktree_path).expanduser().exists()
            )

        branch_probe_working_tree_path = (
            TaskService._resolve_branch_probe_working_tree_path(
                task_obj=task_obj,
                linked_project_obj=resolved_linked_project_obj,
            )
        )
        branch_exists_bool: bool | None = None
        branch_status_message_str: str | None = None

        if branch_probe_working_tree_path is None:
            if not task_obj.project_id and not task_obj.worktree_path:
                branch_status_message_str = (
                    "当前任务未关联本地 Git 项目，无法检查任务分支状态。"
                )
            elif task_obj.worktree_path and not task_worktree_exists_bool:
                branch_status_message_str = "任务 worktree 目录已经不存在，且当前无法定位可回退的项目仓库来检查分支。"
            else:
                branch_status_message_str = "当前无法定位可检查的本地 Git 仓库。"
        else:
            matching_task_branch_name_list = (
                GitWorktreeService.list_local_task_branch_names(
                    branch_probe_working_tree_path,
                    task_obj.id,
                )
            )
            if matching_task_branch_name_list is None:
                branch_exists_bool = None
            else:
                branch_exists_bool = bool(matching_task_branch_name_list)
                if matching_task_branch_name_list:
                    expected_branch_name_str = (
                        TaskService._select_display_task_branch_name(
                            canonical_task_branch_name_str,
                            matching_task_branch_name_list,
                        )
                    )
            if branch_exists_bool is None:
                branch_exists_bool = GitWorktreeService.check_local_branch_exists(
                    branch_probe_working_tree_path,
                    canonical_task_branch_name_str,
                )
            if branch_exists_bool is True:
                branch_status_message_str = f"检测到本地任务分支 `{expected_branch_name_str}` 仍存在，可继续使用标准 Git Complete 流程。"
            elif branch_exists_bool is False:
                if has_entered_worktree_backed_git_flow_bool:
                    branch_status_message_str = (
                        f"检测到本地任务分支 `{expected_branch_name_str}` 不存在。"
                        "请先检查时间线与代码状态，再人工确认是否完成。"
                    )
                else:
                    branch_status_message_str = (
                        f"检测到本地任务分支 `{expected_branch_name_str}` 不存在，"
                        "但该任务尚未进入 worktree-backed Git 流程，因此不会解锁人工完成。"
                    )
            else:
                branch_status_message_str = (
                    f"无法确认本地任务分支 `{expected_branch_name_str}` 是否存在。"
                )

        manual_completion_candidate_bool = (
            has_entered_worktree_backed_git_flow_bool
            and task_obj.lifecycle_status
            not in {
                TaskLifecycleStatus.CLOSED,
                TaskLifecycleStatus.DELETED,
            }
            and branch_exists_bool is False
        )

        return TaskBranchHealthSchema(
            expected_branch_name=expected_branch_name_str,
            branch_exists=branch_exists_bool,
            worktree_exists=task_worktree_exists_bool,
            manual_completion_candidate=manual_completion_candidate_bool,
            status_message=branch_status_message_str,
        )

    @staticmethod
    def build_task_branch_health_map(
        db_session: Session,
        task_list: list[Task],
    ) -> dict[str, TaskBranchHealthSchema]:
        """Build branch-health snapshots for multiple tasks.

        Args:
            db_session: 数据库会话
            task_list: 任务列表

        Returns:
            dict[str, TaskBranchHealthSchema]: `task_id -> branch health` 映射
        """
        linked_project_obj_by_id = TaskService._build_project_map_for_task_list(
            db_session,
            task_list,
        )
        return {
            task_obj.id: TaskService.build_task_branch_health(
                task_obj=task_obj,
                linked_project_obj=linked_project_obj_by_id.get(
                    task_obj.project_id or ""
                ),
            )
            for task_obj in task_list
        }

    @staticmethod
    def validate_manual_completion_candidate(
        task_obj: Task,
        task_branch_health: TaskBranchHealthSchema,
    ) -> None:
        """Validate that a task can use the missing-branch manual-complete path.

        Args:
            task_obj: 任务对象
            task_branch_health: 当前任务的分支健康快照

        Raises:
            ValueError: 当任务生命周期不允许或当前并非缺失分支候选态
        """
        if task_obj.lifecycle_status in {
            TaskLifecycleStatus.CLOSED,
            TaskLifecycleStatus.DELETED,
        }:
            raise ValueError(
                f"Task {task_obj.id[:8]}... cannot manual-complete from lifecycle "
                f"'{task_obj.lifecycle_status.value}'."
            )

        if task_branch_health.manual_completion_candidate:
            return

        if not TaskService._has_task_entered_worktree_backed_git_flow(task_obj):
            raise ValueError(
                "Task has not entered the worktree-backed Git flow yet. Manual "
                "completion is only available after the task worktree/branch has "
                "previously been created."
            )

        if task_branch_health.branch_exists is True:
            raise ValueError(
                "Task branch still exists. Use the normal /complete flow instead of "
                "manual completion."
            )

        raise ValueError(
            "Task is not eligible for manual completion because the missing-branch "
            "candidate state could not be confirmed."
        )

    @staticmethod
    def _apply_workflow_stage_transition(
        task_obj: Task,
        next_workflow_stage: WorkflowStage,
    ) -> None:
        """将任务切换到目标阶段，并维护阶段进入时间.

        Args:
            task_obj: 待更新的任务对象
            next_workflow_stage: 目标工作流阶段
        """
        if (
            task_obj.workflow_stage != next_workflow_stage
            or task_obj.stage_updated_at is None
        ):
            task_obj.stage_updated_at = utc_now_naive()
        task_obj.workflow_stage = next_workflow_stage

    @staticmethod
    def can_rebind_project(task_obj: Task) -> bool:
        """判断任务是否仍允许改绑项目.

        Args:
            task_obj: 待判断的任务对象

        Returns:
            bool: 仅当任务仍在 backlog 且尚未创建 worktree 时返回 True
        """
        if task_obj.lifecycle_status in {
            TaskLifecycleStatus.CLOSED,
            TaskLifecycleStatus.DELETED,
        }:
            return False

        if (
            task_obj.workflow_stage == WorkflowStage.BACKLOG
            and not task_obj.worktree_path
        ):
            return True

        return bool(task_obj.business_sync_restored_at) and not task_obj.worktree_path

    @staticmethod
    def has_task_started(task_obj: Task) -> bool:
        """判断任务是否已经进入受控启动态.

        Args:
            task_obj: 待判断的任务对象

        Returns:
            bool: 当任务已离开 backlog 或已经生成 worktree 时返回 True
        """
        return task_obj.workflow_stage != WorkflowStage.BACKLOG or bool(
            task_obj.worktree_path
        )

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

        Raises:
            ValueError: 当关联的 Project 不存在时
        """
        normalized_project_id: str | None = None
        if task_create_schema.project_id:
            from backend.dsl.services.project_service import ProjectService

            linked_project_obj = ProjectService.get_project_by_id(
                db_session,
                task_create_schema.project_id,
            )
            if linked_project_obj is None:
                raise ValueError(
                    f"Project with id {task_create_schema.project_id} not found"
                )
            normalized_project_id = linked_project_obj.id

        new_task = Task(
            run_account_id=run_account_id,
            task_title=task_create_schema.task_title,
            lifecycle_status=TaskLifecycleStatus.PENDING,
            workflow_stage=WorkflowStage.BACKLOG,
            stage_updated_at=utc_now_naive(),
            project_id=normalized_project_id,
            requirement_brief=task_create_schema.requirement_brief,
            auto_confirm_prd_and_execute=(
                task_create_schema.auto_confirm_prd_and_execute
            ),
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
        project_id: str | None = None,
        unlinked_only: bool = False,
    ) -> list[Task]:
        """获取任务列表.

        Args:
            db_session: 数据库会话
            run_account_id: 运行账户 ID
            status: 按生命周期状态过滤（可选）
            project_id: 按关联项目 ID 过滤（可选）
            unlinked_only: 是否只返回未关联项目的任务

        Returns:
            list[Task]: 任务对象列表，按创建时间倒序排列
        """
        query = db_session.query(Task).filter(Task.run_account_id == run_account_id)

        if status:
            query = query.filter(Task.lifecycle_status == status)

        if project_id is not None:
            query = query.filter(Task.project_id == project_id)
        elif unlinked_only:
            query = query.filter(Task.project_id.is_(None))

        return query.order_by(Task.created_at.desc()).all()

    @staticmethod
    def get_task_log_count_map(
        db_session: Session,
        task_id_list: list[str],
    ) -> dict[str, int]:
        """Build log counts for tasks in one aggregate query.

        Args:
            db_session: 数据库会话
            task_id_list: 需要统计日志数量的任务 ID 列表

        Returns:
            dict[str, int]: `task_id -> log_count` 映射
        """
        if not task_id_list:
            return {}

        aggregated_count_row_list: list[tuple[str, int]] = (
            db_session.query(
                DevLog.task_id,
                func.count(DevLog.id),
            )
            .filter(DevLog.task_id.in_(task_id_list))
            .group_by(DevLog.task_id)
            .all()
        )

        return {
            task_id_str: int(log_count_int)
            for task_id_str, log_count_int in aggregated_count_row_list
        }

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

        Raises:
            ValueError: 当 started task 试图通过旧状态接口直接删除时抛出
        """
        task_obj = TaskService.get_task_by_id(db_session, task_id)
        if not task_obj:
            return None

        if (
            status_update.lifecycle_status == TaskLifecycleStatus.DELETED
            and TaskService.has_task_started(task_obj)
        ):
            raise ValueError(
                "Started tasks must use the destroy flow. "
                "Direct status deletion is only available for backlog tasks."
            )

        task_obj.lifecycle_status = status_update.lifecycle_status

        # 如果关闭任务，记录关闭时间并同步 workflow_stage
        if status_update.lifecycle_status == TaskLifecycleStatus.CLOSED:
            task_obj.closed_at = utc_now_naive()
            TaskService._apply_workflow_stage_transition(task_obj, WorkflowStage.DONE)
        elif status_update.lifecycle_status == TaskLifecycleStatus.DELETED:
            task_obj.closed_at = None
            task_obj.destroy_reason = None
            if task_obj.destroyed_at is None:
                task_obj.destroyed_at = utc_now_naive()
        elif status_update.lifecycle_status == TaskLifecycleStatus.ABANDONED:
            task_obj.closed_at = utc_now_naive()
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
        TaskService._apply_workflow_stage_transition(
            task_obj,
            stage_update.workflow_stage,
        )

        # 阶段为 DONE 时同步关闭任务
        if stage_update.workflow_stage == WorkflowStage.DONE:
            task_obj.lifecycle_status = TaskLifecycleStatus.CLOSED
            task_obj.closed_at = utc_now_naive()
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
        task_obj = TaskService.get_task_by_id(db_session, task_id)
        if not task_obj:
            return None

        allowed_start_stages = {WorkflowStage.BACKLOG, WorkflowStage.PRD_GENERATING}
        if task_obj.workflow_stage not in allowed_start_stages:
            raise ValueError(
                f"Task {task_id[:8]}... cannot start from stage "
                f"'{task_obj.workflow_stage.value}'. Only backlog or prd_generating tasks can be restarted."
            )

        TaskService._apply_workflow_stage_transition(
            task_obj,
            WorkflowStage.PRD_GENERATING,
        )
        task_obj.lifecycle_status = TaskLifecycleStatus.OPEN
        TaskService._clear_business_sync_restore_markers(task_obj)

        TaskService._ensure_task_worktree_if_needed(db_session, task_obj)

        db_session.commit()
        db_session.refresh(task_obj)

        logger.info(f"Task {task_id[:8]}... started → prd_generating")
        return task_obj

    @staticmethod
    def request_prd_regeneration(
        db_session: Session,
        task_id: str,
    ) -> Task | None:
        """将任务重新推进到 PRD_GENERATING 阶段.

        该接口用于在任务已存在 PRD 或需求被修改后，重新生成新的 PRD 草案。
        只要任务尚未关闭或删除，就允许回到 PRD 生成阶段；若缺少 worktree，
        会按当前项目绑定关系自动创建或复用。

        Args:
            db_session: 数据库会话
            task_id: 任务 ID

        Returns:
            Task | None: 更新后的任务对象；若任务不存在则返回 None

        Raises:
            ValueError: 当任务已经关闭/删除，或 worktree 创建失败时
        """
        task_obj = TaskService.get_task_by_id(db_session, task_id)
        if not task_obj:
            return None

        if task_obj.lifecycle_status in {
            TaskLifecycleStatus.CLOSED,
            TaskLifecycleStatus.DELETED,
            TaskLifecycleStatus.ABANDONED,
        }:
            raise ValueError(
                f"Task {task_id[:8]}... cannot regenerate PRD from lifecycle "
                f"'{task_obj.lifecycle_status.value}'."
            )

        if task_obj.workflow_stage == WorkflowStage.DONE:
            raise ValueError(
                f"Task {task_id[:8]}... cannot regenerate PRD from stage 'done'."
            )

        task_obj.workflow_stage = WorkflowStage.PRD_GENERATING
        task_obj.lifecycle_status = TaskLifecycleStatus.OPEN
        TaskService._clear_business_sync_restore_markers(task_obj)

        TaskService._ensure_task_worktree_if_needed(db_session, task_obj)

        db_session.commit()
        db_session.refresh(task_obj)

        logger.info(
            f"Task {task_id[:8]}... PRD regeneration requested → prd_generating"
        )
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

        TaskService._apply_workflow_stage_transition(
            task_obj,
            WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
        )
        task_obj.lifecycle_status = TaskLifecycleStatus.OPEN
        TaskService._clear_business_sync_restore_markers(task_obj)
        TaskService._ensure_task_worktree_if_needed(db_session, task_obj)

        db_session.commit()
        db_session.refresh(task_obj)

        logger.info(
            f"Task {task_id[:8]}... execution started → implementation_in_progress"
            + (f", worktree={task_obj.worktree_path}" if task_obj.worktree_path else "")
        )
        return task_obj

    @staticmethod
    def prepare_task_resume(
        db_session: Session,
        task_id: str,
    ) -> Task | None:
        """Validate that a task can resume interrupted background automation.

        Args:
            db_session: 数据库会话
            task_id: 任务 ID

        Returns:
            Task | None: 当前任务对象；若任务不存在则返回 None

        Raises:
            ValueError: 当任务阶段或生命周期不允许恢复时
        """

        task_obj = TaskService.get_task_by_id(db_session, task_id)
        if not task_obj:
            return None

        if task_obj.lifecycle_status in {
            TaskLifecycleStatus.CLOSED,
            TaskLifecycleStatus.DELETED,
            TaskLifecycleStatus.ABANDONED,
        }:
            raise ValueError(
                f"Task {task_id[:8]}... cannot resume from lifecycle "
                f"'{task_obj.lifecycle_status.value}'."
            )

        resumable_stage_set = {
            WorkflowStage.PRD_GENERATING,
            WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
            WorkflowStage.SELF_REVIEW_IN_PROGRESS,
            WorkflowStage.TEST_IN_PROGRESS,
            WorkflowStage.PR_PREPARING,
        }
        if task_obj.workflow_stage not in resumable_stage_set:
            raise ValueError(
                f"Task {task_id[:8]}... cannot resume from stage "
                f"'{task_obj.workflow_stage.value}'. "
                f"Allowed: {[stage.value for stage in resumable_stage_set]}"
            )

        if (
            task_obj.workflow_stage == WorkflowStage.PR_PREPARING
            and not task_obj.worktree_path
        ):
            raise ValueError(
                f"Task {task_id[:8]}... cannot resume completion without worktree_path."
            )

        logger.info(
            "Task %s... resume prepared from stage %s",
            task_id[:8],
            task_obj.workflow_stage.value,
        )
        return task_obj

    @staticmethod
    def prepare_task_review(
        db_session: Session,
        task_id: str,
    ) -> Task | None:
        """Validate that a task can run standalone review-only automation.

        Args:
            db_session: 数据库会话
            task_id: 任务 ID

        Returns:
            Task | None: 当前任务对象；若任务不存在则返回 None

        Raises:
            ValueError: 当任务生命周期不允许评审时
        """
        task_obj = TaskService.get_task_by_id(db_session, task_id)
        if not task_obj:
            return None

        if task_obj.lifecycle_status in {
            TaskLifecycleStatus.CLOSED,
            TaskLifecycleStatus.DELETED,
            TaskLifecycleStatus.ABANDONED,
        }:
            raise ValueError(
                f"Task {task_id[:8]}... cannot run review from lifecycle "
                f"'{task_obj.lifecycle_status.value}'."
            )

        logger.info(
            "Task %s... standalone review prepared from stage %s",
            task_id[:8],
            task_obj.workflow_stage.value,
        )
        return task_obj

    @staticmethod
    def update_task(
        db_session: Session,
        task_id: str,
        task_update_schema: TaskUpdateSchema,
    ) -> Task | None:
        """更新任务内容.

        Args:
            db_session: 数据库会话
            task_id: 任务 ID
            task_update_schema: 更新后的任务数据

        Returns:
            Task | None: 更新后的任务对象或 None

        Raises:
            ValueError: 当目标项目不存在，或项目绑定已锁定时抛出
        """
        task_obj = TaskService.get_task_by_id(db_session, task_id)
        if not task_obj:
            return None

        task_obj.task_title = task_update_schema.task_title
        if task_update_schema.requirement_brief is not None:
            task_obj.requirement_brief = task_update_schema.requirement_brief

        if "project_id" in task_update_schema.model_fields_set:
            normalized_next_project_id: str | None = None
            if task_update_schema.project_id:
                from backend.dsl.services.project_service import ProjectService

                linked_project_obj = ProjectService.get_project_by_id(
                    db_session,
                    task_update_schema.project_id,
                )
                if linked_project_obj is None:
                    raise ValueError(
                        f"Project with id {task_update_schema.project_id} not found"
                    )
                normalized_next_project_id = linked_project_obj.id

            if normalized_next_project_id != task_obj.project_id:
                if not TaskService.can_rebind_project(task_obj):
                    raise ValueError(
                        "Task project is locked after start. "
                        "Only backlog tasks without a worktree can change project_id."
                    )
                task_obj.project_id = normalized_next_project_id

        db_session.commit()
        db_session.refresh(task_obj)

        logger.info(f"Updated Task {task_id[:8]}... content")
        return task_obj

    @staticmethod
    def destroy_task(
        db_session: Session,
        task_id: str,
        destroy_reason: str,
        *,
        clear_worktree_path: bool = True,
    ) -> Task | None:
        """将已启动任务归档到 deleted history，并记录销毁原因.

        Args:
            db_session: 数据库会话
            task_id: 任务 ID
            destroy_reason: 必填销毁原因
            clear_worktree_path: 是否在销毁后清空 worktree_path

        Returns:
            Task | None: 更新后的任务对象；若任务不存在则返回 None

        Raises:
            ValueError: 当任务尚未启动，或已经关闭/删除时抛出
        """
        task_obj = TaskService.get_task_by_id(db_session, task_id)
        if not task_obj:
            return None

        if task_obj.lifecycle_status == TaskLifecycleStatus.CLOSED:
            raise ValueError("Closed tasks cannot be destroyed.")
        if task_obj.lifecycle_status == TaskLifecycleStatus.DELETED:
            raise ValueError("Task is already deleted.")

        if not TaskService.has_task_started(task_obj):
            raise ValueError(
                "Task destroy is only available after the task has started. "
                "Use Delete for backlog tasks."
            )

        task_obj.lifecycle_status = TaskLifecycleStatus.DELETED
        task_obj.destroy_reason = destroy_reason
        task_obj.destroyed_at = utc_now_naive()
        task_obj.closed_at = None
        if clear_worktree_path:
            task_obj.worktree_path = None

        db_session.commit()
        db_session.refresh(task_obj)

        logger.info(f"Destroyed Task {task_id[:8]}... with recorded reason")
        return task_obj

    @staticmethod
    def restore_task(
        db_session: Session,
        task_id: str,
    ) -> Task | None:
        """将 abandoned 任务恢复回活动工作区.

        恢复时保留原有 `workflow_stage`，仅把生命周期从 `ABANDONED`
        切回活动态：
        - 尚未启动的 backlog 任务恢复为 `PENDING`
        - 已启动或已有 worktree 的任务恢复为 `OPEN`

        Args:
            db_session: 数据库会话
            task_id: 任务 ID

        Returns:
            Task | None: 更新后的任务对象；若任务不存在则返回 None

        Raises:
            ValueError: 当任务当前不是 abandoned 时抛出
        """
        task_obj = TaskService.get_task_by_id(db_session, task_id)
        if not task_obj:
            return None

        if task_obj.lifecycle_status != TaskLifecycleStatus.ABANDONED:
            raise ValueError("Only abandoned tasks can be restored.")

        task_obj.lifecycle_status = (
            TaskLifecycleStatus.OPEN
            if TaskService.has_task_started(task_obj)
            else TaskLifecycleStatus.PENDING
        )
        task_obj.closed_at = None

        db_session.commit()
        db_session.refresh(task_obj)

        logger.info(
            "Restored Task %s... from abandoned history to %s",
            task_id[:8],
            task_obj.lifecycle_status.value,
        )
        return task_obj

    @staticmethod
    def prepare_task_completion(
        db_session: Session,
        task_id: str,
    ) -> Task | None:
        """将任务推进到完成收尾阶段（pr_preparing）.

        仅允许已经拥有 worktree 的任务进入该阶段。进入后，后台会执行
        确定性的 Git 收尾与合并动作。

        Args:
            db_session: 数据库会话
            task_id: 任务 ID

        Returns:
            Task | None: 更新后的任务对象；若任务不存在则返回 None

        Raises:
            ValueError: 当前阶段不允许完成，或任务尚无 worktree
        """
        task_obj = TaskService.get_task_by_id(db_session, task_id)
        if not task_obj:
            return None

        if task_obj.lifecycle_status in {
            TaskLifecycleStatus.CLOSED,
            TaskLifecycleStatus.DELETED,
            TaskLifecycleStatus.ABANDONED,
        }:
            raise ValueError(
                f"Task {task_id[:8]}... cannot complete from lifecycle "
                f"'{task_obj.lifecycle_status.value}'."
            )

        if not task_obj.worktree_path:
            raise ValueError(
                f"Task {task_id[:8]}... has no worktree_path. Start the task first."
            )

        allowed_source_stages = {
            WorkflowStage.SELF_REVIEW_IN_PROGRESS,
            WorkflowStage.TEST_IN_PROGRESS,
            WorkflowStage.PR_PREPARING,
            WorkflowStage.ACCEPTANCE_IN_PROGRESS,
        }
        if task_obj.workflow_stage not in allowed_source_stages:
            raise ValueError(
                f"Task {task_id[:8]}... cannot complete from stage "
                f"'{task_obj.workflow_stage.value}'. "
                f"Allowed: {[stage.value for stage in allowed_source_stages]}"
            )

        task_branch_health = TaskService.build_task_branch_health(task_obj)
        if task_branch_health.manual_completion_candidate:
            raise ValueError(
                "Task branch is missing. Review the timeline/code state and use "
                "/manual-complete instead of the normal /complete flow."
            )

        TaskService._apply_workflow_stage_transition(
            task_obj,
            WorkflowStage.PR_PREPARING,
        )
        task_obj.lifecycle_status = TaskLifecycleStatus.OPEN
        task_obj.closed_at = None

        db_session.commit()
        db_session.refresh(task_obj)

        logger.info(
            f"Task {task_id[:8]}... completion requested → pr_preparing"
            f", worktree={task_obj.worktree_path}"
        )
        return task_obj

    @staticmethod
    def close_task_after_manual_completion(
        db_session: Session,
        task_obj: Task,
    ) -> Task:
        """Converge a manually confirmed task into `done / CLOSED`.

        Args:
            db_session: 数据库会话
            task_obj: 已完成人工校验的任务对象

        Returns:
            Task: 已切换到 `done / CLOSED` 的任务对象
        """
        TaskService._apply_workflow_stage_transition(task_obj, WorkflowStage.DONE)
        task_obj.lifecycle_status = TaskLifecycleStatus.CLOSED
        task_obj.closed_at = utc_now_naive()

        db_session.commit()
        db_session.refresh(task_obj)

        logger.info(
            "Task %s... manually completed after missing-branch confirmation",
            task_obj.id[:8],
        )
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
