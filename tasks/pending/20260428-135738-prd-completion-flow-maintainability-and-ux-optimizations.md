# PRD: Completion Flow Maintainability And UX Optimizations

**Original Need:** 把项目中当前还需要优化的点写入 PRD，并放到 `tasks/pending` 文件夹。
**AI-Normalized Name:** Improve the maintainability, API consistency, user experience, and verification coverage around the completion checklist flow.
**Date:** 2026-04-28
**Status:** Pending

## 1. Introduction & Goals

当前 completion checklist gate 已经把任务完成动作收敛到后端 canonical checklist、签名校验和审计日志路径。这个改动提升了完成流程的安全性，但也暴露出下一阶段可以继续优化的工程点：前端主组件承担了过多状态和突变逻辑，后端 checklist service 同时负责 Markdown 解析、构建、签名、校验和审计，错误合同还只是围绕当前场景做了增量扩展，用户可见文案存在中英混用，真实浏览器端到端验证也还可以补强。

本需求目标不是改变 completion checklist gate 的核心行为，而是在现有行为稳定后，降低维护成本、统一用户体验，并补足回归验证。

Goals:

- 将 completion checklist 相关前端状态、API 调用和 modal UI 从 `App.tsx` 中拆分出来，降低主工作台复杂度。
- 将后端 checklist service 拆分为清晰的 parser / builder / validator / audit 职责，保持路由层和 schema 层轻量。
- 统一 API 错误 envelope，让 stale checklist、缺失确认项、资格不满足等错误都有稳定机器可读字段。
- 统一 completion checklist 用户可见文案语言，避免中英混用。
- 增加真实浏览器端到端用例，覆盖普通 `Complete`、stale checklist refresh 和 `manual_complete`。
- 明确无 worktree 任务的后续归档策略：如果产品需要关闭这类任务，应设计独立 archive/close flow，而不是复用 `Complete`。

## 2. Requirement Shape

- **Actor:** 维护 Koda 任务完成流程的开发者，以及使用任务详情页完成需求的用户。
- **Trigger:** 开发者继续迭代 completion checklist gate；用户在任务详情页点击 `Complete` 或缺失分支场景下的 `Confirm Complete`。
- **Expected Behavior:** 完成流程用户行为不回退；代码结构更容易理解和测试；API 错误更稳定；用户看到的 checklist 和错误提示语言一致；关键完成路径有真实浏览器回归覆盖。
- **Explicit Scope Boundary:** 本需求不改变当前 `/complete` 的 Git finalization 顺序，不取消 checklist signature 校验，不新增 checklist 持久化表，不把前端勾选状态跨会话保存。

## 3. Repository Context And Architecture Fit

Current relevant modules/files:

- `frontend/src/App.tsx`
  - 当前承载 completion checklist modal state、打开 checklist、提交 checklist、stale refresh、普通 complete 和 manual complete 的编排。
  - 文件已经较大，继续堆叠完成流程状态会让主工作台难以维护。
- `frontend/src/api/client.ts`
  - 当前新增了 `ApiClientError`，能处理 `refresh_required` 和 `missing_checklist_item_ids`。
  - 可以继续演进为更通用的 API error contract。
- `frontend/src/types/index.ts`
  - 当前已经定义 `TaskCompletionChecklistMode`、`TaskCompletionChecklistResponse` 和 `TaskCompletionConfirmation`。
- `frontend/src/utils/task_completion.ts`
  - 当前集中维护 Complete 可见性规则。
  - 后续需要继续保持与后端资格校验同步。
- `backend/dsl/services/task_completion_checklist_service.py`
  - 当前同时负责 PRD Markdown 提取、候选排序去重、checklist 构建、签名、确认校验和审计日志。
  - 功能集中但文件偏大，适合进一步按职责切分。
- `backend/dsl/api/tasks.py`
  - 当前负责 completion checklist endpoint、`/complete` 和 `/manual-complete` 的错误映射。
  - 需要避免继续把 checklist 业务细节堆到 route handler。
- `backend/dsl/schemas/task_schema.py`
  - 当前承载 completion checklist schema。
  - 后续如果 checklist schema 增长明显，可考虑按 task 子域拆 schema 文件。
- `tests/test_task_completion_checklist_service.py`
  - 当前覆盖 service-level checklist 行为。
- `tests/test_tasks_api.py`
  - 当前覆盖 HTTP contract 和 legacy bypass rejection。
- `frontend/tests/app_task_mutation_refresh.test.ts`
  - 当前用 jsdom 覆盖 modal 打开、勾选、请求体和 stale refresh。
  - 仍缺少真实浏览器布局、焦点和交互验证。
- `docs/architecture/system-design.md`
- `docs/guides/dsl-development.md`
- `docs/dev/evaluation.md`

Architecture constraints:

- API/routes 只负责请求编排和错误映射，completion checklist 的业务规则应继续留在服务层。
- React render 逻辑不能成为可信边界；后端必须继续重新生成 checklist 并验证 signature 与 item ids。
- 前端拆分应复用现有 `taskApi` 和类型定义，不新增第二套 API client。
- 所有 Markdown、JSON 或日志文件 I/O 必须显式使用 `encoding="utf-8"`。
- 文档必须同步更新，且 `just docs-build` 应通过。

Potential redundancy risks:

- 不要引入第二个 completion modal 状态源；拆分 hook 后仍应只有一个入口管理 checklist modal。
- 不要把 checklist 文案同时硬编码在前端和后端。前端应优先渲染后端返回内容；系统错误提示可以在前端做本地化映射。
- 不要新增无 worktree 的 `Complete`。如果需要关闭无 worktree 任务，应命名为 archive/close/abandon 等独立动作。

