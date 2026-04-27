# PRD：Complete 阶段提交信息改用 AI Summary

**原始需求标题**：任务完成,点击complete的时候, commit信息有问题
**需求名称（AI 归纳）**：Complete 阶段提交信息改用 AI Summary
**文件路径**：`tasks/prd-516e04ff.md`
**创建时间**：2026-03-26 18:47:51 CST
**参考上下文**：`dsl/api/tasks.py`, `dsl/services/codex_runner.py`, `dsl/models/task.py`, `dsl/models/dev_log.py`, `frontend/src/App.tsx`, `frontend/src/api/client.ts`, `docs/guides/codex-cli-automation.md`, `docs/index.md`, `docs/architecture/system-design.md`, `tests/test_tasks_api.py`, `tests/test_codex_runner.py`, `utils/database.py`
**附件检查**：
- `/home/atahang/codes/koda/data/media/original/59e9a0f1-a0b0-4c65-82e6-ca356f922fe2.png` 已实际检查，文件存在，格式为 PNG，分辨率 `1096 x 562`
- 截图可确认问题发生在任务完成后的 Git 历史/工作树查看场景，右上角可见附图标题 `PixPin_2026-03-26 14-53-15.png`
- 截图无法单独证明具体字段来源；代码检查显示当前 `Complete` 链路实际把 `Task.requirement_brief` 作为 commit information 主来源

---

## 1. Introduction & Goals

### 背景

当前仓库的任务完成链路已经是后端驱动的确定性 Git 收尾，而不是单纯让 Codex 自由生成提交信息：

- `dsl/api/tasks.py` 的 `complete_task` 会在用户点击 `Complete` 后，把 `completion_task.requirement_brief` 快照为 `task_summary_snapshot_str`
- `dsl/services/codex_runner.py` 的 `run_codex_completion` 会把该值继续传给 `_execute_git_completion_flow`
- `_build_completion_commit_message()` 当前优先使用 `task_summary_str`，然后再回退到倒序 `DevLog.text_content`，最后才回退到 `task_title`
- 前端 `frontend/src/App.tsx` 和 `frontend/src/api/client.ts` 的文案也明确写着“commit from the task summary”

但代码库中已经存在另一条更接近“实际实现结果”的 AI 摘要链路：

- `dsl/services/codex_runner.py` 在 self-review 阶段会解析 `SELF_REVIEW_SUMMARY`
- review 通过时，这个摘要会被写入成功 `DevLog`，格式为 `摘要：<summary>`
- 这个摘要代表 AI 对“本次代码已经完成了什么”的总结，比 `requirement_brief` 更适合作为最终 commit information

因此，本需求的核心不是“重新设计 Git Complete 流程”，而是把 commit information 的来源从“需求摘要”切换为“最新可用的 AI 实现摘要”，同时保留兼容回退。

### 可衡量目标

- [ ] 用户点击 `Complete` 后，commit information 默认优先使用最近一轮通过的 self-review AI summary
- [ ] 若没有可用 AI summary，系统仍能继续完成，按 `requirement_brief -> task_title` 顺序回退
- [ ] 完成链路不再把任意 `DevLog.text_content` 当作 commit message 的兜底来源
- [ ] 前端成功提示、后端日志和文档同步说明新的来源规则，避免“task summary / AI summary”术语混淆
- [ ] 历史任务、人工接管任务、无 self-review 摘要任务不会因为该改动而无法完成

### 1.1 Clarifying Questions

以下问题无法仅靠原始一句话需求直接确定。本 PRD 采用下列推荐选项作为默认实现边界。

1. 这里的“AI summary”具体应指哪一类现有文本？
A. `DevLog.ai_analysis_text`，即图片/附件 AI 解析结果
B. self-review 通过后产出的 `SELF_REVIEW_SUMMARY`
C. `Task.requirement_brief`
> **Recommended: B**（`DevLog.ai_analysis_text` 属于附件/媒体理解链路，不能代表最终代码实现；而 `SELF_REVIEW_SUMMARY` 已由 `dsl/services/codex_runner.py` 在评审通过时生成，语义上最接近最终 commit information。）

