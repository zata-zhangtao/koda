# PRD：修复 PRD 启动链未透传 auto-confirm 参数

**原始需求标题**：它根本没有在工作,是不是前面的某次commit 破坏了codex 的调用
**需求名称（AI 归纳）**：修复 PRD 启动链未透传 auto-confirm 参数
**文件路径**：`tasks/20260330-141018-prd-prd-wrapper-auto-confirm-forwarding-fix.md`
**创建时间**：2026-03-30 14:10:18 CST
**参考上下文**：`logs/app.log`, `dsl/api/tasks.py`, `dsl/services/automation_runner.py`, `dsl/services/codex_runner.py`, `tests/test_automation_runner_registry.py`, `tasks/archive/20260326-235534-prd-card-create-auto-confirm-and-run.md`

---

## 1. Background

用户反馈“PRD 根本不会创建”，界面停留在 `prd_generating`，右侧 PRD 面板一直为空。进一步查看应用日志发现：

- `2026-03-30 13:41:53 +0800`：任务 `1648aff5` 已进入 `prd_generating`
- `2026-03-30 13:51:14 +0800`：watchdog 检测任务卡死并尝试恢复
- 同一时间抛出异常：`TypeError: run_task_prd() got an unexpected keyword argument 'auto_confirm_prd_and_execute_bool'`

这说明问题不在“PRD 生成后是否跳过人工确认”，而是在 PRD 启动链本身已经因为参数签名不匹配而无法稳定执行。

## 2. Root Cause

### 2.1 代码链路

1. `dsl/api/tasks.py` 在开始任务和恢复 `prd_generating` 时，都会调度 `run_codex_prd(...)`
2. 该名称在 API 层实际上别名到了 `dsl/services/automation_runner.py:run_task_prd(...)`
3. 自 `c0656f86 feat(task): add auto-confirm PRD and execute strategy` 起，调用方开始传入：
   - `auto_confirm_prd_and_execute_bool=task_obj.auto_confirm_prd_and_execute`
4. 但 `automation_runner.run_task_prd(...)` 仍保留 `494f511 feat(runners): add multi-runner support with Claude CLI integration` 时的旧签名，没有接收该参数

### 2.2 影响

- 任务开始后的 PRD 后台任务可能直接因 `TypeError` 失败
- watchdog 自动恢复 `prd_generating` 任务时会稳定崩溃
- UI 只会看到任务长期停在“AI 正在生成 PRD”，而不会出现 PRD 文件

## 3. Clarification

“跳过确认 / auto-confirm” 不是“PRD 不创建”的直接原因。

`dsl/services/codex_runner.py:run_codex_prd(...)` 的逻辑是：

1. 先执行 `_run_codex_phase(...)` 生成 PRD
2. 只有在 PRD 生成成功后，才读取 `auto_confirm_prd_and_execute_bool`
3. 然后决定停在 `prd_waiting_confirmation`，还是直接进入 `implementation_in_progress`

因此，若 PRD 文件根本没生成，优先排查的是启动链路和 wrapper 契约，而不是 auto-confirm 的业务策略。

## 4. Implementation Guide

### 4.1 Required Change

更新 `dsl/services/automation_runner.py:run_task_prd(...)`：

- 新增可选参数 `auto_confirm_prd_and_execute_bool: bool | None = None`
- 将该参数原样透传给 `dsl/services/codex_runner.py:run_codex_prd(...)`
- 保持 `None` 兼容语义不变，让下游在必要时仍可从数据库回读任务策略

### 4.2 Regression Coverage

在 `tests/test_automation_runner_registry.py` 增加回归测试：

- 直接调用 `automation_runner.run_task_prd(...)`
- 显式传入 `auto_confirm_prd_and_execute_bool=True`
- 断言下游 `run_codex_prd(...)` 收到了相同值

这条测试会在 wrapper 再次发生签名漂移时第一时间失败。

## 5. Change Matrix

| Change Target | Current State | Target State | Affected Files |
|---|---|---|---|
| PRD wrapper signature | 未接收 `auto_confirm_prd_and_execute_bool` | 接收并透传该参数 | `dsl/services/automation_runner.py` |
| Regression coverage | 无直接覆盖 wrapper 参数漂移 | 增加 wrapper 透传测试 | `tests/test_automation_runner_registry.py` |

## 6. Definition of Done

- [x] 明确定位“PRD 不生成”的真实根因
- [x] 证明问题不是 auto-confirm 业务分支本身
- [x] 修复 `run_task_prd(...)` 的参数签名与透传逻辑
- [x] 新增回归测试覆盖该参数透传
- [x] 相关 pytest 节点测试通过

## 7. Verification

- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_automation_runner_registry.py::test_run_task_prd_forwards_auto_confirm_flag -q`
  - 结果：`1 passed in 2.12s`
- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_automation_runner_registry.py::test_runner_registry_supports_codex_and_claude -q`
  - 结果：`1 passed in 2.13s`
- `git diff --check -- dsl/services/automation_runner.py tests/test_automation_runner_registry.py`
  - 结果：通过，无 whitespace / patch 格式问题

## 8. Delivered Outcome

- 修复了 task start / watchdog resume 共用的 PRD wrapper 契约漂移问题
- 保留 auto-confirm 原有语义，不改动 PRD 成功后的分流逻辑
- 为该回归点补上了最小且直接的单元测试
