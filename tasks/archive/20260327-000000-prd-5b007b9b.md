# PRD：PRD 命令输出文件命名恢复为语义化需求名（兼容中文）

**原始需求标题**：修改prd命令
**需求名称（AI 归纳）**：PRD 命令输出文件命名恢复为语义化需求名（兼容中文）
**文件路径**：`tasks/archive/prd-5b007b9b.md`
**创建时间**：2026-03-27
**需求背景/上下文**：当前 PRD 文件名再次出现随机/短 ID 风格，未按需求语义命名；历史上曾支持按需求命名，怀疑在中文输入场景退化。
**附件输入检查**：
- 已检查文件：`/home/tao/codes/koda/data/media/original/f17eb373-881e-4721-b4a6-05df453aceff.png`（PNG 文件存在且可读取）
- 可确认信息：截图中被高亮的文件名为 `prd-c3e023d8.md`，体现当前输出偏向短随机 ID，而非需求语义命名
- 结论：附件证据与本需求描述一致，需恢复“按需求命名”的 PRD 输出合同，并补齐中文输入兼容策略
**参考上下文**：`dsl/services/codex_runner.py`, `dsl/services/prd_file_service.py`, `dsl/api/tasks.py`, `tests/test_codex_runner.py`, `tests/test_tasks_api.py`, `docs/guides/codex-cli-automation.md`, `docs/core/prompt-management.md`

---

## 1. Introduction & Goals

### 背景

当前系统的 PRD 生成链路中，`build_codex_prd_prompt` 仍将输出路径合同写为固定文件名 `tasks/prd-{task_id[:8]}.md`，导致模型在执行时缺少“语义化命名”强约束。与此同时，文档和文件服务能力已经期望并支持 `tasks/prd-{task_id[:8]}-<semantic-slug>.md` 形态。

这形成了“代码合同与文档合同不一致”，并在中文需求输入时进一步放大不稳定性（例如模型产出随机词或直接退回短 ID）。

### 目标（可衡量）

- [x] PRD 输出文件名恢复为 `tasks/prd-{task_short_id}-<requirement-slug>.md`，禁止仅输出短 ID 文件名。
- [x] `<requirement-slug>` 必须来源于需求语义，不得使用随机值。
- [x] 中文需求输入场景可稳定命名（允许保留中文语义或可预测转写），不得回退为随机串。
- [x] 后端 PRD 读取兼容逻辑保持可用，前端无需改动即可读取最新 PRD。
- [x] 相关测试与文档同步更新，`just docs-build` 可通过。

### 1.1 Clarifying Questions（默认采用推荐项）

1. 中文需求的文件名策略应采用哪种方案？
A. 仅允许英文 slug（模型自行翻译）
B. 允许多语言 slug（保留中文），并做跨平台非法字符清洗
C. 中文统一强制转拼音
> **Recommended: B**（可读性最好且最贴近“按需求命名”；同时通过字符清洗保障跨平台安全。）

2. 命名合同应由谁最终约束？
A. 仅依赖 Prompt 文案
B. 后端生成目标路径合同 + Prompt 明确写入 + 结果校验
C. 前端生成后传给后端
> **Recommended: B**（当前架构由后端驱动 `run_codex_prd`，应在后端侧形成可测试的单一合同。）

3. 是否保留 `task_id` 前缀？
A. 保留 `prd-{task_short_id}-` 前缀
B. 仅保留语义名
C. 改为时间戳前缀
> **Recommended: A**（保证任务归属可追溯，兼容 `find_task_prd_file_path` 的前缀匹配策略。）

4. 若模型未按合同输出语义文件名，如何处理？
A. 允许通过，只要有 PRD 内容
B. 标记失败并回退阶段
C. 自动修正为合同文件名（必要时重命名）并记录日志
> **Recommended: C**（优先保证流程连续，同时保证最终产物满足命名合同。）

## 2. Implementation Guide (Technical Specs)

### 2.1 Core Logic

1. 在 PRD Prompt 构建时，使用统一路径合同函数输出目标路径，替换当前硬编码 `tasks/prd-{task_id[:8]}.md`。
2. 将命名占位从“仅英文”扩展为“语义 slug（支持中文输入）”，并明确禁止随机字符串。
3. 保持任务前缀 `prd-{task_short_id}` 不变，后缀由需求语义生成。
4. 在 PRD 执行完成后增加结果校验：若未生成符合前缀+语义后缀的文件，执行自动修正/重命名并写日志。
5. `dsl/api/tasks.py` 继续通过 `find_task_prd_file_path` 前缀匹配读取，保证向后兼容历史文件。

### 2.2 Change Matrix

| Change Target | Current State | Target State | How to Modify | Affected Files |
|---|---|---|---|---|
| PRD Prompt 输出路径合同 | 固定 `tasks/prd-{task_id[:8]}.md` | `tasks/prd-{task_id[:8]}-<requirement-slug>.md` | `build_codex_prd_prompt` 改用统一合同函数并更新文案约束 | `dsl/services/codex_runner.py`, `dsl/services/prd_file_service.py` |
| slug 语义约束 | 文案要求不稳定，中文场景易退化 | 明确“语义化、非随机、中文可兼容”规则 | 在 Prompt 中补充命名规则与示例 | `dsl/services/codex_runner.py` |
| 结果一致性保障 | 依赖模型自觉写对路径 | 增加后处理校验与纠正机制 | 运行后检查 `tasks/prd-{task_id[:8]}*.md`，异常时修正并记录 | `dsl/services/codex_runner.py`, `dsl/services/prd_file_service.py` |
| API 读取兼容 | 已支持按前缀查找最新候选 | 保持兼容并强化语义文件优先 | 维持排序策略并补充测试断言 | `dsl/services/prd_file_service.py`, `tests/test_tasks_api.py` |
| 单元测试合同 | 仍断言固定短 ID 路径 | 断言语义路径合同与中文兼容 | 更新 Prompt 测试与路径匹配测试 | `tests/test_codex_runner.py`, `tests/test_tasks_api.py` |
| 文档一致性 | 文档多处写语义文件名，但实现不一致 | 文档与代码合同完全对齐 | 更新 PRD Prompt 章节、排障说明、验证步骤 | `docs/core/prompt-management.md`, `docs/guides/codex-cli-automation.md`, `docs/core/ai-assets.md`, `docs/architecture/system-design.md` |

### 2.3 Flow Diagram

```mermaid
flowchart TD
    A[Start Task] --> B[run_codex_prd]
    B --> C[build_codex_prd_prompt]
    C --> D[输出目标路径合同: prd-shortid-semantic-slug.md]
    D --> E[codex exec 生成 PRD]
    E --> F{文件名是否符合合同?}
    F -- Yes --> G[推进到 prd_waiting_confirmation]
    F -- No --> H[自动修正文件名并记日志]
    H --> G
    G --> I[/api/tasks/{id}/prd-file 按前缀读取]
```

## 3. Global Definition of Done (DoD)

- [x] `build_codex_prd_prompt` 不再输出固定 `tasks/prd-{task_id[:8]}.md`。
- [x] Prompt 明确要求语义 slug，禁止随机值，并声明中文输入兼容。
- [x] 至少覆盖 1 个中文标题用例，最终文件名非随机且可读。
- [x] `tests/test_codex_runner.py`、`tests/test_tasks_api.py` 相关断言更新并通过。
- [x] PRD 读取接口在“历史固定文件名 + 新语义文件名”共存时行为正确。
- [x] `just docs-build` 通过，文档与实现合同一致。

## 4. User Stories

### US-001：作为用户，我希望 PRD 文件名体现需求语义

**Description:** As a user, I want PRD filenames to reflect requirement meaning so that I can quickly identify files without opening them.

**Acceptance Criteria:**
- [x] 文件名包含需求语义后缀，而非仅短 ID
- [x] 同批任务下可通过文件名快速区分主题

### US-002：作为中文用户，我希望中文需求也能稳定命名

**Description:** As a Chinese-speaking user, I want Chinese requirement inputs to generate predictable semantic filenames so that naming does not degrade to random strings.

**Acceptance Criteria:**
- [x] 中文标题输入不会退化为随机值
- [x] 文件名规则稳定、可重复

### US-003：作为维护者，我希望命名合同可测试

**Description:** As a maintainer, I want naming rules encoded in tests and docs so prompt refactors cannot silently break behavior.

**Acceptance Criteria:**
- [x] Prompt 合同有单元测试断言
- [x] 文档写明命名规则、回退策略和验证步骤

## 5. Functional Requirements

1. **FR-1**：PRD 输出路径合同必须为 `tasks/prd-{task_id[:8]}-<requirement-slug>.md`。
2. **FR-2**：`<requirement-slug>` 必须来源于需求语义，不得使用随机字符串。
3. **FR-3**：命名规则必须兼容中文输入，不得因非英文标题退化为随机 ID。
4. **FR-4**：PRD 生成 Prompt 必须明确“语义命名 + 非随机 + 中文兼容”约束。
5. **FR-5**：保留 `prd-{task_short_id}` 前缀用于任务归属与后端检索。
6. **FR-6**：若生成结果未满足命名合同，系统必须执行自动修正并记录日志。
7. **FR-7**：`/api/tasks/{id}/prd-file` 读取逻辑必须继续兼容旧文件名与新文件名。
8. **FR-8**：测试必须覆盖固定路径回归、语义路径合同、中文标题命名场景。
9. **FR-9**：文档必须同步更新，确保实现与文档描述一致。

## 6. Non-Goals

- 不在本需求内改造前端 PRD 渲染方式。
- 不在本需求内引入新的数据库字段持久化 slug。
- 不批量重命名历史归档 PRD 文件。
- 不扩展到 PRD 之外的其他输出文件命名体系（如 review、lint 日志文件）。

## 7. Delivery Notes

### 7.1 Implemented

- `dsl/services/prd_file_service.py`
  - 新增多语言 PRD slug 规范化、随机后缀识别、合法文件名校验和自动修正逻辑。
  - 保持 `prd-{task_short_id}` 前缀不变，允许中文语义 slug 经过跨平台安全清洗后直接落盘。
- `dsl/services/codex_runner.py`
  - `build_codex_prd_prompt(...)` 改为使用统一输出合同 `tasks/prd-{task_id[:8]}-<requirement-slug>.md`。
  - Prompt 显式要求“语义命名 + 非随机 + 中文兼容”，并要求模型写错文件名时先自行修正。
  - `run_codex_prd(...)` 在 Codex 成功后执行 PRD 文件校验；若命名不合法则自动重命名并记录日志，若完全没有合法 PRD 文件则回退到 `changes_requested`。
- `dsl/api/tasks.py`
  - 保持 `/api/tasks/{id}/prd-file` 通过任务前缀兼容查找，文案同步改为“语义 slug”而非“英文 slug”。
- `tests/test_prd_file_service.py`
  - 新增中文 slug 清洗、短随机后缀校验与旧文件名修正测试。
- `tests/test_codex_runner.py`
  - 更新 Prompt 合同断言。
  - 增加 PRD 生成后自动修正旧固定文件名和短随机后缀文件名的回归测试。
- `tests/test_tasks_api.py`
  - 增加“新语义文件优先、旧固定文件兼容，并在只剩随机后缀时执行读取修正”的回归测试。
- `docs/guides/codex-cli-automation.md`
- `docs/core/prompt-management.md`
- `docs/core/ai-assets.md`
- `docs/architecture/system-design.md`
  - 全部同步为 `<requirement-slug>` 合同，并补充命名规则、自动修正与验证步骤。

### 7.2 Verification

- [x] `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_prd_file_service.py tests/test_codex_runner.py tests/test_tasks_api.py -q`
  - 结果：`43 passed`
- [x] `just docs-build`
  - 结果：通过
- [x] `uv run pytest tests/test_prd_file_service.py tests/test_tasks_api.py tests/test_codex_runner.py`
  - 结果：`91 passed`（2026-03-31 reopened merge conflict re-verification）
- [x] `just docs-build`
  - 结果：通过（2026-03-31 reopened merge conflict re-verification）

### 7.3 Deviations / Notes

- 采用 PRD 已确认的推荐方案 B：保留多语言语义 slug，不强制英文翻译或拼音转换。
- 对“短随机串”的拦截补充为保守规则：会拒绝 `k9m2qz`、`a1b2c` 这类短单段交错字母数字 token，但不会把 `ios17` 这类单段版本语义直接判成随机值。
- `run_codex_prd(...)` 的预清理范围已扩展到所有 `prd-{task_id[:8]}*.md` 候选文件，避免历史随机后缀文件在“本轮成功但未真正产出 PRD”时被误判为新产物。
- `/api/tasks/{id}/prd-file` 读取链路不会直接暴露随机后缀文件名；当任务目录里只剩 hex / 非 hex 随机后缀文件时，后端会按任务标题/PRD 元数据先修正到合法语义文件名，再把修正后的路径返回给前端。
- 多语言 slug 现在同时受字符数和 UTF-8 字节数约束，避免长中文需求名生成超过常见 255-byte basename 上限的文件名。
- 未引入新的数据库字段，也未批量处理历史归档 PRD 文件；兼容性继续依赖任务前缀查找。