2. commit information 的来源应如何落地？
A. 在 `Complete` 时从现有 `DevLog` 中解析最近一次通过评审的 AI summary
B. 新增数据库字段，把 AI summary 持久化到 `Task`
C. 点击 `Complete` 时再调用一次 Codex 重新生成摘要
> **Recommended: A**（当前项目已经大量使用 `DevLog` 标记驱动工作流推断，例如 `dsl/api/tasks.py`、`frontend/src/App.tsx` 都会扫描日志判断 self-review/lint 是否通过；本需求只修正 commit 来源，不值得引入新的持久化字段或额外 AI 调用。）

3. 当没有 AI summary 时应该怎么办？
A. 阻止 `Complete`，要求用户先让 AI 生成摘要
B. 回退到 `requirement_brief`，再回退到 `task_title`
C. 使用固定模板文本
> **Recommended: B**（既满足兼容性，也最接近当前行为；历史任务和人工接管场景不会被新规则阻断。）

4. 新规则是否需要同步到 UI / 日志 / 文档？
A. 只改后端 commit message 逻辑
B. 后端、前端提示文案、DevLog 留痕、文档同时更新
C. 额外新增确认弹窗
> **Recommended: B**（当前 UI 与文档都明确写着“task summary”，如果只改后端，用户会继续被误导。）

5. 本次要不要顺带扩展为多段 commit message（subject + body）？
A. 不扩展，保持单行 subject，只把 subject 来源切到 AI summary
B. 扩展为 subject + body，把完整 AI summary 放进 body
C. 直接把原始 AI summary 全量塞进单个 `-m`
> **Recommended: A**（当前链路和测试都围绕单行 subject 设计；本需求先修正“来源错误”，不扩大为 commit message 结构重构。）

### 1.2 范围定义

本 PRD 将“AI summary”明确限定为：

- 最近一轮通过的 self-review 成功日志中的摘要行
- 典型来源是 `✅ AI 自检闭环完成...` 之后的 `摘要：...`
- 不包含图片识别/附件解析用的 `ai_analysis_text`
- 不要求新增新的 summary 生成流程

## 2. Implementation Guide

### 核心逻辑

建议把 `Complete` 的 commit information 解析拆成一个独立、可测试的“来源解析器”，并在进入后台 Git 收尾前就决定来源：

1. `complete_task` 继续按现有流程读取按时间排序的 `DevLog`
2. 新增一个解析 helper，逆序扫描最近日志，找到“最近一轮通过的 self-review 成功日志”
3. 从该日志中提取 `摘要：...` 的正文，作为 `preferred_commit_information_text`
4. 若未找到有效 AI summary，则回退到 `Task.requirement_brief`
5. 若 `requirement_brief` 也为空，则回退到 `task_title`
6. 解析结果以显式参数传给 `run_codex_completion`，不要再用 `task_summary_str` 这种混淆命名
7. `_build_completion_commit_message()` 只负责“单行化、清洗、裁剪”，不再从任意 DevLog 文本里碰运气选 commit subject
8. 完成开始日志和前端成功提示要明确说明本次使用的是 `AI summary` 还是 `requirement summary fallback`

这样可以把“业务规则判定”与“Git 命令执行”解耦，减少以后再出现“UI 说的是 A，后端实际用的是 B”的问题。

### 2.1 Change Matrix

