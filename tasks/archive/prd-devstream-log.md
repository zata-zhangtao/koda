# PRD: DevStream Log (DSL) V2.0 — 智能开发流日志

| 文档属性 | 内容 |
| --- | --- |
| **产品名称** | Koda |
| **版本号** | V2.0 (多模态智能版) |
| **PRD 版本** | 1.0 |
| **最后更新** | 2026-02-09 |
| **核心理念** | Keep Flow, Log Smart. (保持心流，智能记录) |
| **技术栈** | Python 3.14+ / FastAPI / SQLite (SQLAlchemy) / React SPA |
| **项目位置** | 在现有 koda 项目内构建 |

---

## 1. Introduction & Goals (产品简介与目标)

### 1.1 产品愿景

为开发者提供一款 **"低摩擦、高保真"** 的过程记录工具。开发者可以极速（文本/截图）记录开发过程中的每一个瞬间，利用 AI 异步解析复杂的报错截图，最终将碎片化的日志自动编排成一份逻辑严密、图文并茂的 **项目编年史 (Project Chronicle)**。

### 1.2 目标用户

独立开发者或小型团队中的开发人员，需要在编码过程中快速记录 bug、排查过程、解决方案，并自动生成结构化技术文档。

### 1.3 可衡量目标 (Measurable Objectives)

- [ ] **MO-1:** 用户从发现 bug 到完成一条日志记录的操作时间 < 10 秒（文本）/ < 15 秒（含截图）
- [ ] **MO-2:** 支持 Markdown 文本 + 图片混合输入，图片粘贴后不阻塞后续输入
- [ ] **MO-3:** 日志可按时间线 (Timeline) 和任务 (Task View) 两种维度浏览
- [ ] **MO-4:** 一键导出包含完整排错路径和代码片段的 Markdown 技术文档
- [ ] **MO-5:** (Phase 2) AI 图片解析准确率 > 80%，异步处理不打断用户心流

---

## 2. Implementation Guide (技术架构)

### 2.1 Tech Stack (技术选型)

| 层级 | 技术 | 说明 |
| --- | --- | --- |
| **Language** | Python 3.14+ | 项目已有基础设施 |
| **Package Manager** | uv | 遵循项目规范 |
| **Backend Framework** | FastAPI | 本地 HTTP API 服务，`utils/database.py:71` 已有 `get_db()` 依赖注入模式 |
| **Database** | SQLite via SQLAlchemy | 复用 `utils/database.py`，本地存储无需联网 |
| **AI Integration** | LangChain (multi-provider) | 复用 `ai_agent/utils/model_loader.py`，已支持 DashScope / OpenRouter / Anthropic |
| **Frontend** | React SPA (Vite) | 本地浏览器访问，支持 Ctrl+V 图片粘贴、3 栏布局 |
| **Logging** | Singleton Logger | 复用 `utils/logger.py` |
| **Config** | dotenv + Config class | 复用 `utils/settings.py`，需扩展 DSL 配置项 |

### 2.2 Project Structure (项目结构)

在现有 koda 项目内新增 `dsl/` 模块和 `frontend/` 目录：

