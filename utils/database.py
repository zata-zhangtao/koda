"""通用数据库连接模块.

此模块提供 SQLAlchemy 数据库连接、建表和会话管理功能。
"""

from threading import Lock
from typing import Any, Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from sqlalchemy.pool import NullPool, StaticPool

from utils.settings import config
from utils.logger import logger

# 创建声明式基类，供模型继承
Base = declarative_base()

_INCREMENTAL_SCHEMA_PATCHES: tuple[tuple[str, str], ...] = (
    (
        "ALTER TABLE tasks ADD COLUMN requirement_brief VARCHAR(5000)",
        "Migration: added requirement_brief column to tasks",
    ),
    (
        "ALTER TABLE tasks ADD COLUMN stage_updated_at DATETIME",
        "Migration: added stage_updated_at column to tasks",
    ),
    (
        "ALTER TABLE tasks ADD COLUMN last_ai_activity_at DATETIME",
        "Migration: added last_ai_activity_at column to tasks",
    ),
    (
        "ALTER TABLE tasks ADD COLUMN auto_confirm_prd_and_execute "
        "BOOLEAN NOT NULL DEFAULT 0",
        "Migration: added auto_confirm_prd_and_execute column to tasks",
    ),
    (
        "ALTER TABLE projects ADD COLUMN repo_remote_url VARCHAR(500)",
        "Migration: added repo_remote_url column to projects",
    ),
    (
        "ALTER TABLE projects ADD COLUMN repo_head_commit_hash VARCHAR(64)",
        "Migration: added repo_head_commit_hash column to projects",
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_tasks_run_account_created_at "
        "ON tasks (run_account_id, created_at)",
        "Migration: ensured idx_tasks_run_account_created_at",
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_tasks_stage_updated_at "
        "ON tasks (workflow_stage, stage_updated_at)",
        "Migration: ensured idx_tasks_stage_updated_at",
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_dev_logs_task_created_at "
        "ON dev_logs (task_id, created_at)",
        "Migration: ensured idx_dev_logs_task_created_at",
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_dev_logs_run_account_created_at "
        "ON dev_logs (run_account_id, created_at)",
        "Migration: ensured idx_dev_logs_run_account_created_at",
    ),
    (
        "ALTER TABLE email_settings ADD COLUMN stalled_task_threshold_minutes "
        "INTEGER NOT NULL DEFAULT 20",
        "Migration: added stalled_task_threshold_minutes column to email_settings",
    ),
    (
        "UPDATE tasks SET stage_updated_at = CURRENT_TIMESTAMP "
        "WHERE stage_updated_at IS NULL",
        "Migration: backfilled missing stage_updated_at values on tasks",
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_task_qa_messages_task_created_at "
        "ON task_qa_messages (task_id, created_at)",
        "Migration: ensured idx_task_qa_messages_task_created_at",
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_task_qa_messages_task_status_role "
        "ON task_qa_messages (task_id, generation_status, role)",
        "Migration: ensured idx_task_qa_messages_task_status_role",
    ),
)
_database_initialization_lock = Lock()
_initialized_database_keys: set[tuple[int, int]] = set()
_SQLITE_BUSY_TIMEOUT_MS = 30_000
_TASK_QA_DUPLICATE_PENDING_REPAIR_ERROR_TEXT = (
    "This sidecar Q&A reply was released during schema repair because another "
    "pending reply already existed for the same task."
)

# 从配置中获取数据库URL
DATABASE_URL = config.DATABASE_URL

# 如果是 MySQL 数据库，确保使用 pymysql 驱动
if DATABASE_URL.startswith("mysql://"):
    DATABASE_URL = DATABASE_URL.replace("mysql://", "mysql+pymysql://")


def _is_sqlite_database_url(database_url_str: str) -> bool:
    """判断数据库 URL 是否使用 SQLite 方言.

    Args:
        database_url_str: 数据库连接 URL

    Returns:
        bool: 若为 SQLite URL 则返回 True
    """
    return database_url_str.startswith("sqlite")