| Change Target | Current State | Target State | How to Modify | Affected Files |
|---|---|---|---|---|
| Complete 阶段 commit 来源判定 | `complete_task` 直接把 `completion_task.requirement_brief` 传入后台完成链路 | `Complete` 先解析最近一轮通过的 self-review AI summary，并将其作为首选 commit information | 在任务 API 或共享 helper 中新增“commit information 来源解析器”，优先从成功 self-review 日志提取 `摘要：...`，再回退到 `requirement_brief` 和 `task_title` | `dsl/api/tasks.py`, `dsl/services/codex_runner.py` |
| Commit subject 构建逻辑 | `_build_completion_commit_message()` 候选来源为 `task_summary`、倒序 `DevLog.text_content`、`task_title` | 仅使用“已解析的 commit information”构建 subject，不再把任意 DevLog 正文当兜底 | 重构函数签名与命名，例如 `preferred_commit_information_text`；保留单行清洗、空白折叠、长度限制 | `dsl/services/codex_runner.py`, `tests/test_codex_runner.py` |
| Complete 链路参数语义 | `task_summary_str` 同时承担 requirement summary 与 commit summary 语义 | completion worker 明确接收 `commit_information_text` 与 `commit_information_source` | 在 API、runner、日志文案中统一新命名，避免继续把 AI summary 误称为 task summary | `dsl/api/tasks.py`, `dsl/services/codex_runner.py`, `frontend/src/App.tsx`, `frontend/src/api/client.ts` |
| 用户可观测性 | UI 成功提示与接口注释仍写“commit from the task summary” | UI、后端日志、文档统一改为“优先使用 AI summary；无则回退 requirement summary” | 更新成功提示、接口注释和操作手册；必要时在 DevLog 中补充“本次 commit 来源”说明 | `frontend/src/App.tsx`, `frontend/src/api/client.ts`, `docs/index.md`, `docs/guides/codex-cli-automation.md`, `docs/architecture/system-design.md` |
| 回归测试 | 现有测试覆盖 requirement summary 链路，但没有“AI summary 优先级”回归 | 新增覆盖 AI summary 命中、缺失回退、人工接管、历史任务兼容的测试 | 为 API 层和 runner 层分别补充解析与收尾链路测试 | `tests/test_tasks_api.py`, `tests/test_codex_runner.py` |

### 2.2 Flow Diagram

```mermaid
flowchart TD
    A["User clicks Complete"] --> B["POST /api/tasks/{task_id}/complete"]
    B --> C["Load ordered DevLogs and Task metadata"]
    C --> D{"Latest passed self-review log has '摘要：...'?}
    D -- Yes --> E["Resolve commit information from AI summary"]
    D -- No --> F{"Task.requirement_brief exists?"}
    F -- Yes --> G["Use requirement summary fallback"]
    F -- No --> H["Use task title fallback"]
    E --> I["Sanitize to single-line Git subject"]
    G --> I
    H --> I
    I --> J["run_codex_completion receives explicit commit_information_text"]
    J --> K["git add ."]
    K --> L["git commit -m <subject>"]
    L --> M["git rebase main -> merge -> cleanup"]
    J --> N["Write DevLog / UI message with actual source label"]
```

### 2.3 Low-Fidelity Prototype

```text
Complete 按钮点击后

┌──────────────────────────────────────────┐
│ Commit Information Resolver              │
│                                          │
│ 1. Latest passed self-review summary     │
│    例：摘要：refine completion flow      │
│                                          │
│ 2. requirement_brief fallback            │
│                                          │
│ 3. task_title fallback                   │
└──────────────────────┬───────────────────┘
                       │
                       ▼
            git commit -m "<sanitized subject>"

用户可见反馈：
- Success toast / banner 显示实际来源
- DevLog 留痕显示本次使用 AI summary 还是 fallback
```

### 2.4 ER Diagram

本需求推荐复用现有 `Task` 与 `DevLog` 关系，不新增持久化字段：

- `Task.requirement_brief` 继续作为回退来源
- `DevLog.text_content` 中已经存在 self-review 通过日志和 `摘要：...`
- 因此本 PRD 不要求数据库 schema 变更，也不新增 ER 图

### 2.5 关键实现细节

1. 解析器必须只信任“最近一轮通过的 self-review 成功日志”中的摘要，不能盲目从任意 `摘要：` 文本中取值。
2. 若最近日志里存在新一轮 self-review 开始标记但尚未通过，则不能继续使用更旧轮次的摘要误导 commit information。
3. `dev_log_text_list` 仍可继续用于冲突修复 Prompt 上下文，但不再参与 commit subject 候选排序。
4. 对 AI summary 的清洗规则应与当前 Git subject 规则保持一致：
   - 取首个有效文本行
   - 压缩连续空白
   - 去除尾部多余句号
   - 限制长度，保持现有 72 字符上限
5. 前端不需要新增复杂交互，但成功提示文案必须改正术语，避免继续说“task summary”。

### 2.6 风险与缓解