```
koda/
├── dsl/                          # DSL 后端核心模块 (NEW)
│   ├── __init__.py
│   ├── app.py                    # FastAPI application factory
│   ├── models/                   # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── run_account.py        # RunAccount model
│   │   ├── task.py               # Task model
│   │   ├── dev_log.py            # DevLog model
│   │   └── enums.py              # StateTag, AIProcessingStatus enums
│   ├── schemas/                  # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── run_account_schema.py
│   │   ├── task_schema.py
│   │   └── dev_log_schema.py
│   ├── api/                      # FastAPI routers
│   │   ├── __init__.py
│   │   ├── run_accounts.py       # /api/run-accounts
│   │   ├── tasks.py              # /api/tasks
│   │   ├── logs.py               # /api/logs
│   │   ├── media.py              # /api/media (image upload/serve)
│   │   └── chronicle.py          # /api/chronicle (export)
│   ├── services/                 # Business logic layer
│   │   ├── __init__.py
│   │   ├── log_service.py        # Log CRUD + state transitions
│   │   ├── task_service.py       # Task lifecycle management
│   │   ├── media_service.py      # Image storage + thumbnail generation
│   │   ├── chronicle_service.py  # Timeline/Task view rendering
│   │   └── ai_vision_service.py  # (Phase 2) AI image analysis
│   └── workers/                  # (Phase 2) Background task processing
│       ├── __init__.py
│       └── vision_worker.py
├── frontend/                     # React SPA (NEW)
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── StreamView.tsx     # 中栏：日志流
│   │   │   ├── InputBox.tsx       # 底栏：超级输入框
│   │   │   ├── Sidebar.tsx        # 左栏：Context & Queue
│   │   │   ├── LogCard.tsx        # 日志卡片组件
│   │   │   ├── ReviewModal.tsx    # (Phase 2) 校正弹窗
│   │   │   └── ChronicleView.tsx  # 编年史视图
│   │   ├── hooks/
│   │   ├── api/                   # API client layer
│   │   └── types/
│   └── index.html
├── utils/                        # 现有共享工具 (REUSE)
├── ai_agent/                     # 现有 AI 工具 (REUSE)
├── data/                         # SQLite DB + media storage (NEW)
│   ├── dsl.db
│   └── media/
└── main.py                       # 入口：启动 FastAPI server
```

### 2.3 Data Model (数据模型 — SQLAlchemy)

将 `init.md` 中的 TypeScript 接口转换为 SQLAlchemy ORM 模型，遵循项目 AI-Native 编码规范（Fully Qualified Naming + Pydantic schemas）。

#### Enums (`dsl/models/enums.py`)

```python
class DevLogStateTag(str, Enum):
    """日志状态标记，驱动任务生命周期。"""
    NONE = "NONE"
    BUG = "BUG"                    # 🐛 发现 Bug
    OPTIMIZATION = "OPTIMIZATION"  # 💡 优化建议
    FIXED = "FIXED"                # ✅ 已修复
    TRANSFERRED = "TRANSFERRED"    # ⏭️ 已转移

class TaskLifecycleStatus(str, Enum):
    """任务生命周期状态。"""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PENDING = "PENDING"

class AIProcessingStatus(str, Enum):
    """AI 图片解析处理状态。"""
    PENDING = "PENDING"            # ⏳ 等待处理
    PROCESSING = "PROCESSING"      # ⏳ 正在解析
    WAITING_REVIEW = "WAITING_REVIEW"  # 🔔 待校正
    CONFIRMED = "CONFIRMED"        # ✔ 已确认
```

#### RunAccount (`dsl/models/run_account.py`)

| Column | Type | Description |
| --- | --- | --- |
| `id` | `String(36)` PK | UUID 主键 |
| `account_display_name` | `String(100)` | 显示名称，如 `Zata @ MacOS-Pro` |
| `user_name` | `String(50)` | 用户名 |
| `environment_os` | `String(50)` | 操作系统 |
| `git_branch_name` | `String(100)` nullable | 当前 Git 分支 |
| `created_at` | `DateTime` | 创建时间 |
| `is_active` | `Boolean` default=True | 是否为当前活跃账户 |

#### Task (`dsl/models/task.py`)

| Column | Type | Description |
| --- | --- | --- |
| `id` | `String(36)` PK | UUID 主键 |
| `run_account_id` | `String(36)` FK | 关联 RunAccount |
| `task_title` | `String(200)` | 任务标题 |
| `lifecycle_status` | `Enum(TaskLifecycleStatus)` | 任务状态 |
| `created_at` | `DateTime` | 创建时间 |
| `closed_at` | `DateTime` nullable | 关闭时间 |

**Relationship:** `task.dev_logs` → one-to-many → `DevLog`

