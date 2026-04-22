# PRD：任务强制中断能力

**原始需求标题**：现在缺少一个强制中断的功能
**需求名称（AI 归纳）**：任务强制中断能力
**文件路径**：`tasks/20260422-145351-prd-force-interrupt.md`
**创建时间**：2026-04-22 14:53:51 CST
**参考上下文**：`backend/dsl/api/tasks.py`, `frontend/src/App.tsx`, `frontend/src/api/client.ts`, `tests/test_tasks_api.py`, `docs/api/references.md`, `docs/guides/dsl-development.md`, `docs/guides/codex-cli-automation.md`

---

## 1. Introduction & Goals

### 背景

当前系统已经有普通 `POST /api/tasks/{task_id}/cancel`：

- 后端会尝试终止活跃 runner，并把任务回退到 `changes_requested`
- 如果有邮件配置，还会发送“手动中断”通知

但产品层仍然缺一个显式的“强制中断”能力：

- 前端现有中断按钮只在 `is_codex_task_running=true` 时显示
- 一旦任务仍停在 `prd_generating` / `implementation_in_progress` / `self_review_in_progress` / `test_in_progress` / `pr_preparing`，但进程内运行标记已经丢失，用户就没有可点击的解锁入口
- 用户只能等待 watchdog 自动补救，或者手工刷新/排查，缺少明确的 break-glass 操作

### 目标

- [x] 提供独立的 `force-interrupt` API
- [x] 允许对运行阶段但卡死的任务执行强制中断
- [x] 在前端为“正在运行”和“运行标记丢失但阶段仍卡住”两类场景都暴露入口
- [x] 写入可见审计日志，说明这是人工强制接管
- [x] 补齐后端回归测试、前端构建验证和文档同步

## 2. Change Matrix

| Change Target | Current State | Target State | How to Modify | Affected Files |
|---|---|---|---|---|
| 强制中断 API | 没有独立 break-glass 路由 | 新增 `POST /api/tasks/{task_id}/force-interrupt` | 复用共享中断 helper，限制到 AI 运行阶段，并写审计日志 | `backend/dsl/api/tasks.py` |
| 中断逻辑复用 | `/cancel` 自己做 kill + 回退 + 发邮件 | 提取共享 interruption helper | 减少 `/cancel` 与 `/force-interrupt` 行为分叉 | `backend/dsl/api/tasks.py` |
| 审计可观测性 | 普通取消没有单独的强制接管日志 | Force interrupt 写一条时间线日志 | 用 `DevLog` 标记人工强制接管和 runner 清理结果 | `backend/dsl/api/tasks.py`, `tests/test_tasks_api.py` |
| 前端入口 | 只有运行态 banner 里的普通 `Cancel` | 运行中增加 `强制中断`，卡死时在动作区也显示 | 新增 API 调用、确认文案、按钮样式和兜底显隐逻辑 | `frontend/src/App.tsx`, `frontend/src/api/client.ts`, `frontend/src/index.css` |
| 文档合同 | API 参考与自动化说明中无 force-interrupt | 明确 force-interrupt 的适用阶段和用途 | 更新 API 路由引用、DSL 开发指南和自动化说明 | `docs/api/references.md`, `docs/guides/dsl-development.md`, `docs/guides/codex-cli-automation.md` |

## 3. Functional Requirements

1. **FR-1**：系统必须提供独立的 `POST /api/tasks/{task_id}/force-interrupt`，而不是只复用普通 `cancel` 文案。
2. **FR-2**：强制中断只允许在 `prd_generating`、`implementation_in_progress`、`self_review_in_progress`、`test_in_progress`、`pr_preparing` 触发。
3. **FR-3**：即使没有活跃 runner 进程，强制中断仍必须清理运行态，并把任务回退到 `changes_requested`。
4. **FR-4**：强制中断必须写入一条可见的 `DevLog`，记录中断前阶段和 runner 清理结果。
5. **FR-5**：前端在任务活跃执行时必须展示 `强制中断`；在任务停留于运行阶段但 `is_codex_task_running=false` 时，也必须提供兜底入口。
6. **FR-6**：API、前端和文档必须保持一致，避免只上线代码不更新说明。

## 4. Non-Goals

- 不新增数据库字段记录“强制中断原因”
- 不改动现有 `changes_requested` 的业务语义
- 不替代 watchdog 的自动恢复职责；force-interrupt 是人工 break-glass，而不是后台自愈
- 不重做前端整套任务动作布局

## 5. Definition of Done

- [x] `POST /api/tasks/{task_id}/force-interrupt` 可用
- [x] 强制中断仅允许 AI 运行阶段触发
- [x] 强制中断后任务回退到 `changes_requested`
- [x] 时间线出现一条强制接管审计日志
- [x] 前端在运行中与卡死兜底两种场景都能触发强制中断
- [x] `uv run pytest tests/test_tasks_api.py -q` 通过
- [x] `npm run build`（`frontend/`）通过
- [x] `just docs-build` 通过

## 6. Implementation Outcome

### 已交付内容

- 新增 `force_interrupt_task(...)` 路由
- 抽出共享 `_interrupt_task_to_changes_requested(...)` helper
- 新增 `_build_force_interrupt_log_text(...)` 审计日志生成逻辑
- 前端新增 `taskApi.forceInterrupt(...)`
- 详情页执行 banner 新增 `强制中断`
- 详情页动作区新增“卡死兜底” `强制中断`
- 新增强制中断后端回归测试
- 更新 API 参考、DSL 开发指南和 Codex 自动化说明

### 验证证据

- `uv run pytest tests/test_tasks_api.py -q`
  - 结果：`55 passed, 5 warnings`
- `npm run build`（在 `frontend/`）
  - 结果：Vite 生产构建成功
- `just docs-build`
  - 结果：MkDocs 严格模式构建成功

### 偏差与取舍

- 为了保持现有恢复路径一致，强制中断仍统一落到 `changes_requested`，而不是引入新的“强制停止”持久化阶段
- 邮件通知复用现有“手动中断”模板；本次没有单独拆出“强制中断”通知事件类型
- 前端没有新增复杂弹窗，而是先使用确认对话框，优先交付功能闭环

### Follow-up

- 如果后续需要区分普通取消和强制中断的通知审计，可以新增专门的 `TaskNotificationEventType`
- 如果需要更强的前端可追溯性，可以在成功强制中断后主动刷新当前任务时间线，而不是等待下一轮日志刷新
