# Koda 项目文档

## 项目目标

Koda 当前的真实主线不是“通用 Python 模板”，而是一套围绕 **需求卡片、开发日志和 AI 自动化执行** 搭建的 DevStream Log 平台。

仓库已经落地的能力可以概括为三件事：

- 把需求拆成 `Task`，并用 `DevLog` 持续记录上下文、反馈、附件和 AI 输出。
- 让 FastAPI 后端在任务启动或执行时调起可配置执行器（`codex` / `claude`），自动生成 PRD 或代码实现。
- 用 React 前端把任务状态、对话时间线、PRD 内容和项目入口组织成一个单机开发工作台。

## 核心特性

- **需求卡片工作流**：`backlog`、`prd_generating`、`implementation_in_progress` 等阶段已经进入数据模型与前端展示。
- **任务时间线**：文本日志、图片附件、状态标记和 AI 输出统一归档到同一条需求历史里。
- **项目绑定与 Worktree**：任务可关联本地 Git 仓库，并在启动时创建独立 worktree。新 worktree 默认创建在仓库同级的 `task/` 目录下，例如项目仓库是 `/Users/zata/code/my-app` 时，任务 worktree 默认会落到 `/Users/zata/code/task/my-app-wt-12345678`。
- **多执行器自动化**：后端通过统一编排层调用 `backend/dsl/services/codex_runner.py`（执行器无关主流程）与 `backend/dsl/services/runners/`（CLI 适配层），按 `KODA_AUTOMATION_RUNNER` 选择 `codex` 或 `claude`。
- **媒体与导出**：支持图片上传、缩略图生成、Markdown 编年史导出。
- **AI 模型配置工具**：`ai_agent/` 中保留了可复用的模型注册与凭据解析能力。

## Quick Install

```bash
uv sync
cd frontend && npm install
cd ..
just dsl-dev
```

启动后访问：

- 前端：`http://localhost:5173`
- 后端：`http://localhost:8000`
- 健康检查：`http://localhost:8000/health`

## 代码资产盘点

### 入口点

- `main.py`：后端启动入口，调用 `uvicorn.run("backend.dsl.app:app", ...)`
- `backend/dsl/app.py`：FastAPI 应用工厂，负责生命周期、路由注册与媒体挂载
- `frontend/src/main.tsx`：前端挂载入口
- `justfile`：统一命令入口，已包含 `docs-serve`、`docs-build`、`dsl-dev`、`run`

### 核心逻辑

- `backend/dsl/api/`：HTTP 路由层，按 `run_accounts`、`projects`、`tasks`、`logs`、`media`、`chronicle` 拆分
- `backend/dsl/services/`：任务编排、日志解析、媒体存储、编年史导出、Codex 自动化
- `frontend/src/App.tsx`：需求工作台主界面，负责任务列表、阶段按钮、轮询与 PRD 展示
- `utils/`：配置、日志、数据库连接等底座能力

### 数据层

- ORM 模型：`backend/dsl/models/project.py`、`backend/dsl/models/task.py`、`backend/dsl/models/dev_log.py`、`backend/dsl/models/run_account.py`
- Pydantic Schema：`backend/dsl/schemas/`
- 数据库接入：`utils/database.py`
- 默认数据库：`data/dsl.db`

### AI 资产

- `backend/dsl/services/codex_runner.py`：执行器无关编排、Prompt 构造、实时日志回写、阶段推进
- `backend/dsl/services/runners/`：Runner 协议、注册中心与 Codex / Claude CLI 适配器
- `ai_agent/utils/model_loader.py`：模型配置读取与聊天模型实例化
- `ai_agent/utils/models.json`：提供商与模型注册表
- `ai_agent/.env.example`：AI 服务凭据示例

### 配置文件

- `pyproject.toml`：Python 依赖与开发依赖
- `utils/settings.py`：运行时配置与路径
- `frontend/vite.config.ts`：前端端口与代理
- `mkdocs.yml`：文档站点导航与插件配置

## 当前落地范围

需要明确区分“已实现”和“路线图”：

- 已实现的自动化主链路是：创建任务、生成 PRD、等待用户确认 PRD、触发编码、自动进入 AI 自检闭环并写回执行日志。若 self-review 首轮发现 blocker，系统会先在同一个 worktree 中自动回改并复审；只有闭环最终失败才会进入 `changes_requested`。
- self-review 闭环通过后，系统会自动进入 `test_in_progress`，执行 `uv run pre-commit run --all-files`；若 lint 在自动重跑后仍失败，会继续进入有上限的 AI lint-fix 闭环，只有最终失败才会进入 `changes_requested`。
- 任务级 schedule 现在除了 `start_task` / `resume_task` 之外，也支持独立 `review_task`：它会在任务 worktree 或绑定项目仓库上执行一次 review-only 评审，把 transcript 与结论写回 `DevLog`，但不会自动回改、不会推进到 lint，也不会修改 `workflow_stage`。
- 默认不会在实现阶段自动执行 `git commit`；只有用户点击 `Complete` 后，系统才会在任务 worktree 中执行 `git add .`，如果 staging 后仍有变更，就由当前 AI runner 基于 staged diff 生成符合 Conventional Commits 的 message 并提交；如果用户已经提交过导致 worktree 干净，则跳过 commit，随后执行 `git rebase main`。同步 `main` 时会优先解析该分支配置的 remote，而不是写死 `origin`；merge 成功后的 cleanup 也会继续核验 worktree / branch 是否真的移除，并在需要时做 fallback 清理，最后再标记完成。
- `WorkflowStage` 中的 `pr_preparing` 现在已接入真实自动化：`Complete` 会先进入该阶段，成功后自动推进到 `done`；如果最近一次 `Complete` 是因为 Git 收尾环境问题失败而掉回 `changes_requested`，用户修复仓库状态后也可以直接再次点击 `Complete` 重试收尾，而不必重跑实现链。`test_in_progress` 现在承载 post-review lint / lint-fix，`acceptance_in_progress` 仍主要是预留阶段。
- 对于“任务分支已被人工 merge 并删除”的边缘场景，后端会通过 `branch_health` 派生状态把已进入 worktree-backed Git 流程的任务标记为“缺失分支待确认”；前端要求用户先查看完成检查单，再走独立的 `/manual-complete` 收口接口，避免 backlog/未启动任务被误关单，也避免错误重跑普通 Git 收尾。
- `ai_agent/` 当前是工具库，不是 DSL 请求链路中的主处理器。

当前仍保留两个明确的人工边界：

- PRD 就绪后是否进入编码执行，仍需要用户确认；PRD 就绪来源可以是 AI 生成、`tasks/pending` 选择或手动导入（上传 / 粘贴 Markdown）
- self-review 闭环通过后是否执行最终 `Complete`，仍需要用户明确点击；若 AI 自检尚未形成最近一轮“通过”结论但后台已经空闲，用户也可以手动点击 `Complete`，系统会在 `DevLog` 中记录这次人工接管

## 推荐阅读路径

- 第一次接手项目：先看[快速开始](getting-started.md)
- 想理解真实模块边界：看[系统设计](architecture/system-design.md)
- 想改配置或端口：看[配置说明](guides/configuration.md)
- 想看多执行器是怎么接进任务流的：看[多执行器自动化](guides/codex-cli-automation.md)
- 想核对对象签名：看[API 参考](api/references.md)

## 文档维护约定

- 业务逻辑、函数签名、环境变量或工作流阶段变化时，必须同步更新 `docs/` 与 `mkdocs.yml`。
- 文档预览命令是 `just docs-serve`。
- 提交前至少执行一次 `just docs-build`，确保站点在严格模式下构建通过。