#### DevLog (`dsl/models/dev_log.py`)

| Column | Type | Description |
| --- | --- | --- |
| `id` | `String(36)` PK | UUID 主键 |
| `task_id` | `String(36)` FK | 关联 Task |
| `run_account_id` | `String(36)` FK | 关联 RunAccount |
| `created_at` | `DateTime` | 创建时间 |
| `text_content` | `Text` | 用户输入的 Markdown 文本 |
| `state_tag` | `Enum(DevLogStateTag)` | 状态标记 |
| `media_original_image_path` | `String(500)` nullable | 图片本地存储路径 |
| `media_thumbnail_path` | `String(500)` nullable | 缩略图路径 |
| `ai_processing_status` | `Enum(AIProcessingStatus)` nullable | AI 处理状态 |
| `ai_generated_title` | `String(200)` nullable | AI 生成的标题 |
| `ai_analysis_text` | `Text` nullable | AI 分析文本 |
| `ai_extracted_code` | `Text` nullable | AI 提取的代码块 |
| `ai_confidence_score` | `Float` nullable | AI 置信度分数 |

> **设计决策:** 将 `init.md` 中的嵌套 `media` 对象扁平化为 DevLog 表的列，避免额外的关联表。AI 相关字段在 Phase 1 中为 nullable，Phase 2 启用。

### 2.4 Core Logic & Data Flow (核心数据流)

#### Phase 1: 输入处理管线 (Input Pipeline)

```
用户输入 (text / image / command)
    │
    ├─ 文本输入 → parse_markdown() → create DevLog(text_content=..., state_tag=NONE)
    │
    ├─ 指令输入 (/bug, /fix, /opt, /transfer)
    │   → parse_command() → update DevLog.state_tag
    │   → /task <title> → create/switch Task
    │
    └─ 图片粘贴 (Ctrl+V)
        → media_service.save_image() → 本地存储 + 生成缩略图
        → create DevLog(media_original_image_path=..., ai_processing_status=PENDING)
        → (Phase 2) 触发 BackgroundTask → ai_vision_service.analyze()
```

#### Phase 2: AI 异步处理管线 (AI Vision Pipeline)

```
DevLog(ai_processing_status=PENDING)
    │
    → BackgroundTask 启动
    → ai_processing_status = PROCESSING
    → model_loader.create_chat_model("qwen3-vl-plus") 或 fallback 到 "openai/gpt-4o"
    → 发送图片 → 获取 AI 结果 (title, analysis, code)
    │
    ├─ confidence_score >= threshold (0.85)
    │   → ai_processing_status = CONFIRMED (自动确认)
    │
    └─ confidence_score < threshold
        → ai_processing_status = WAITING_REVIEW
        → 推送到 Review Queue 侧边栏
```

### 2.5 Reused Modules (复用现有模块)

| 现有模块 | 复用方式 | 需要的修改 |
| --- | --- | --- |
| `ai_agent/utils/model_loader.py` | Phase 2 直接调用 `create_chat_model()` | 无需修改，`models.json` 已配置 vision_models |
| `ai_agent/utils/models.json` | Vision models: `qwen3-vl-plus`, `openai/gpt-4o`, `google/gemini-3-pro-preview` | 无需修改 |
| `utils/database.py` | 复用 `Base`, `get_db()`, `create_tables()`, `SessionLocal` | **需修复:** `settings.py` 缺少 `DATABASE_URL` 定义 |
| `utils/logger.py` | 直接复用 singleton logger | 无需修改 |
| `utils/settings.py` | 扩展 DSL 配置项 | 新增 `DATABASE_URL`, `MEDIA_STORAGE_PATH`, `AI_CONFIDENCE_THRESHOLD` |
| `utils/helpers.py` | 复用 `safe_json_loads`, `truncate_string`, `normalize_whitespace`, `retry_on_exception` | 无需修改 |

### 2.6 Prerequisites (前置修复)

