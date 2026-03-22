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
3. 如果任务绑定了 `Project`，优先创建或复用 Git worktree；在 `worktree_path` 落库前，还会复制 `.env*` 并准备基础前后端依赖环境
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
8. 若 review 发现阻塞问题，系统会在同一个 worktree 中进入有上限的自动回改轮次，再重新执行 review-only 评审
9. 若 review 闭环在额度内通过，任务自动推进到 `test_in_progress`，并开始执行 `uv run pre-commit run --all-files`
10. 若 pre-commit 首次执行返回非零，系统会自动重跑一次，吸收 auto-fix hook 的常见改写场景
11. 若 lint 在自动重跑后仍失败，系统会在同一个 worktree 中进入有上限的 `lint -> AI lint-fix -> lint` 闭环
12. 若 lint 闭环在额度内通过，任务保持在 `test_in_progress`，等待用户点击 `Complete`
13. 只有当 review / lint 自动闭环次数耗尽、输出持续无效，或相关阶段执行失败时，任务才回退到 `changes_requested`

### 完成收尾链路

1. 前端点击“Complete”
2. 后端将任务推进到 `pr_preparing`
3. `run_codex_completion` 在任务 worktree 中执行固定 Git 命令：`git add .`、`git commit -m "<task summary>"`、`git rebase main`
4. 若 `rebase` 或后续 `merge` 出现冲突，后端会调用 Codex 自动修复冲突并继续 Git 操作
5. 后端会复用当前持有 `main` 分支的工作区完成 `git merge <task branch>`
6. merge 成功后继续清理 task worktree 与本地任务分支
7. 日志继续写入 `DevLog`
8. 若收尾成功，任务自动推进到 `done`
9. 若在合并到 `main` 前失败，任务回退到 `changes_requested`

## Prompt 来源

### PRD Prompt

由 `build_codex_prd_prompt` 构造，输入包括：

- 任务标题
- 最近几条任务日志
- 最近日志里解析出的本地图片/附件路径
- 任务 ID（用于目标文件名）
- 当前 worktree 路径
- 生成 PRD 的输出合同

当前 Prompt 会显式要求：

- 在 PRD 顶部元数据区域，同时输出 `原始需求标题` 和 `需求名称（AI 归纳）`
- `需求名称（AI 归纳）` 必须位于主要章节之前，且不能为空
- 如果上下文不足，`需求名称（AI 归纳）` 必须回退为原始标题的规范化版本
- 如果上下文里出现 `Attached local files:`，必须显式检查这些本地文件；若某些二进制文件无法完整解析，也不能静默忽略
- 将完整 PRD 写入任务专属文件 `tasks/prd-{task_id[:8]}-<english-requirement-slug>.md`，而不是只把内容打印到终端
- 文件名中的 `<english-requirement-slug>` 必须是基于需求内容归纳出的英文 kebab-case 短语，不能使用随机值

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

### 自动回改 Prompt

由 `build_codex_review_fix_prompt` 构造，输入包括：

- 任务标题
- 最近最多 10 条历史日志
- 最近一轮 review 的原始输出
- 当前自动回改轮次与回改上限
- 可选的 worktree 路径

当前 Prompt 会显式要求：

- 这是 review-fix 阶段，只修复最近一轮 review 明确指出的阻塞性问题
- 可以同步补齐代码、测试和文档，但不能重新大范围发散实现
- 必须继续在同一个 task worktree 中执行
- 不要执行 `git commit`、`git rebase`、`git merge`，不要创建 PR

### Lint 定向修复 Prompt

由 `build_codex_lint_fix_prompt` 构造，输入包括：

- 任务标题
- 最近最多 10 条历史日志
- 最近一次 pre-commit lint 的原始输出
- 当前 lint 定向修复轮次与回改上限
- 可选的 worktree 路径

当前 Prompt 会显式要求：

- 这是 lint-fix 阶段，只修复最近一次 lint 输出明确指出的问题
- 可以修改代码、文档和配置，但不能重新大范围发散实现
- 必须继续在同一个 task worktree 中执行
- 不要执行 `git commit`、`git rebase`、`git merge`，不要创建 PR

### 完成阶段说明文本

`build_codex_completion_prompt` 现在主要作为完成链路的人类可读说明，输入包括：

- 任务标题
- 最近最多 8 条历史日志
- 必填的 worktree 路径

它描述的真实后台行为是：

