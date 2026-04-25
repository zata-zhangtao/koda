# 多执行器自动化

## 总览

这个仓库不是“仅仅支持手动调用某个 CLI”，而是已经把可配置执行器接进了任务生命周期。

当前通过 `KODA_AUTOMATION_RUNNER` 选择执行器：

- `codex`（默认）
- `claude`

真实调用入口有四个：

- `backend/dsl/api/tasks.py` 的 `start_task` 会在后台触发 `run_codex_prd`
- `backend/dsl/api/tasks.py` 的 `execute_task` 会在后台触发 `run_codex_task`
- `backend/dsl/api/tasks.py` 的 `review_task` 会在后台触发 `run_task_review`
- `backend/dsl/api/tasks.py` 的 `resume_task` 会在后台从持久化工作流阶段恢复中断的自动化

对应的核心实现位于：

- `backend/dsl/services/automation_runner.py`（API 层统一入口）
- `backend/dsl/services/codex_runner.py`（执行器无关主编排）
- `backend/dsl/services/runners/`（Runner 协议、注册中心和 CLI 适配器）

## 当前实现方式

### PRD 生成链路

1. 前端点击“开始任务”
2. 后端将任务推进到 `prd_generating`
3. 如果任务绑定了 `Project`，优先创建或复用 Git worktree；在 `worktree_path` 落库前，还会复制 `.env*` 并准备基础前后端依赖环境
4. 新建 worktree 分支默认命名为 `task/<task_id[:8]>-<semantic-slug>`：优先尝试 AI 命名，失败时自动回退到标题规则化 slug，若仍为空则回退到 `task/<task_id[:8]>`
5. `run_codex_prd` 组装 PRD Prompt
6. 后端按配置调用目标 runner CLI（`codex` 或 `claude`）
7. 输出被实时写入数据库和 `/tmp/koda-<task短ID>.log`
8. 成功后按任务策略分流：
   - 默认策略：推进到 `prd_waiting_confirmation`，等待用户确认 PRD
   - 自动策略（`auto_confirm_prd_and_execute=true`）：跳过人工确认，直接推进到 `implementation_in_progress` 并启动 `run_codex_task`
9. 仅默认策略会发送“PRD Ready / 等待确认”通知；自动策略不会发送该通知
10. 默认策略不会自动继续执行代码实现，也不会默认提交代码

### 编码执行链路

1. 前端点击“开始执行”
2. 后端将任务推进到 `implementation_in_progress`
3. `run_codex_task` 组装实现 Prompt
4. 后端按配置调用目标 runner CLI（`codex` 或 `claude`）
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
3. `run_codex_completion` 在任务 worktree 中执行固定 Git 命令：`git add .`；若 staging 后仍有变更，则调用当前 AI runner 基于 staged diff 生成符合 Conventional Commits 的 message 并执行 `git commit -m "<ai generated conventional commit>"`；若 staging 后已经干净，则跳过 commit，继续 `git rebase <worktree_base_branch_name>`
4. 若 `rebase` 或后续 `merge` 出现冲突，后端会调用 Codex 自动修复冲突并继续 Git 操作
5. 后端会优先解析任务基底分支已配置的 remote；若无显式配置，则回退到仓库唯一 remote，再回退到 `origin` / `zata`，并在当前持有该基底分支的工作区完成远程同步与 `git merge <task branch>`
6. merge 成功后继续清理 task worktree 与本地任务分支；repo-local cleanup script 即使返回非零，后端也会继续核验 worktree / branch 的真实状态，并尝试 `git worktree remove --force`、`git worktree prune` 与 orphan 目录清理作为 fallback
7. 日志继续写入 `DevLog`
8. 若收尾成功，任务自动推进到 `done`
9. 若在合并到任务基底分支前失败，任务回退到 `changes_requested`
10. 若这次失败属于 Git 收尾阶段本身（例如承载任务基底分支的工作区不干净），用户修复外部 Git 状态后，可以直接再次点击 `Complete` 重试收尾，而不必重跑整条实现链

### 独立代码评审链路

1. 用户直接调用 `POST /api/tasks/{task_id}/review`，或通过 schedule 的 `review_task` 动作触发 `run-now` / Cron
2. 后端校验该任务当前没有活跃自动化，且本机存在可用的 task worktree 或绑定项目仓库
3. `run_task_review` / `run_codex_review_only` 复用 `build_codex_review_prompt`
4. 输出继续实时写入 `DevLog`
5. 若评审输出 `SELF_REVIEW_STATUS: PASS`，系统会写一条“独立代码评审完成”摘要日志
6. 若评审输出 `SELF_REVIEW_STATUS: CHANGES_REQUESTED`，系统只记录 blocker 结论，不自动回改，不推进到 lint，也不修改 `workflow_stage`
7. 若评审阶段执行失败或未产出有效结构化状态，也只记录失败日志，不会把任务强制推进到 `changes_requested`

### 中断恢复链路

