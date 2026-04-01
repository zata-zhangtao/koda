# PRD：任务调度支持独立 Review-Only 动作

**原始需求标题**：帮我这个项目做 code review 怎么结合定时器使用
**需求名称（AI 归纳）**：任务调度独立代码评审动作
**文件路径**：`tasks/20260401-014406-prd-scheduled-review-task.md`
**创建时间**：2026-04-01 01:44:06 CST
**需求背景/上下文**：现有 schedule 已支持 `start_task` / `resume_task`，但“帮我对这个项目定时做 code review”会误落到工作流恢复语义；若强行复用 `resume_task`，self-review 通过后会继续进入 lint，不能表达纯 review-only 巡检。
**参考上下文**：`dsl/api/tasks.py`, `dsl/services/automation_runner.py`, `dsl/services/codex_runner.py`, `dsl/services/task_scheduler_dispatcher.py`, `dsl/models/enums.py`, `frontend/src/App.tsx`, `frontend/src/api/client.ts`, `frontend/src/types/index.ts`

---

## 1. Introduction & Goals

### 背景

当前任务调度已经能自动启动或恢复任务，但“定时代码评审”缺少一个正式动作类型。直接复用 `resume_task` 的问题是：

- 它要求任务已经停在特定持久化阶段；
- 它表达的是“恢复自动化”，不是“做一次独立审查”；
- 一旦 self-review 通过，会自动进入 post-review lint，偏离 review-only 语义。

### 目标

- [x] 新增可被 schedule 使用的 `review_task` 动作。
- [x] 提供独立 `POST /api/tasks/{task_id}/review` 路由。
- [x] 复用现有 review prompt，但不自动回改、不推进到 lint、不修改 `workflow_stage`。
- [x] 前端调度面板支持创建/展示/`run-now` 该动作。
- [x] 同步测试与文档，保证调度、任务 API、runner wrapper、MkDocs 和前端构建都通过。

## 2. Implementation Guide

### 2.1 核心方案

在现有任务调度白名单动作中新增 `review_task`：

- 调度层仍然复用任务 API 路由分发，而不是直接调用私有函数；
- 任务 API 新增 `review_task` 路由，负责生命周期校验、执行目录解析、后台任务注册；
- runner 层新增独立 `run_task_review` / `run_codex_review_only` 入口；
- review-only 运行只执行单轮 `build_codex_review_prompt`，并根据 `SELF_REVIEW_STATUS` 写摘要日志；
- 无论 PASS、CHANGES_REQUESTED 还是结构化标记缺失，都不推进到 lint，也不修改任务阶段。

### 2.2 变更矩阵

| Change Target | Delivered Behavior | Affected Files |
| --- | --- | --- |
| 调度动作枚举 | 新增 `review_task` | `dsl/models/enums.py`, `frontend/src/types/index.ts` |
| 调度分发 | `TaskSchedulerDispatcher` 新增 review-only 分支 | `dsl/services/task_scheduler_dispatcher.py` |
| 任务 API | 新增 `POST /api/tasks/{task_id}/review` | `dsl/api/tasks.py`, `dsl/services/task_service.py` |
| Runner 入口 | 新增 `run_task_review` / `run_codex_review_only` | `dsl/services/automation_runner.py`, `dsl/services/codex_runner.py` |
| 前端调度面板 | 可创建/展示 `review_task`，API union 已扩展 | `frontend/src/api/client.ts`, `frontend/src/App.tsx` |
| 文档 | README、范围说明、开发说明、自动化说明、schema、API 参考已同步 | `README.md`, `docs/index.md`, `docs/guides/dsl-development.md`, `docs/guides/codex-cli-automation.md`, `docs/database/schema.md`, `docs/api/references.md` |
| 测试 | 新增 wrapper / dispatcher / tasks API / codex runner 回归 | `tests/test_automation_runner_registry.py`, `tests/test_task_schedule_service.py`, `tests/test_tasks_api.py`, `tests/test_codex_runner.py` |

### 2.3 关键约束

- review-only 必须有真实目标目录：优先 task worktree，其次绑定项目仓库；不允许回退到 Koda 自身仓库。
- review-only 继续使用 `SELF_REVIEW_SUMMARY` / `SELF_REVIEW_STATUS` 结构化输出合同。
- schedule `run-now` 的成功语义仍是“成功派发后台任务”，而不是“review 结论为 PASS”。

## 3. Definition of Done

- [x] 调度创建接口接受 `action_type=review_task`
- [x] 调度器会把 `review_task` 分发到独立任务 API 路由
- [x] review-only 背景任务不会触发 lint、自动回改或阶段推进
- [x] 无 worktree 且无绑定项目仓库时，review-only 会明确拒绝执行
- [x] 前端调度面板能配置并显示 `review_task`
- [x] 聚焦 Python 回归测试通过
- [x] 前端生产构建通过
- [x] MkDocs 严格构建通过

## 4. Verification Evidence

- `uv run pytest tests/test_task_schedule_service.py tests/test_automation_runner_registry.py tests/test_tasks_api.py tests/test_codex_runner.py -q` -> PASS (`103 passed`)
- `npm run build` -> PASS
- `UV_CACHE_DIR=/tmp/uv-cache just docs-build` -> PASS
- `git diff --check` -> PASS

## 5. Key Decisions & Deviations

- 没有复用 `resume_task` 伪装成“定时 review”，因为那会把成功路径错误地接到 lint。
- 没有让 review-only 改写 `workflow_stage`，因为这个动作表达的是巡检/审查，而不是交付流水线推进。
- 目前前端只在调度面板暴露 `review_task`；独立“Review Now”按钮留作后续 UX 扩展，不影响本次能力落地。
