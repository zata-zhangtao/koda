# PRD：任务自动化中断后恢复执行

**原始需求标题**：there is a issue, if program be interupt, it can not continue
**需求名称（AI 归纳）**：任务自动化中断后恢复执行
**文件路径**：`tasks/20260324-194918-prd-interrupted-automation-resume.md`
**创建时间**：2026-03-24 19:49:18 CST
**参考上下文**：`dsl/api/tasks.py`, `dsl/services/task_service.py`, `dsl/services/codex_runner.py`, `frontend/src/App.tsx`, `frontend/src/api/client.ts`, `tests/test_tasks_api.py`, `tests/test_codex_runner.py`

---

## 1. Introduction & Goals

### 背景

当前任务自动化把真实业务阶段持久化在数据库的 `workflow_stage` 中，但后台执行中的瞬时运行态只保存在进程内存里：

- `is_codex_task_running` 依赖 `dsl/services/codex_runner.py` 里的运行中任务注册表
- 当后端进程、后台任务或服务本身被打断后，内存态会丢失
- 数据库里的任务却会停留在最近一次已落库的阶段，例如 `prd_generating`、`implementation_in_progress`、`self_review_in_progress`、`test_in_progress` 或 `pr_preparing`

结果是：

- 前端仍然看到任务停在“执行中阶段”
- 但后台其实已经没有活跃自动化
- 用户输入 `go on` / `continue` 时，只能覆盖少数阶段，无法真正从中断点继续

### 目标

- [x] 为中断后的任务提供显式的后端恢复入口
- [x] 支持从 `prd_generating`、`implementation_in_progress`、`self_review_in_progress`、`test_in_progress`、`pr_preparing` 恢复
- [x] 保持已停在“等待用户点击 Complete”的 self-review / lint 阶段不可重跑
- [x] 让前端现有的 `go on` / `continue` / `resume` 快捷输入真正走恢复链路
- [x] 补齐后端测试、前端构建验证与文档同步

## 2. Change Matrix

| Change Target | Current State | Target State | How to Modify | Affected Files |
|---|---|---|---|---|
| 任务恢复 API | 没有独立恢复入口 | 新增 `POST /api/tasks/{task_id}/resume` | 校验当前阶段、运行态与 parked 状态，再调度对应后台任务 | `dsl/api/tasks.py`, `dsl/services/task_service.py` |
| 中断后的自检恢复 | 只能重新走完整执行或人工接管 | 可从 `self_review_in_progress` 继续自检并自动进入 lint | 新增 `run_codex_review_resume` wrapper | `dsl/services/codex_runner.py` |
| 中断后的 lint 恢复 | `test_in_progress` 中断后没有恢复入口 | 可从 `test_in_progress` 继续 lint 闭环 | 新增 `run_post_review_lint_resume` wrapper | `dsl/services/codex_runner.py` |
| 前端 continue 快捷指令 | 仅覆盖 `changes_requested` 和部分 `implementation_in_progress` | 可对真正可恢复的阶段调用新恢复 API | 扩展 continue 逻辑并保留 parked 阶段提示 | `frontend/src/App.tsx`, `frontend/src/api/client.ts` |
| 回归测试 | 未覆盖恢复链路 | 覆盖 API 调度、parked 阶段保护、runner wrapper 行为 | 新增测试 | `tests/test_tasks_api.py`, `tests/test_codex_runner.py` |
| 文档 | 未定义中断恢复合同 | 明确恢复入口与 continue 行为 | 更新 API 参考与自动化说明 | `docs/api/references.md`, `docs/guides/codex-cli-automation.md` |

## 3. Functional Requirements

1. **FR-1**：系统必须提供独立的任务恢复 API，而不是复用普通 `execute` 起跑入口。
2. **FR-2**：恢复 API 只允许在没有活跃后台自动化时触发。
3. **FR-3**：恢复 API 必须支持 `prd_generating`、`implementation_in_progress`、`self_review_in_progress`、`test_in_progress`、`pr_preparing`。
4. **FR-4**：若 `self_review_in_progress` 最近一轮已经通过，则恢复 API 必须拒绝重跑，并要求用户点击 `Complete`。
5. **FR-5**：若 `test_in_progress` 最近一轮 lint 已通过，则恢复 API 必须拒绝重跑，并要求用户点击 `Complete`。
6. **FR-6**：前端输入 `go on`、`continue`、`resume`、`retry` 等继续指令时，必须对可恢复阶段调用恢复 API。
7. **FR-7**：`changes_requested` 的继续语义保持不变，仍走正常的 `execute` 重试入口。
8. **FR-8**：文档必须同步记录新的恢复入口与 parked 阶段保护规则。

## 4. Non-Goals

- 不改变 `changes_requested` 的业务语义
- 不自动把所有中断阶段都强制回退到 `changes_requested`
- 不重构现有完整 workflow 状态机
- 不新增数据库字段记录恢复点；继续基于现有日志和 `workflow_stage` 推断 parked 状态

## 5. Definition of Done

- [x] 可恢复阶段存在后端恢复入口
- [x] `self_review_in_progress` 与 `test_in_progress` 的 parked 状态不会被错误重跑
- [x] 前端 continue 指令能触发真实恢复
- [x] `uv run pytest tests/test_tasks_api.py tests/test_codex_runner.py` 通过
- [x] `npm --prefix frontend run build` 通过
- [x] `just docs-build` 通过

## 6. Implementation Outcome

### 已交付内容

- 新增 `resume_task(...)` 路由与阶段校验
- 新增 `TaskService.prepare_task_resume(...)`
- 新增 `run_codex_review_resume(...)` 与 `run_post_review_lint_resume(...)`
- 更新前端 continue 快捷输入逻辑
- 更新 API 文档与 Codex 自动化文档
- 新增恢复链路回归测试

### 验证证据

- `uv run pytest tests/test_tasks_api.py tests/test_codex_runner.py -q`
  - 结果：`30 passed in 1.08s`
- `npm --prefix frontend run build`
  - 结果：Vite 生产构建成功
- `just docs-build`
  - 结果：MkDocs 严格模式构建成功

### 偏差与取舍

- 恢复能力基于现有 `workflow_stage + DevLog` 推断，不新增持久化恢复元数据
- parked 自检和 parked lint 仍然保持人工 `Complete` 边界，不会因为 `continue` 而重新跑自动化

### Follow-up

- 若未来需要更细粒度的恢复点，考虑把“最近一轮 review/lint 是否已 settle”沉淀为显式持久化状态，而不是仅靠日志推断
