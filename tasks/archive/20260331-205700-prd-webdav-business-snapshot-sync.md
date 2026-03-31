# PRD：WebDAV 业务快照同步

**原始需求标题**：webdav 同步的时候会同步所有的项目和需求卡片, 但是感觉有点不合理, 需求对应的完成程度并没有同步哎
**需求名称（AI 归纳）**：在保留原始 WebDAV 数据库备份的同时，新增一条“业务快照同步”能力，用于跨设备同步项目/卡片进度与任务上下文
**文件路径**：`tasks/20260331-205700-prd-webdav-business-snapshot-sync.md`
**创建时间**：2026-03-31 20:57:00 CST
**需求背景/上下文**：用户反馈当前 WebDAV 看起来“会同步项目和需求卡片”，但和真实执行进度并不一致。根因是现有实现只有原始 SQLite 数据库备份/恢复，缺少一条专门面向跨设备业务状态同步的安全链路。仅靠文案纠偏还不够，需要把“原始 DB 备份”和“业务快照同步”拆成两条明确能力，并把任务恢复后的机器边界展示清楚。
**参考上下文**：`dsl/services/webdav_service.py`, `dsl/services/webdav_business_sync_service.py`, `dsl/api/webdav_settings.py`, `dsl/services/task_service.py`, `frontend/src/components/SettingsModal.tsx`, `frontend/src/App.tsx`, `docs/database/schema.md`

## 1. Introduction & Goals

本次交付把 WebDAV 能力拆成两条并行路径：

- 原始数据库备份/恢复：继续保留，适合灾备与整机迁移。
- 业务快照同步：新增 ZIP 快照，跨设备同步项目、需求卡片、日志、PRD/planning 快照、媒体文件、任务侧边问答和任务引用关系。

核心目标：

- 在不破坏现有数据库备份路由的前提下，新增独立的业务快照同步能力。
- 让“需求对应的完成程度”能够随业务快照一起同步到另一台机器。
- 明确排除 `repo_path`、`worktree_path`、本地分支存在性、后台进程运行态等机器事实。
- 对依赖本机代码执行上下文的阶段做安全降级，并向前端明确展示“同步时的原始进度”和“本机可安全继续的阶段”。
- 用自动化测试、前端构建和文档构建锁住这套行为。

## 2. Implementation Guide

### 2.1 Change Matrix

| Change Target | Current State | Target State | How to Modify | Affected Files |
| --- | --- | --- | --- | --- |
| WebDAV 核心能力 | 只有 SQLite 数据库备份/恢复 | 保留 DB backup，同时新增 business snapshot ZIP | 新增业务快照服务，复用现有 WebDAV 传输层 | `dsl/services/webdav_business_sync_service.py`, `dsl/services/webdav_service.py` |
| WebDAV API | 只有 `/sync/upload` 和 `/sync/download` | 增加 `/sync/business/upload` 和 `/sync/business/download` | 在设置路由中接入新服务并保持旧路由不变 | `dsl/api/webdav_settings.py` |
| WebDAV 设置语义 | 偏向“数据库备份”单一能力 | 明确为“存储配置”，同时服务于 backup 与 business sync | 更新 model / schema / 前端类型与默认远端目录 | `dsl/models/webdav_settings.py`, `dsl/schemas/webdav_settings_schema.py`, `frontend/src/types/index.ts` |
| 任务恢复状态 | 恢复后缺少“原始远端进度”标记 | 新增恢复标记字段，保存远端阶段/生命周期与恢复时间 | 扩展 `Task`、schema、增量 schema patch | `dsl/models/task.py`, `dsl/schemas/task_schema.py`, `utils/database.py` |
| 任务执行安全性 | 恢复后的任务可能丢失 worktree 但仍停留在机器相关阶段 | 对实现/测试/PR 等阶段做安全降级，并在真正恢复本地执行时清理恢复标记 | 调整任务恢复逻辑与 `TaskService` | `dsl/services/webdav_business_sync_service.py`, `dsl/services/task_service.py`, `dsl/api/tasks.py` |
| 设置页操作区 | 只有原始 DB backup 操作 | 同一 WebDAV 配置下展示两组操作：Raw Database Backup + Business Snapshot Sync | 更新按钮、说明文案和确认提示 | `frontend/src/components/SettingsModal.tsx`, `frontend/src/api/client.ts` |
| 任务 UI 展示 | 看不到“这是同步恢复的快照进度” | 卡片与详情明确展示同步恢复说明与恢复时间 | 扩展前端类型、卡片 metadata fallback 和详情事实卡 | `frontend/src/App.tsx`, `frontend/src/index.css`, `frontend/src/types/index.ts` |
| 数据文档与回归保护 | 文档未覆盖新语义；测试只有原始 DB 文案 | 文档明确两条 WebDAV 语义；测试覆盖 business snapshot 导出/导入 | 更新 schema 文档与测试 | `docs/database/schema.md`, `tests/test_webdav_service.py` |

## 3. Global Definition of Done