| Risk | Why It Matters | Mitigation |
|---|---|---|
| 日志解析过于宽松，误把非完成态摘要拿来提交 | 会再次出现 commit subject 与实际变更不一致 | 只解析最近一轮“self-review 通过”日志块，并为解析 helper 单独加测试 |
| 旧任务没有 AI summary | 历史任务会因为新规则无法 Complete | 明确保留 `requirement_brief -> task_title` 回退链路 |
| UI / 文档仍保留旧术语 | 用户会继续认为系统使用 task summary | 同步更新前端文案、API 注释和 MkDocs 文档 |
| 仍保留任意 DevLog 正文兜底 | commit subject 可能出现随机日志文本 | 从 commit builder 中移除“任意 DevLog 正文兜底”策略 |

### 2.7 兼容性说明

- 不新增数据库字段，不需要修改 `utils/database.py` 的增量补丁
- 不改变 `Complete` 的整体 Git 顺序：仍然是 `git add . -> git commit -> git rebase main -> merge -> cleanup`
- 不改变人工点击 `Complete` 的入口与权限
- 不要求新增 prototype 页面，也不要求新增 API 路由

### 2.8 Interactive Prototype Change Log

No interactive prototype file changes in this PRD.

### 2.9 Interactive Prototype Link

No interactive prototype page is required for this PRD.

## 3. Global Definition of Done

- [x] `Complete` 点击后，commit subject 优先来自最近一轮通过的 self-review AI summary
- [x] 缺失 AI summary 时，系统按 `requirement_brief -> task_title` 回退，不阻断任务完成
- [x] 完成链路不再把任意 `DevLog.text_content` 作为 commit message 随机候选
- [x] 前端成功提示、接口注释和文档统一使用新的术语说明
- [x] `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_codex_runner.py tests/test_tasks_api.py tests/test_git_worktree_service.py -q` 通过
- [x] `npm --prefix frontend run build` 通过
- [x] `just docs-build` 通过
- [x] 不引入新的数据库 schema 变更，不影响历史任务完成

## 4. User Stories

### US-001：作为任务操作者，我希望 Complete 时 commit information 反映 AI 对已实现结果的总结

**Description:** As an operator, I want the final commit information to use the latest successful AI self-review summary so that the Git history reflects the actual implemented outcome instead of only the original requirement brief.

**Acceptance Criteria:**
- [x] 当最近一轮 self-review 已通过且日志中存在 `摘要：...` 时，commit subject 使用该摘要
- [x] 成功提示或 DevLog 能看到本次 commit 来源是 `AI summary`
- [x] 不再优先使用 `Task.requirement_brief` 覆盖 AI summary

### US-002：作为历史任务或人工接管任务的操作者，我希望系统保留兼容回退

**Description:** As an operator handling legacy or manually completed tasks, I want completion to keep working even if no AI summary is available so that the workflow remains robust.

**Acceptance Criteria:**
- [x] 没有 AI summary 时，系统回退到 `requirement_brief`
- [x] 连 `requirement_brief` 也为空时，系统回退到 `task_title`
- [x] 不会因为缺失 AI summary 而返回新的阻断型错误

### US-003：作为维护者，我希望 commit 来源规则可读、可测、可追踪

**Description:** As a maintainer, I want the commit source resolution to be explicit and tested so that future changes do not silently regress the completion workflow.

**Acceptance Criteria:**
- [x] 后端存在单独的 commit information 解析 helper 或等价清晰实现
- [x] 相关测试覆盖 AI summary 命中、缺失回退和人工接管场景
- [x] 文档中的“task summary commit”描述已同步修正

## 5. Functional Requirements

1. **FR-1**：系统必须将“AI summary”定义为最近一轮通过的 self-review 成功日志中的摘要文本，而不是图片/附件 AI 解析字段。
2. **FR-2**：`POST /api/tasks/{task_id}/complete` 在调度后台完成任务前，必须先解析 commit information 的实际来源。
3. **FR-3**：commit information 的优先级必须为：最近一轮通过的 self-review AI summary -> `Task.requirement_brief` -> `Task.task_title`。
4. **FR-4**：commit information 解析逻辑不得继续把任意 `DevLog.text_content` 作为无约束的兜底来源。
5. **FR-5**：commit information 解析逻辑必须识别“最近一轮 self-review 是否已通过”，不能误用上一轮或更旧轮次的摘要。
6. **FR-6**：传入 `run_codex_completion` 的参数命名必须反映真实语义，不得继续把 AI summary 误命名为 `task_summary`。
7. **FR-7**：Git commit subject 生成必须继续执行单行化、空白折叠、尾部标点清理和长度限制。
8. **FR-8**：当前完成链路的 Git 执行顺序不得改变，仍保持 `git add .`、`git commit`、`git rebase main`、冲突修复、merge、cleanup。
9. **FR-9**：前端成功提示文案必须说明 commit 信息优先来源于 AI summary，必要时说明存在 requirement summary fallback。
10. **FR-10**：后端 DevLog 或等价可观测输出必须能反映本次 commit information 的实际来源。
11. **FR-11**：文档必须更新 `Complete` 阶段描述，将“基于 task summary 提交”修正为“优先基于 AI summary 提交，缺失时回退 requirement summary”。
12. **FR-12**：自动化测试必须至少覆盖以下场景：AI summary 命中、AI summary 缺失但 requirement brief 存在、两者都缺失时回退 task title、人工接管后仍可完成。

