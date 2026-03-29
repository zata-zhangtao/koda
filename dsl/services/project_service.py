"""Project 服务模块.

提供 Project 的 CRUD 操作，并负责验证本地 Git 仓库路径.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from dsl.models.project import Project
from dsl.schemas.project_schema import ProjectCreateSchema, ProjectUpdateSchema
from utils.logger import logger


class ProjectService:
    """项目服务类.

    处理项目的创建、查询等业务逻辑.
    """

    @dataclass(frozen=True)
    class RepoFingerprint:
        """Git 仓库指纹快照.

        Attributes:
            normalized_remote_url: 归一化后的 origin remote URL
            head_commit_hash: 当前 HEAD commit 哈希
        """

        normalized_remote_url: str | None
        head_commit_hash: str | None

    @dataclass(frozen=True)
    class ProjectConsistencySnapshot:
        """当前本机仓库与项目已保存指纹的比较结果.

        Attributes:
            current_repo_remote_url: 当前本机仓库的归一化 origin remote URL
            current_repo_head_commit_hash: 当前本机仓库的 HEAD commit 哈希
            is_repo_remote_consistent: remote 是否一致
            is_repo_head_consistent: HEAD 是否一致
            repo_consistency_note: 说明信息
        """

        current_repo_remote_url: str | None
        current_repo_head_commit_hash: str | None
        is_repo_remote_consistent: bool | None
        is_repo_head_consistent: bool | None
        repo_consistency_note: str | None

    @staticmethod
    def _normalize_project_category(raw_project_category_str: str | None) -> str | None:
        """标准化项目类别文本.

        Args:
            raw_project_category_str: 原始项目类别文本

        Returns:
            str | None: 去首尾空白后的项目类别；空字符串返回 None
        """
        if raw_project_category_str is None:
            return None
        normalized_project_category_str = raw_project_category_str.strip()
        return normalized_project_category_str or None

    @staticmethod
    def _normalize_repo_path(raw_repo_path_str: str) -> Path:
        """标准化并验证项目仓库路径.

        Args:
            raw_repo_path_str: 用户提交的仓库路径

        Returns:
            Path: 标准化后的绝对路径对象

        Raises:
            ValueError: 当路径不存在或不是 Git 仓库时抛出
        """
        normalized_repo_path_obj = Path(raw_repo_path_str).expanduser().resolve()

        if not normalized_repo_path_obj.exists():
            raise ValueError(f"路径不存在：{normalized_repo_path_obj}")

        if not (normalized_repo_path_obj / ".git").exists():
            raise ValueError(
                f"该路径不是 Git 仓库（未找到 .git）：{normalized_repo_path_obj}"
            )

        return normalized_repo_path_obj

    @staticmethod
    def _normalize_repo_remote_url(raw_remote_url_str: str | None) -> str | None:
        """将 Git remote URL 规范化为可比较的稳定格式.

        Args:
            raw_remote_url_str: `git remote get-url origin` 返回的原始值

        Returns:
            str | None: 归一化后的 remote URL；若为空则返回 None
        """
        if not raw_remote_url_str:
            return None

        stripped_remote_url_str = raw_remote_url_str.strip()
        if not stripped_remote_url_str:
            return None

        if (
            stripped_remote_url_str.startswith("git@")
            and ":" in stripped_remote_url_str
        ):
            authority_str, raw_repo_path_str = stripped_remote_url_str.split(":", 1)
            host_str = authority_str.split("@", 1)[1].lower()
            normalized_repo_path_str = raw_repo_path_str.strip("/").removesuffix(".git")
            return f"{host_str}/{normalized_repo_path_str}"

        parsed_remote_url = urlsplit(stripped_remote_url_str)
        if parsed_remote_url.scheme:
            host_str = (parsed_remote_url.hostname or "").lower()
            normalized_repo_path_str = parsed_remote_url.path.strip("/").removesuffix(
                ".git"
            )
            if host_str and normalized_repo_path_str:
                return f"{host_str}/{normalized_repo_path_str}"
            if host_str:
                return host_str
            if normalized_repo_path_str:
                return normalized_repo_path_str

        normalized_remote_url_str = stripped_remote_url_str.rstrip("/").removesuffix(
            ".git"
        )
        return normalized_remote_url_str or None

    @staticmethod
    def _run_git_command(
        repo_path_obj: Path, git_argument_list: list[str]
    ) -> str | None:
        """在指定仓库中执行 Git 命令并返回标准输出.

        Args:
            repo_path_obj: 仓库路径
            git_argument_list: Git 参数列表

        Returns:
            str | None: 命令输出；失败时返回 None
        """
        try:
            completed_process = subprocess.run(
                ["git", "-C", str(repo_path_obj), *git_argument_list],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        except (FileNotFoundError, OSError, subprocess.CalledProcessError):
            return None

        command_output_str = completed_process.stdout.strip()
        return command_output_str or None

    @staticmethod
    def get_repo_fingerprint(repo_path_obj: Path) -> RepoFingerprint:
        """读取仓库当前的 remote 与 HEAD 指纹.

        Args:
            repo_path_obj: 已验证存在的 Git 仓库根目录

        Returns:
            RepoFingerprint: 当前仓库指纹
        """
        raw_remote_url_str = ProjectService._run_git_command(
            repo_path_obj,
            ["config", "--get", "remote.origin.url"],
        )
        normalized_remote_url_str = ProjectService._normalize_repo_remote_url(
            raw_remote_url_str
        )
        head_commit_hash_str = ProjectService._run_git_command(
            repo_path_obj,
            ["rev-parse", "HEAD"],
        )
        return ProjectService.RepoFingerprint(
            normalized_remote_url=normalized_remote_url_str,
            head_commit_hash=head_commit_hash_str,
        )

    @staticmethod
    def is_repo_path_valid(raw_repo_path_str: str) -> bool:
        """判断项目仓库路径在当前机器上是否有效.

        Args:
            raw_repo_path_str: 数据库存储的仓库路径字符串

        Returns:
            bool: 路径存在且包含 `.git` 目录时返回 True
        """
        repo_path_obj = Path(raw_repo_path_str).expanduser()
        if not repo_path_obj.is_absolute():
            return False
        if not repo_path_obj.exists():
            return False
        return (repo_path_obj / ".git").exists()

    @staticmethod
    def build_project_consistency_snapshot(
        project_obj: Project,
    ) -> ProjectConsistencySnapshot:
        """构建项目仓库的一致性快照.

        Args:
            project_obj: 项目对象

        Returns:
            ProjectConsistencySnapshot: 当前路径对应仓库与已保存指纹的比较结果
        """
        if not ProjectService.is_repo_path_valid(project_obj.repo_path):
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

        current_repo_path_obj = Path(project_obj.repo_path).expanduser().resolve()
        current_repo_fingerprint = ProjectService.get_repo_fingerprint(
            current_repo_path_obj
        )

        is_repo_remote_consistent: bool | None = None
        if project_obj.repo_remote_url is not None:
            is_repo_remote_consistent = (
                current_repo_fingerprint.normalized_remote_url
                == project_obj.repo_remote_url
            )

        is_repo_head_consistent: bool | None = None
        if project_obj.repo_head_commit_hash is not None:
            is_repo_head_consistent = (
                current_repo_fingerprint.head_commit_hash
                == project_obj.repo_head_commit_hash
            )

        repo_consistency_note: str | None = None
        if project_obj.repo_remote_url and is_repo_remote_consistent is False:
            repo_consistency_note = (
                "Current repo origin does not match the stored synced fingerprint."
            )
        elif project_obj.repo_head_commit_hash and is_repo_head_consistent is False:
            repo_consistency_note = (
                "Current repo HEAD differs from the stored synced fingerprint. "
                "Upload a fresh WebDAV backup after confirming this revision is intended."
            )
        elif (
            project_obj.repo_remote_url is None
            or project_obj.repo_head_commit_hash is None
        ):
            repo_consistency_note = (
                "Project fingerprint is incomplete. A future WebDAV upload will refresh it "
                "from the current local repo."
            )

        return ProjectService.ProjectConsistencySnapshot(
            current_repo_remote_url=current_repo_fingerprint.normalized_remote_url,
            current_repo_head_commit_hash=current_repo_fingerprint.head_commit_hash,
            is_repo_remote_consistent=is_repo_remote_consistent,
            is_repo_head_consistent=is_repo_head_consistent,
            repo_consistency_note=repo_consistency_note,
        )

    @staticmethod
    def refresh_project_repo_fingerprints(
        db_session: Session,
        *,
        only_missing: bool = False,
    ) -> int:
        """刷新数据库中项目的 Git 指纹.

        Args:
            db_session: 数据库会话
            only_missing: 仅补全缺失字段；False 时会覆盖为当前最新指纹

        Returns:
            int: 实际更新的项目数量
        """
        updated_project_count_int = 0
        project_list = db_session.query(Project).all()
        for project_obj in project_list:
            if not ProjectService.is_repo_path_valid(project_obj.repo_path):
                continue

            repo_path_obj = Path(project_obj.repo_path).expanduser().resolve()
            current_repo_fingerprint = ProjectService.get_repo_fingerprint(
                repo_path_obj
            )

            next_repo_remote_url = current_repo_fingerprint.normalized_remote_url
            next_repo_head_commit_hash = current_repo_fingerprint.head_commit_hash

            if only_missing:
                next_repo_remote_url = (
                    project_obj.repo_remote_url
                    if project_obj.repo_remote_url is not None
                    else current_repo_fingerprint.normalized_remote_url
                )
                next_repo_head_commit_hash = (
                    project_obj.repo_head_commit_hash
                    if project_obj.repo_head_commit_hash is not None
                    else current_repo_fingerprint.head_commit_hash
                )

            if (
                project_obj.repo_remote_url == next_repo_remote_url
                and project_obj.repo_head_commit_hash == next_repo_head_commit_hash
            ):
                continue

            project_obj.repo_remote_url = next_repo_remote_url
            project_obj.repo_head_commit_hash = next_repo_head_commit_hash
            updated_project_count_int += 1

        if updated_project_count_int > 0:
            db_session.commit()

        return updated_project_count_int

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
        normalized_repo_path_obj = ProjectService._normalize_repo_path(
            project_create_schema.repo_path
        )
        repo_fingerprint_obj = ProjectService.get_repo_fingerprint(
            normalized_repo_path_obj
        )

        new_project = Project(
            display_name=project_create_schema.display_name,
            project_category=ProjectService._normalize_project_category(
                project_create_schema.project_category
            ),
            repo_path=str(normalized_repo_path_obj),
            repo_remote_url=repo_fingerprint_obj.normalized_remote_url,
            repo_head_commit_hash=repo_fingerprint_obj.head_commit_hash,
            description=project_create_schema.description,
        )

        db_session.add(new_project)
        db_session.commit()
        db_session.refresh(new_project)

        logger.info(
            f"Created Project: {new_project.id[:8]}... - {new_project.display_name}"
        )
        return new_project

    @staticmethod
    def update_project(
        db_session: Session,
        project_id: str,
        project_update_schema: ProjectUpdateSchema,
    ) -> Project | None:
        """更新已有项目，并在必要时清理失效的 worktree 路径.

        Args:
            db_session: 数据库会话
            project_id: 项目 ID
            project_update_schema: 更新数据

        Returns:
            Project | None: 更新后的项目对象；若项目不存在则返回 None

        Raises:
            ValueError: 当 repo_path 不是有效的 Git 仓库时
        """
        existing_project_obj = ProjectService.get_project_by_id(db_session, project_id)
        if not existing_project_obj:
            return None

        normalized_repo_path_obj = ProjectService._normalize_repo_path(
            project_update_schema.repo_path
        )
        current_repo_fingerprint_obj = ProjectService.get_repo_fingerprint(
            normalized_repo_path_obj
        )
        normalized_repo_path_str = str(normalized_repo_path_obj)
        repo_path_changed_bool = (
            existing_project_obj.repo_path != normalized_repo_path_str
        )

        if (
            existing_project_obj.repo_remote_url is not None
            and existing_project_obj.repo_remote_url
            != current_repo_fingerprint_obj.normalized_remote_url
        ):
            raise ValueError(
                "所选仓库的 origin remote 与已同步项目指纹不一致。"
                "请确认你绑定的是同一个代码仓库。"
            )

        existing_project_obj.display_name = project_update_schema.display_name
        existing_project_obj.project_category = (
            ProjectService._normalize_project_category(
                project_update_schema.project_category
            )
        )
        existing_project_obj.repo_path = normalized_repo_path_str
        if existing_project_obj.repo_remote_url is None:
            existing_project_obj.repo_remote_url = (
                current_repo_fingerprint_obj.normalized_remote_url
            )
        if existing_project_obj.repo_head_commit_hash is None:
            existing_project_obj.repo_head_commit_hash = (
                current_repo_fingerprint_obj.head_commit_hash
            )
        existing_project_obj.description = project_update_schema.description

        cleared_worktree_count_int = 0
        if repo_path_changed_bool:
            from dsl.models.task import Task

            linked_task_list = (
                db_session.query(Task)
                .filter(Task.project_id == existing_project_obj.id)
                .all()
            )
            for linked_task_obj in linked_task_list:
                if not linked_task_obj.worktree_path:
                    continue
                linked_worktree_path_obj = Path(
                    linked_task_obj.worktree_path
                ).expanduser()
                if linked_worktree_path_obj.exists():
                    continue
                linked_task_obj.worktree_path = None
                cleared_worktree_count_int += 1

        db_session.commit()
        db_session.refresh(existing_project_obj)

        logger.info(
            "Updated Project: %s... - %s (repo_path_changed=%s, cleared_worktrees=%s, head_consistent=%s)",
            existing_project_obj.id[:8],
            existing_project_obj.display_name,
            repo_path_changed_bool,
            cleared_worktree_count_int,
            existing_project_obj.repo_head_commit_hash
            == current_repo_fingerprint_obj.head_commit_hash,
        )
        return existing_project_obj

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