def _configure_sqlite_connection(
    dbapi_connection: Any,
    _connection_record: Any,
) -> None:
    """为 SQLite 连接设置并发友好的 PRAGMA.

    Args:
        dbapi_connection: 原生 DB-API 连接对象
        _connection_record: SQLAlchemy 连接记录（未使用）
    """
    sqlite_cursor = dbapi_connection.cursor()
    try:
        sqlite_cursor.execute(f"PRAGMA busy_timeout = {_SQLITE_BUSY_TIMEOUT_MS}")
        sqlite_cursor.execute("PRAGMA foreign_keys = ON")

        # WAL 允许读写更好地并行；某些特殊 SQLite 目标不支持时可安全跳过。
        try:
            sqlite_cursor.execute("PRAGMA journal_mode = WAL")
            sqlite_cursor.execute("PRAGMA synchronous = NORMAL")
        except (
            Exception
        ) as sqlite_pragmas_error:  # pragma: no cover - defensive fallback
            logger.debug("Skipped SQLite WAL pragmas: %s", sqlite_pragmas_error)
    finally:
        sqlite_cursor.close()


def create_database_engine(**kwargs: Any) -> Engine:
    """创建数据库引擎

    Args:
        **kwargs: 传递给 create_engine 的额外参数

    Returns:
        sqlalchemy.engine.Engine: 数据库引擎实例

    Examples:
        >>> engine = create_database_engine(echo=True)
        >>> engine = create_database_engine(pool_size=10)
    """
    default_kwargs: dict[str, Any] = {
        "echo": False,  # 设置为 True 可以看到 SQL 语句，便于调试
    }
    provided_connect_args = kwargs.pop("connect_args", None)

    # SQLite 需要 check_same_thread=False 以支持多线程并发请求
    # 使用 NullPool 避免多请求共享同一连接导致的 cursor 冲突
    if _is_sqlite_database_url(DATABASE_URL):
        sqlite_connect_args = {
            "check_same_thread": False,
            "timeout": _SQLITE_BUSY_TIMEOUT_MS / 1000,
        }
        if provided_connect_args:
            sqlite_connect_args.update(provided_connect_args)
        default_kwargs["connect_args"] = sqlite_connect_args
        default_kwargs["poolclass"] = NullPool
    else:
        if provided_connect_args is not None:
            default_kwargs["connect_args"] = provided_connect_args
        default_kwargs["poolclass"] = StaticPool

    default_kwargs.update(kwargs)

    database_engine = create_engine(DATABASE_URL, **default_kwargs)
    if _is_sqlite_database_url(DATABASE_URL):
        event.listen(database_engine, "connect", _configure_sqlite_connection)
    return database_engine


# 创建默认引擎
engine = create_database_engine()


def _import_dsl_models() -> None:
    """导入 DSL 所有 ORM 模型，确保 Base.metadata 注册完整."""
    import dsl.models  # noqa: F401


def _run_incremental_schema_patches(database_engine: Engine) -> None:
    """执行少量内置的增量补丁.

    Args:
        database_engine: 需要应用补丁的数据库引擎
    """
    with database_engine.connect() as database_connection:
        for (
            schema_patch_sql_str,
            success_log_message_str,
        ) in _INCREMENTAL_SCHEMA_PATCHES:
            try:
                database_connection.execute(text(schema_patch_sql_str))
                database_connection.commit()
                logger.info(success_log_message_str)
            except Exception:
                # 列已存在或目标表尚未创建时安全忽略
                pass

    _ensure_task_qa_single_pending_reply_index(database_engine)


def _ensure_task_qa_single_pending_reply_index(database_engine: Engine) -> None:
    """Repair duplicate pending sidecar replies and enforce the SQLite invariant.

    Args:
        database_engine: Database engine that may need the SQLite-only index.
    """

    if database_engine.dialect.name != "sqlite":
        return

    with database_engine.begin() as database_connection:
        try:
            pending_row_mapping_list = (
                database_connection.execute(
                    text(
                        "SELECT id, task_id "
                        "FROM task_qa_messages "
                        "WHERE role = 'assistant' "
                        "AND generation_status = 'pending' "
                        "ORDER BY task_id ASC, created_at DESC, id DESC"
                    )
                )
                .mappings()
                .all()
            )
        except Exception:
            return

        seen_task_id_set: set[str] = set()
        duplicate_pending_message_id_list: list[str] = []
        for pending_row_mapping in pending_row_mapping_list:
            task_id_str = str(pending_row_mapping["task_id"])
            if task_id_str in seen_task_id_set:
                duplicate_pending_message_id_list.append(str(pending_row_mapping["id"]))
                continue
            seen_task_id_set.add(task_id_str)

        if duplicate_pending_message_id_list:
            database_connection.execute(
                text(
                    "UPDATE task_qa_messages "
                    "SET generation_status = :failed_status, "
                    "error_text = :error_text, "
                    "updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = :message_id"
                ),
                [
                    {
                        "failed_status": "failed",
                        "error_text": _TASK_QA_DUPLICATE_PENDING_REPAIR_ERROR_TEXT,
                        "message_id": duplicate_pending_message_id,
                    }
                    for duplicate_pending_message_id in duplicate_pending_message_id_list
                ],
            )
            logger.warning(
                "Released %s duplicate pending sidecar Q&A replies during schema repair",
                len(duplicate_pending_message_id_list),
            )

        database_connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_task_qa_messages_single_pending_assistant "
                "ON task_qa_messages (task_id) "
                "WHERE role = 'assistant' AND generation_status = 'pending'"
            )
        )
        logger.info("Migration: ensured uq_task_qa_messages_single_pending_assistant")


