"""Project API 路由.

提供项目的创建、查询、更新和删除功能.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from dsl.models.project import Project
from dsl.schemas.project_schema import (
    ProjectCreateSchema,
    ProjectResponseSchema,
    ProjectUpdateSchema,
)
from dsl.services.project_service import ProjectService
from utils.database import get_db

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _to_response(project_obj: Project) -> ProjectResponseSchema:
    """将 ORM Project 转换为带本机路径状态的响应模型.

    Args:
        project_obj: 项目 ORM 实例

    Returns:
        ProjectResponseSchema: 前端消费的项目响应
    """
    consistency_snapshot = ProjectService.build_project_consistency_snapshot(project_obj)
    return ProjectResponseSchema(
        id=project_obj.id,
        display_name=project_obj.display_name,
        repo_path=project_obj.repo_path,
        repo_remote_url=project_obj.repo_remote_url,
        repo_head_commit_hash=project_obj.repo_head_commit_hash,
        current_repo_remote_url=consistency_snapshot.current_repo_remote_url,
        current_repo_head_commit_hash=consistency_snapshot.current_repo_head_commit_hash,
        description=project_obj.description,
        is_repo_path_valid=ProjectService.is_repo_path_valid(project_obj.repo_path),
        is_repo_remote_consistent=consistency_snapshot.is_repo_remote_consistent,
        is_repo_head_consistent=consistency_snapshot.is_repo_head_consistent,
        repo_consistency_note=consistency_snapshot.repo_consistency_note,
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
    return [_to_response(project_obj) for project_obj in ProjectService.list_projects(db_session)]


@router.post("", response_model=ProjectResponseSchema, status_code=status.HTTP_201_CREATED)
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
    try:
        created_project_obj = ProjectService.create_project(db_session, project_create_schema)
    except ValueError as validation_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
    try:
        updated_project_obj = ProjectService.update_project(
            db_session=db_session,
            project_id=project_id,
            project_update_schema=project_update_schema,
        )
    except ValueError as validation_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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


@router.post("/{project_id}/open-in-trae", status_code=status.HTTP_200_OK)
def open_project_in_trae(
    project_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> dict:
    """使用 trae-cn 打开项目根目录.

    Args:
        project_id: 项目 ID
        db_session: 数据库会话

    Returns:
        dict: 包含打开路径的确认信息

    Raises:
        HTTPException: 项目不存在（404）或 trae-cn 未找到（500）
    """
    import subprocess

    project_obj = ProjectService.get_project_by_id(db_session, project_id)
    if not project_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    consistency_snapshot = ProjectService.build_project_consistency_snapshot(project_obj)
    if not ProjectService.is_repo_path_valid(project_obj.repo_path):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Project repo_path is not valid on this machine. "
                "Update the project path before opening it."
            ),
        )
    if consistency_snapshot.is_repo_remote_consistent is False:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Project repo_path points to a different Git remote than the stored "
                "synced fingerprint. Update the project path to the correct repository."
            ),
        )

    try:
        subprocess.Popen(
            ["trae-cn", project_obj.repo_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="trae-cn executable not found in PATH.",
        )

    return {"opened": project_obj.repo_path}


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
