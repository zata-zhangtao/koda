"""DSL FastAPI 应用工厂模块.

提供 FastAPI 应用的创建和配置功能.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from dsl.api import (
    chronicle_router,
    email_settings_router,
    logs_router,
    media_router,
    projects_router,
    run_accounts_router,
    tasks_router,
    webdav_settings_router,
)

from utils.database import SessionLocal, ensure_database_schema_ready
from utils.logger import logger
from utils.settings import config


def _backfill_missing_project_repo_fingerprints() -> None:
    """补全旧数据库中缺失的项目仓库指纹."""
    from dsl.services.project_service import ProjectService

    db_session = SessionLocal()
    try:
        updated_project_count_int = ProjectService.refresh_project_repo_fingerprints(
            db_session,
            only_missing=True,
        )
        if updated_project_count_int > 0:
            logger.info(
                "Backfilled repo fingerprints for %s existing projects",
                updated_project_count_int,
            )
    finally:
        db_session.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理.

    在应用启动时创建数据库表，在关闭时清理资源。

    Args:
        app: FastAPI 应用实例

    Yields:
        None
    """
    # 启动时初始化数据库结构，并对旧数据执行轻量回填
    ensure_database_schema_ready()
    _backfill_missing_project_repo_fingerprints()
    logger.info("DSL tables initialized")

    yield

    # 关闭时清理
    logger.info("DSL application shutting down")


def create_application() -> FastAPI:
    """创建并配置 FastAPI 应用.

    Returns:
        FastAPI: 配置好的 FastAPI 应用实例
    """
    application = FastAPI(
        title="DevStream Log (DSL) API",
        description="智能开发流日志 API - 低摩擦、高保真的开发过程记录工具",
        version="2.0.0",
        lifespan=lifespan,
    )

    # 配置 CORS
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # Vite 开发服务器
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册 API 路由
    application.include_router(run_accounts_router)
    application.include_router(projects_router)
    application.include_router(tasks_router)
    application.include_router(logs_router)
    application.include_router(media_router)
    application.include_router(chronicle_router)
    application.include_router(email_settings_router)
    application.include_router(webdav_settings_router)

    # 挂载静态文件服务（媒体文件）
    media_path = config.MEDIA_STORAGE_PATH
    media_path.mkdir(parents=True, exist_ok=True)

    # 挂载原始图片目录
    original_media_path = media_path / "original"
    original_media_path.mkdir(parents=True, exist_ok=True)
    application.mount(
        "/media/original",
        StaticFiles(directory=str(original_media_path)),
        name="media_original",
    )

    # 挂载缩略图目录
    thumbnail_media_path = media_path / "thumbnail"
    thumbnail_media_path.mkdir(parents=True, exist_ok=True)
    application.mount(
        "/media/thumbnail",
        StaticFiles(directory=str(thumbnail_media_path)),
        name="media_thumbnail",
    )

    # 健康检查端点
    @application.get("/health")
    def health_check():
        """健康检查端点.

        Returns:
            dict: 健康状态信息
        """
        return {
            "status": "healthy",
            "service": "dsl",
            "version": "2.0.0",
        }

    return application


# 全局应用实例
app = create_application()
