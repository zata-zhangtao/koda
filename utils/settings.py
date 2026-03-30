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


def _load_float_env(env_var_name: str, default_value: float) -> float:
    """读取浮点数环境变量.

    Args:
        env_var_name (str): 环境变量名
        default_value (float): 默认值

    Returns:
        float: 解析后的浮点数
    """
    raw_env_value = os.getenv(env_var_name)
    if raw_env_value is None or raw_env_value.strip() == "":
        return default_value
    try:
        return float(raw_env_value)
    except ValueError:
        return default_value


def _load_positive_int_env(env_var_name: str, default_value: int) -> int:
    """读取正整数环境变量.

    Args:
        env_var_name (str): 环境变量名
        default_value (int): 默认值

    Returns:
        int: 解析后的正整数

    Raises:
        ValueError: 当环境变量不是合法正整数时抛出
    """
    raw_env_value = os.getenv(env_var_name)
    if raw_env_value is None or raw_env_value.strip() == "":
        return default_value

    try:
        parsed_int_value = int(raw_env_value)
    except ValueError as value_error:
        raise ValueError(
            f"{env_var_name} must be an integer, got: {raw_env_value}"
        ) from value_error

    if parsed_int_value <= 0:
        raise ValueError(
            f"{env_var_name} must be a positive integer, got: {raw_env_value}"
        )
    return parsed_int_value


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


def _load_automation_runner_kind() -> str:
    """Load and validate automation runner kind.

    Returns:
        str: Normalized runner kind value.

    Raises:
        ValueError: When the configured runner kind is unsupported.
    """
    raw_runner_kind_str = os.getenv("KODA_AUTOMATION_RUNNER", "codex")
    normalized_runner_kind_str = raw_runner_kind_str.strip().lower()
    supported_runner_kind_set = {"codex", "claude"}
    if normalized_runner_kind_str in supported_runner_kind_set:
        return normalized_runner_kind_str

    supported_runner_kind_text = ", ".join(sorted(supported_runner_kind_set))
    raise ValueError(
        "Invalid KODA_AUTOMATION_RUNNER value: "
        f"{raw_runner_kind_str}. Supported values: {supported_runner_kind_text}"
    )


def _load_task_qa_backend() -> str:
    """加载任务独立问答后端类型.

    Returns:
        str: 合法的 sidecar Q&A 后端类型

    Raises:
        ValueError: 当 `TASK_QA_BACKEND` 不是支持的后端类型时抛出
    """

    raw_task_qa_backend = os.getenv("TASK_QA_BACKEND", "chat_model")
    normalized_task_qa_backend = raw_task_qa_backend.strip().lower()
    if normalized_task_qa_backend == "chat_model":
        return normalized_task_qa_backend
    raise ValueError(
        f"Invalid TASK_QA_BACKEND value: {raw_task_qa_backend}. Expected: chat_model"
    )