- 当前 task worktree 中执行 `git add .`、基于任务摘要的 `git commit -m ...`、`git rebase main`
- 优先复用已经持有 `main` 分支的工作区，而不是假定可以随时 `checkout main`
- 若 `rebase` / `merge` 冲突，则自动调用 Codex 修复并继续
- merge 成功后清理 worktree 与本地任务分支，不会 push

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

Codex 的输出不是单独存放在某个审计表中，而是直接写回 `DevLog` 时间线。这意味着前端可以把 AI 执行过程当成普通日志流来展示。对于当前自动化链路，时间线里会明确看到：

- 第 N 轮 review 发现问题 -> 第 N 轮自动回改 -> 第 N+1 轮复审
- review 通过 -> pre-commit lint -> AI lint-fix -> lint 复检

### 本地日志文件

每个任务还会生成一个独立的本地日志文件：

```text
/tmp/koda-<task短ID>.log
```

你可以通过后端接口 `POST /api/tasks/{task_id}/open-terminal` 打开一个新的终端窗口执行 `tail -f`。默认支持 macOS、WSL 与常见 Linux 桌面终端；如果默认命令不适合当前环境，可通过 `KODA_OPEN_TERMINAL_COMMAND` 覆盖。

### PRD 文件定位

后端读取 PRD 内容时，会在任务的 worktree 中查找：

```text
tasks/prd-{task_id[:8]}-<english-requirement-slug>.md
```

后端会按任务前缀 `tasks/prd-{task_id[:8]}*.md` 查找并返回最合适的文件，优先读取带英文语义 slug 的新命名，同时兼容旧的固定文件名。

## 故障处理

### 未安装 `codex`

如果开发机找不到 `codex` 可执行文件：

- 后端会写入一条 `BUG` 类型的 DevLog
- 任务阶段会回退到 `changes_requested`

### `changes_requested` 的真实语义

当前实现里，`changes_requested` 应理解为“自动化流程已经无法自行完成闭环，需要人工介入”。它不是第一次 self-review 失败的同义词。

### PRD 重新生成

用户在 `prd_waiting_confirmation` 阶段修改需求、补充反馈，或上传图片/附件后，可以调用 `POST /api/tasks/{task_id}/regenerate-prd`：

1. 后端先把任务重新推进到 `prd_generating`
2. 写入一条“PRD 重新生成请求”时间线日志
3. 重新收集当前任务的最新上下文
4. 再次调用 `run_codex_prd`

`run_codex_prd` 在执行前会清理 worktree 下当前任务对应的旧 PRD 文件 `tasks/prd-{task_id[:8]}*.md`，避免前端读取到历史版本。

### Worktree 选择优先级

Codex 的工作目录选择顺序如下：

1. 任务已有 `worktree_path`
2. 任务绑定的 `Project.repo_path`
3. Koda 仓库根目录

### Worktree 环境准备

对任务型 worktree 来说，目录创建成功还不算完成。当前实现会在保存 `worktree_path` 前补做以下准备：

- 复制源仓库中的 `.env*` 文件到新 worktree（保留相对路径）
- 若检测到前端项目，则按现有 `WORKTREE_FRONTEND_STRATEGY` / `WORKTREE_SKIP_FRONTEND_INSTALL` 约定处理依赖
- 若检测到 `pyproject.toml`，则尝试执行 `uv sync --all-extras`

如果 bootstrap 失败，任务启动会直接报错，而不是把不可直接使用的 worktree 写入任务状态。

## 当前边界

当前实现已经把 Codex 接进任务编排，但还不是完整代理平台：

- 没有使用结构化 JSON 事件流
- 还没有把容器级集成测试、PR 创建、验收代理自动串起来；当前 `test_in_progress` 首期只真实承载 post-review lint / lint-fix
- Prompt 仍然写死在 Python 字符串中，没有独立版本管理

同时要注意当前仍保留两个显式人工边界：

- PRD 生成完成后，是否进入执行仍需要用户确认
- review 与 lint 自动闭环都通过后，是否执行最终 `Complete` 仍需要用户点击；若 AI 自检尚未形成最近一轮“通过”结论但后台已空闲，用户也可以手动点击 `Complete`，系统会把这次人工接管写入 `DevLog`

如果你打算继续扩展这一层，建议先看[Prompt 管理](../core/prompt-management.md)和[系统设计](../architecture/system-design.md)。