如果后端进程或后台任务在执行途中异常中断，数据库里的 `workflow_stage` 会保留在最近一次已落库的阶段，但内存态的 `is_codex_task_running` 会在重启后变成 `False`。这时可以调用 `POST /api/tasks/{task_id}/resume`：

1. 后端校验该任务当前没有活跃自动化
2. 后端只允许从以下阶段恢复：`prd_generating`、`implementation_in_progress`、`self_review_in_progress`、`test_in_progress`、`pr_preparing`
3. 若 `self_review_in_progress` 已经出现最近一轮“通过”标记，或 `test_in_progress` 已经出现最近一轮 lint 通过标记，则不会恢复，而是要求用户直接点击 `Complete`
4. 若阶段仍处于真正的中断态，后端会从该阶段重新挂起对应后台任务，继续 PRD、实现、自检、lint 或 Git 收尾链路

如果用户不希望继续恢复，而是要立即解除卡死或人工接管，也可以调用 `POST /api/tasks/{task_id}/force-interrupt`：

1. 后端只允许在以下阶段强制中断：`prd_generating`、`implementation_in_progress`、`self_review_in_progress`、`test_in_progress`、`pr_preparing`
2. 即使此时已经没有活跃 runner，后端仍会清理进程内运行标记并把任务回退到 `changes_requested`
3. 系统会写入一条“Force Interrupt Triggered”审计日志，并继续发送统一的“手动中断”通知邮件

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
- 如果 PRD 中仍有待确认问题，必须输出固定章节 `## 0. 待确认问题（结构化）`
- 结构化章节必须包含 fenced `json` code block，顶层键为 `pending_questions`
- 每个问题对象至少包含 `id`、`title`、`required`、`recommended_option_key`、`recommendation_reason`、`options`
- 如果上下文里出现 `Attached local files:`，必须显式检查这些本地文件；若某些二进制文件无法完整解析，也不能静默忽略
- 将完整 PRD 写入任务专属文件 `tasks/YYYYMMDD-HHMMSS-prd-<requirement-slug>.md`，而不是只把内容打印到终端
- 文件名中的 `<requirement-slug>` 必须来自需求语义，不能使用随机值、UUID 或纯短 ID
- `<requirement-slug>` 兼容中文输入：可以保留中文或其他自然语言词语，但必须经过文件系统安全清洗
- 如果模型先写出了旧的 task-id 前缀文件名或带随机后缀的文件名，后端会在成功阶段后自动修正并写日志

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

这同一份 Prompt 既用于实现后的 `self_review_in_progress` 闭环，也用于独立 `review_task`。两者差异不在 Prompt，而在编排层：

- `self_review_in_progress` 会在 blocker 时进入自动回改闭环，并在通过后继续 post-review lint
- 独立 `review_task` 只执行单轮 review-only，不自动回改，不进入 lint，也不改任务阶段

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

- 当前 task worktree 中执行 `git add .`；若 staging 后仍有变更，则当前 AI runner 会基于 staged diff 生成符合 Conventional Commits 的 message 并执行 `git commit -m ...`；若 staging 后已经干净，说明用户已经提交过，系统会跳过 commit，随后执行 `git rebase <worktree_base_branch_name>`
- 优先复用已经持有任务基底分支的工作区，而不是假定可以随时 `checkout <worktree_base_branch_name>`
- 若 `rebase` / `merge` 冲突，则自动调用 Codex 修复并继续
- merge 成功后清理 worktree 与本地任务分支，不会 push

## 实际调用特征

当前仓库中的调用并没有使用统一 JSON 事件流，而是选择了更直接的标准输出监听方式：

```bash
# codex
printf '%s' "<prompt>" | codex exec --dangerously-bypass-approvals-and-sandbox -

# claude
printf '%s' "<prompt>" | claude -p --dangerously-skip-permissions
```

实现细节如下：

- `cwd` 由 Python `asyncio.create_subprocess_exec` 指定为项目根目录或 worktree
- Prompt 文本通过 `stdin` 发送给 CLI，避免超长上下文触发操作系统的 argv 长度限制
- `stderr` 被合并到 `stdout`
- 输出按行读取
- 每积累 5 行，或等待 1.5 秒，就批量写入一条 `DevLog`
- 同一次 phase attempt 的 flush chunk 会共享 `automation_session_id`，并记录单调递增的 `automation_sequence_index`
- chunk 还会附带 `automation_phase_label` 与 `automation_runner_kind`，供读取侧恢复连续 transcript
- 每个阶段日志头部会写入 `runner_kind=<codex|claude>` 便于排障

## 日志与可观测性

### 数据库时间线

Codex 的输出不是单独存放在某个审计表中，而是直接写回 `DevLog` 时间线。这意味着前端可以把 AI 执行过程当成普通日志流来展示。对于当前自动化链路，时间线里会明确看到：

- 第 N 轮 review 发现问题 -> 第 N 轮自动回改 -> 第 N+1 轮复审
- review 通过 -> pre-commit lint -> AI lint-fix -> lint 复检