class Config:
    """配置类 - 集中管理所有配置项

    Attributes:
        BASE_DIR (Path): 项目根目录
        LOG_DIR (Path): 日志文件目录
        LOG_FILE (Path): 日志文件路径
        LOG_LEVEL (str): 日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）
        APP_NAME (str): 应用名称，用于日志记录器命名
        APP_TIMEZONE (str): 应用级展示时区（IANA 名称）
        KODA_AUTOMATION_RUNNER (str): 自动化执行器类型（`codex` 或 `claude`）
        OPEN_PATH_COMMAND_TEMPLATE (str): 打开项目目录 / worktree 的命令模板
        TERMINAL_OPEN_COMMAND_TEMPLATE (str | None): 终端打开命令模板（可选）
        SERVE_FRONTEND_DIST (bool): 是否由 FastAPI 同源托管 `frontend/dist`
        FRONTEND_DIST_PATH (Path): 前端构建产物目录
        KODA_PUBLIC_BASE_URL (str | None): 公网访问基础地址
        KODA_TUNNEL_SERVER_URL (str): 隧道服务器基础地址
        KODA_TUNNEL_ID (str): 单租户隧道标识
        KODA_TUNNEL_SHARED_TOKEN (str): agent 与 gateway 共用鉴权令牌
        KODA_TUNNEL_UPSTREAM_URL (str): 本地 agent 转发的上游地址
        TASK_QA_BACKEND (str): 任务内独立问答使用的后端类型
        TASK_QA_MODEL_NAME (str): 当问答后端切换到聊天模型时使用的模型名
        TASK_QA_MODEL_TEMPERATURE (float): 问答聊天模型温度
        WORKTREE_BRANCH_AI_NAMING_ENABLED (bool): 是否启用 AI worktree 分支命名
        WORKTREE_BRANCH_AI_MODEL (str): 用于 worktree 分支命名的模型名
        WORKTREE_BRANCH_AI_TIMEOUT_SECONDS (float): AI 命名超时时间（秒）
        SCHEDULER_ENABLE (bool): 是否启用任务调度器
        SCHEDULER_POLL_INTERVAL_SECONDS (int): 调度轮询间隔（秒）
        SCHEDULER_MAX_DISPATCH_PER_TICK (int): 每轮最多派发条数
    """

    # 目录配置
    BASE_DIR: ClassVar[Path] = Path(__file__).resolve().parent.parent
    LOG_DIR: ClassVar[Path] = BASE_DIR / "logs"
    LOG_FILE: ClassVar[Path] = LOG_DIR / "app.log"

    # 日志配置
    LOG_LEVEL: ClassVar[str] = os.getenv("LOG_LEVEL", "INFO")
    APP_NAME: ClassVar[str] = os.getenv("APP_NAME", "app")
    APP_TIMEZONE: ClassVar[str] = _load_app_timezone_name()
    KODA_AUTOMATION_RUNNER: ClassVar[str] = _load_automation_runner_kind()

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

    # 任务内独立问答配置
    TASK_QA_BACKEND: ClassVar[str] = _load_task_qa_backend()
    TASK_QA_MODEL_NAME: ClassVar[str] = os.getenv(
        "TASK_QA_MODEL_NAME",
        "qwen-plus",
    )
    TASK_QA_MODEL_TEMPERATURE: ClassVar[float] = _load_float_env(
        "TASK_QA_MODEL_TEMPERATURE",
        0.0,
    )

    # 目录打开命令模板
    OPEN_PATH_COMMAND_TEMPLATE: ClassVar[str] = os.getenv(
        "KODA_OPEN_PATH_COMMAND_TEMPLATE",
        "trae-cn {target_path_shell}",
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
    WORKTREE_BRANCH_AI_NAMING_ENABLED: ClassVar[bool] = _load_bool_env(
        "WORKTREE_BRANCH_AI_NAMING_ENABLED",
        True,
    )
    WORKTREE_BRANCH_AI_MODEL: ClassVar[str] = os.getenv(
        "WORKTREE_BRANCH_AI_MODEL",
        "qwen-flash",
    )
    WORKTREE_BRANCH_AI_TIMEOUT_SECONDS: ClassVar[float] = _load_float_env(
        "WORKTREE_BRANCH_AI_TIMEOUT_SECONDS",
        8.0,
    )

    # 任务调度器配置
    SCHEDULER_ENABLE: ClassVar[bool] = _load_bool_env("SCHEDULER_ENABLE", True)
    SCHEDULER_POLL_INTERVAL_SECONDS: ClassVar[int] = _load_positive_int_env(
        "SCHEDULER_POLL_INTERVAL_SECONDS",
        30,
    )
    SCHEDULER_MAX_DISPATCH_PER_TICK: ClassVar[int] = _load_positive_int_env(
        "SCHEDULER_MAX_DISPATCH_PER_TICK",
        20,
    )

    # Runner 看门狗配置
    RUNNER_WATCHDOG_POLL_INTERVAL_SECONDS: ClassVar[int] = _load_positive_int_env(
        "RUNNER_WATCHDOG_POLL_INTERVAL_SECONDS",
        60,
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
