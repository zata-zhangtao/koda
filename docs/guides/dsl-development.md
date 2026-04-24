# DSL 开发指南

## 总览

当前 DSL 是一个前后端分离的单机工作台：

- `frontend/` 提供需求卡片与时间线界面
- `backend/dsl/` 提供 FastAPI 应用、领域切片、路由、服务层与 ORM 模型
- `utils/` 提供配置、数据库和日志底座
- `ai_agent/` 提供与主业务链路松耦合的模型配置工具
- 新增能力优先采用 `backend/dsl/<domain>/` 领域切片；历史模块仍保留在 `backend/dsl/services/`
- `backend/dsl/services/task_qa_service.py` 则把这层工具能力用于任务内独立问答，而不是复用 `DevLog`

## 后端结构

后端包从仓库根目录的 `backend/` 开始。当前 DSL 应用位于 `backend/dsl/`，导入路径统一写作 `backend.dsl...`。新增后端模块时，先按业务域确定目录和边界，再在模块内部保持简洁架构：API 层处理 HTTP 合同，application/use case 层承载编排，domain 层表达业务规则，infrastructure 层接入数据库、文件系统、runner 等外部系统。

`backend/dsl/services/` 是历史平铺服务目录，不再作为新增业务能力的默认落点。新能力应优先采用如下领域切片结构：

```text
backend/dsl/<domain>/
  api.py
  schemas.py
  domain/
  application/
  infrastructure/
```

`backend/dsl/prd_sources/` 是该模式的首个落地模块：pending PRD 列表、选择、手动导入、路径安全、文件 staging、任务阶段推进和 auto-confirm 分流都收敛在该领域切片内；旧 `TaskService`、runner 和 PRD 文件命名/读取逻辑只通过 infrastructure adapter 复用。

### 启动链路

1. `main.py` 调用 `uvicorn.run("backend.dsl.app:app", ...)`
2. `backend.dsl.app.create_application()` 创建 FastAPI 应用
3. `lifespan` 在启动时调用共享数据库初始化逻辑
4. `lifespan` 同时启动停滞任务提醒扫描器与任务调度分发循环
5. 如果某个调用路径提前创建数据库会话，`utils.database.DatabaseSession` 也会兜底补齐缺失表结构
6. 文件型 SQLite 连接会在创建时统一设置 `busy_timeout`、`foreign_keys=ON` 与 `journal_mode=WAL`，降低后台写日志和前台读接口并发时的锁冲突
7. 应用注册 `run_accounts`、`projects`、`tasks`、`task_qa`、`task_schedules`、`logs`、`media`、`chronicle`、`email_settings` 路由
8. `/media/original` 与 `/media/thumbnail` 通过 `StaticFiles` 暴露

### 路由与服务分工

- `backend/dsl/<domain>/api.py` 或 `backend/dsl/api/`：负责参数校验、依赖注入、HTTP 异常与状态码
- `backend/dsl/<domain>/application/`：负责用例编排和端口依赖
- `backend/dsl/<domain>/domain/`：负责纯业务规则，不依赖 FastAPI、SQLAlchemy、真实文件系统或前端类型
- `backend/dsl/<domain>/infrastructure/`：负责数据库、文件系统、CLI runner、WebDAV、邮件等外部系统适配
- `backend/dsl/services/`：历史服务层，新增能力应通过 adapter 复用而不是继续平铺扩张
- `backend/dsl/models/`：定义数据库实体
- `backend/dsl/schemas/`：定义请求与响应模型
- 任务调度约定：自动触发统一复用既有 `start_task` / `resume_task` / `review_task` 路由逻辑；其中 `review_task` 只写日志，不改变任务阶段
- 热路径约定：任务列表要通过聚合查询计算 `log_count`，日志列表要在主查询里带出 `task_title`，不要依赖关系懒加载去补齐列表页字段
- sidecar Q&A 约定：问答消息必须落到独立表，默认不写 `DevLog`，并且不得隐式改动 `workflow_stage`

新增后端功能时，推荐保持下面的修改顺序：

