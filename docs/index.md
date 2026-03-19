# Koda 文档总览

`README.md` 是仓库入口，本页承接站内总览和阅读导航。两者都以同一套事实为准：这个仓库是 **Koda / DevStream Log 开发工作台**，而不是通用模板。

## 项目定位

Koda 当前的核心目标，是把需求卡片、开发日志和 AI 自动化执行串成一条单机研发链路：

- `Task` 承载需求与阶段状态。
- `DevLog` 记录上下文、反馈、附件和 AI 输出。
- FastAPI 后端负责 worktree、Codex 调用、日志回写和状态推进。
- React 前端负责把任务、PRD、时间线和项目入口组织成工作台。

## 最小启动路径

```bash
uv sync
cd frontend && npm install
cd ..
just dsl-dev
```

本地默认地址：

- 前端：`http://localhost:5173`
- 后端：`http://localhost:8000`
- 健康检查：`http://localhost:8000/health`

## 仓库地图

- `dsl/`：FastAPI 路由、服务层、模型与 Schema。
- `frontend/`：React + Vite 前端。
- `docs/`：MkDocs 文档站点。
- `ai_agent/`：模型注册、凭据解析和聊天模型工具。
- `tasks/`：PRD 等任务产物。
- `utils/`：配置、数据库、日志等基础设施。

## 当前已落地能力

- 任务可以从 `backlog` 进入 `prd_generating`，由 `codex exec` 生成 PRD，并停在 `prd_waiting_confirmation` 等待确认。
- 确认后可以进入 `implementation_in_progress` 执行实现，再自动进入 `self_review_in_progress` 触发 AI 自检。
- 点击 `Complete` 后，任务会进入 `pr_preparing`，并在 task worktree 中执行确定性的 Git 收尾链路：`git add .`、基于任务摘要生成 `git commit -m ...`、`git rebase main`、必要时调用 Codex 解决冲突、复用持有 `main` 的工作区完成 merge，再清理 worktree 和本地分支。
- `test_in_progress` 与 `acceptance_in_progress` 仍主要作为后续自动化的扩展阶段。

## 文档地图

- [快速开始](getting-started.md)：环境要求、安装、启动与常见问题。
- [配置说明](guides/configuration.md)：环境变量、端口、代理和命令入口。
- [DSL 开发](guides/dsl-development.md)：后端 / 前端结构、工作流状态与开发协作方式。
- [Codex 自动化](guides/codex-cli-automation.md)：PRD、实现、自检与 Complete 链路。
- [系统设计](architecture/system-design.md)：模块边界与架构分层。
- [API 参考](api/references.md)：对象级与 API 级参考的唯一权威页面，不在其他 Markdown 中复制成员说明。

## 文档维护规则

- 业务逻辑、工作流、函数签名、环境变量、命令或路径规范变化时，同步更新相关 `docs/` 页面和 `README.md`。
- 新增、重命名或移动文档页面时，同步更新 `mkdocs.yml` 的 `nav`，不要做无意义的导航改动。
- 本地预览使用 `just docs-serve`，提交前执行 `just docs-build`，确保 MkDocs 严格模式构建通过。
