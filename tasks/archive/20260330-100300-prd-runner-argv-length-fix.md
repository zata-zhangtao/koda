# PRD：修复 Runner Prompt 参数过长导致自动回改失败

**原始需求标题**：这个是什么问题 / 修复 Codex 自动回改阶段 `Errno 7 Argument list too long`
**需求名称（AI 归纳）**：Runner Prompt 传输修复：将自动化 Prompt 从 argv 改为 stdin，避免超长参数失败
**文件路径**：`tasks/20260330-100300-prd-runner-argv-length-fix.md`
**创建时间**：2026-03-30 10:03:00 CST
**需求背景/上下文**：任务异常处理日志显示 `runner_kind=codex` 在 AI 自动回改阶段反复报 `Errno 7 Argument list too long`，自动重试后仍失败并回退到 `changes_requested` / 待修改阶段。根因是后端把大 Prompt 直接作为 CLI 位置参数传给 `codex exec` / `claude -p`，触发操作系统 argv 长度限制。
**附件信息**：用户提供了异常处理面板截图，显示同一轮自动回改连续重试后仍以 `Errno 7 Argument list too long` 失败。
**参考上下文**：`dsl/services/codex_runner.py`, `dsl/services/runners/base.py`, `dsl/services/runners/codex_cli_runner.py`, `dsl/services/runners/claude_cli_runner.py`, `tests/test_codex_runner.py`, `docs/guides/codex-cli-automation.md`, `docs/core/prompt-management.md`

---

## 1. Introduction & Goals

### 背景

当前自动化链路会把实现、review、review-fix、lint-fix、冲突修复等阶段生成的完整 Prompt 直接拼进命令行参数：

- `codex exec --dangerously-bypass-approvals-and-sandbox "<prompt>"`
- `claude -p "<prompt>" --dangerously-skip-permissions`

当上下文包含较长 DevLog、自检结论或冲突说明时，子进程会在启动前就被操作系统拒绝，表现为：

- `Errno 7 Argument list too long`
- 自动重试无效，因为根因不是临时中断，而是确定性的启动参数溢出
- 最终任务回退到人工处理阶段

### 可衡量目标

- [x] 内置 Codex/Claude runner 在异步自动化阶段不再通过 argv 传递完整 Prompt。
- [x] 同步冲突修复路径（rebase / merge runner conflict resolution）也不再通过 argv 传递完整 Prompt。
- [x] 保持现有阶段推进、取消、自动重试、日志落库和任务回退语义不变。
- [x] 为新传输合同增加定向回归测试。
- [x] 同步更新操作文档，避免运行时行为与文档描述不一致。

## 2. Root Cause

### 2.1 直接原因

`dsl/services/codex_runner.py` 在以下位置把完整 Prompt 作为位置参数传给 CLI：

- `_create_codex_subprocess(...)`
- `_create_claude_subprocess(...)`
- `_run_logged_runner_conflict_resolution(...)`

其中 review-fix / lint-fix / conflict-resolution 阶段都可能组合较大的上下文块，因此最容易命中 argv 长度限制。

### 2.2 为什么重试无效

当前 `_run_codex_phase(...)` 会把子进程创建阶段抛出的异常视为阶段异常并重试。但 `Argument list too long` 不是临时失败，而是同一输入下每次都会稳定复现的启动失败，所以自动重试只会重复写相同错误日志。

## 3. Delivered Changes

### 3.1 代码改动

| Change Target | Delivered Behavior | Files |
|---|---|---|
| 异步 Codex 启动 | 改为 `codex exec ... -`，并通过 stdin 写入 Prompt | `dsl/services/codex_runner.py`, `dsl/services/runners/codex_cli_runner.py` |
| 异步 Claude 启动 | 改为 `claude -p --dangerously-skip-permissions`，并通过 stdin 写入 Prompt | `dsl/services/codex_runner.py`, `dsl/services/runners/claude_cli_runner.py` |
| 同步冲突修复 | 改为 `subprocess.run(..., input=runner_prompt_text)`，不再把 Prompt 拼进 argv | `dsl/services/codex_runner.py` |
| Runner 协议 | 新增 `build_stdin_prompt_text(...)`，显式表达 stdin 传输合同 | `dsl/services/runners/base.py` |
| 通用 fallback | generic async launcher 也会遵守新的 stdin 合同 | `dsl/services/codex_runner.py` |
| 回归测试 | 新增 3 条 stdin 传输回归，锁定 Codex、Claude、冲突修复三条关键路径 | `tests/test_codex_runner.py` |
| 文档同步 | 把调用示例从 argv 形式改为 stdin 形式，并补充 transport 说明 | `docs/guides/codex-cli-automation.md`, `docs/core/prompt-management.md` |

### 3.2 明确不做的事

- 不在本次修复里引入 Prompt 截断或摘要化。
- 不调整自动重试次数或阶段回退语义。
- 不新增数据库字段。

原因：这次线上问题的根因是 transport 方式错误，而不是 Prompt 内容本身必须缩短。

## 4. Verification

### 4.1 通过的验证

- [x] `./.venv/bin/pytest tests/test_codex_runner.py -q -k "create_codex_subprocess or create_claude_subprocess or run_logged_runner_conflict_resolution"`
  - 结果：`3 passed, 24 deselected in 1.59s`
- [x] `/bin/bash -lc 'UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build'`
  - 结果：`Documentation built in 3.58 seconds`
- [x] `git diff --check`
  - 结果：无输出，退出码 `0`

### 4.2 验证限制

- [ ] `tests/test_automation_runner_registry.py` 的若干本地运行在当前环境中卡在 `collecting ...`，没有产出可操作的失败栈。
- [ ] 一些 exact node-id 形式的 pytest 调用在当前环境也出现相同现象。

这说明当前本地 pytest 环境还存在独立于本次改动的稳定性问题；本次交付主要依赖已通过的 stdin 回归、文档构建和 diff 健康检查作为验收证据。

## 5. Delivered Outcome

### 已完成

- [x] 解决 `Errno 7 Argument list too long` 对自动回改阶段的直接触发条件
- [x] 把同样的修复扩展到冲突修复分支，避免只修主流程、遗漏 Git 收尾链路
- [x] 保持 runner_kind 可观测性与当前日志合同
- [x] 保持现有 Prompt 语义，不做静默截断

### 残余风险

- pytest 环境中的 collection 卡顿仍需单独排查，否则会影响更大范围回归信心。
- Prompt 本身依然可能非常长；虽然现在不会再触发 argv 溢出，但后续仍可评估 token 成本与摘要策略。

## 6. Follow-up

- [ ] 排查 `tests/test_automation_runner_registry.py` 在当前环境里卡在 `collecting ...` 的原因。
- [ ] 后续评估是否需要在 transport 修复之外，再增加 token-budget 级别的 Prompt 保护措施。
