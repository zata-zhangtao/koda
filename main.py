"""DevStream Log (DSL) 入口模块.

提供 FastAPI 服务器的启动入口。
"""

import uvicorn

from dsl.app import app
from utils.logger import logger


def main():
    """启动 DSL FastAPI 服务器.

    使用 uvicorn 启动开发服务器，监听 8000 端口。
    """
    logger.info("Starting DevStream Log (DSL) server...")

    uvicorn.run(
        "dsl.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