def create_tables(base: Any = None, database_engine: Engine | None = None) -> None:
    """创建所有表

    Args:
        base: SQLAlchemy 声明式基类，默认使用本模块的 Base
        database_engine: 数据库引擎，默认使用本模块全局 engine

    Examples:
        >>> from utils.database import Base, create_tables
        >>> # 定义模型后
        >>> create_tables()
    """
    if base is None:
        base = Base
    if database_engine is None:
        database_engine = engine
    base.metadata.create_all(bind=database_engine)
    logger.info("数据库表创建成功！")


def ensure_database_schema_ready(
    base: Any = None,
    database_engine: Engine | None = None,
) -> None:
    """确保数据库结构已经就绪.

    这个方法会注册全部 ORM 模型、创建缺失表，并执行少量内置增量补丁。
    它是幂等的，可在应用启动和会话创建时重复调用。

    Args:
        base: SQLAlchemy 声明式基类，默认使用本模块的 Base
        database_engine: 数据库引擎，默认使用本模块全局 engine
    """
    target_base = Base if base is None else base
    target_database_engine = engine if database_engine is None else database_engine
    initialization_key = (id(target_base.metadata), id(target_database_engine))

    with _database_initialization_lock:
        if initialization_key in _initialized_database_keys:
            return

        _import_dsl_models()
        create_tables(base=target_base, database_engine=target_database_engine)
        _run_incremental_schema_patches(target_database_engine)
        _initialized_database_keys.add(initialization_key)


class DatabaseSession(Session):
    """带有数据库自举能力的 Session.

    在首次创建会话时，自动确保目标数据库的表结构已经初始化，
    从而避免请求先于 FastAPI lifespan 访问数据库时出现空库报错。
    """

    @staticmethod
    def _resolve_engine_from_bind(bound_resource: Any) -> Engine | None:
        """从 SQLAlchemy bind 对象中解析 Engine.

        Args:
            bound_resource: `Session` 构造函数收到的 `bind` 或 `binds` 条目

        Returns:
            Engine | None: 解析到的数据库引擎；若无法解析则返回 None
        """
        if isinstance(bound_resource, Engine):
            return bound_resource

        resolved_engine_obj = getattr(bound_resource, "engine", None)
        if isinstance(resolved_engine_obj, Engine):
            return resolved_engine_obj

        return None

    def __init__(self, **kwargs: Any) -> None:
        """初始化 Session 前先保证数据库结构存在."""
        requested_bind_obj = kwargs.get("bind")
        resolved_database_engine = self._resolve_engine_from_bind(requested_bind_obj)

        if resolved_database_engine is None:
            requested_bind_mapping = kwargs.get("binds") or {}
            if requested_bind_mapping:
                first_bound_resource = next(iter(requested_bind_mapping.values()))
                resolved_database_engine = self._resolve_engine_from_bind(
                    first_bound_resource
                )

        ensure_database_schema_ready(database_engine=resolved_database_engine or engine)
        super().__init__(**kwargs)


# 创建会话工厂
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=DatabaseSession,
)


def get_db() -> Generator[Session, None, None]:
    """获取数据库会话（生成器模式）

    用于依赖注入场景（如 FastAPI）

    Yields:
        Session: 数据库会话实例

    Examples:
        >>> from utils.database import get_db
        >>>
        >>> # FastAPI 中使用
        >>> @app.get("/items/")
        >>> def read_items(db: Session = Depends(get_db)):
        >>>     return db.query(Item).all()
    """
    ensure_database_schema_ready()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_database(base: Any = None) -> None:
    """初始化数据库

    创建所有表结构

    Args:
        base: SQLAlchemy 声明式基类，默认使用本模块的 Base

    Examples:
        >>> from utils.database import init_database
        >>> init_database()
    """
    ensure_database_schema_ready(base=base)
