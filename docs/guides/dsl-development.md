# DSL 开发指南

## 总览

当前 DSL 是一个前后端分离的单机工作台：

- `frontend/` 提供需求卡片与时间线界面
- `dsl/` 提供 FastAPI 路由、服务层与 ORM 模型
- `utils/` 提供配置、数据库和日志底座
- `ai_agent/` 提供与主业务链路松耦合的模型配置工具

## 后端结构

### 启动链路

1. `main.py` 调用 `uvicorn.run("dsl.app:app", ...)`
2. `dsl.app.create_application()` 创建 FastAPI 应用
3. `lifespan` 在启动时调用共享数据库初始化逻辑
4. 如果某个调用路径提前创建数据库会话，`utils.database.DatabaseSession` 也会兜底补齐缺失表结构
5. 应用注册 `run_accounts`、`projects`、`tasks`、`logs`、`media`、`chronicle` 路由
6. `/media/original` 与 `/media/thumbnail` 通过 `StaticFiles` 暴露

### 路由与服务分工

- `dsl/api/`：负责参数校验、依赖注入、HTTP 异常与状态码
- `dsl/services/`：负责业务规则与状态推进
- `dsl/models/`：定义数据库实体
- `dsl/schemas/`：定义请求与响应模型

新增后端功能时，推荐保持下面的修改顺序：

1. 先定义或调整 Pydantic Schema
2. 在 `dsl/services/` 实现业务规则
3. 在 `dsl/api/` 暴露路由
4. 在前端 `api/client.ts` 对接接口
5. 更新 `README.md` 和相关 `docs/` 页面，并执行 `just docs-build`

### 时间处理约定

- 后端统一复用 `utils/helpers.py` 中的时间 helper，不要在服务层直接对业务时间做 `isoformat()` 或字符串切片。
- 前端统一复用 `frontend/src/utils/datetime.ts`，不要在组件里直接用浏览器本地时区做业务分组或显示。
- `utils/logger.py` 现在也按 `APP_TIMEZONE` 输出显式偏移时间，便于把日志、导出和 UI 对齐。

## 前端结构

前端主入口集中在 `frontend/src/App.tsx`，它承担了三个关键职责：

- 拉取 `RunAccount`、`Task`、`DevLog`、`Project` 四类核心数据
- 根据 `workflow_stage` 渲染按钮、阶段标签与 PRD 面板
- 在 PRD 生成或编码执行阶段每秒轮询一次后端，实时刷新时间线

除 `App.tsx` 外，以下文件是主要协作点：

- `frontend/src/api/client.ts`：所有 HTTP 请求入口
- `frontend/src/types/index.ts`：后端数据结构的 TypeScript 映射
- `frontend/src/components/`：时间线、侧边栏、输入框等局部视图

## 当前工作流实现情况

### 已落地的阶段推进

项目已经具备以下链路：

1. 创建任务，默认进入 `backlog`
2. 点击“开始任务”，后端创建 worktree 并进入 `prd_generating`
3. `run_codex_prd` 调起 `codex exec` 生成 PRD，成功后推进到 `prd_waiting_confirmation`，等待用户确认
4. 点击“开始执行”，后端进入 `implementation_in_progress`
5. `run_codex_task` 调起 `codex exec` 完成实现，成功后推进到 `self_review_in_progress`
6. `run_codex_review` 在 `self_review_in_progress` 阶段自动执行代码评审，并将输出继续写回 `DevLog`
7. 自检若发现阻塞问题，任务自动回退到 `changes_requested`
8. 点击“Complete”后，后端会进入 `pr_preparing`，执行确定性的 Git 收尾链路，并在成功后推进到 `done`

### 已建模但尚未自动化闭环的阶段

以下阶段已经在 `WorkflowStage` 中定义，也能在前端显示，但当前仓库尚未完整实现自动推进器：

- `test_in_progress`
- `acceptance_in_progress`
- `changes_requested` 到后续更细粒度阶段的闭环

这部分要理解为“产品路线已经确定，自动化编排还在建设中”。

## 数据与文件

- SQLite 数据库：`data/dsl.db`
- 原图与附件：`data/media/original`
- 缩略图：`data/media/thumbnail`
- 应用日志：`logs/app.log`
- 任务实时输出：`/tmp/koda-<task短ID>.log`

如果出现“数据库有记录但界面没刷新”的情况，优先检查：

- 当前任务是否处于前端会自动轮询的阶段
- API 是否返回了预期的 `workflow_stage`
- `DevLog` 是否真正写入了当前任务

## 开发建议

### 改任务流时

- 把 `workflow_stage` 视为唯一事实来源
- 后端和前端要同时更新 `WorkflowStage` 相关逻辑
- 文档中要同步说明哪些阶段已自动化，哪些只是占位
- 如果阶段、命令、端口、环境变量或路径规范变化，要同步更新 `README.md`、相关 `docs/` 页面，并在提交前执行 `just docs-build`

### 改媒体上传时

- 优先在 `dsl/services/media_service.py` 保持文件路径策略一致
- 任何路径字段变更都要同步更新文档与前端展示逻辑

### 改 AI 自动化时

- 先看 `dsl/services/codex_runner.py`
- 明确是改 PRD Prompt 还是实现 Prompt
- 注意日志写回、阶段推进和 `/tmp` 实时日志文件三者必须保持一致

## 推荐开发流程

```bash
uv sync
cd frontend && npm install
cd ..
just dsl-dev
```

只调后端时可以简化为：

```bash
just setup-data
uv run python main.py
```