## 4. Recommendation

### Recommended Approach

分三步做小范围重构和验证增强。

1. 前端拆分 completion checklist flow：
   - 新增 `frontend/src/hooks/useCompletionChecklist.ts`，负责打开 checklist、维护勾选状态、提交确认、处理 stale refresh。
   - 新增 `frontend/src/components/CompletionChecklistModal.tsx`，只负责展示和交互事件回调。
   - `App.tsx` 保留任务级动作入口和成功后的 dashboard refresh 编排，不直接管理 checklist item set。
   - 保持 `TaskCompletionConfirmation` 请求体结构不变。

2. 后端拆分 checklist service 内部职责：
   - 将 PRD Markdown acceptance checklist 解析逻辑拆到单独 helper/module。
   - 将 canonical item 构建和 signature 生成保留为纯函数，便于单元测试。
   - 将 confirmation validation 保留为服务层 use case，继续返回当前 response schema。
   - 将 audit log 写入保持在服务层，避免 route handler 直接拼审计文本。

3. 统一错误合同和用户体验：
   - 定义稳定 error detail shape，例如 `message`、`code`、`refresh_required`、`missing_checklist_item_ids`。
   - 前端 `ApiClientError` 暴露 `code`，用 `refresh_required` 驱动 stale refresh。
   - completion checklist 用户可见 label 和 modal 文案统一语言。推荐当前中文界面使用中文系统安全项；保留机器字段英文。
   - 对无 worktree 任务，如果产品确实需要手动归档，单独设计 `Archive without worktree` 或 `Close non-code requirement`，并要求独立审计日志，不复用 `Complete`。

4. 补充验证：
   - 保留并更新现有 backend unit/API tests。
   - 保留并更新现有 frontend jsdom tests。
   - 增加真实浏览器 E2E：普通 Complete 打开 modal、未全选按钮禁用、全选提交；stale signature 返回后刷新 modal；manual complete 打开 `manual_complete` checklist 并提交。
   - 更新 `docs/dev/evaluation.md`，把真实浏览器验证加入人工验收清单。

Why this fits the current architecture:

- checklist gate 的安全边界仍在后端。
- 前端复杂状态从主工作台移出，但不会改变现有任务突变和 dashboard refresh 策略。
- service 拆分后更符合 backend layered architecture，便于后续扩展 checklist 来源。
- 错误合同稳定后，前端不需要解析任意字符串判断行为。

### Alternatives Considered

| Alternative | Why Not Recommended |
| --- | --- |
| 继续把 checklist flow 留在 `App.tsx` | 短期省事，但主组件会继续膨胀，后续完成流程或错误处理修改风险更高。 |
| 把所有 checklist 逻辑搬到前端 | 会破坏可信边界，旧客户端仍可能绕过确认。 |
| 新增 checklist 数据表保存勾选状态 | 当前需求只需要提交前一次性确认，持久化会引入过期、清理和迁移成本。 |
| 重新允许无 worktree Complete | 会重新模糊 Complete 的语义，削弱当前 gate 的价值。 |

## 5. Acceptance Checklist

### Frontend Acceptance

- [ ] `App.tsx` 不再直接维护 `checkedItemIdSet` 或 checklist modal submit 细节。
- [ ] Completion checklist modal 被拆成独立组件，并通过 props 接收展示状态和事件回调。
- [ ] 普通 `Complete` 和 `manual_complete` 继续复用同一套 hook/组件。
- [ ] stale checklist refresh 后会清空勾选项，并提示用户重新勾选。
- [ ] 用户可见 completion checklist 系统项和 modal 提示语言一致。

### Backend Acceptance

- [ ] PRD acceptance checklist 解析、canonical checklist 构建、signature 生成和 confirmation validation 有清晰职责边界。
- [ ] `/completion-checklist`、`/complete`、`/manual-complete` 的外部合同保持兼容，除非文档明确说明迁移。
- [ ] API error detail 包含稳定机器可读 `code`，并保留 `refresh_required` 与 `missing_checklist_item_ids`。
- [ ] 后端仍拒绝 legacy `PUT /status -> CLOSED` 和 `PUT /stage -> done` 绕过 checklist gate。

### Test Acceptance

- [ ] Backend unit/API tests 覆盖拆分后的 parser、builder、validator 和 route error mapping。
- [ ] Frontend tests 覆盖 hook、modal 禁用态、提交 payload 和 stale refresh。
- [ ] 新增真实浏览器 E2E 覆盖普通 Complete、manual complete 和 stale checklist refresh。
- [ ] `uv run pytest` 或项目约定的后端测试命令通过。
- [ ] 前端测试命令通过。
- [ ] `just docs-build` 通过。

### Documentation Acceptance

- [ ] `docs/architecture/system-design.md` 说明新的 frontend/backend 责任边界。
- [ ] `docs/guides/dsl-development.md` 说明 completion checklist 开发约束。
- [ ] `docs/dev/evaluation.md` 加入浏览器端到端验收步骤。
- [ ] API reference 仍能渲染 completion checklist schemas 和 endpoints。

## 6. Non-Goals

- 不改变当前 Git finalization 的 `git add / commit / rebase / merge / cleanup` 顺序。
- 不新增 checklist 持久化表。
- 不自动判断代码是否真的满足 PRD 验收项。
- 不把无 worktree 任务重新纳入普通 `Complete`。
- 不引入 GitHub PR-backed completion；该方向应由远程协作 PRD 单独处理。
