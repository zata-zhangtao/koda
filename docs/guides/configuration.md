# 配置说明

## 总览

Koda 的配置分散在少量关键文件中，但职责边界比较清晰：运行时配置看 `utils/settings.py`，前端端口和代理看 `frontend/vite.config.ts`，AI 提供商看 `ai_agent/`。

## 配置文件清单

| 位置 | 作用 | 关键内容 |
| --- | --- | --- |
| `pyproject.toml` | Python 依赖定义 | FastAPI、SQLAlchemy、LangChain、MkDocs、Pytest |
| `justfile` | 命令入口 | `run`、`dsl-dev`、`docs-serve`、`docs-build` |
| `utils/settings.py` | 后端运行配置 | 日志、数据库、媒体目录、AI 阈值 |
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
| `DATABASE_URL` | `sqlite:///.../data/dsl.db` | 默认 SQLite 数据库 |
| `MEDIA_STORAGE_PATH` | `<repo>/data/media` | 图片与附件目录 |
| `AI_CONFIDENCE_THRESHOLD` | `0.85` | AI 解析置信度阈值预留值 |

### 注意点

- `MEDIA_STORAGE_PATH` 当前不是环境变量，而是直接由项目根路径推导。
- 如果你切换到 MySQL，`utils/database.py` 会自动把 `mysql://` 替换成 `mysql+pymysql://`。
- SQLite 模式下启用了 `check_same_thread=False` 与 `NullPool`。

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

## 配置变更建议

### 修改运行目录或数据库时

优先改 `utils/settings.py`，不要在多个模块里分散读取环境变量。

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
