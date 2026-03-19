"""配置文件 - 集中管理所有环境变量和配置"""

import os
from pathlib import Path
from typing import ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()


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