**`utils/settings.py` 缺少 `DATABASE_URL`：** 当前 `utils/database.py:18` 引用 `config.DATABASE_URL`，但 `utils/settings.py` 中未定义此属性。需在 `Config` 类中添加：

```python
# 数据库配置
DATABASE_URL: ClassVar[str] = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{BASE_DIR / 'data' / 'dsl.db'}"
)

# DSL 媒体存储路径
MEDIA_STORAGE_PATH: ClassVar[Path] = BASE_DIR / "data" / "media"

# AI 置信度阈值 (Phase 2)
AI_CONFIDENCE_THRESHOLD: ClassVar[float] = float(
    os.getenv("AI_CONFIDENCE_THRESHOLD", "0.85")
)
```

### 2.7 API Design (API 端点设计)

| Method | Endpoint | Description | Phase |
| --- | --- | --- | --- |
| `GET` | `/api/run-accounts` | 列出所有 RunAccount | 1 |
| `POST` | `/api/run-accounts` | 创建 RunAccount | 1 |
| `PUT` | `/api/run-accounts/{id}/activate` | 切换活跃账户 | 1 |
| `GET` | `/api/tasks` | 列出当前账户的任务 | 1 |
| `POST` | `/api/tasks` | 创建任务 | 1 |
| `PUT` | `/api/tasks/{id}/status` | 更新任务状态 (OPEN/CLOSED/PENDING) | 1 |
| `GET` | `/api/logs` | 获取日志列表 (支持 task_id 过滤) | 1 |
| `POST` | `/api/logs` | 创建日志 (text + optional state_tag) | 1 |
| `POST` | `/api/media/upload` | 上传图片，返回 DevLog with media | 1 |
| `GET` | `/api/media/{filename}` | 获取图片/缩略图 | 1 |
| `GET` | `/api/chronicle/timeline` | 按时间线渲染日志 | 1 |
| `GET` | `/api/chronicle/task/{task_id}` | 按任务渲染日志 | 1 |
| `GET` | `/api/chronicle/export` | 导出 Markdown 文档 | 1 |
| `GET` | `/api/review-queue` | 获取待校正列表 | 2 |
| `PUT` | `/api/logs/{id}/ai-review` | 确认/编辑/重试 AI 结果 | 2 |

---

## 3. Phasing & Milestones (分阶段交付)

### Phase 1: Core Logging (MVP — 核心日志功能)

**目标:** 完成基础日志记录闭环 — 输入、存储、浏览、导出。

**包含功能:**
- RunAccount 管理 (创建/切换)
- Task 生命周期 (创建/关闭/切换)
- Stream Input (Markdown 文本 + 图片粘贴)
- State Tagging (/bug, /fix, /opt, /transfer 指令)
- 3 栏 UI 布局 (Sidebar | Stream | Input)
- Timeline 视图 + Task 视图
- Markdown 导出

### Phase 2: AI Vision & Review Queue (AI 视觉解析)

**目标:** 实现 AI 异步图片解析和校正队列。

**包含功能:**
- 图片上传后自动触发 AI 解析 (BackgroundTasks)
- 多 provider fallback (DashScope → OpenRouter)
- Review Queue 侧边栏 (待校正计数 badge)
- 校正界面 (Accept / Edit / Retry)
- 高置信度自动确认

### Phase 3: Chronicle & Polish (编年史增强)

**目标:** 完善文档生成和用户体验。

**包含功能:**
- 增强的 Task View (完整生命周期可视化)
- 富文本 Markdown 导出 (嵌入图片)
- 键盘快捷键 (Enter 确认, Esc 跳过, 全局呼出)
- Bug → Fixed 耗时自动计算

---

## 4. Global Definition of Done (全局完成标准)

以下标准适用于 **所有** User Stories：

