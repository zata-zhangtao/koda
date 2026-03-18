# Codex 自动化

## 总览

这个仓库不是“仅仅支持手动调用 Codex”，而是已经把 `codex exec` 接进了任务生命周期。

真实调用入口有两个：

- `dsl/api/tasks.py` 的 `start_task` 会在后台触发 `run_codex_prd`
- `dsl/api/tasks.py` 的 `execute_task` 会在后台触发 `run_codex_task`

对应的核心实现位于 `dsl/services/codex_runner.py`。

## 当前实现方式

### PRD 生成链路

1. 前端点击“开始任务”
2. 后端将任务推进到 `prd_generating`
3. 如果任务绑定了 `Project`，优先创建或复用 Git worktree
4. `run_codex_prd` 组装 PRD Prompt
5. 后端调用 `codex exec`
6. 输出被实时写入数据库和 `/tmp/koda-<task短ID>.log`
7. 成功后任务推进到 `prd_waiting_confirmation`
8. 默认停在确认阶段，等待用户确认 PRD；不会自动继续执行代码实现，也不会默认提交代码

### 编码执行链路

1. 前端点击“开始执行”
2. 后端将任务推进到 `implementation_in_progress`
3. `run_codex_task` 组装实现 Prompt
4. 后端调用 `codex exec`
5. 输出继续实时写入 `DevLog`
6. 实现成功后任务推进到 `self_review_in_progress`
7. 后端立即启动 `run_codex_review` 执行 AI 自检与代码评审
8. 若 review 发现阻塞问题，任务回退到 `changes_requested`
9. 若 review 通过，任务保持在 `self_review_in_progress`，等待后续测试自动化或人工推进

### 完成收尾链路

1. 前端点击“Complete”
2. 后端将任务推进到 `pr_preparing`
3. `run_codex_completion` 组装完成阶段 Prompt
4. 后端调用 `codex exec`
5. Codex 在任务 worktree 中按顺序执行：先 `commit`，再 `git rebase main`
6. 输出继续实时写入 `DevLog`
7. 若收尾成功，任务自动推进到 `done`
8. 若收尾失败，任务回退到 `changes_requested`

## Prompt 来源

### PRD Prompt

由 `run_codex_prd` 直接在代码中拼接，输入包括：

- 任务标题
- 最近几条任务日志
- 当前 worktree 路径
- 生成 PRD 的固定章节规范

它会要求 Codex 真正在 `tasks/` 目录中写出 `*-prd-*.md` 文件，而不是只把内容打印到终端。

### 实现 Prompt

由 `build_codex_prompt` 构造，输入包括：

- 任务标题
- 最近最多 10 条历史日志
- 可选的 worktree 路径

当前 Prompt 会显式要求：

- 在现有代码风格内修改
- Python 保持 Google Style Docstring
- 文件读写显式使用 `encoding="utf-8"`
- 不要默认执行 `git commit`，必须等待用户确认

### 自检 Prompt

由 `build_codex_review_prompt` 构造，输入包括：

- 任务标题
- 最近最多 12 条历史日志
- 可选的 worktree 路径

当前 Prompt 会显式要求：

- 这是 review-only 阶段，不修改文件
- 审查需求覆盖、明显回归、文档同步和错误路径
- 输出结构化标记 `SELF_REVIEW_SUMMARY` 与 `SELF_REVIEW_STATUS`

### 完成阶段 Prompt

由 `build_codex_completion_prompt` 构造，输入包括：

- 任务标题
- 最近最多 8 条历史日志
- 必填的 worktree 路径

当前 Prompt 会显式要求：

- 所有 Git 操作都发生在当前任务 worktree
- 严格按顺序先执行 `commit`，再执行 `git rebase main`
- 不要 push、不要 merge、不要删除分支
- 若无可提交改动、缺少 `main` 或 rebase 冲突，要明确报告失败原因

## 实际调用特征

当前仓库中的调用并没有使用 `--json` 事件流，而是选择了更直接的标准输出监听方式：

```bash
codex exec --dangerously-bypass-approvals-and-sandbox "<prompt>"
```

实现细节如下：

- `cwd` 由 Python `asyncio.create_subprocess_exec` 指定为项目根目录或 worktree
- `stderr` 被合并到 `stdout`
- 输出按行读取
- 每积累 5 行，或等待 1.5 秒，就批量写入一条 `DevLog`

## 日志与可观测性

### 数据库时间线

Codex 的输出不是单独存放在某个审计表中，而是直接写回 `DevLog` 时间线。这意味着前端可以把 AI 执行过程当成普通日志流来展示。

### 本地日志文件

每个任务还会生成一个独立的本地日志文件：

```text
/tmp/koda-<task短ID>.log
```

你可以通过后端接口 `POST /api/tasks/{task_id}/open-terminal` 打开一个新的终端窗口执行 `tail -f`。默认支持 macOS、WSL 与常见 Linux 桌面终端；如果默认命令不适合当前环境，可通过 `KODA_OPEN_TERMINAL_COMMAND` 覆盖。

### PRD 文件定位

后端读取 PRD 内容时，会在任务的 worktree 中查找：

```text
tasks/*-prd-*.md
```

并选择按名称逆序排序后的最新文件返回给前端。

## 故障处理

### 未安装 `codex`

如果开发机找不到 `codex` 可执行文件：

- 后端会写入一条 `BUG` 类型的 DevLog
- 任务阶段会回退到 `changes_requested`

### PRD 重新生成

`run_codex_prd` 在执行前会清理 worktree `tasks/` 下旧的 `*-prd-*.md` 文件，避免前端读取到历史版本。

### Worktree 选择优先级

Codex 的工作目录选择顺序如下：

1. 任务已有 `worktree_path`
2. 任务绑定的 `Project.repo_path`
3. Koda 仓库根目录

## 当前边界

当前实现已经把 Codex 接进任务编排，但还不是完整代理平台：

- 没有使用结构化 JSON 事件流
- 还没有把测试、PR 创建、验收代理自动串起来
- Prompt 仍然写死在 Python 字符串中，没有独立版本管理

如果你打算继续扩展这一层，建议先看[Prompt 管理](../core/prompt-management.md)和[系统设计](../architecture/system-design.md)。
