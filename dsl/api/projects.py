"""Project API 路由.

提供项目的创建、查询和删除功能.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from dsl.models.project import Project
from dsl.schemas.project_schema import ProjectCreateSchema, ProjectResponseSchema
from dsl.services.project_service import ProjectService
from utils.database import get_db

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectResponseSchema])
def list_projects(
    db_session: Annotated[Session, Depends(get_db)],
) -> list[Project]:
    """列出所有项目.

    Args:
        db_session: 数据库会话

    Returns:
        list[Project]: 项目列表
    """
    return ProjectService.list_projects(db_session)


@router.post("", response_model=ProjectResponseSchema, status_code=status.HTTP_201_CREATED)
def create_project(
    project_create_schema: ProjectCreateSchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> Project:
    """创建新项目.

    Args:
        project_create_schema: 项目创建数据
        db_session: 数据库会话

    Returns:
        Project: 新创建的项目

    Raises:
        HTTPException: 当 repo_path 无效时返回 422
    """
    try:
        return ProjectService.create_project(db_session, project_create_schema)
    except ValueError as validation_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(validation_error),
        ) from validation_error


@router.get("/{project_id}", response_model=ProjectResponseSchema)
def get_project(
    project_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> Project:
    """获取单个项目详情.

    Args:
        project_id: 项目 ID
        db_session: 数据库会话

    Returns:
        Project: 项目详情

    Raises:
        HTTPException: 当项目不存在时返回 404
    """
    project_obj = ProjectService.get_project_by_id(db_session, project_id)
    if not project_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )
    return project_obj


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