- [ ] Ruff lint + format 通过 (遵循 `.pre-commit-config.yaml` 配置)
- [ ] 所有 public functions 包含 Google Style docstrings
- [ ] 所有文件 I/O 操作显式指定 `encoding="utf-8"`
- [ ] 变量命名遵循 Fully Qualified Naming 规范 (禁止 `data`, `item`, `res` 等泛化名称)
- [ ] Pydantic schemas 用于所有 API 请求/响应
- [ ] 核心业务逻辑有 pytest 单元测试
- [ ] API 端点有基本的集成测试
- [ ] 浏览器中手动验证 UI 交互
- [ ] 无已有功能的回归

---

## 5. User Stories (用户故事)

### Phase 1: Core Logging (MVP)

#### US-001: 项目初始化与数据模型

**Description:** As a developer, I want the DSL project structure and database schema set up so that all subsequent features have a foundation to build on.

**Acceptance Criteria:**
- [ ] `dsl/` 模块目录结构创建完成 (models, schemas, api, services)
- [ ] SQLAlchemy models 定义完成: `RunAccount`, `Task`, `DevLog`, enums
- [ ] Pydantic schemas 定义完成 (Create/Update/Response for each entity)
- [ ] `utils/settings.py` 新增 `DATABASE_URL`, `MEDIA_STORAGE_PATH` 配置
- [ ] `create_tables()` 成功创建所有表
- [ ] FastAPI app factory (`dsl/app.py`) 可启动
- [ ] `main.py` 更新为启动 FastAPI server (uvicorn)

#### US-002: RunAccount 管理

**Description:** As a developer, I want to create and switch Run Accounts so that my logs are associated with the correct environment context.

**Acceptance Criteria:**
- [ ] `POST /api/run-accounts` 创建新账户 (user_name, environment_os, git_branch_name)
- [ ] `GET /api/run-accounts` 列出所有账户，标记当前活跃账户
- [ ] `PUT /api/run-accounts/{id}/activate` 切换活跃账户 (同时将其他账户设为 inactive)
- [ ] 首次启动时自动创建默认 RunAccount (从系统环境检测 user/OS/branch)
- [ ] 前端 Sidebar 顶部显示当前 RunAccount 信息

#### US-003: Task 生命周期管理

**Description:** As a developer, I want to create, switch, and close tasks so that my logs are organized by work units.

**Acceptance Criteria:**
- [ ] `POST /api/tasks` 创建任务 (task_title)，自动关联当前 RunAccount
- [ ] `GET /api/tasks` 列出当前账户的任务，按状态分组
- [ ] `PUT /api/tasks/{id}/status` 更新状态 (OPEN → CLOSED / PENDING)
- [ ] 输入框支持 `/task <title>` 指令创建新任务
- [ ] 输入框支持 `/task` (无参数) 显示任务列表并切换
- [ ] 前端 Sidebar 中部显示活跃任务列表，点击切换当前任务
- [ ] 关闭任务时自动记录 `closed_at` 时间戳

#### US-004: Stream Input — 文本与 Markdown

**Description:** As a developer, I want a super input box that accepts Markdown text so that I can quickly log my thoughts and findings.

**Acceptance Criteria:**
- [ ] 底栏输入框支持多行 Markdown 文本输入
- [ ] `POST /api/logs` 创建 DevLog (text_content, 关联当前 task_id 和 run_account_id)
- [ ] 提交后日志立即出现在中栏 Stream 视图
- [ ] Stream 视图中 Markdown 正确渲染 (代码块、链接、列表等)
- [ ] 日志卡片显示时间戳和关联任务名称
- [ ] Enter 提交，Shift+Enter 换行

#### US-005: Stream Input — 图片粘贴与本地存储

**Description:** As a developer, I want to paste screenshots directly into the input box so that I can capture error messages without leaving my workflow.

