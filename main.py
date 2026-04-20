"""DevStream Log (DSL) 入口模块.

提供 FastAPI 服务器的启动入口。
"""

import os

import uvicorn

from utils.logger import logger
from utils.settings import config


def main():
    """启动 DSL FastAPI 服务器.

    从环境变量 KODA_SERVER_PORT 读取监听端口，默认为 8000。
    """
    server_port: int = int(os.getenv("KODA_SERVER_PORT", "8000"))
    logger.info("Starting DevStream Log (DSL) server on port %d...", server_port)

    uvicorn.run(
        "backend.dsl.app:app",
        host="0.0.0.0",
        port=server_port,
        reload=not config.SERVE_FRONTEND_DIST,
        log_level="info",
    )


if __name__ == "__main__":
    main()