## 6. Non-Goals

- 不重构 `Complete` 的整体 Git 收尾流程
- 不新增新的 Codex 调用去即时生成 commit summary
- 不把图片/附件解析得到的 `ai_analysis_text` 作为本需求中的 commit information 来源
- 不扩展为多段 commit message（subject + body）设计
- 不新增数据库字段或新的独立 summary 表
- 不改造 `Start`、`Execute`、`Resume` 等其他任务阶段的文案或语义边界

## 7. Implementation Outcome (2026-03-27)

### Delivered

- `dsl/api/tasks.py`
  - 新增 `CompletionCommitInformationResolution`、self-review 摘要提取与 commit information 解析 helper。
  - `complete_task()` 现在会在调度后台收尾前解析并记录 commit information 来源。
  - `resume_task()` 的 `pr_preparing` 分支也改为复用同一套 AI-summary-first 解析逻辑。
  - 增补 `开始重新执行 AI 自检` marker，避免新一轮 review 已开始时继续误用旧摘要。
- `dsl/services/codex_runner.py`
  - 完成链路参数从 `task_summary_str` 迁移为 `commit_information_text_str` / `commit_information_source_str`。
  - `_build_completion_commit_message()` 不再把任意 `DevLog.text_content` 当作兜底来源，只保留 resolved commit information 与 task title fallback。
- `frontend/src/App.tsx`, `frontend/src/api/client.ts`
  - 完成提示与接口注释统一改为“优先使用最近一轮通过的 AI summary，缺失时回退 requirement brief / task title”。
  - 同步补齐 `开始重新执行 AI 自检` marker，避免前端在新一轮 self-review 已开始时继续误判旧一轮 review 为“已通过”。
- `docs/index.md`, `docs/architecture/system-design.md`, `docs/guides/codex-cli-automation.md`
  - Complete 工作流文档同步为 AI-summary-first 语义。
- `tests/test_tasks_api.py`, `tests/test_codex_runner.py`, `tests/test_git_worktree_service.py`
  - 增加并修正了 commit information 命中、fallback、resume、prompt wording 与 git helper 参数契约的回归覆盖。

### Verification

- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_codex_runner.py tests/test_tasks_api.py tests/test_git_worktree_service.py -q` -> PASS (`43 passed`)
- `npm --prefix frontend run build` -> PASS
- `just docs-build` -> PASS
- Follow-up verification on 2026-03-30 after synchronizing the frontend self-review restart marker:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_codex_runner.py tests/test_tasks_api.py tests/test_git_worktree_service.py -q` -> PASS (`43 passed`)
  - `npm --prefix frontend run build` -> PASS
  - `just docs-build` -> PASS

### Deviations / Notes

- 原 PRD 主要聚焦首次点击 `Complete` 的路径；实现阶段额外发现并修复了 `pr_preparing` 的 completion resume 仍使用旧参数名的问题，否则恢复执行会与新 contract 脱节。
- 后续 code review 额外发现前端 `SELF_REVIEW_STARTED_LOG_MARKER_LIST` 未同步 `开始重新执行 AI 自检`，会导致 UI 在新一轮 self-review 已开始时复用旧的“已通过”结论；该回归已在本次跟进中修复。
- 未引入数据库 schema 变更，也未改变 `git add . -> git commit -> git rebase main -> merge -> cleanup` 的既有顺序。