**Acceptance Criteria:**
- [ ] 输入框支持 `Ctrl+V` / `Cmd+V` 粘贴剪贴板图片
- [ ] `POST /api/media/upload` 接收图片，保存到 `data/media/` 目录
- [ ] 自动生成缩略图 (max 300px width)
- [ ] 图片粘贴后立即在输入框显示缩略图预览，**不阻塞**后续文本输入
- [ ] 创建 DevLog 时 `media_original_image_path` 和 `media_thumbnail_path` 正确填充
- [ ] Stream 视图中图片日志显示为带缩略图的卡片，点击可查看原图
- [ ] `GET /api/media/{filename}` 正确返回图片文件

#### US-006: State Tagging (状态标记)

**Description:** As a developer, I want to tag logs with states (/bug, /fix, /opt, /transfer) so that the chronicle can visualize the problem-solving lifecycle.

**Acceptance Criteria:**
- [ ] 输入框识别指令前缀: `/bug`, `/fix`, `/opt`, `/transfer`
- [ ] 指令后的文本作为日志内容，state_tag 自动设置
- [ ] `/bug` → `DevLogStateTag.BUG` (红色左边框)
- [ ] `/fix` → `DevLogStateTag.FIXED` (绿色左边框)
- [ ] `/opt` → `DevLogStateTag.OPTIMIZATION` (黄色左边框)
- [ ] `/transfer` → `DevLogStateTag.TRANSFERRED` (蓝色左边框)
- [ ] 底栏显示 4 个状态快捷按钮，点击等同于输入对应指令
- [ ] `/fix` 时如果当前 Task 下所有 BUG 都已 FIXED，提示是否关闭 Task

#### US-007: 基础 Timeline 视图与 Markdown 导出

**Description:** As a developer, I want to view my logs as a chronological timeline and export them as a Markdown document.

**Acceptance Criteria:**
- [ ] `GET /api/chronicle/timeline` 返回按时间排序的日志列表 (支持日期过滤)
- [ ] `GET /api/chronicle/task/{task_id}` 返回按任务分组的日志
- [ ] 中栏 Stream 视图默认显示 Timeline 模式
- [ ] 可切换到 Task View 模式 (按任务分组显示)
- [ ] 状态日志带有对应颜色的左边框标识
- [ ] 图片日志显示缩略图，点击展开
- [ ] `GET /api/chronicle/export?format=markdown` 导出完整 Markdown 文档
- [ ] 导出的 Markdown 包含: 任务标题、时间戳、状态标记、文本内容、图片引用

### Phase 2: AI Vision & Review Queue

#### US-008: AI 异步图片解析

**Description:** As a developer, I want uploaded screenshots to be automatically analyzed by AI in the background so that error information is extracted without interrupting my flow.

**Acceptance Criteria:**
- [ ] 图片上传后自动触发 FastAPI `BackgroundTasks` 异步处理
- [ ] 调用 `ai_agent/utils/model_loader.py` 的 `create_chat_model()` 加载 vision model
- [ ] Provider fallback: DashScope `qwen3-vl-plus` → OpenRouter `openai/gpt-4o` → `google/gemini-3-pro-preview`
- [ ] AI 提取三项内容: `ai_generated_title` (摘要), `ai_analysis_text` (根因), `ai_extracted_code` (代码)
- [ ] 处理过程中 `ai_processing_status` 从 PENDING → PROCESSING → WAITING_REVIEW/CONFIRMED
- [ ] Stream 视图中图片卡片显示状态指示灯 (⏳/🔔/✔)

#### US-009: Review Queue 侧边栏

**Description:** As a developer, I want a review queue in the sidebar so that I can see pending AI results at a glance.

**Acceptance Criteria:**
- [ ] `GET /api/review-queue` 返回 `ai_processing_status=WAITING_REVIEW` 的日志列表
- [ ] 左栏 Sidebar 底部显示 "待校正 (N)" badge，N 为待校正数量
- [ ] 点击 badge 展开待校正列表，显示缩略图 + AI 生成的标题
- [ ] 列表项点击后打开 Review Modal

#### US-010: AI 结果校正流程