1. 先定义或调整 Pydantic Schema
2. 为新业务域创建 `backend/dsl/<domain>/domain/` 与 `application/`，先写纯业务规则和 use case
3. 在 `backend/dsl/<domain>/infrastructure/` 适配旧服务、数据库、文件系统或 runner
4. 在 `backend/dsl/<domain>/api.py` 暴露路由，并在 `backend/dsl/app.py` 注册
5. 在前端 `api/client.ts` 对接接口
6. 更新文档并执行验证

如果新功能属于“只读 sidecar”而不是主执行链路，额外要确认：

1. 是否引入了独立存储，而不是复用 `DevLog`
2. 是否会被错误地拼进 Codex Prompt 上下文
3. 是否错误复用了 `is_codex_task_running` 作为 sidecar 运行态
4. 是否提供了从 sidecar 结论到正式反馈的显式转换入口

### 时间处理约定

- 后端统一复用 `utils/helpers.py` 中的时间 helper，不要在服务层直接对业务时间做 `isoformat()` 或字符串切片。
- 前端统一复用 `frontend/src/utils/datetime.ts`，不要在组件里直接用浏览器本地时区做业务分组或显示。
- `utils/logger.py` 现在也按 `APP_TIMEZONE` 输出显式偏移时间，便于把日志、导出和 UI 对齐。

## 前端结构

前端主入口集中在 `frontend/src/App.tsx`，它承担了三个关键职责：

- 拉取 `RunAccount`、`Task`、`DevLog` 三类核心数据，并在初始加载或打开项目面板时按需刷新 `Project`
- 维护项目面板里的 `Project` 元数据，包括仓库路径、描述以及可供时间线跨项目聚合的 `project_category`
- 根据 `workflow_stage` 渲染阶段标签与 PRD 面板，并结合 `TaskResponse.is_codex_task_running` 判断后台自动化是否仍在执行
- 在执行阶段做轻量任务状态轮询，并对当前任务通过 `created_after` 增量拉取新增日志，避免反复重拉完整时间线

除 `App.tsx` 外，以下文件是主要协作点：

- `frontend/src/api/client.ts`：所有 HTTP 请求入口
- `frontend/src/types/index.ts`：后端数据结构的 TypeScript 映射
- `frontend/src/components/`：时间线、侧边栏、输入框等局部视图
- `frontend/src/pages/ProjectTimelinePage.tsx`：项目时间线独立页面，支持按 `project_category` 或单项目查看历史

## 当前工作流实现情况

### 已落地的阶段推进

项目已经具备以下链路：

1. 创建任务，默认进入 `backlog`
2. 点击“开始任务”，后端创建 worktree 并进入 `prd_generating`
3. 默认 PRD 来源是 AI 生成：`run_codex_prd` 调起当前配置 runner（`codex` / `claude`）生成 PRD，成功后按任务策略分流：
   - 默认：推进到 `prd_waiting_confirmation`，等待用户确认
   - 自动模式（`auto_confirm_prd_and_execute=true`）：直接推进到 `implementation_in_progress` 并启动实现链路
