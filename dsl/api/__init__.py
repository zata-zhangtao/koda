"""DSL API 路由模块.

包含所有 FastAPI 路由定义：
- run_accounts: 运行账户管理
- tasks: 任务生命周期管理
- logs: 日志 CRUD
- media: 图片上传和服务
- chronicle: 编年史视图和导出
- projects: 项目管理
- task_schedules: 任务调度规则管理
- app_config: 前端运行时配置
"""

from dsl.api.app_config import router as app_config_router
from dsl.api.run_accounts import router as run_accounts_router
from dsl.api.tasks import router as tasks_router
from dsl.api.logs import router as logs_router
from dsl.api.media import router as media_router
from dsl.api.chronicle import router as chronicle_router
from dsl.api.projects import router as projects_router
from dsl.api.email_settings import router as email_settings_router
from dsl.api.task_schedules import router as task_schedules_router
from dsl.api.webdav_settings import router as webdav_settings_router

__all__ = [
    "app_config_router",
    "run_accounts_router",
    "tasks_router",
    "logs_router",
    "media_router",
    "chronicle_router",
    "projects_router",
    "email_settings_router",
    "task_schedules_router",
    "webdav_settings_router",
]