**Description:** As a developer, I want to review, edit, or retry AI-generated analysis so that the final log content is accurate.

**Acceptance Criteria:**
- [ ] Review Modal 左侧显示原始大图，右侧显示 AI 填写的表单 (title, analysis, code)
- [ ] 三个操作按钮: Accept (接受) / Edit (微调) / Retry (重试)
- [ ] Accept: `ai_processing_status` → CONFIRMED，AI 内容合并到日志显示
- [ ] Edit: 允许修改 AI 生成的字段，保存后 → CONFIRMED
- [ ] Retry: 重新触发 AI 解析 (可选择不同 provider)
- [ ] `PUT /api/logs/{id}/ai-review` 处理上述三种操作

#### US-011: 高置信度自动确认

**Description:** As a developer, I want high-confidence AI results to be auto-confirmed so that I only need to review uncertain analyses.

**Acceptance Criteria:**
- [ ] AI 返回结果包含 `confidence_score` (0.0 ~ 1.0)
- [ ] `confidence_score >= AI_CONFIDENCE_THRESHOLD` (默认 0.85) 时自动设为 CONFIRMED
- [ ] 自动确认的日志在 Stream 视图中直接显示 AI 内容 (带 "AI Auto-confirmed" 标记)
- [ ] 用户可在设置中调整 `AI_CONFIDENCE_THRESHOLD`

### Phase 3: Chronicle & Polish

#### US-012: 增强 Task View (任务编年史)

**Description:** As a developer, I want a comprehensive task view showing the full lifecycle from bug discovery to resolution.

**Acceptance Criteria:**
- [ ] Task View 显示任务从创建到关闭的完整日志链
- [ ] Bug → Fixed 自动计算耗时并显示
- [ ] 状态转换节点在时间线上高亮标记
- [ ] 支持折叠/展开各状态段落

#### US-013: 富文本 Markdown 导出

**Description:** As a developer, I want to export a standalone Markdown document with embedded images.

**Acceptance Criteria:**
- [ ] 导出的 Markdown 文件包含 Base64 编码的图片 (或相对路径引用)
- [ ] 按 `init.md` Section 3.4 的渲染逻辑格式化 (时间戳 + 状态 + 内容 + 图片)
- [ ] 支持按任务或按时间范围导出
- [ ] AI 分析内容以引用块形式嵌入

#### US-014: 键盘快捷键与快速校正

**Description:** As a developer, I want keyboard shortcuts for efficient review and input.

**Acceptance Criteria:**
- [ ] Review Modal: `Enter` 确认下一张, `Esc` 跳过
- [ ] 输入框: `Enter` 提交, `Shift+Enter` 换行
- [ ] 全局: 可配置快捷键呼出/隐藏应用窗口 (如果后续包装为桌面应用)

---

## 6. Functional Requirements (功能需求)

### 输入系统

- **FR-1:** 系统应提供支持 Markdown 语法的多行文本输入框
- **FR-2:** 系统应支持通过 `Ctrl+V` / `Cmd+V` 粘贴剪贴板图片
- **FR-3:** 图片粘贴后应立即显示缩略图预览，不阻塞后续输入
- **FR-4:** 系统应识别以 `/` 开头的指令 (`/bug`, `/fix`, `/opt`, `/transfer`, `/task`)
- **FR-5:** 每条日志必须关联一个 Task 和一个 RunAccount

### 状态管理

- **FR-6:** 系统应支持 5 种日志状态: NONE, BUG, OPTIMIZATION, FIXED, TRANSFERRED
- **FR-7:** 状态变更应在 UI 中以颜色编码的左边框体现 (红/黄/绿/蓝)
- **FR-8:** 任务支持 3 种生命周期状态: OPEN, CLOSED, PENDING
- **FR-9:** 同一时间只能有一个活跃的 RunAccount

### 数据存储

