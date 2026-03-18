# 快速开始

## 环境要求

### 必需工具

- Python `3.13`
- `uv`
- Node.js 与 `npm`
- `just`

### 可选工具

- `codex` CLI：用于任务启动后的 PRD 生成与编码执行
- `trae-cn`：用于从 Web 界面直接打开项目目录或 worktree
- 终端启动器：`open-terminal` 默认支持 macOS、WSL 和常见 Linux 桌面终端

如果默认终端启动器不适合你的环境，可以在根目录 `.env` 中设置：

```bash
KODA_OPEN_TERMINAL_COMMAND='cmd.exe /c start "" wsl.exe bash -lc {tail_command_shell}'
```

可用占位符：

- `{log_file}`：原始日志路径
- `{log_file_shell}`：Shell 转义后的日志路径
- `{tail_command}`：原始 `tail -f ...` 命令
- `{tail_command_shell}`：Shell 转义后的 `tail -f ...` 命令

## 安装依赖

后端、测试和文档依赖都由 `uv` 管理：

```bash
uv sync
```

前端依赖位于 `frontend/`：

```bash
cd frontend && npm install
cd ..
```

如果你希望顺手安装开发期 hooks，可以直接执行：

```bash
just dev
```

## 启动项目

最直接的本地开发方式：

```bash
just dsl-dev
```

这个命令会做以下事情：

1. 创建 `data/media/original` 与 `data/media/thumbnail`
2. 先检查 `8000` 和 `5173` 端口是否空闲
3. 启动 FastAPI 后端
4. 启动 Vite 前端

如果任一端口已被占用，`just dsl-dev` 会立即退出并打印当前监听进程，避免出现“前端还在跑、后端已启动失败”这类半启动状态。命令退出时，也会主动清理本次启动的子进程。

如果你需要分别调试前后端，可以拆开运行：

```bash
just setup-data
uv run python main.py
cd frontend && npm run dev
```

## 本地地址

- 前端工作台：`http://localhost:5173`
- 后端 API：`http://localhost:8000`
- 健康检查：`http://localhost:8000/health`

## 首次启动后会发生什么

- `dsl.app` 的 `lifespan` 会调用 `create_tables(Base)`，自动创建缺失的数据表。
- `/api/run-accounts/current` 首次访问时，如果数据库中还没有活跃账户，会自动创建一个默认 `RunAccount`。
- 媒体目录会在应用启动或上传文件时自动补齐。

## 关键目录

- `dsl/`：后端路由、服务、模型与 Schema
- `frontend/`：React + Vite 前端
- `utils/`：配置、日志、数据库
- `ai_agent/`：模型配置加载工具
- `data/`：SQLite 数据库与媒体文件
- `docs/`：MkDocs 文档站点

## 文档命令

本仓库已经在 `justfile` 中提供 MkDocs 命令入口：

```bash
just docs-serve
```

严格构建：

```bash
just docs-build
```

## 常见问题

### 前端能打开，但接口请求失败

优先确认后端是否已经启动，并检查 `http://localhost:8000/health` 是否返回 JSON。

### `just dsl-dev` 提示 `Address already in use`

这通常表示 `8000` 或 `5173` 上已经有旧的开发进程在监听。先根据命令输出里打印的监听进程定位并停止它，再重新运行 `just dsl-dev`。

### 任务点击“开始任务”后没有自动生成 PRD

优先检查开发机上是否安装了 `codex` CLI。当前实现中，如果找不到 `codex`，后端会写入一条 `BUG` 类型的 DevLog，并把阶段回退到 `changes_requested`。

### 点击“打开终端”没有反应或报错

优先确认任务日志文件已经生成。若你在 Linux/WSL 下使用了非常规终端，请设置 `KODA_OPEN_TERMINAL_COMMAND` 指向可用的启动命令。

### 图片或附件上传失败

优先确认 `data/media/` 目录存在且当前用户有写权限。

### 文档构建失败

先执行 `uv sync`，确保 `mkdocs`、`mkdocs-material`、`mkdocstrings[python]` 和 `pymdown-extensions` 已安装，再重新运行 `just docs-build`。
