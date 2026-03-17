# 快速开始

## 运行前提

- Python `3.13`
- `uv`
- Node.js 与 `npm`
- `just`

## 安装依赖

后端依赖和文档工具都由 `uv` 管理：

```bash
uv sync
```

前端依赖位于 `frontend/`：

```bash
cd frontend && npm install
```

## 启动 DSL

最省事的方式是直接使用现成的 `just` 配方：

```bash
just dsl-dev
```

这个命令会做三件事：

1. 创建 `data/media/original` 与 `data/media/thumbnail`
2. 启动 FastAPI 后端
3. 启动 Vite 前端

如果你希望分开调试，也可以单独执行：

```bash
just setup-data
uv run python main.py
cd frontend && npm run dev
```

## 本地访问地址

- 前端：`http://localhost:5173`
- 后端：`http://localhost:8000`
- 健康检查：`http://localhost:8000/health`

## 配置文件

仓库目前有两类主要配置入口：

- 根目录运行配置：`utils/settings.py`
- AI 模型配置：`ai_agent/.env.example` 与 `ai_agent/utils/models.json`

如果你需要自定义数据库或日志路径，优先从 `utils/settings.py` 着手。默认数据库是 `data/dsl.db`，媒体目录是 `data/media/`。

## 文档预览

```bash
just docs-serve
```

构建静态站点并启用严格检查：

```bash
just docs-build
```

## 常见排查

### 前端可以打开，但接口请求失败

优先检查 `main.py` 是否已经启动，以及 `http://localhost:8000/health` 是否返回 JSON。

### 图片上传失败

优先确认 `data/media/` 目录存在，并且当前用户对该目录有写权限。

### 文档构建失败

先执行 `uv sync`，确保 `mkdocs`、`mkdocs-material` 和 `mkdocstrings` 已安装，再重新运行 `just docs-build`。
