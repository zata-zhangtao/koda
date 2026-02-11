"""DSL API 路由模块.

包含所有 FastAPI 路由定义：
- run_accounts: 运行账户管理
- tasks: 任务生命周期管理
- logs: 日志 CRUD
- media: 图片上传和服务
- chronicle: 编年史视图和导出
"""

from dsl.api.run_accounts import router as run_accounts_router
from dsl.api.tasks import router as tasks_router
from dsl.api.logs import router as logs_router
from dsl.api.media import router as media_router
from dsl.api.chronicle import router as chronicle_router

__all__ = [
    "run_accounts_router",
    "tasks_router",
    "logs_router",
    "media_router",
    "chronicle_router",
]