- **FR-10:** 所有数据存储在本地 SQLite 数据库中，无需网络连接
- **FR-11:** 图片文件存储在本地 `data/media/` 目录
- **FR-12:** 系统应自动为上传的图片生成缩略图 (max width 300px)

### 浏览与导出

- **FR-13:** 系统应提供 Timeline 视图 (按时间排序) 和 Task View (按任务分组)
- **FR-14:** 系统应支持将日志导出为 Markdown 格式文档
- **FR-15:** 导出的文档应包含时间戳、状态标记、文本内容和图片引用

### AI 解析 (Phase 2)

- **FR-16:** 图片上传后应自动触发后台 AI 解析任务
- **FR-17:** AI 解析应提取: 摘要 (title)、根因分析 (analysis)、代码片段 (code)
- **FR-18:** AI 解析结果置信度 >= 阈值时应自动确认，否则进入 Review Queue
- **FR-19:** 用户应能对 AI 结果执行 Accept / Edit / Retry 操作
- **FR-20:** AI provider 应支持 fallback 机制 (DashScope → OpenRouter)

---

## 7. Non-Goals (不在范围内)

以下功能明确 **不在** 当前产品范围内：

- **NG-1:** 云端同步或多设备数据同步
- **NG-2:** 多用户协作或实时共享
- **NG-3:** 移动端 (iOS/Android) 应用
- **NG-4:** Tauri / Electron 桌面应用包装 (可作为未来增强)
- **NG-5:** 与第三方项目管理工具集成 (Jira, Linear, etc.)
- **NG-6:** 代码仓库深度集成 (Git commit 自动关联)
- **NG-7:** 自然语言搜索日志
- **NG-8:** 自定义主题或 UI 皮肤

---

## 8. Risks & Open Questions (风险与待决问题)

### 技术风险

| 风险 | 影响 | 缓解措施 |
| --- | --- | --- |
| **Frontend build pipeline** | 项目需引入 Node.js 工具链 (Vite + React)，增加开发环境复杂度 | 使用 Vite 最小化配置；`justfile` 中添加 frontend build 命令 |
| **图片处理性能** | 大尺寸截图的缩略图生成可能阻塞 API 响应 | 使用 Pillow 异步处理；限制上传图片最大尺寸 (10MB) |
| **Vision API 成本** | GPT-4o / Qwen VL 的多模态调用费用较高 | 仅在用户上传图片时触发；提供 provider 选择；显示预估费用 |
| **SQLite 并发** | FastAPI 异步 + SQLite 可能有写锁冲突 | 使用 WAL mode；BackgroundTasks 串行处理写操作 |

### 待决问题

- **OQ-1:** Frontend 框架最终选择 React 还是 Vue？(建议 React，生态更成熟)
- **OQ-2:** 是否需要 Alembic 做数据库迁移管理？(建议 Phase 1 直接 `create_tables()`，Phase 2 引入 Alembic)
- **OQ-3:** 图片缩略图生成使用 Pillow 还是其他库？
- **OQ-4:** FastAPI 静态文件服务是否足够，还是需要 Nginx 代理？(本地单用户场景下 FastAPI 足够)

---

## Appendix: User Story Dependencies (用户故事依赖关系)

```
US-001 (项目初始化)
  ├── US-002 (RunAccount)
  ├── US-003 (Task)
  │     └── US-006 (State Tagging) ─── depends on US-003 + US-004
  ├── US-004 (Text Input)
  │     └── US-005 (Image Paste) ─── depends on US-004
  └── US-007 (Timeline & Export) ─── depends on US-004 + US-005 + US-006

US-008 (AI Vision) ─── depends on US-005
  ├── US-009 (Review Queue) ─── depends on US-008
  ├── US-010 (Review Flow) ─── depends on US-009
  └── US-011 (Auto-confirm) ─── depends on US-008

US-012 (Enhanced Task View) ─── depends on US-007
US-013 (Rich Export) ─── depends on US-007
US-014 (Keyboard Shortcuts) ─── depends on US-010
```
