"""Project 服务模块.

提供 Project 的 CRUD 操作，并负责验证本地 Git 仓库路径.
"""

from pathlib import Path

from sqlalchemy.orm import Session

from dsl.models.project import Project
from dsl.schemas.project_schema import ProjectCreateSchema
from utils.logger import logger


class ProjectService:
    """项目服务类.

    处理项目的创建、查询等业务逻辑.
    """

    @staticmethod
    def create_project(
        db_session: Session,
        project_create_schema: ProjectCreateSchema,
    ) -> Project:
        """创建新项目.

        Args:
            db_session: 数据库会话
            project_create_schema: 项目创建数据

        Returns:
            Project: 新创建的项目对象

        Raises:
            ValueError: 当 repo_path 不是有效的 Git 仓库时
        """
        repo_path_obj = Path(project_create_schema.repo_path).expanduser().resolve()

        if not repo_path_obj.exists():
            raise ValueError(f"路径不存在：{repo_path_obj}")

        if not (repo_path_obj / ".git").exists():
            raise ValueError(f"该路径不是 Git 仓库（未找到 .git）：{repo_path_obj}")

        new_project = Project(
            display_name=project_create_schema.display_name,
            repo_path=str(repo_path_obj),
            description=project_create_schema.description,
        )

        db_session.add(new_project)
        db_session.commit()
        db_session.refresh(new_project)

        logger.info(f"Created Project: {new_project.id[:8]}... - {new_project.display_name}")
        return new_project

    @staticmethod
    def list_projects(db_session: Session) -> list[Project]:
        """获取所有项目列表.

        Args:
            db_session: 数据库会话

        Returns:
            list[Project]: 项目列表，按创建时间倒序
        """
        return db_session.query(Project).order_by(Project.created_at.desc()).all()

    @staticmethod
    def get_project_by_id(db_session: Session, project_id: str) -> Project | None:
        """通过 ID 获取项目.

        Args:
            db_session: 数据库会话
            project_id: 项目 ID

        Returns:
            Project | None: 项目对象或 None
        """
        return db_session.query(Project).filter(Project.id == project_id).first()

    @staticmethod
    def delete_project(db_session: Session, project_id: str) -> bool:
        """删除项目.

        Args:
            db_session: 数据库会话
            project_id: 项目 ID

        Returns:
            bool: 是否成功删除
        """
        project_obj = ProjectService.get_project_by_id(db_session, project_id)
        if not project_obj:
            return False

        db_session.delete(project_obj)
        db_session.commit()
        logger.info(f"Deleted Project: {project_id[:8]}...")
        return True