4. 用户也可以在任务详情中选择非 AI 来源：从 `tasks/pending/*.md` 选择 PRD，或手动上传 / 粘贴 Markdown PRD。两者由 `backend/dsl/prd_sources/` 负责移动/导入到 `tasks/YYYYMMDD-HHMMSS-prd-<requirement-slug>.md`，然后进入与 AI 生成一致的 PRD ready 后续链路。
5. 系统会为每次阶段切换维护 `stage_updated_at`，并在 `prd_waiting_confirmation` / `changes_requested` 上通过统一通知服务与后台扫描器计算停滞提醒
6. 点击“开始执行”，后端进入 `implementation_in_progress`
7. `run_codex_task` 调起当前配置 runner 完成实现，成功后推进到 `self_review_in_progress`
8. `run_codex_review` 在 `self_review_in_progress` 阶段自动执行代码评审，并将输出继续写回 `DevLog`
9. 自检若发现阻塞问题，系统会在同一个 worktree 内执行有上限的 `review -> 自动回改 -> review` 闭环，并通过统一通知服务发送 `changes_requested` 邮件
10. 自检通过后，系统会自动推进到 `test_in_progress`，并执行 `uv run pre-commit run --all-files`
11. 若 lint 在自动重跑后仍失败，系统会继续进入有上限的 `lint -> AI lint-fix -> lint` 闭环
12. 只有当 review / lint 自动闭环最终失败时，任务才会回退到 `changes_requested`
13. 当 lint 闭环通过且后台自动化空闲后，任务会停留在 `test_in_progress`，等待用户点击 `Complete`
14. 若用户在运行中点击 `Cancel`，系统会把任务回退到 `changes_requested`，并通过统一通知服务发送“手动中断”邮件
15. 若任务仍停留在 `prd_generating` / `implementation_in_progress` / `self_review_in_progress` / `test_in_progress` / `pr_preparing`，但实时 runner 标记已经丢失，详情页会额外暴露 `Force Interrupt`；后端会清理运行态、回退到 `changes_requested`，并写入一条“人工强制接管”的 `DevLog` 审计日志
16. 若任务仍停留在 `self_review_in_progress` 且最近一轮 review 尚未出现通过标记，或任务已进入 `changes_requested` 但用户已在 worktree 中完成修复，只要后台自动化已经空闲，人工也可以直接点击 `Complete`；后端会先写入一条 `DevLog` 记录人工接管
17. 对于关联 Git 项目的未关闭任务，后端现在会额外返回只读 `branch_health` 派生状态；它会先按 `task/{task_id[:8]}` 前缀探测本地任务分支，兼容 `task/{task_id[:8]}-<semantic-slug>` 这种真实 worktree 分支名，并在命中时返回解析到的实际分支名
18. 只有任务已经创建过 `worktree_path`、确实进入过 worktree-backed Git 流程时，`branch_health.manual_completion_candidate=true` 才会把卡片/详情头部展示为“缺失分支待确认”，并要求用户先查看完成检查单，再允许点击人工确认完成
19. 用户点击“确认 Complete”后，前端会调用 `POST /api/tasks/{task_id}/manual-complete`；后端写入一条“检测到分支缺失后由用户人工确认完成”的 `DevLog`，并直接把任务收敛到 `workflow_stage=done`、`lifecycle_status=CLOSED`
20. 后台 stuck-task watchdog 现在也会扫描 `pr_preparing`；若任务在该阶段停留超过阈值，且当前只残留陈旧的进程内运行标记、但尚未写出 completion start `DevLog`，watchdog 会清理这个假运行态并自动触发一次 `resume_task`，避免前端长期看不到 `Complete`/恢复入口
21. `pr_preparing` 会先执行 `git add .`；如果 staging 后没有变更，Koda 会把它视为“用户已经提交过”，跳过 `git commit` 并继续 rebase/merge；如果 staging 后仍有变更，则先由当前 AI runner 基于 staged diff 生成符合 Conventional Commits 的 message，再执行 `git commit`
22. `pr_preparing` 的 `git commit` 若被 commit hook 自动改写文件并返回非零，Koda 会在同一 worktree 中自动补做一次 `git add .` 并重试一次 `git commit`；若重试后仍失败，任务才会回退到 `changes_requested`
23. 对 worktree-backed 的 `changes_requested` 任务，前端会恢复普通 `Complete` CTA；用户修复实现、自检、lint 或 Git 环境问题后可以直接重试收尾，而不必回到 `execute` 重跑实现链
24. `pr_preparing` 在同步 `main` 时会优先解析该分支配置的 remote；如果没有显式配置，则回退到仓库唯一 remote，再回退到 `origin` / `zata`，避免因 remote 名称与仓库实际配置不一致而误报
25. merge 成功后的 cleanup 不会只看 repo-local cleanup script 的退出码；系统还会继续核验 worktree / branch 是否真的消失，并在必要时回退到 `git worktree remove --force`、`git worktree prune` 与 orphan 目录清理