- [x] 保留原始 `/api/webdav-settings/sync/upload` 与 `/api/webdav-settings/sync/download`
- [x] 新增 `/api/webdav-settings/sync/business/upload` 与 `/api/webdav-settings/sync/business/download`
- [x] 业务快照能够同步项目、任务、日志、PRD/planning 快照、媒体、侧边问答和任务引用
- [x] 业务快照不会同步 `repo_path`、`worktree_path`、本地分支状态和后台运行态
- [x] 恢复后的任务会保存原始同步阶段，并在需要时降级到本机安全阶段
- [x] 恢复后的无 worktree 任务允许先重绑项目再继续本地执行
- [x] 设置页同时展示 Raw Database Backup 和 Business Snapshot Sync
- [x] 任务卡片与详情会展示业务快照恢复说明
- [x] 自动化测试覆盖新的导出/导入行为与 WebDAV 密码保留逻辑
- [x] 前端构建通过
- [x] 文档构建通过

## 4. User Stories

### US-001：作为用户，我希望能跨设备同步“业务进度”而不是误以为同步了整套本机执行环境

**Description:** As a user, I want a dedicated WebDAV business snapshot sync so that projects, cards, logs, PRDs, and progress snapshots can move across devices without pretending local repos and worktrees also moved.

**Acceptance Criteria:**
- [x] 设置页提供独立的 Business Snapshot Sync 操作区
- [x] 上传/导入说明明确区分 business facts 与 machine-local facts
- [x] 恢复后任务列表能看到同步过来的阶段进度

### US-002：作为用户，我希望恢复后的任务不会呈现错误的“可直接续跑”状态

**Description:** As a user, I want restored tasks to reopen in a safe local stage while still showing the original synced progress, so I can relink the correct repo before continuing work.

**Acceptance Criteria:**
- [x] 机器相关的执行阶段会被安全降级
- [x] 任务响应与卡片 metadata 会暴露同步前的原始阶段/生命周期说明
- [x] 没有 worktree 的恢复任务允许重绑项目

### US-003：作为维护者，我希望这套边界和恢复语义有回归保护

**Description:** As a maintainer, I want tests around business snapshot export/import, backup messaging, and settings persistence so future changes do not silently regress into unsafe or misleading behavior.

**Acceptance Criteria:**
- [x] 测试覆盖 business snapshot 导出媒体/工件/侧边数据
- [x] 测试覆盖恢复时的阶段降级、run account 重绑和媒体落盘
- [x] 测试覆盖 WebDAV 空密码保存时保留旧密码

## 5. Functional Requirements

1. **FR-1**：系统必须保留原始 SQLite 数据库备份/恢复能力，不得破坏现有 DB backup 路由。
2. **FR-2**：系统必须新增一条独立的 WebDAV 业务快照同步能力，使用 ZIP 归档传输业务数据与媒体文件。
3. **FR-3**：业务快照必须同步项目、任务、日志、`TaskArtifact`、媒体文件、任务侧边问答和任务引用关系。
4. **FR-4**：业务快照不得同步 `repo_path`、`worktree_path`、本地分支存在性、后台运行态和直接可恢复的本机执行上下文。
5. **FR-5**：导入任务必须重绑到当前活跃 `RunAccount`，否则无法在当前工作区可见。
6. **FR-6**：业务快照恢复必须保留原始同步阶段/生命周期，并在必要时安全降级到本机可接受的阶段。
7. **FR-7**：业务快照恢复后、尚未生成 worktree 的任务必须允许重新绑定项目。
8. **FR-8**：前端必须同时展示 Raw Database Backup 与 Business Snapshot Sync，并明确各自语义边界。
9. **FR-9**：卡片与详情必须向用户解释“当前看到的是同步恢复的业务进度，不代表本机 repo/worktree 已恢复”。
10. **FR-10**：新增实现必须附带自动化测试、文档同步和验证记录。

## 6. Non-Goals

- 不实现 Git 仓库、patch、未提交变更或 worktree 文件系统级别的跨设备同步
- 不尝试把远端正在运行的后台自动化无损迁移到另一台机器继续执行
- 不引入新的外部依赖来实现业务快照归档或传输
- 不改变现有数据库备份文件格式

## 7. Implementation Outcome

### Delivered Files

- `dsl/services/webdav_business_sync_service.py`
- `dsl/api/webdav_settings.py`
- `dsl/models/task.py`
- `dsl/models/webdav_settings.py`
- `dsl/schemas/task_schema.py`
- `dsl/schemas/webdav_settings_schema.py`
- `dsl/services/task_service.py`
- `dsl/api/tasks.py`
- `frontend/src/App.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/components/SettingsModal.tsx`
- `frontend/src/index.css`
- `frontend/src/types/index.ts`
- `docs/database/schema.md`
- `tests/test_webdav_service.py`
- `utils/database.py`

### Verification

| Command | Purpose | Result |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_webdav_service.py -q` | Verify raw backup messaging, business snapshot export/import behavior, and WebDAV password retention | Passed (`5 passed`) |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_task_service.py -q` | Verify existing task lifecycle/worktree behavior still passes after restore-aware task changes | Passed (`14 passed`) |
| `npm run build` | Verify frontend settings/task UI changes compile cleanly | Passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build --strict` | Verify schema docs remain valid after WebDAV semantics update | Passed |
| `git diff --check` | Verify touched diffs are whitespace-clean | Passed |

### Variances

- 先前的 `tasks/20260331-181001-prd-webdav-database-backup-wording.md` 只覆盖“文案纠偏为数据库备份”，与最终交付的“双通道 WebDAV 能力”范围不再匹配，因此新增本 PRD 作为最终实现记录。
- 业务快照恢复不会试图保留远端的 `stage_updated_at` 作为本机停滞判断基准，而是以恢复时间重新开始本机阶段窗口，避免错误触发提醒或误导“已在本机等待很久”。
