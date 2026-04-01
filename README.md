# Koda / DevStream Log 工作台

Koda 是一个围绕需求卡片、开发日志、PRD 和 Codex 自动化执行构建的开发工作台。这个仓库同时包含 FastAPI 后端、React 前端、MkDocs 文档站点，以及 `ai_agent/` 中可复用的模型配置工具。

## 核心能力

- 需求卡片与 `DevLog` 时间线：围绕任务沉淀上下文、反馈、附件和 AI 输出。
- Codex 自动化执行：支持生成 PRD、执行实现、自检 review，以及 `Complete` 阶段的 Git 收尾。
- 任务调度：支持 `once` / `cron` 自动触发 `start_task`、`resume_task` 和独立 `review_task`。
- 项目绑定与 worktree：任务可关联本地 Git 仓库，并在独立 worktree 中执行；创建时会同步复制 `.env*` 并准备基础依赖环境。
- 文档站点：`docs/` 承载深度说明，`docs/api/references.md` 继续作为对象级 API 参考入口。

## Quick Start

```bash
uv sync
cd frontend && npm install
cd ..
just dsl-dev
```

本地默认启动地址：

- 前端：`http://localhost:5173`
- 后端：`http://localhost:8000`
- 健康检查：`http://localhost:8000/health`

如需手动指定端口，可执行：

```bash
just dsl-dev backend_port=8100 frontend_port=5174
```

省略 `backend_port` 时，命令会从 `8000` 开始自动寻找空闲后端端口；`frontend_port` 默认是 `5173`，如被占用则需要显式换端口后重试。

可选开发命令：

```bash
just dev
```

`just dev` 会同步依赖并安装 `pre-commit` hooks；文档提交前请执行：

```bash
just docs-build
```

## 项目结构

- `dsl/`：FastAPI 路由、服务层、ORM 模型与 Schema。
- `frontend/`：React + Vite 工作台前端。
- `docs/`：MkDocs 文档站点。
- `ai_agent/`：模型注册、凭据解析和聊天模型工具。
- `tasks/`：任务产出的 PRD 等文件。
- `utils/`：配置、数据库、日志等基础设施代码。
- `data/`：SQLite 数据库和媒体文件目录。

## 文档地图

- [站内概览](docs/index.md)：仓库定位、模块边界与阅读路径。
- [快速开始](docs/getting-started.md)：环境要求、安装、启动与常见问题。
- [配置说明](docs/guides/configuration.md)：环境变量、端口、代理和命令入口。
- [Codex 自动化](docs/guides/codex-cli-automation.md)：PRD、实现、自检与 Complete 链路。
- [API 参考](docs/api/references.md)：`mkdocstrings` 驱动的对象级参考页。

## 文档维护规则

- 业务逻辑、工作流、函数签名、环境变量、命令或路径规范变化时，同步更新 `README.md` 和相关 `docs/` 页面。
- 新增、重命名或移动文档页面时，同步更新 `mkdocs.yml` 的 `nav`。
- 提交前执行 `just docs-build`，确保 MkDocs 严格模式构建通过。