为了修复连续输出被切碎后的阅读问题，任务详情时间线不会直接逐条展示这些 flush chunk，而是先按 `automation_session_id` 做一次只读聚合：只有“相邻且 session 相同”的 chunk 会被合并成一个 transcript 卡片；如果中间插入人工反馈或系统日志，就会强制断开。`/tmp/koda-<task短ID>.log` 和数据库里的原子 `DevLog` 仍保持原样，方便 tail 与审计。

任务级 Markdown 编年史导出也使用相同的 continuity 合同：同一连续 transcript 会导出为一个 Markdown block，标题展示时间范围与 phase，正文保留原始 chunk 顺序和换行。

### 本地日志文件

每个任务还会生成一个独立的本地日志文件：

```text
/tmp/koda-<task短ID>.log
```

你可以通过后端接口 `POST /api/tasks/{task_id}/open-terminal` 打开一个新的终端窗口执行 `tail -f`。默认支持 macOS、WSL 与常见 Linux 桌面终端；如果默认命令不适合当前环境，可通过 `KODA_OPEN_TERMINAL_COMMAND` 覆盖。

### PRD 文件定位

后端读取 PRD 内容时，会在任务的 worktree 中查找：

```text
tasks/YYYYMMDD-HHMMSS-prd-<requirement-slug>.md
```

后端会按任务工作区内的 PRD 文件集合查找并返回最合适的文件，优先读取满足语义命名合同的新文件名，同时兼容旧的固定文件名和旧的 task-id 语义文件名。
如果 Codex 写出了旧固定文件名或随机后缀，`run_codex_prd` 会自动重命名到合法的语义文件名并把修正结果写回日志。

除 AI 生成外，任务详情也支持两种非 runner PRD 来源：

- 从 `tasks/pending/*.md` 选择一个既有 PRD；后端会把该文件移动到 `tasks/` 根目录，并改名为当前任务专属的语义 PRD 文件名。
- 手动上传 `.md` PRD，或直接粘贴 Markdown；后端会按 UTF-8 Markdown 校验后写入 `tasks/` 根目录，并使用同一任务专属文件名合同。

这两条路径由 `backend/dsl/prd_sources/` 领域切片实现，不会调用 `run_codex_prd`，但 PRD ready 之后的确认、自动确认执行和 `/api/tasks/{task_id}/prd-file` 读取逻辑与 AI 生成保持一致。

## 故障处理

### 执行器 CLI 缺失

如果开发机找不到当前配置执行器的可执行文件：

- 后端会写入一条 `BUG` 类型的 DevLog（包含 `runner_kind`、`executable` 和安装提示）
- 后端也会创建该任务对应的本地日志文件（`/tmp/koda-{task_id[:8]}.log`），方便“打开终端”直接查看失败原因
- 任务阶段会回退到 `changes_requested`

#### Codex 排障

当 `KODA_AUTOMATION_RUNNER=codex` 时：

- 先确认 `codex --version` 可执行
- 确认 PATH 中包含 `codex` 可执行文件
- 若仍失败，检查 DevLog 中 `runner_kind=codex` 的缺失提示

#### Claude 排障

当 `KODA_AUTOMATION_RUNNER=claude` 时：

- 先确认 `claude --version` 可执行
- 确认 PATH 中包含 `claude` 可执行文件
- 若仍失败，检查 DevLog 中 `runner_kind=claude` 的缺失提示

### `changes_requested` 的真实语义

当前实现里，`changes_requested` 应理解为“自动化流程已经无法自行完成闭环，需要人工介入”。它不是第一次 self-review 失败的同义词。

### 意外中断后的继续执行

当前前端把 `go on`、`continue`、`resume`、`retry` 等输入视为“继续执行”指令：

- 若任务已经落到 `changes_requested`，可以走正常的 `execute` 重试入口
- 若用户已在 worktree 中人工修复当前问题，详情页也会恢复 `Complete`，允许用户直接进入 Git 收尾
- 若任务卡在可恢复的运行阶段且当前没有活跃后台进程，则会调用 `POST /api/tasks/{task_id}/resume`
- 若任务卡在运行阶段但用户明确要求立即终止当前链路，则可以改走 `POST /api/tasks/{task_id}/force-interrupt`
- 若任务其实已经停在 self-review 或 lint 的“等待用户点击 Complete”状态，则不会重跑自动化，而是提示用户直接完成收尾

### PRD 重新生成

用户在 `prd_waiting_confirmation` 阶段修改需求、补充反馈，或上传图片/附件后，可以调用 `POST /api/tasks/{task_id}/regenerate-prd`：

1. 后端先把任务重新推进到 `prd_generating`
2. 写入一条“PRD 重新生成请求”时间线日志
3. 重新收集当前任务的最新上下文
4. 再次调用 `run_codex_prd`

`run_codex_prd` 在执行前会清理 worktree 下当前任务对应的旧 PRD 文件，避免前端读取到历史版本；新生成结果仍按时间戳语义文件名合同写回。

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
- 分支命名来源会记录到后端日志（`ai` / `title_fallback` / `legacy_fallback`），便于排查命名回退

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