### 调度能力（新增）

当前已支持任务级调度规则：

1. 一次性规则（`trigger_type=once`）在触发后自动停用
2. 周期规则（`trigger_type=cron`）按时区与 Cron 规则推进 `next_run_at`
3. 调度动作支持 `start_task`、`resume_task`、`review_task`
4. 自动轮询分发会先领取调度窗口，再执行动作，避免同一窗口重复派发
5. 每次分发都会写入 `TaskScheduleRun` 审计，状态包含 `succeeded` / `failed` / `skipped`
6. 当任务已有后台自动化运行时，调度分发会标记为 `skipped`，不并发启动
7. 任务详情页已提供调度面板，可创建规则、启停、立即执行并查看最近执行历史
8. 前端创建 `once` 规则时会把 `datetime-local` 输入转换为 UTC ISO 并携带浏览器时区，避免与后端默认 `APP_TIMEZONE` 不一致导致触发时间偏移
9. `review_task` 会在任务 worktree 或关联项目仓库上执行一次独立 review-only 评审；结论写回 `DevLog`，但不会自动回改，也不会推进到 lint / Complete

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
- 任务内独立问答：`task_qa_messages` 表（由 `utils.database.ensure_database_schema_ready()` 自动创建）

如果出现“数据库有记录但界面没刷新”的情况，优先检查：

- 当前任务是否处于前端会自动轮询的阶段
- 当前任务日志轮询是否拿到了正确的 `created_after` 时间戳
- API 是否同时返回了预期的 `workflow_stage` 与 `is_codex_task_running`
- 普通 `Complete` 成功后，前端是否已经把 `/complete` 返回的 `pr_preparing` 任务快照写回本地任务列表；即使运行标记短暂丢失，open 的 `pr_preparing` 仍应继续 dashboard 轮询，直到拉到 `done / CLOSED`
- `destroy`、`restore`、`updateStatus`、`updateStage`、`execute`、`cancel`、`forceInterrupt` 等任务突变接口是否把返回的 `TaskResponse` 立即写回本地任务列表；硬删除未启动草稿因为返回 204，需要前端先本地移除该任务
- `DevLog` 是否真正写入了当前任务

## 开发建议

### 改任务流时

- 把 `workflow_stage` 视为业务阶段事实来源，但不要再把它等同为“后台自动化仍在运行”
- 后端和前端要同时更新 `WorkflowStage` 相关逻辑
- 若前端需要判断是否显示轮询 banner、取消按钮或 `Complete`，优先使用 `TaskResponse.is_codex_task_running`；dashboard 任务列表轮询有一个明确例外：open 的 `pr_preparing` 会继续刷新，以便 Git 收尾完成后自动切到 `done / CLOSED`
- 会改变任务列表归属的前端动作（例如 Destroy、Delete、Abandon、Restore、Request Changes、Accept、Complete）必须先消费突变接口返回的任务快照或本地移除 hard-delete 项，再把全量 dashboard refresh 当作后台一致性补偿
- 若前端需要处理“分支已被人工 merge/删除”的异常收口，优先使用 `TaskResponse.branch_health` / `TaskCardMetadata.branch_health`，不要再把 worktree 是否存在当成唯一依据
- 文档中要同步说明哪些阶段已自动化，哪些只是占位
- `changes_requested` 现在代表“AI 无法自行完成闭环后的人工介入态”，不要再把它当成第一次 self-review 失败的直接别名
- 任何会改变 `workflow_stage` 的新逻辑，都要同步考虑 `stage_updated_at` 是否应该刷新，以及是否需要进入统一通知服务

### 改媒体上传时

- 优先在 `backend/dsl/services/media_service.py` 保持文件路径策略一致
- 任何路径字段变更都要同步更新文档与前端展示逻辑

### 改 AI 自动化时

- 先看 `backend/dsl/services/automation_runner.py`（API 入口）和 `backend/dsl/services/codex_runner.py`（主编排）
- 再看 `backend/dsl/services/runners/`（runner 协议、注册中心和 Codex / Claude 适配器）
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
