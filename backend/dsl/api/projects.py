"""Project API 路由.

提供项目的创建、查询、更新和删除功能.
"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.dsl.models.project import Project
from backend.dsl.models.run_account import RunAccount
from backend.dsl.schemas.project_schema import (
    ProjectBranchListSchema,
    ProjectCreateSchema,
    ProjectResponseSchema,
    RemoteRequirementSyncResponseSchema,
    ProjectUpdateSchema,
)
from backend.dsl.worktree_resources import (
    ProjectWorktreeResourcePolicySchema,
    WorktreeResourceCandidateListSchema,
    WorktreeResourcePolicyConfirmation,
    WorktreeResourcePreviewRequestSchema,
    preview_project_worktree_resource_candidates,
    resolve_project_worktree_resource_policy,
)
from backend.dsl.services.path_opener import (
    PathOpenCommandError,
    PathOpenTargetNotFoundError,
    open_path_in_editor,
)
from backend.dsl.services.project_service import ProjectService
from backend.dsl.remote_requirements.domain import RemoteRequirementError
from backend.dsl.remote_requirements.service import RemoteRequirementService
from utils.database import get_db

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _build_lightweight_consistency_snapshot(
    project_obj: Project,
) -> ProjectService.ProjectConsistencySnapshot:
    """Build a non-blocking consistency snapshot for project list responses.

    The full snapshot executes Git commands for every project. That is useful on
    detail/update paths, but it makes the project list wait on slow local repos.
    """

    is_repo_path_valid_bool = ProjectService.is_repo_path_valid(project_obj.repo_path)
    if not is_repo_path_valid_bool:
        return ProjectService.ProjectConsistencySnapshot(
            current_repo_remote_url=None,
            current_repo_head_commit_hash=None,
            is_repo_remote_consistent=None,
            is_repo_head_consistent=None,
            repo_consistency_note=(
                "Project repo_path is not valid on this machine. "
                "Relink it before comparing remote URL or commit hash."
            ),
        )

    return ProjectService.ProjectConsistencySnapshot(
        current_repo_remote_url=None,
        current_repo_head_commit_hash=None,
        is_repo_remote_consistent=None,
        is_repo_head_consistent=None,
        repo_consistency_note=None,
    )


def _build_lightweight_policy_snapshot(
    project_obj: Project,
) -> tuple[bool, str | None, ProjectWorktreeResourcePolicySchema | None]:
    """Build a non-scanning policy snapshot for project list responses."""

    raw_policy_json_str = project_obj.worktree_resource_policy_json
    parsed_policy_obj = resolve_project_worktree_resource_policy(project_obj)
    if parsed_policy_obj is None:
        if raw_policy_json_str:
            return (
                False,
                "Project worktree resource policy JSON could not be parsed.",
                None,
            )
        if project_obj.repo_path:
            return (
                False,
                "Legacy project without stored worktree resource policy; confirm Worktree Resources before starting a task.",
                None,
            )
        return False, "Project worktree resource policy is not configured yet.", None

    if (
        parsed_policy_obj.confirmation_status
        == WorktreeResourcePolicyConfirmation.DEFERRED
    ):
        return (
            False,
            "Confirm Worktree Resources in Project settings before starting a task.",
            parsed_policy_obj,
        )

    return True, None, parsed_policy_obj


def _get_current_run_account_id(db_session: Session) -> str:
    """Return the active run account ID.

    Args:
        db_session: 数据库会话

    Returns:
        str: 当前活跃账户 ID

    Raises:
        HTTPException: 当没有活跃账户时返回 400
    """
    active_account = db_session.query(RunAccount).filter(RunAccount.is_active).first()
    if active_account is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active run account. Please create a run account first.",
        )
    return active_account.id


def _to_response(
    project_obj: Project,
    *,
    include_git_consistency_snapshot: bool = True,
    include_worktree_resource_policy_snapshot: bool = True,
) -> ProjectResponseSchema:
    """将 ORM Project 转换为带本机路径状态的响应模型.

    Args:
        project_obj: 项目 ORM 实例
        include_git_consistency_snapshot: 是否执行 Git 命令构建完整一致性快照
        include_worktree_resource_policy_snapshot: 是否扫描仓库构建 legacy policy 草稿

    Returns:
        ProjectResponseSchema: 前端消费的项目响应
    """
    consistency_snapshot = (
        ProjectService.build_project_consistency_snapshot(project_obj)
        if include_git_consistency_snapshot
        else _build_lightweight_consistency_snapshot(project_obj)
    )
    is_policy_ready_bool, policy_note_str, parsed_policy_obj = (
        ProjectService.build_project_worktree_resource_policy_snapshot(project_obj)
        if include_worktree_resource_policy_snapshot
        else _build_lightweight_policy_snapshot(project_obj)
    )
    return ProjectResponseSchema(
        id=project_obj.id,
        display_name=project_obj.display_name,
        project_category=project_obj.project_category,
        repo_path=project_obj.repo_path,
        repo_remote_url=project_obj.repo_remote_url,
        repo_head_commit_hash=project_obj.repo_head_commit_hash,
        worktree_resource_policy_confirmation=(
            parsed_policy_obj.confirmation_status
            if parsed_policy_obj is not None
            else WorktreeResourcePolicyConfirmation.DEFERRED
        ),
        worktree_resource_policy=parsed_policy_obj,
        remote_requirement_management_enabled=bool(
            project_obj.remote_requirement_management_enabled
        ),
        remote_requirement_branch_prefix=(
            project_obj.remote_requirement_branch_prefix or "task"
        ),
        remote_requirement_remote_name=project_obj.remote_requirement_remote_name,
        github_pr_creation_enabled=(
            True
            if project_obj.github_pr_creation_enabled is None
            else bool(project_obj.github_pr_creation_enabled)
        ),
        github_repository_full_name=project_obj.github_repository_full_name,
        remote_requirement_delete_branch_after_pr_merge=bool(
            project_obj.remote_requirement_delete_branch_after_pr_merge
        ),
        current_repo_remote_url=consistency_snapshot.current_repo_remote_url,
        current_repo_head_commit_hash=consistency_snapshot.current_repo_head_commit_hash,
        description=project_obj.description,
        is_repo_path_valid=ProjectService.is_repo_path_valid(project_obj.repo_path),
        is_repo_remote_consistent=consistency_snapshot.is_repo_remote_consistent,
        is_repo_head_consistent=consistency_snapshot.is_repo_head_consistent,
        repo_consistency_note=consistency_snapshot.repo_consistency_note,
        is_worktree_resource_policy_ready=is_policy_ready_bool,
        worktree_resource_policy_note=policy_note_str,
        created_at=project_obj.created_at,
    )


@router.get("", response_model=list[ProjectResponseSchema])
def list_projects(
    db_session: Annotated[Session, Depends(get_db)],
) -> list[ProjectResponseSchema]:
    """列出所有项目.

    Args:
        db_session: 数据库会话

    Returns:
        list[ProjectResponseSchema]: 项目列表
    """
    return [
        _to_response(
            project_obj,
            include_git_consistency_snapshot=False,
            include_worktree_resource_policy_snapshot=False,
        )
        for project_obj in ProjectService.list_projects(db_session)
    ]


@router.post(
    "", response_model=ProjectResponseSchema, status_code=status.HTTP_201_CREATED
)
def create_project(
    project_create_schema: ProjectCreateSchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> ProjectResponseSchema:
    """创建新项目.

    Args:
        project_create_schema: 项目创建数据
        db_session: 数据库会话

    Returns:
        ProjectResponseSchema: 新创建的项目

    Raises:
        HTTPException: 当 repo_path 无效时返回 422
    """
    if "worktree_resource_policy_confirmation" not in (
        project_create_schema.model_fields_set
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="worktree_resource_policy_confirmation is required",
        )
    try:
        created_project_obj = ProjectService.create_project(
            db_session, project_create_schema
        )
    except ValueError as validation_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(validation_error),
        ) from validation_error
    return _to_response(created_project_obj)


@router.put("/{project_id}", response_model=ProjectResponseSchema)
def update_project(
    project_id: str,
    project_update_schema: ProjectUpdateSchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> ProjectResponseSchema:
    """更新项目信息，主要用于在新机器上重绑本地仓库路径.

    Args:
        project_id: 项目 ID
        project_update_schema: 更新数据
        db_session: 数据库会话

    Returns:
        ProjectResponseSchema: 更新后的项目信息

    Raises:
        HTTPException: 项目不存在时返回 404；路径无效时返回 422
    """
    if "worktree_resource_policy_confirmation" not in (
        project_update_schema.model_fields_set
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="worktree_resource_policy_confirmation is required",
        )
    try:
        updated_project_obj = ProjectService.update_project(
            db_session=db_session,
            project_id=project_id,
            project_update_schema=project_update_schema,
        )
    except ValueError as validation_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(validation_error),
        ) from validation_error

    if not updated_project_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    return _to_response(updated_project_obj)


@router.get("/{project_id}", response_model=ProjectResponseSchema)
def get_project(
    project_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> ProjectResponseSchema:
    """获取单个项目详情.

    Args:
        project_id: 项目 ID
        db_session: 数据库会话

    Returns:
        ProjectResponseSchema: 项目详情

    Raises:
        HTTPException: 当项目不存在时返回 404
    """
    project_obj = ProjectService.get_project_by_id(db_session, project_id)
    if not project_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )
    return _to_response(project_obj)


@router.post(
    "/worktree-resource-candidates/preview",
    response_model=WorktreeResourceCandidateListSchema,
)
def preview_worktree_resource_candidates(
    request_schema: WorktreeResourcePreviewRequestSchema,
) -> WorktreeResourceCandidateListSchema:
    """Preview local resource candidates for a repo path before project creation."""

    try:
        repo_path_obj = ProjectService._normalize_repo_path(request_schema.repo_path)
    except ValueError as validation_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(validation_error),
        ) from validation_error

    return preview_project_worktree_resource_candidates(
        repo_root_path=repo_path_obj,
        draft_policy=request_schema.draft_policy,
    )


@router.get(
    "/{project_id}/worktree-resource-candidates",
    response_model=WorktreeResourceCandidateListSchema,
)
def list_project_worktree_resource_candidates(
    project_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> WorktreeResourceCandidateListSchema:
    """Preview local resource candidates for an existing project."""

    project_obj = ProjectService.get_project_by_id(db_session, project_id)
    if not project_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    try:
        repo_path_obj = ProjectService._normalize_repo_path(project_obj.repo_path)
    except ValueError as validation_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(validation_error),
        ) from validation_error

    return preview_project_worktree_resource_candidates(
        repo_root_path=repo_path_obj,
        draft_policy=resolve_project_worktree_resource_policy(project_obj),
    )


@router.get("/{project_id}/branches", response_model=ProjectBranchListSchema)
def list_project_branches(
    project_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> ProjectBranchListSchema:
    """List local branches for a project repository.

    Args:
        project_id: 项目 ID
        db_session: 数据库会话

    Returns:
        ProjectBranchListSchema: 本地分支列表与当前分支

    Raises:
        HTTPException: 项目不存在时返回 404；仓库路径无效或 Git 探测失败时返回 422
    """
    project_obj = ProjectService.get_project_by_id(db_session, project_id)
    if not project_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    try:
        repo_path_obj = Path(project_obj.repo_path)
        local_branch_name_list = ProjectService.list_local_branch_names(repo_path_obj)
        current_branch_name_str = ProjectService.get_current_branch_name(repo_path_obj)
    except ValueError as validation_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(validation_error),
        ) from validation_error

    return ProjectBranchListSchema(
        branches=local_branch_name_list,
        current_branch_name=current_branch_name_str,
    )


@router.post(
    "/{project_id}/sync-remote-requirements",
    response_model=RemoteRequirementSyncResponseSchema,
)
def sync_project_remote_requirements(
    project_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> RemoteRequirementSyncResponseSchema:
    """Fetch remote task branches and materialize local requirement cards.

    Args:
        project_id: 项目 ID
        db_session: 数据库会话

    Returns:
        RemoteRequirementSyncResponseSchema: 同步摘要

    Raises:
        HTTPException: 项目不存在或远程协作不可用时返回错误
    """
    project_obj = ProjectService.get_project_by_id(db_session, project_id)
    if not project_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    try:
        sync_outcome = RemoteRequirementService().sync_project_remote_requirements(
            db_session,
            project_obj,
            _get_current_run_account_id(db_session),
        )
    except RemoteRequirementError as remote_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(remote_error),
        ) from remote_error

    return RemoteRequirementSyncResponseSchema(
        project_id=project_id,
        imported_count=sync_outcome.imported_count,
        updated_count=sync_outcome.updated_count,
        skipped_count=sync_outcome.skipped_count,
        message=(
            "Remote requirements synced: "
            f"{sync_outcome.imported_count} imported, "
            f"{sync_outcome.updated_count} updated, "
            f"{sync_outcome.skipped_count} skipped."
        ),
    )


def _open_project_root_in_editor(
    project_id: str,
    db_session: Session,
) -> dict[str, str]:
    """使用配置的编辑器命令打开项目根目录.

    Args:
        project_id: 项目 ID
        db_session: 数据库会话

    Returns:
        dict: 包含打开路径的确认信息

    Raises:
        HTTPException: 项目不存在（404）、仓库路径异常（422）
            或命令模板 / 可执行命令异常（500）
    """
    project_obj = ProjectService.get_project_by_id(db_session, project_id)
    if not project_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    consistency_snapshot = ProjectService.build_project_consistency_snapshot(
        project_obj
    )
    if not ProjectService.is_repo_path_valid(project_obj.repo_path):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Project repo_path is not valid on this machine. "
                "Update the project path before opening it."
            ),
        )
    if consistency_snapshot.is_repo_remote_consistent is False:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Project repo_path points to a different Git remote than the stored "
                "synced fingerprint. Update the project path to the correct repository."
            ),
        )

    try:
        open_path_in_editor(
            target_path=Path(project_obj.repo_path),
            target_kind="project",
        )
    except PathOpenTargetNotFoundError as path_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(path_error),
        ) from path_error
    except PathOpenCommandError as path_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(path_error),
        ) from path_error

    return {"opened": project_obj.repo_path}


@router.post("/{project_id}/open-in-editor", status_code=status.HTTP_200_OK)
def open_project_in_editor(
    project_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    """使用配置的编辑器命令打开项目根目录.

    Args:
        project_id: 项目 ID
        db_session: 数据库会话

    Returns:
        dict[str, str]: 包含打开路径的确认信息
    """
    return _open_project_root_in_editor(project_id=project_id, db_session=db_session)


@router.post(
    "/{project_id}/open-in-trae",
    status_code=status.HTTP_200_OK,
    deprecated=True,
)
def open_project_in_trae(
    project_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    """兼容旧客户端的别名路由，内部复用 `open-in-editor` 逻辑.

    Args:
        project_id: 项目 ID
        db_session: 数据库会话

    Returns:
        dict[str, str]: 包含打开路径的确认信息
    """
    return _open_project_root_in_editor(project_id=project_id, db_session=db_session)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> None:
    """删除项目.

    Args:
        project_id: 项目 ID
        db_session: 数据库会话

    Raises:
        HTTPException: 当项目不存在时返回 404
    """
    if not ProjectService.delete_project(db_session, project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )
