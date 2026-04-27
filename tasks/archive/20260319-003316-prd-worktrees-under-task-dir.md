# PRD：将所有 Git Worktree 统一放入 `../task/` 目录

**文件路径**：`tasks/20260319-003316-prd-worktrees-under-task-dir.md`
**创建时间**：`2026-03-19 00:33:16 +0800`
**需求标题**：`put all worktree into ../task folder`
**需求上下文**：`put all worktree put into ../task folder`

---

## 0. 澄清问题（按现有仓库模式给出推荐默认值）

以下问题是 `/prd` workflow 要求的关键澄清项。由于当前任务是直接生成 PRD，本文先按推荐选项起草，后续如有业务决定变化，可据此修订。

### 0.1 新的默认 worktree 子目录命名应是什么？

A. `../task/<repo-name>-wt-<task8>`
B. `../task/<task8>`
C. `../task/task/<task8>`

> **Recommended: A**
> 现有 `dsl/services/git_worktree_service.py` 已经把 basename 固定为 `<repo>-wt-<task8>`，`tests/test_git_worktree_service.py` 也围绕该命名断言。只改变根目录、不改变 basename，改动面最小。

### 0.2 当 `../task/` 目录不存在时应如何处理？

A. 自动创建 `../task/` 及缺失父目录
B. 直接报错，要求人工先创建
C. 仅在开发环境自动创建，生产环境报错

> **Recommended: A**
> 当前 Koda 的 worktree 创建是 `TaskService.start_task()` 的自动链路，人工前置创建目录会破坏“点击开始任务即可执行”的体验，也不符合现有自动化模式。

### 0.3 对已落库的旧 `worktree_path` 应如何处理？

A. 仅影响新创建的 worktree；旧任务保留原绝对路径，不自动迁移
B. 启动时自动移动旧 worktree 到 `../task/`
C. 只改数据库中的路径字符串，不移动磁盘目录

> **Recommended: A**
> `Task.worktree_path` 是后续 `/prd-file`、`open-in-trae`、完成态 merge/cleanup 的真实工作目录。自动搬迁 live worktree 风险过高，而“新任务新规则、旧任务继续可读”最稳妥。

### 0.4 对 repo-local 的 branch-only 脚本（`git_worktree.sh`）应采用什么兼容策略？

A. 继续支持，但创建后必须解析真实路径，并校验最终路径位于 `../task/` 下
B. 停止支持 branch-only 脚本，只保留可显式传 path 的脚本
C. 继续支持，且不限制脚本最终创建到哪里

> **Recommended: B（2026-04-27 修订）**
> Koda 的 task worktree 创建是产品自身能力，不应要求每个绑定项目都提供 `just worktree` 或兼容 `--base` 的 `scripts/git_worktree.sh`。Branch-only 脚本无法显式接收 Koda 计算出的目标路径，容易把项目本地约定泄漏进任务启动链路；后续只保留可接收 `<target_path> <branch_name> <base_branch>` 的 path-aware 脚本作为项目自定义钩子。

以下 PRD 原按推荐选项 A / A / A / A 起草；2026-04-27 已将第 0.4 项修订为 B。

---

## 1. 背景与目标

当前 Koda 在 `TaskService.start_task()` 中调用 `GitWorktreeService.create_task_worktree()` 为项目型任务创建隔离工作区，并把绝对路径写入 `Task.worktree_path`。下游链路如 `GET /api/tasks/{id}/prd-file`、`POST /api/tasks/{id}/open-in-trae` 与完成态 Git 收尾流程都直接依赖这个路径。

现状存在两个问题：

- 默认 fallback 路径由 `build_task_worktree_path()` 生成，格式为仓库同级的 `<repo>-wt-<task8>`
- branch-only 脚本分支的预期路径隐含在项目脚本内部，且不同项目不一定支持 Koda 传入的 `--base` 参数，说明任务启动不应依赖每个项目自带的脚本能力

本需求的目标是把“所有新建 task worktree 的根目录”统一收敛到目标仓库父目录下的 `task/` 目录，例如：

- 项目仓库：`/Users/zata/code/my-app`
- 新默认 worktree 根目录：`/Users/zata/code/task/`
- 新默认 worktree 路径：`/Users/zata/code/task/my-app-wt-12345678`

### 目标

- [ ] 所有新创建的 task worktree 默认落在目标仓库父目录的 `task/` 子目录下
- [ ] `new-worktree.sh` / `create-worktree.sh` / fallback `git worktree add` 的落盘根目录策略保持一致
- [ ] branch-only `git_worktree.sh` 不再作为 task worktree 创建策略；普通创建必须由 Koda 内置 `git worktree add` fallback 承担
- [ ] 不修改数据库 schema，继续复用 `Task.worktree_path` 存储最终绝对路径
- [ ] 更新测试与文档，避免代码与 MkDocs 描述再次出现路径语义分叉

---

## 2. 实现指南（技术规格）

### 核心逻辑

当前路径控制点集中在 `dsl/services/git_worktree_service.py`，这是本需求的单一事实源，技术实现应尽量收敛在该服务中，而不是把路径拼接散落到 API、前端或 `codex_runner`。

推荐实现路径：

1. 在 `GitWorktreeService` 中新增 `build_task_worktree_root_path(repo_root_path)`，统一返回 `repo_root_path.parent / "task"`
2. 让 `build_task_worktree_path(repo_root_path, task_id)` 基于该 root 生成默认路径：`<task-root>/<repo-name>-wt-<task8>`
3. 在真正执行创建前确保 `task/` 根目录存在
4. 对可显式传 path 的脚本与 fallback `git worktree add`，直接传入新的默认路径
5. 忽略 branch-only `scripts/git_worktree.sh` / `git_worktree.sh`，避免项目本地脚本抢占 Koda 的默认创建能力；如项目确需自定义创建逻辑，必须提供 path-aware `new-worktree.sh` / `create-worktree.sh`
6. `TaskService.start_task()` 继续只做两件事：调用服务创建 worktree、把返回值写入 `Task.worktree_path`
7. 下游 API 与 `codex_runner` 将继续把 `worktree_path` 当成透明绝对路径使用，无需知道其根目录策略

### 2.1 Change Matrix

| Change Target | Current State | Target State | How to Modify | Affected Files |
|---|---|---|---|---|
| Worktree root strategy | 默认 fallback 使用 `repo_root.parent / "<repo>-wt-<task8>"` | 所有新建 worktree 的默认根目录统一为 `repo_root.parent / "task"` | 在 `GitWorktreeService` 内新增 root helper，并让默认 path builder 基于该 helper 生成路径 | `dsl/services/git_worktree_service.py`, `tests/test_git_worktree_service.py` |
| Path-aware script invocation | `new-worktree.sh` / `create-worktree.sh` 接收旧路径 | 接收 `../task/<repo>-wt-<task8>` | 保持脚本发现逻辑不变，只替换传参路径来源 | `dsl/services/git_worktree_service.py`, `tests/test_git_worktree_service.py` |
| Branch-only script handling | 旧逻辑会优先调用 `scripts/git_worktree.sh` / `git_worktree.sh` | Koda 忽略 branch-only 脚本，普通任务启动走内置 `git worktree add` fallback | 删除 branch-only 创建策略，新增“旧脚本不会被调用”的回归测试 | `dsl/services/git_worktree_service.py`, `tests/test_git_worktree_service.py` |
| Task path persistence | `TaskService.start_task()` 保存服务返回的 worktree 绝对路径 | 继续保存绝对路径，但内容变为 `../task/...` 根目录下的新地址 | 维持 schema 不变，只更新日志与测试断言 | `dsl/services/task_service.py`, `tests/test_task_service.py` |
| Completion/open flows | 下游链路读取任意绝对 `worktree_path` | 下游链路继续工作，且示例/测试路径更新为 `../task/...` | 更新高层回归测试中的样例路径，不修改业务流程 | `tests/test_codex_runner.py`, `dsl/api/tasks.py` |
| Documentation | 文档只描述“有 worktree_path”，未统一说明新的目录规范 | 文档明确：新建 worktree 默认位于 sibling `task/` 目录 | 更新架构、数据库、验证清单与概览文档 | `docs/architecture/system-design.md`, `docs/database/schema.md`, `docs/dev/evaluation.md`, `docs/index.md` |

### 2.2 Flow Diagram

```mermaid
flowchart TD
    A[User clicks Start Task] --> B[TaskService.start_task]
    B --> C[GitWorktreeService.create_task_worktree]
    C --> D[build_task_worktree_root_path]
    D --> E["<repo-parent>/task/"]
    C --> F{Creation strategy}
    F -->|Path-aware script| G["Pass <repo-parent>/task/<repo>-wt-<task8>"]
    F -->|Legacy branch-only script exists| H["Ignore script"]
    F -->|Fallback git| I["git worktree add <repo-parent>/task/<repo>-wt-<task8> -b task/<task8> main"]
    G --> J[Validate path exists]
    H --> I
    I --> J
    J --> L[Persist Task.worktree_path]
    L --> M["/prd-file, open-in-trae, codex completion reuse stored path"]
```

### 2.3 Low-Fidelity Prototype

```text
/Users/zata/code/
├── my-app/
│   └── .git/
└── task/
    ├── my-app-wt-12345678/
    │   ├── tasks/
    │   │   └── prd-12345678.md
    │   ├── frontend/
    │   └── ...
    └── my-app-wt-87654321/
        └── ...

Task.worktree_path:
  /Users/zata/code/task/my-app-wt-12345678
```

说明：

- `task/` 是每个目标仓库父目录下的统一 worktree 根目录
- basename 默认继续使用 `<repo>-wt-<task8>`，从而减少已有测试、日志与认知模型的变更成本
- branch-only 脚本不再决定 task worktree 子目录名；项目需要自定义创建时必须使用 path-aware 脚本合同

### 2.4 ER Diagram

本需求**不涉及数据库表结构、字段或实体关系变化**，因此不需要新增 Mermaid `erDiagram`。

需要明确的是：

- `Task.worktree_path` 继续保留为绝对路径字段
- 变化发生在“路径生成规则”，而不是“数据模型结构”

### 2.8 Interactive Prototype Change Log

No interactive prototype file changes in this PRD.

### 2.9 Interactive Prototype Link

Not applicable. This requirement does not introduce or modify an interactive prototype page.

---

## 3. Global Definition of Done（DoD）

- [ ] `GitWorktreeService.build_task_worktree_path()` 的默认返回值已变为 `repo_root.parent / "task" / "<repo>-wt-<task8>"`
- [ ] 当 `../task/` 不存在时，系统会自动创建目录后再执行 worktree 创建
- [ ] path-aware 脚本模式与 fallback `git worktree add` 模式都在 `../task/` 下创建 worktree
- [ ] branch-only `git_worktree.sh` 不会被任务启动链路调用；存在旧脚本时仍走 Koda 内置 fallback
- [ ] `TaskService.start_task()` 写入的新 `worktree_path` 可被 `/prd-file`、`open-in-trae`、完成态 merge/cleanup 继续正常消费
- [ ] 旧任务若仍保存历史路径，只要磁盘目录存在，系统继续按旧绝对路径工作，不强制迁移
- [ ] `uv run pytest tests/test_git_worktree_service.py tests/test_task_service.py tests/test_codex_runner.py` 通过
- [ ] `uv run mkdocs build` 无警告通过
- [ ] 实现遵循现有代码规范：Google Style Docstring、明确命名、Windows-safe UTF-8 I/O 约束不被破坏
- [ ] 相关文档页已更新，且手工验证步骤能反映新目录结构

---

## 4. User Stories

### US-001：统一新建 worktree 的根目录

**Description:** As an operator, I want every new task worktree created under a sibling `task/` directory so that repository parents stay predictable and clean.

**Acceptance Criteria:**
- [ ] 默认路径变为 `<repo-parent>/task/<repo>-wt-<task8>`
- [ ] `task/` 根目录缺失时系统自动创建
- [ ] `Task.worktree_path` 中保存的是实际创建成功后的绝对路径

### US-002：保留明确的创建钩子，移除隐式脚本依赖

**Description:** As a maintainer, I want Koda to own default worktree creation and only call project scripts that explicitly accept the target path so that task execution behavior is deterministic across arbitrary linked repositories.

**Acceptance Criteria:**
- [ ] `new-worktree.sh` / `create-worktree.sh` 接收到的新路径参数位于 `../task/` 下
- [ ] `scripts/git_worktree.sh` / `git_worktree.sh` 即使存在也不会被 task worktree 创建链路调用
- [ ] 没有 path-aware 脚本时，系统稳定使用 Koda 内置 `git worktree add` fallback

### US-003：保持下游任务链路无回归

**Description:** As a developer, I want PRD 读取、打开目录和完成态 Git 收尾继续依赖 `Task.worktree_path`，so that changing the root folder does not break downstream workflows.

**Acceptance Criteria:**
- [ ] `/api/tasks/{id}/prd-file` 仍能读取 worktree 内的 `tasks/prd-<task8>.md`
- [ ] `/api/tasks/{id}/open-in-trae` 仍能打开真实 worktree 目录
- [ ] 完成态 `git add / commit / rebase / merge / cleanup` 流程继续基于新路径运行

### US-004：补齐测试与文档

**Description:** As a team member, I want tests and MkDocs pages updated together with the path-rule change so that future维护者不会误解 worktree 的目录约定。

**Acceptance Criteria:**
- [ ] 回归测试覆盖新的默认路径、自动创建目录、path-aware 脚本以及旧 branch-only 脚本被忽略
- [ ] 文档中出现的 worktree 路径示例与实现一致
- [ ] 验证文档明确要求检查新 worktree 是否落在 `../task/` 目录

---

## 5. Functional Requirements

1. **FR-1:** 系统必须将 task worktree 的默认根目录计算为 `repo_root_path.parent / "task"`。
2. **FR-2:** 系统必须将默认 worktree 目录名保留为 `<repo-name>-wt-<task8>`。
3. **FR-3:** 在执行任何 worktree 创建命令前，系统必须确保 `../task/` 目录已存在。
4. **FR-4:** 当仓库存在 `new-worktree.sh` 或 `create-worktree.sh` 时，系统必须把 `../task/...` 下的新目标路径作为显式参数传入。
5. **FR-5:** 当仓库存在 branch-only `scripts/git_worktree.sh` 或 `git_worktree.sh` 时，任务启动链路必须忽略它并继续使用 Koda 内置 fallback，除非仓库同时提供 path-aware `new-worktree.sh` / `create-worktree.sh`。
6. **FR-6:** Path-aware 脚本仍必须显式接收 Koda 计算出的目标路径、任务分支名与基底分支名。
7. **FR-7:** `TaskService.start_task()` 必须继续把创建成功后的 worktree 绝对路径写入 `Task.worktree_path`，且不引入新的数据库字段。
8. **FR-8:** `/api/tasks/{id}/prd-file`、`/api/tasks/{id}/open-in-trae` 与完成态 Git 收尾流程必须继续把 `Task.worktree_path` 当作唯一目录来源。
9. **FR-9:** 回归测试必须覆盖 fallback、path-aware script、旧 branch-only script 被忽略这三类行为。
10. **FR-10:** 文档必须给出明确示例：若项目仓库为 `/Users/zata/code/my-app`，则新 worktree 默认位于 `/Users/zata/code/task/my-app-wt-12345678`。
11. **FR-11:** 旧任务已经保存的历史 `worktree_path` 不应被自动重写或搬迁；系统只改变新建 worktree 的路径策略。
12. **FR-12:** 错误信息必须明确指出 path-aware script “创建后未找到预期目录”或环境准备失败原因；branch-only 脚本不得再成为任务启动失败来源。

---

## 6. Non-Goals

- 不在本期引入新的数据库表、字段或迁移机制
- 不在本期新增“自定义 worktree 根目录”的 UI、环境变量或 per-project 配置
- 不在本期改变任务分支命名规则 `task/<task8>`
- 不自动迁移、移动或重写已经存在的历史 worktree 目录
- 不修改前端交互或新增原型页面
- 不处理与本需求无关的 Git merge/cleanup 逻辑重构

---

## 7. 2026-04-27 修订交付记录

- 已将 Koda task worktree 创建收敛为产品自有能力：普通项目不再需要提供 `just worktree`、`scripts/git_worktree.sh` 或兼容 `--base` 的 wrapper。
- 已保留 path-aware 自定义钩子：`scripts/new-worktree.sh` / `scripts/create-worktree.sh` 仍会收到 Koda 计算出的目标路径、任务分支名和基底分支名。
- 已将 worktree 环境准备改为软链接优先：`.env*`、前端 `node_modules`、Python `.venv` 默认从源仓库链接到 task worktree，避免每个 worktree 复制或重装本地运行依赖。
- 已新增回归测试，验证旧式 `git_worktree.sh` 即使存在也不会被调用，任务仍由 Koda 内置 fallback 创建到 `<repo-parent>/task/<repo>-wt-<task8>`。
- 验证命令：
  - `bash -n scripts/bootstrap_worktree_env.sh`
  - `uv run python -m py_compile backend/dsl/services/git_worktree_service.py tests/test_git_worktree_service.py`
  - `uv run pytest tests/test_git_worktree_service.py::test_create_task_worktree_bootstraps_env_and_dependencies_for_raw_fallback -q`
  - `uv run pytest tests/test_git_worktree_service.py::test_create_task_worktree_passes_task_root_to_path_aware_script tests/test_git_worktree_service.py::test_create_task_worktree_ignores_branch_only_project_script tests/test_git_worktree_service.py::test_create_task_worktree_can_use_non_main_base_branch -q`
  - `uv run pytest tests/test_git_worktree_service.py -q`
  - `uv run pytest tests/test_task_service.py -q`
  - `just docs-build`
