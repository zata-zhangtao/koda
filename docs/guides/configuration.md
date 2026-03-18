# 配置说明

## 总览

Koda 的配置分散在少量关键文件中，但职责边界比较清晰：运行时配置看 `utils/settings.py`，前端端口和代理看 `frontend/vite.config.ts`，AI 提供商看 `ai_agent/`。

## 配置文件清单

| 位置 | 作用 | 关键内容 |
| --- | --- | --- |
| `pyproject.toml` | Python 依赖定义 | FastAPI、SQLAlchemy、LangChain、MkDocs、Pytest |
| `justfile` | 命令入口 | `run`、`dsl-dev`、`docs-serve`、`docs-build` |
| `utils/settings.py` | 后端运行配置 | 日志、数据库、应用时区、媒体目录、AI 阈值、终端启动命令 |
| `frontend/vite.config.ts` | 前端开发服务器配置 | 端口 `5173`、`/api` 与 `/media` 代理 |
| `ai_agent/.env.example` | AI 服务凭据示例 | `DASHSCOPE_API_KEY`、`OPENROUTER_API_KEY` 等 |
| `ai_agent/utils/models.json` | 模型注册表 | 提供商、基础 URL、模型分类 |
| `mkdocs.yml` | 文档站点配置 | 导航、插件、Mermaid 支持 |

## 后端运行配置

`utils/settings.py` 通过 `load_dotenv()` 读取根目录 `.env`，然后暴露 `Config` 类。

### 当前关键配置项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `LOG_LEVEL` | `INFO` | Python 日志级别 |
| `APP_NAME` | `app` | 日志记录器名称 |
| `APP_TIMEZONE` | `Asia/Shanghai` | 应用展示时区，控制 API 时间输出、Markdown 导出与业务日志时间 |
| `DATABASE_URL` | `sqlite:///.../data/dsl.db` | 默认 SQLite 数据库 |
| `MEDIA_STORAGE_PATH` | `<repo>/data/media` | 图片与附件目录 |
| `AI_CONFIDENCE_THRESHOLD` | `0.85` | AI 解析置信度阈值预留值 |
| `KODA_OPEN_TERMINAL_COMMAND` | 未设置 | 覆盖“打开终端”按钮的启动命令模板 |

### 注意点

- `MEDIA_STORAGE_PATH` 当前不是环境变量，而是直接由项目根路径推导。
- 如果你切换到 MySQL，`utils/database.py` 会自动把 `mysql://` 替换成 `mysql+pymysql://`。
- SQLite 模式下启用了 `check_same_thread=False` 与 `NullPool`。
- 业务时间采用“双层契约”：数据库继续存 UTC 语义的 naive datetime，API/UI/Markdown 导出统一转换为 `APP_TIMEZONE`，并带显式偏移输出。
- 前端启动时会请求只读接口 `/api/app-config`，用它同步 `APP_TIMEZONE`，避免 UI 与后端配置漂移。
- `KODA_OPEN_TERMINAL_COMMAND` 支持 `{log_file}`、`{log_file_shell}`、`{tail_command}`、`{tail_command_shell}` 四个占位符。

## 前端配置

`frontend/vite.config.ts` 当前约定如下：

- 开发端口固定为 `5173`
- `/api` 代理到 `http://localhost:8000`
- `/media` 代理到 `http://localhost:8000`
- 构建产物输出到 `frontend/dist`

如果你修改前端端口或域名，需要同时关注：

- `frontend/vite.config.ts`
- `dsl/app.py` 中的 CORS 白名单
- 本文档

## AI 提供商配置

### 环境变量

`ai_agent/.env.example` 当前给出了以下占位项：

- `DASHSCOPE_API_KEY`
- `OPENROUTER_API_KEY`
- `VECTORENGINE_API_KEY`
- `AZHEXING_API_KEY`
- `REDBOX_API_KEY`

真实密钥不应该提交到仓库。

### 模型注册表

`ai_agent/utils/models.json` 当前记录的提供商包括：

- `dashscope`
- `openrouter`
- `vectorengine`
- `azhexing`
- `redbox`

每个提供商都可以定义：

- `api_key_env`
- `base_url`
- 若干模型分类，如 `chat_models`、`coder_models`、`omni_models`

## 命令入口

`justfile` 已经把常用操作封装好了：

| 命令 | 作用 |
| --- | --- |
| `just sync` | 同步 Python 依赖 |
| `just dev` | 同步依赖并安装 pre-commit |
| `just run` | 启动后端 |
| `just dsl-dev` | 同时启动后端和前端 |
| `just docs-serve` | 预览文档 |
| `just docs-build` | 严格构建文档 |

`just dsl-dev` 现在会在启动前检查 `8000` 和 `5173` 是否空闲；如果某个端口已被占用，会直接退出并打印当前监听进程。命令退出时，也会清理本次启动的后端和前端子进程，避免留下陈旧监听器。

## 配置变更建议

### 修改运行目录或数据库时

优先改 `utils/settings.py`，不要在多个模块里分散读取环境变量。

如果你通过 WebDAV 在另一台机器上恢复数据库，还需要检查项目面板中的 `Project.repo_path`。这些路径是机器本地绑定，不会自动适配新的目录结构；当前版本会把失效项目标记为 `Need relink`，remote 不一致的项目标记为 `Wrong repo`，HEAD 偏离同步基线的项目标记为 `Commit drift`。

其中：

- `Need relink`：当前机器上找不到这个仓库路径
- `Wrong repo`：你绑定到了另一个 Git remote，系统会阻止把它当成原项目使用
- `Commit drift`：remote 一致，但当前 HEAD 不同于最近一次同步到 WebDAV 时记录的 commit；确认无误后再次执行 WebDAV 上传即可刷新同步基线

### 新增 AI 提供商时

至少同步修改：

1. `ai_agent/utils/models.json`
2. `ai_agent/.env.example`
3. 本页和[AI 资产](../core/ai-assets.md)

### 修改端口时

至少同步修改：

1. `frontend/vite.config.ts`
2. `dsl/app.py` 的 CORS 白名单
3. 本页和[快速开始](../getting-started.md)
