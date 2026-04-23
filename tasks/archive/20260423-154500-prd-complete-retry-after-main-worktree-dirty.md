# PRD：Complete 失败后恢复可重试收尾入口

**原始需求标题**：为什么 Koda 提示 main 工作区不干净，而且我清理干净以后页面上的 Complete 按钮没了
**需求名称（AI 归纳）**：Complete 重试修复：当 Git 收尾因 main 工作区脏而失败后，允许用户修复仓库状态后直接重试收尾
**文件路径**：`tasks/20260423-154500-prd-complete-retry-after-main-worktree-dirty.md`
**创建时间**：2026-04-23 15:45:00 CST
**需求背景/上下文**：当前 deterministic `Complete` 流程在执行 `git merge <task branch>` 前，会先检查承载 `main` 分支的工作区是否干净。只要该工作区存在未提交改动，后端就会终止收尾并把任务回退到 `changes_requested`。但前端没有为这类“收尾失败但实现本身已完成”的任务保留普通 `Complete` 入口，用户即使在仓库外清理干净主工作区，也只能看到“重新执行”，导致必须重跑实现链路。
**参考上下文**：`backend/dsl/services/codex_runner.py`, `backend/dsl/api/tasks.py`, `backend/dsl/services/task_service.py`, `frontend/src/App.tsx`, `tests/test_task_service.py`, `tests/test_tasks_api.py`, `docs/guides/codex-cli-automation.md`, `docs/index.md`, `docs/architecture/system-design.md`, `docs/guides/dsl-development.md`

---

## 1. Introduction & Goals

### 背景

当前收尾阶段失败后统一掉回 `changes_requested`。这个语义对实现 / review / lint 失败是合理的，但对“代码已经准备好，只是 main 工作区脏导致 Git merge 没法继续”的场景过于粗暴。

结果是：

- 用户看到错误提示，却不知道它来自哪一步
- 用户在仓库外修复了主工作区后，前端不再显示 `Complete`
- “重新执行”会重跑实现链路，而不是只重试 Git 收尾

### 可衡量目标

- [x] 保留现有“main 工作区必须干净”保护，不降低 Git 合并安全性。
- [x] 为“最近一次 `changes_requested` 来自 `Complete` 收尾失败”的任务恢复普通 `Complete` 入口。
- [x] 保持普通实现失败 / review 失败 / lint 失败的 `changes_requested` 仍默认走“重新执行”。
- [x] 增加前后端回归测试，锁定 eligibility 判定与 API 合同。
- [x] 更新文档，明确 `Complete` 失败后的重试路径。

## 2. Root Cause

### 2.1 直接原因

`backend/dsl/services/codex_runner.py` 在真正 merge 前会对承载 `main` 的工作区执行 `git status --short`。只要有输出，就会返回：

- `承载 main 分支的工作区不是干净状态，无法自动执行 merge。`

随后 `run_codex_completion(...)` 会把任务写回 `changes_requested`。

### 2.2 为什么按钮会消失

- `frontend/src/App.tsx` 的 `canCompleteTask(...)` 默认不允许 worktree-backed `changes_requested` 任务继续显示 `Complete`
- `backend/dsl/services/task_service.py` 的 `prepare_task_completion(...)` 也默认拒绝从 `changes_requested` 再次进入 `pr_preparing`
- 因此前后端都没有“只重试收尾”的通道

## 3. Delivered Changes

### 3.1 代码改动

| Change Target | Delivered Behavior | Files |
|---|---|---|
| Completion retry eligibility | 新增“最近一次 BUG 日志是否为 `Complete` 收尾失败”判定，用来识别可直接重试收尾的 `changes_requested` 任务 | `backend/dsl/api/tasks.py`, `frontend/src/utils/completion_retry.ts` |
| Service contract | `prepare_task_completion(...)` 增加显式开关，仅在路由层确认 eligibility 后才允许从 `changes_requested` 进入 `pr_preparing` | `backend/dsl/services/task_service.py` |
| API behavior | `/api/tasks/{id}/complete` 现在允许符合条件的 `changes_requested` 任务直接重试 Git 收尾 | `backend/dsl/api/tasks.py` |
| Frontend CTA | 详情页会在符合条件时恢复普通 `Complete`，而不是只剩“重新执行” | `frontend/src/App.tsx` |
| Frontend regression | 新增纯函数测试，锁定“最近一次 BUG 日志”的判定规则 | `frontend/tests/completion_retry.test.ts` |
| Backend regression | 新增 service/API 回归测试，覆盖 retry-Complete 开关与 route 行为 | `tests/test_task_service.py`, `tests/test_tasks_api.py` |
| Documentation | 补充 Complete 失败后的重试语义 | `docs/guides/codex-cli-automation.md`, `docs/index.md`, `docs/architecture/system-design.md`, `docs/guides/dsl-development.md` |

### 3.2 明确不做的事

- 不放宽“任意 `changes_requested` 都可直接 Complete”。
- 不改变“main 工作区必须干净”这一 Git 安全前提。
- 不改写已有 `manual-complete` 缺失分支收口语义。

## 4. Verification

### 4.1 通过的验证

- [x] `uv run pytest tests/test_task_service.py tests/test_tasks_api.py -q`
  - 结果：`74 passed, 5 warnings`
- [x] `npm test`
  - 结果：`PASS`（包含新增 `completion_retry.test.ts`）
- [x] `npm run build`
  - 结果：`PASS`
- [x] `just docs-build`
  - 结果：`PASS`

### 4.2 验证限制

- [ ] 没有在真实任务数据库上做 UI 点击演练；本次依赖现有纯函数测试、FastAPI 路由回归和 TypeScript/MkDocs 构建作为验收证据。

## 5. Delivered Outcome

### 已完成

- [x] 用户现在能理解错误来源：是 merge 前的 main 工作区脏保护触发
- [x] 用户在清理主工作区后，可以直接再次点击 `Complete`
- [x] 普通 `changes_requested` 任务不会被误显示为可直接 Complete

### 残余风险

- 当前 eligibility 依赖最近一次 `BUG` 日志内容；如果未来更改 completion 失败日志文案，需要同步更新前后端判定常量。

## 6. Follow-up

- [ ] 如果后续还要细分 `changes_requested` 的来源，可以考虑把“completion retry candidate”沉淀为显式 API 字段，而不是继续基于日志内容推断。
