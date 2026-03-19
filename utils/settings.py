"""配置文件 - 集中管理所有环境变量和配置"""

import os
from pathlib import Path
from typing import ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()


def _load_bool_env(env_var_name: str, default_value: bool) -> bool:
    """读取布尔环境变量.

    Args:
        env_var_name (str): 环境变量名
        default_value (bool): 默认值

    Returns:
        bool: 解析后的布尔值
    """
    raw_env_value = os.getenv(env_var_name)
    if raw_env_value is None:
        return default_value
    return raw_env_value.strip().lower() in {"1", "true", "yes", "on"}


def _load_path_env(env_var_name: str, default_path: Path) -> Path:
    """读取路径环境变量.

    Args:
        env_var_name (str): 环境变量名
        default_path (Path): 默认路径

    Returns:
        Path: 解析后的路径对象
    """
    raw_env_value = os.getenv(env_var_name)
    if raw_env_value is None or raw_env_value.strip() == "":
        return default_path
    return Path(raw_env_value).expanduser()


def _load_app_timezone_name() -> str:
    """加载并验证应用时区配置.

    Returns:
        str: 合法的 IANA 时区名称

    Raises:
        ValueError: 当 `APP_TIMEZONE` 不是合法时区名称时抛出
    """
    app_timezone_name = os.getenv("APP_TIMEZONE", "Asia/Shanghai")
    try:
        ZoneInfo(app_timezone_name)
    except ZoneInfoNotFoundError as timezone_error:
        raise ValueError(
            f"Invalid APP_TIMEZONE value: {app_timezone_name}"
        ) from timezone_error
    return app_timezone_name


class Config:
    """配置类 - 集中管理所有配置项

    Attributes:
        BASE_DIR (Path): 项目根目录
        LOG_DIR (Path): 日志文件目录
        LOG_FILE (Path): 日志文件路径
        LOG_LEVEL (str): 日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）
        APP_NAME (str): 应用名称，用于日志记录器命名
        APP_TIMEZONE (str): 应用级展示时区（IANA 名称）
        TERMINAL_OPEN_COMMAND_TEMPLATE (str | None): 终端打开命令模板（可选）
        SERVE_FRONTEND_DIST (bool): 是否由 FastAPI 同源托管 `frontend/dist`
        FRONTEND_DIST_PATH (Path): 前端构建产物目录
        KODA_PUBLIC_BASE_URL (str | None): 公网访问基础地址
        KODA_TUNNEL_SERVER_URL (str): 隧道服务器基础地址
        KODA_TUNNEL_ID (str): 单租户隧道标识
        KODA_TUNNEL_SHARED_TOKEN (str): agent 与 gateway 共用鉴权令牌
        KODA_TUNNEL_UPSTREAM_URL (str): 本地 agent 转发的上游地址
    """

    # 目录配置
    BASE_DIR: ClassVar[Path] = Path(__file__).resolve().parent.parent
    LOG_DIR: ClassVar[Path] = BASE_DIR / "logs"
    LOG_FILE: ClassVar[Path] = LOG_DIR / "app.log"

    # 日志配置
    LOG_LEVEL: ClassVar[str] = os.getenv("LOG_LEVEL", "INFO")
    APP_NAME: ClassVar[str] = os.getenv("APP_NAME", "app")
    APP_TIMEZONE: ClassVar[str] = _load_app_timezone_name()

    # 数据库配置
    DATABASE_URL: ClassVar[str] = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'dsl.db'}"
    )

    # DSL 媒体存储路径
    MEDIA_STORAGE_PATH: ClassVar[Path] = BASE_DIR / "data" / "media"

    # AI 置信度阈值 (Phase 2)
    AI_CONFIDENCE_THRESHOLD: ClassVar[float] = float(
        os.getenv("AI_CONFIDENCE_THRESHOLD", "0.85")
    )

    # 终端打开命令模板（用于 Linux/WSL 覆盖默认行为）
    TERMINAL_OPEN_COMMAND_TEMPLATE: ClassVar[str | None] = os.getenv(
        "KODA_OPEN_TERMINAL_COMMAND"
    )

    # DSL 公网打包运行模式
    SERVE_FRONTEND_DIST: ClassVar[bool] = _load_bool_env(
        "SERVE_FRONTEND_DIST",
        False,
    )
    FRONTEND_DIST_PATH: ClassVar[Path] = _load_path_env(
        "FRONTEND_DIST_PATH",
        BASE_DIR / "frontend" / "dist",
    )

    # 公网转发 / 隧道配置
    KODA_PUBLIC_BASE_URL: ClassVar[str | None] = os.getenv("KODA_PUBLIC_BASE_URL")
    KODA_TUNNEL_SERVER_URL: ClassVar[str] = os.getenv(
        "KODA_TUNNEL_SERVER_URL",
        "ws://127.0.0.1:9000",
    )
    KODA_TUNNEL_ID: ClassVar[str] = os.getenv("KODA_TUNNEL_ID", "default")
    KODA_TUNNEL_SHARED_TOKEN: ClassVar[str] = os.getenv(
        "KODA_TUNNEL_SHARED_TOKEN",
        "",
    )
    KODA_TUNNEL_UPSTREAM_URL: ClassVar[str] = os.getenv(
        "KODA_TUNNEL_UPSTREAM_URL",
        "http://127.0.0.1:8000",
    )

    @classmethod
    def ensure_log_directory(cls) -> None:
        """确保日志目录存在

        如果日志目录不存在则创建。

        Raises:
            OSError: 当无法创建目录时抛出
        """
        cls.LOG_DIR.mkdir(parents=True, exist_ok=True)


# 全局配置实例
config = Config()

# 确保日志目录存在
config.ensure_log_directory()
