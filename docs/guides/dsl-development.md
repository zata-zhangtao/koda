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
4. `lifespan` 同时启动每 60 秒一次的停滞任务提醒扫描器
5. 如果某个调用路径提前创建数据库会话，`utils.database.DatabaseSession` 也会兜底补齐缺失表结构
6. 文件型 SQLite 连接会在创建时统一设置 `busy_timeout`、`foreign_keys=ON` 与 `journal_mode=WAL`，降低后台写日志和前台读接口并发时的锁冲突
7. 应用注册 `run_accounts`、`projects`、`tasks`、`logs`、`media`、`chronicle`、`email_settings` 路由
8. `/media/original` 与 `/media/thumbnail` 通过 `StaticFiles` 暴露

### 路由与服务分工

- `dsl/api/`：负责参数校验、依赖注入、HTTP 异常与状态码
- `dsl/services/`：负责业务规则与状态推进
- `dsl/models/`：定义数据库实体
- `dsl/schemas/`：定义请求与响应模型
- 热路径约定：任务列表要通过聚合查询计算 `log_count`，日志列表要在主查询里带出 `task_title`，不要依赖关系懒加载去补齐列表页字段
- 热路径约定：任务列表要通过聚合查询计算 `log_count`，日志列表要在主查询里带出 `task_title`，不要依赖关系懒加载去补齐列表页字段

新增后端功能时，推荐保持下面的修改顺序：

1. 先定义或调整 Pydantic Schema
2. 在 `dsl/services/` 实现业务规则
3. 在 `dsl/api/` 暴露路由
4. 在前端 `api/client.ts` 对接接口
5. 更新文档并执行验证

### 时间处理约定

- 后端统一复用 `utils/helpers.py` 中的时间 helper，不要在服务层直接对业务时间做 `isoformat()` 或字符串切片。
- 前端统一复用 `frontend/src/utils/datetime.ts`，不要在组件里直接用浏览器本地时区做业务分组或显示。
- `utils/logger.py` 现在也按 `APP_TIMEZONE` 输出显式偏移时间，便于把日志、导出和 UI 对齐。

## 前端结构

前端主入口集中在 `frontend/src/App.tsx`，它承担了三个关键职责：

- 拉取 `RunAccount`、`Task`、`DevLog` 三类核心数据，并在初始加载或打开项目面板时按需刷新 `Project`
- 根据 `workflow_stage` 渲染阶段标签与 PRD 面板，并结合 `TaskResponse.is_codex_task_running` 判断后台自动化是否仍在执行
- 在执行阶段做轻量任务状态轮询，并对当前任务通过 `created_after` 增量拉取新增日志，避免反复重拉完整时间线

除 `App.tsx` 外，以下文件是主要协作点：

- `frontend/src/api/client.ts`：所有 HTTP 请求入口
- `frontend/src/types/index.ts`：后端数据结构的 TypeScript 映射
- `frontend/src/components/`：时间线、侧边栏、输入框等局部视图

## 当前工作流实现情况

### 已落地的阶段推进

项目已经具备以下链路：

1. 创建任务，默认进入 `backlog`
2. 点击“开始任务”，后端创建 worktree 并进入 `prd_generating`
3. `run_codex_prd` 调起 `codex exec` 生成 PRD，成功后按任务策略分流：
   - 默认：推进到 `prd_waiting_confirmation`，等待用户确认
   - 自动模式（`auto_confirm_prd_and_execute=true`）：直接推进到 `implementation_in_progress` 并启动实现链路
4. 系统会为每次阶段切换维护 `stage_updated_at`，并在 `prd_waiting_confirmation` / `changes_requested` 上通过统一通知服务与后台扫描器计算停滞提醒
5. 点击“开始执行”，后端进入 `implementation_in_progress`
6. `run_codex_task` 调起 `codex exec` 完成实现，成功后推进到 `self_review_in_progress`
7. `run_codex_review` 在 `self_review_in_progress` 阶段自动执行代码评审，并将输出继续写回 `DevLog`
8. 自检若发现阻塞问题，系统会在同一个 worktree 内执行有上限的 `review -> 自动回改 -> review` 闭环，并通过统一通知服务发送 `changes_requested` 邮件
9. 自检通过后，系统会自动推进到 `test_in_progress`，并执行 `uv run pre-commit run --all-files`
10. 若 lint 在自动重跑后仍失败，系统会继续进入有上限的 `lint -> AI lint-fix -> lint` 闭环
11. 只有当 review / lint 自动闭环最终失败时，任务才会回退到 `changes_requested`
12. 当 lint 闭环通过且后台自动化空闲后，任务会停留在 `test_in_progress`，等待用户点击 `Complete`
13. 若用户在运行中点击 `Cancel`，系统会把任务回退到 `changes_requested`，并通过统一通知服务发送“手动中断”邮件
14. 若任务仍停留在 `self_review_in_progress` 且最近一轮 review 尚未出现通过标记，只要后台自动化已经空闲，人工也可以直接点击 `Complete`；后端会先写入一条 `DevLog` 记录人工接管

### 已建模但尚未自动化闭环的阶段

以下阶段已经在 `WorkflowStage` 中定义，也能在前端显示，但当前仓库尚未完整实现自动推进器：

- `pr_preparing`
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
- 当前任务日志轮询是否拿到了正确的 `created_after` 时间戳
- API 是否同时返回了预期的 `workflow_stage` 与 `is_codex_task_running`
- `DevLog` 是否真正写入了当前任务

## 开发建议

### 改任务流时

- 把 `workflow_stage` 视为业务阶段事实来源，但不要再把它等同为“后台自动化仍在运行”
- 后端和前端要同时更新 `WorkflowStage` 相关逻辑
- 若前端需要判断是否显示轮询 banner、取消按钮或 `Complete`，优先使用 `TaskResponse.is_codex_task_running`
- 文档中要同步说明哪些阶段已自动化，哪些只是占位
- `changes_requested` 现在代表“AI 无法自行完成闭环后的人工介入态”，不要再把它当成第一次 self-review 失败的直接别名
- 任何会改变 `workflow_stage` 的新逻辑，都要同步考虑 `stage_updated_at` 是否应该刷新，以及是否需要进入统一通知服务

### 改媒体上传时

- 优先在 `dsl/services/media_service.py` 保持文件路径策略一致
- 任何路径字段变更都要同步更新文档与前端展示逻辑

### 改 AI 自动化时

- 先看 `dsl/services/codex_runner.py`
- 明确是改 PRD Prompt 还是实现 Prompt
- 注意日志写回、阶段推进和 `/tmp` 实时日志文件三者必须保持一致
- 若修改 self-review / lint 自动化逻辑，要同时核对 review-only Prompt、review-fix Prompt、lint-fix Prompt、失败通知时机以及 `TaskService.execute_task(...)` 的入口契约

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
