# 快速开始

本页与 `README.md` 使用同一套最小启动路径，避免在仓库入口和站内文档之间出现两套 onboarding 说明。

## 最小可执行路径

```bash
uv sync
cd frontend && npm install
cd ..
just dsl-dev
```

本地默认地址：

- 前端工作台：`http://localhost:5173`
- 后端 API：`http://localhost:8000`
- 健康检查：`http://localhost:8000/health`

如果你需要手动指定端口：

```bash
just dsl-dev backend_port=8100 frontend_port=5174
```

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

与 README 保持一致，最直接的本地开发方式是：

```bash
just dsl-dev
```

这个命令会做以下事情：

1. 创建 `data/media/original` 与 `data/media/thumbnail`
2. 若未显式传入 `backend_port`，则从 `8000` 开始为后端寻找空闲端口；若显式传入，则要求该端口必须空闲
3. 检查 `frontend_port`（默认 `5173`）是否空闲
4. 按选定端口启动 FastAPI 后端
5. 让 Vite 前端把 `/api` 与 `/media` 代理到当前后端端口

如果你显式指定的端口已被占用，`just dsl-dev` 会立即退出并打印当前监听进程，避免出现“前端还在跑、后端已启动失败”这类半启动状态。命令退出时，也会主动清理本次启动的子进程。

如果你需要分别调试前后端，可以拆开运行：

```bash
just setup-data
uv run python main.py
cd frontend && npm run dev
```

## 首次启动后会发生什么

- `dsl.app` 的 `lifespan` 会调用共享的数据库初始化逻辑，自动创建缺失的数据表并补齐少量内置列补丁。
- 即使某些调用路径绕过了 `lifespan`，首次创建数据库会话时也会再次执行同一套初始化逻辑，避免出现空 SQLite 文件但没有表结构的状态。
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

提交前请至少执行一次 `just docs-build`。如果你修改了工作流、函数签名、环境变量、命令或路径规范，请同步更新 `README.md`、本页和相关 `docs/` 页面；若新增、重命名或移动文档页面，还需要同步更新 `mkdocs.yml` 的 `nav`。

## 常见问题

### 前端能打开，但接口请求失败

优先确认后端是否已经启动，并检查当前后端端口上的 `/health` 是否返回 JSON；如果你使用了自定义端口，请把 `8000` 替换成实际端口。

### `just dsl-dev` 提示 `Address already in use`

这通常表示你请求的端口已经有旧进程在监听。先根据命令输出里打印的监听进程定位并停止它，再重新运行 `just dsl-dev`；如果只是想换端口，也可以直接执行 `just dsl-dev backend_port=8100 frontend_port=5174`。

### 任务点击“开始任务”后没有自动生成 PRD

优先检查当前配置执行器是否安装可用：

- `KODA_AUTOMATION_RUNNER=codex` 时检查 `codex`
- `KODA_AUTOMATION_RUNNER=claude` 时检查 `claude`

当前实现中，如果找不到对应可执行文件，后端会写入一条带 `runner_kind` 的 `BUG` 类型 DevLog，并把阶段回退到 `changes_requested`。

### 点击“打开终端”没有反应或报错

优先确认任务日志文件已经生成。若你在 Linux/WSL 下使用了非常规终端，请设置 `KODA_OPEN_TERMINAL_COMMAND` 指向可用的启动命令。

### 图片或附件上传失败

优先确认 `data/media/` 目录存在且当前用户有写权限。

### 文档构建失败

先执行 `uv sync`，确保 `mkdocs`、`mkdocs-material`、`mkdocstrings[python]` 和 `pymdown-extensions` 已安装，再重新运行 `just docs-build`。
