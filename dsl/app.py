"""DSL FastAPI 应用工厂模块.

提供 FastAPI 应用的创建和配置功能.
"""

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dsl.api import (
    app_config_router,
    chronicle_router,
    email_settings_router,
    logs_router,
    media_router,
    projects_router,
    run_accounts_router,
    task_qa_router,
    task_schedules_router,
    tasks_router,
    webdav_settings_router,
)

from utils.database import SessionLocal, ensure_database_schema_ready
from utils.logger import logger
from utils.settings import config


def _build_dev_cors_origins() -> list[str]:
    """构建本地开发模式下的 CORS 白名单."""
    frontend_port_str = os.getenv("KODA_DEV_FRONTEND_PORT", "5173")
    return [
        f"http://localhost:{frontend_port_str}",
        f"http://127.0.0.1:{frontend_port_str}",
    ]


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


async def _run_stalled_task_notification_loop() -> None:
    """后台周期扫描停滞任务并发送提醒."""
    from dsl.services.task_notification_service import TaskNotificationService

    while True:
        await asyncio.sleep(60)
        try:
            sent_notification_count_int = await asyncio.to_thread(
                TaskNotificationService.scan_and_send_stalled_task_notifications
            )
            if sent_notification_count_int > 0:
                logger.info(
                    "Processed %s stalled task reminder notification(s)",
                    sent_notification_count_int,
                )
        except asyncio.CancelledError:
            raise
        except Exception as stalled_task_scan_error:
            logger.exception(
                "Stalled task notification scan failed: %s",
                stalled_task_scan_error,
            )


async def _run_task_schedule_dispatch_loop() -> None:
    """后台周期扫描到期调度规则并分发执行."""
    from dsl.services.task_scheduler_dispatcher import TaskSchedulerDispatcher

    while True:
        try:
            processed_schedule_count_int = await asyncio.to_thread(
                TaskSchedulerDispatcher.dispatch_due_schedules,
                config.SCHEDULER_MAX_DISPATCH_PER_TICK,
            )
            if processed_schedule_count_int > 0:
                logger.info(
                    "Processed %s task schedule dispatch(es)",
                    processed_schedule_count_int,
                )
        except asyncio.CancelledError:
            raise
        except Exception as task_schedule_dispatch_error:
            logger.exception(
                "Task schedule dispatch loop failed: %s",
                task_schedule_dispatch_error,
            )

        await asyncio.sleep(config.SCHEDULER_POLL_INTERVAL_SECONDS)


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

    stalled_task_notification_task = asyncio.create_task(
        _run_stalled_task_notification_loop()
    )
    task_schedule_dispatch_task = (
        asyncio.create_task(_run_task_schedule_dispatch_loop())
        if config.SCHEDULER_ENABLE
        else None
    )

    try:
        yield
    finally:
        stalled_task_notification_task.cancel()
        with suppress(asyncio.CancelledError):
            await stalled_task_notification_task
        if task_schedule_dispatch_task is not None:
            task_schedule_dispatch_task.cancel()
            with suppress(asyncio.CancelledError):
                await task_schedule_dispatch_task

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
        allow_origins=_build_dev_cors_origins(),  # Vite 开发服务器
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册 API 路由
    application.include_router(app_config_router)
    application.include_router(run_accounts_router)
    application.include_router(projects_router)
    application.include_router(tasks_router)
    application.include_router(task_qa_router)
    application.include_router(task_schedules_router)
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

    if config.SERVE_FRONTEND_DIST:
        _register_frontend_dist_routes(application)

    return application


def _register_frontend_dist_routes(application: FastAPI) -> None:
    """在公网模式下注册同源前端静态资源与 SPA fallback.

    Args:
        application: FastAPI 应用实例

    Raises:
        RuntimeError: 当前端构建目录不存在或缺少 `index.html` 时抛出
    """
    frontend_dist_path = config.FRONTEND_DIST_PATH.resolve()
    frontend_index_path = frontend_dist_path / "index.html"

    if not frontend_dist_path.exists() or not frontend_index_path.exists():
        raise RuntimeError(
            "SERVE_FRONTEND_DIST=true 但未找到 frontend/dist。"
            "请先执行 `npm --prefix frontend run build`，"
            f"当前 FRONTEND_DIST_PATH={frontend_dist_path}"
        )

    logger.info("Serving packaged frontend dist from %s", frontend_dist_path)

    @application.get("/", include_in_schema=False)
    async def serve_frontend_root() -> FileResponse:
        """返回前端首页."""
        return FileResponse(frontend_index_path)

    @application.get("/{frontend_path:path}", include_in_schema=False)
    async def serve_frontend_path(frontend_path: str) -> FileResponse:
        """返回前端静态资源或 SPA fallback.

        Args:
            frontend_path: 请求的相对路径

        Returns:
            FileResponse: 静态资源文件或 `index.html`

        Raises:
            HTTPException: 当请求命中保留后端前缀或越界/缺失静态文件时抛出
        """
        normalized_frontend_path = frontend_path.strip("/")
        if normalized_frontend_path == "":
            return FileResponse(frontend_index_path)

        if (
            normalized_frontend_path == "health"
            or normalized_frontend_path.startswith("api/")
            or normalized_frontend_path == "api"
            or normalized_frontend_path.startswith("media/")
            or normalized_frontend_path == "media"
        ):
            raise HTTPException(status_code=404, detail="Not Found")

        candidate_asset_path = (frontend_dist_path / normalized_frontend_path).resolve()
        if frontend_dist_path not in candidate_asset_path.parents:
            raise HTTPException(status_code=404, detail="Not Found")

        if candidate_asset_path.is_file():
            return FileResponse(candidate_asset_path)

        if Path(normalized_frontend_path).suffix:
            raise HTTPException(status_code=404, detail="Not Found")

        return FileResponse(frontend_index_path)


# 全局应用实例
app = create_application()
