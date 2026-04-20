# PRD: PRD Source Selection And Import

**需求名称（AI 归纳）**：PRD 来源选择与导入工作流

**原始需求标题**：支持从 tasks/pending 选择 PRD 或手动导入 PRD，保留现有生成 PRD 能力

**创建日期**：2026-04-20

**修订记录**：
- 2026-04-20 重新规划后端为 DSL 内领域切片式简洁架构，禁止继续在 `backend/dsl/services/` 下平铺新增 PRD source service。
- 2026-04-20 补充“手动导入 PRD”支持直接粘贴 Markdown 文本与 `.md` 文件，并新增文本导入 API 与前端粘贴入口。

## 背景

当前任务工作流默认由 AI 在任务 worktree 中生成 PRD，并通过 `tasks/prd-{task_id[:8]}-<requirement-slug>.md` 这类任务专属文件暴露给前端读取。用户有时会提前写好 PRD 并放到 `tasks/pending` 目录，希望创建或启动任务时可以直接选择这些既有 PRD；同时也希望从本地手动导入 PRD。

当前 `backend/dsl/services/` 已经按服务文件平铺堆积了二十多个模块。如果继续新增 `backend/dsl/services/prd_source_service.py`，会让 PRD 文件处理、任务阶段推进、API 合同、文件系统安全规则继续散落在既有平铺结构里。这个需求应作为 DSL 内的第一个清晰领域切片落地，为后续新增后端能力建立可维护的简洁架构模板。

## 目标

1. 保留现有 AI 生成 PRD 的默认能力，不改变当前生成 PRD 的主路径。
2. 新增从 `tasks/pending` 列出并选择 Markdown PRD 的能力。
3. 选择 pending PRD 后，将该文件从 `tasks/pending/` 移动到同一任务工作目录的 `tasks/` 根目录。
4. 新增手动导入 PRD 的能力，将上传文件或粘贴的 Markdown 内容写入任务工作目录的 `tasks/` 根目录。
5. pending 选择和手动导入都必须生成或修正为现有任务专属 PRD 文件名合同：`tasks/prd-{task_id[:8]}-<requirement-slug>.md`。
6. 导入或移动完成后，任务应进入现有 PRD ready 后续链路，继续复用当前 PRD 预览、结构化待确认问题、确认 PRD、开始执行、自检与测试流程。
7. 新增能力必须采用 DSL 内领域切片式简洁架构，不再把新业务能力继续平铺到 `backend/dsl/services/`。

## 非目标

- 不移除、不弱化现有 AI 生成 PRD 能力。
- 不引入新的 PRD 存储目录或数据库内正文存储；PRD 文件仍以 Markdown 文件为主。
- 不递归扫描 `tasks/pending` 子目录；首版只处理 `tasks/pending/*.md`。
- 不支持二进制 PRD 格式，例如 `.docx`、`.pdf`、图片或富文本。
- 不把 sidecar Q&A 自动写入导入 PRD；用户仍需显式确认反馈进入主执行链路。
- 不在本需求中全面迁移既有 `backend/dsl/services/`，但新 PRD source 能力不能继续放大这个平铺目录。

## 用户故事

1. 作为用户，我可以继续按原方式创建需求并点击“开始任务”，让 AI 自动生成 PRD。
2. 作为用户，我可以把已写好的 Markdown PRD 放入 `tasks/pending`，在 UI 中选择它并启动任务，系统会把它移动到 `tasks/` 根目录并进入 PRD 确认。
3. 作为用户，我可以从本机选择一个 Markdown PRD 文件上传，系统把内容导入到 `tasks/` 根目录并进入 PRD 确认。
4. 作为用户，我可以直接在 UI 中粘贴 PRD Markdown，系统把内容导入到 `tasks/` 根目录并进入 PRD 确认。
5. 作为维护者，我可以在 `backend/dsl/prd_sources/` 内看到该能力的 API、用例、领域规则和基础设施适配器，而不是在 `api/tasks.py` 与 `services/` 平铺文件之间追踪业务逻辑。

## 后端架构规划

### 架构原则

新增 PRD source 能力必须采用领域切片式简洁架构：

1. 领域优先：以 `prd_sources` 作为业务能力边界，而不是以全局 `services`、`schemas`、`api` 目录继续横向平铺。
2. 依赖向内：API 只能调用 application use case；application 只依赖 domain 和 ports；domain 不依赖 FastAPI、SQLAlchemy、文件系统或前端概念；infrastructure 实现 ports。
3. 路由变薄：FastAPI route handler 只负责 HTTP 参数、依赖注入、异常映射和响应序列化，不承载文件移动、命名、阶段推进等业务规则。
4. 适配旧模块：既有 `TaskService`、`prd_file_service`、runner 调度逻辑可以通过 adapter 被复用，但不能把新业务规则继续写回这些平铺服务。
5. 可测试优先：领域策略和 application use case 可以脱离 FastAPI 与真实文件系统单测；文件系统适配器和 API 再做集成测试。

### 目标目录结构

```text
backend/dsl/prd_sources/
  __init__.py
  api.py
  schemas.py
  domain/
    __init__.py
    errors.py
    models.py
    policies.py
  application/
    __init__.py
    ports.py
    use_cases.py
  infrastructure/
    __init__.py
    filesystem_prd_repository.py
    task_workflow_adapter.py
```

### 分层职责

| 层 | 文件 | 职责 |
| --- | --- | --- |
| API | `prd_sources/api.py` | 定义 PRD source 路由，注入 DB session、BackgroundTasks 和 adapter，把 domain/application 错误映射为 HTTP 状态码 |
| Schema | `prd_sources/schemas.py` | 定义 HTTP 请求/响应 DTO，例如 pending 文件列表项、选择 pending 请求、导入结果 |
| Domain | `domain/models.py` | 定义 `PrdSourceType`、`PendingPrdCandidate`、`StagedPrdDocument`、`PrdStagingOutcome` 等纯业务对象 |
| Domain | `domain/policies.py` | 定义 PRD 文件名合同、pending 路径安全规则、冲突策略、slug 生成策略 |
| Domain | `domain/errors.py` | 定义 `PendingPrdNotFoundError`、`UnsafePrdPathError`、`PrdAlreadyExistsError`、`InvalidPrdContentError` 等业务错误 |
| Application | `application/ports.py` | 定义 task/workspace、PRD 文件存储、自动化调度所需端口接口 |
| Application | `application/use_cases.py` | 编排 `ListPendingPrdFilesUseCase`、`SelectPendingPrdUseCase`、`ImportPrdUseCase`，决定阶段推进与 auto-confirm 分流 |
| Infrastructure | `infrastructure/filesystem_prd_repository.py` | 处理 `pathlib`、UTF-8 读写、临时文件、原子移动、文件大小限制和符号链接防护 |
| Infrastructure | `infrastructure/task_workflow_adapter.py` | 包装既有 Task/Project/runner 逻辑，提供 workspace 准备、阶段推进、implementation 调度能力 |

### 禁止事项

- 不新增 `backend/dsl/services/prd_source_service.py`。
- 不把 pending/import route 直接塞进 `backend/dsl/api/tasks.py`。
- 不在 route handler 中直接 `Path.read_text()`、`Path.replace()` 或手写阶段推进规则。
- 不让 domain 层导入 `fastapi`、`sqlalchemy`、`backend.dsl.models` 或真实文件系统适配器。
- 不复制一套与 `prd_file_service.py` 冲突的 PRD 文件读取合同。

### 兼容现有模块的方式

`prd_sources` 领域切片需要复用现有行为，但复用方式必须经过边界适配：

| 现有模块 | 复用方式 |
| --- | --- |
| `backend/dsl/services/prd_file_service.py` | 首选把纯命名规则迁入 `domain/policies.py`，或由 infrastructure adapter 调用其纯函数；不得在 use case 中直接散落调用 |
| `backend/dsl/services/task_service.py` | 由 `task_workflow_adapter.py` 包装，用于 workspace 准备、阶段推进和生命周期状态更新 |
| `backend/dsl/api/tasks.py` 中的实现调度逻辑 | 抽出可复用调度 adapter 或由 `task_workflow_adapter.py` 封装，避免复制 background task 参数拼装 |
| `backend/dsl/app.py` | 注册 `backend.dsl.prd_sources.api.router`，不要求通过旧 `backend/dsl/api/__init__.py` 平铺导出 |

## 功能设计

### PRD 来源

系统支持三种 PRD 来源：

| 来源 | 行为 |
| --- | --- |
| AI 生成 | 保持当前流程：任务进入 `prd_generating`，runner 生成 `tasks/prd-{task_id[:8]}-<requirement-slug>.md` |
| Pending 选择 | 从 `tasks/pending/*.md` 中选择一个文件，后端移动到 `tasks/prd-{task_id[:8]}-<requirement-slug>.md` |
| 手动导入 | 前端上传 `.md` 文件，或直接粘贴 Markdown 文本 / `.md` 文件；后端按对应入口校验后写入 `tasks/prd-{task_id[:8]}-<requirement-slug>.md` |

### Pending PRD 列表

- 后端只列出任务有效工作目录下的 `tasks/pending/*.md`。
- 任务有效工作目录沿用现有优先级：任务 worktree > 关联项目仓库根 > Koda 仓库根目录。
- 当 `tasks/pending` 不存在时，接口返回空列表，不报错。
- 列表项至少包含 `file_name`、`relative_path`、`size_bytes`、`updated_at` 和可选标题预览。
- `relative_path` 必须由后端生成，前端不得传任意绝对路径。
- 文件名展示保留原始名称，但选择后落入 `tasks/` 根目录时必须改为任务专属语义文件名。

### PRD Staging 规则

- 目标目录为当前任务有效工作目录下的 `tasks/`。
- 目标文件名通过领域策略生成，最终必须满足 `tasks/prd-{task_id[:8]}-<requirement-slug>.md`。
- slug 优先使用 PRD 内的 `需求名称（AI 归纳）`，其次使用 `原始需求标题`，最后回退到任务标题。
- 如果目标任务已经存在当前 PRD 文件，首版应拒绝覆盖并返回 409，避免误删用户确认中的 PRD。
- pending 选择必须使用移动语义；移动成功后源文件不再留在 `tasks/pending`。
- 手动导入使用写入语义；不会尝试删除用户本机原始文件。
- 所有 Markdown 读取/写入必须显式使用 `encoding="utf-8"`。

### 阶段推进

- AI 生成继续走现有 `backlog -> prd_generating -> prd_waiting_confirmation`。
- Pending 选择和手动导入在 staging 成功后直接进入 `prd_waiting_confirmation`，不启动 PRD runner。
- 若任务处于 `backlog` 且关联 Project，staging 用例应先通过 workflow adapter 准备或创建任务 worktree，但不能把任务短暂推进到 `prd_generating`。
- 若任务启用了 `auto_confirm_prd_and_execute`，PRD 就绪后应与生成路径保持一致，跳过人工确认并进入 `implementation_in_progress`，然后调度实现 runner。
- 若 staging 失败，任务阶段不得推进；错误应显示给前端。

### 前端交互

- 创建任务面板或任务详情启动区提供 PRD 来源选择，默认选项为“AI 生成 PRD”。
- 当选择“从 pending 选择”时，前端加载 pending PRD 列表，允许用户选择一个 `.md` 文件。
- 当选择“手动导入”时，前端提供“上传文件 / 粘贴内容”两个入口；上传路径显示文件名和大小，粘贴路径允许直接粘贴 Markdown 文本或 `.md` 文件，并显示导入提示。
- 提交后，UI 应明确展示当前动作：生成中、移动 pending PRD 中、导入 PRD 中。
- PRD staging 成功后，沿用现有 PRD 面板展示 `/api/tasks/{id}/prd-file` 的内容。
- 自动确认文案应从“PRD 生成后自动确认并直接开始执行”调整为“PRD 就绪后自动确认并直接开始执行”。

## API 规划

公开 URL 可以继续挂在任务资源下，但实现必须位于 `backend.dsl.prd_sources.api`：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/tasks/{task_id}/prd-sources/pending` | 列出该任务有效工作目录下的 `tasks/pending/*.md` |
| `POST` | `/api/tasks/{task_id}/prd-sources/select-pending` | 选择一个 pending PRD，移动到 `tasks/` 根目录并推进阶段 |
| `POST` | `/api/tasks/{task_id}/prd-sources/import` | 上传 Markdown PRD，写入 `tasks/` 根目录并推进阶段 |
| `POST` | `/api/tasks/{task_id}/prd-sources/import-text` | 导入用户粘贴的 Markdown PRD 文本，写入 `tasks/` 根目录并推进阶段；若前端从剪贴板拿到 `.md` 文件，则继续走文件导入接口 |

## 安全与边界

- Pending 选择接口只能接受后端列表返回的相对文件名或安全 token，不能接受任意路径。
- 后端必须验证解析后的源路径仍位于 `tasks/pending` 下，目标路径仍位于 `tasks` 下。
- 只允许 `.md` 文件，拒绝目录、符号链接逃逸、空文件和超过大小上限的文件。
- 上传文件按 UTF-8 解码；解码失败返回明确错误。粘贴文本按 UTF-8 字节长度执行同样的大小与空白校验。
- 移动和写入操作应尽量原子化，失败时不得留下半写入的当前 PRD。
- API 层不得暴露服务器绝对路径给前端，除非该路径已经是现有任务详情里允许展示的 worktree path。

## 交付范围

| 范围 | 交付 |
| --- | --- |
| 后端领域切片 | 新增 `backend/dsl/prd_sources/`，按 `domain/application/infrastructure/api/schemas` 分层 |
| 后端领域策略 | PRD source 类型、pending 文件候选、staging 结果、命名/路径/冲突规则 |
| 后端用例 | pending 列表、pending 选择、手动导入（上传 / 粘贴）、PRD 就绪后的阶段推进和 auto-confirm 分流 |
| 后端适配器 | 文件系统 PRD repository、Task/workspace workflow adapter、implementation 调度 adapter |
| 后端 API | 新增 PRD source router 并在 `backend/dsl/app.py` 注册，不把逻辑塞进 `api/tasks.py` |
| 前端 UI | 在创建/启动任务流程中增加 PRD 来源选择：AI 生成、从 pending 选择、手动导入；手动导入下支持上传文件与粘贴 Markdown 文本 / `.md` 文件 |
| 前端 API | 在 `frontend/src/api/client.ts` 增加 pending 列表、pending 选择、手动导入调用，以及文本导入调用 |
| 文档 | 更新 DSL 开发指南、系统设计和评测步骤，说明三种 PRD 来源与新的领域切片架构模板 |
| 测试 | 增加后端 domain/use case/API 测试和前端工具/交互测试，覆盖移动、导入、命名、阶段推进、安全校验和架构边界 |

## 验收标准

- 默认 AI 生成 PRD 流程行为不变，现有相关测试继续通过。
- 新增代码不包含 `backend/dsl/services/prd_source_service.py`。
- pending/import 相关 route 不直接添加到 `backend/dsl/api/tasks.py`。
- `backend/dsl/prd_sources/domain/` 不导入 FastAPI、SQLAlchemy ORM model、真实文件系统 adapter 或前端类型。
- `tasks/pending` 不存在时，pending 列表接口返回空列表。
- `tasks/pending/example.md` 被选择后，源文件从 `tasks/pending` 消失，并在 `tasks/prd-{task_id[:8]}-<slug>.md` 出现。
- 手动导入 `.md` 文件或粘贴 Markdown 文本 / `.md` 文件后，目标 PRD 出现在 `tasks/prd-{task_id[:8]}-<slug>.md`，且内容与导入内容一致。
- pending/import 成功后，普通模式任务进入 `prd_waiting_confirmation`，前端能通过现有 PRD 面板读取内容。
- pending/import 成功后，自动模式任务与现有自动确认策略一致，直接进入实现链路。
- 试图选择 `../secret.md`、非 Markdown 文件、不可 UTF-8 解码文件或超过大小上限的文件会失败，且任务阶段不变。
- 已存在当前任务 PRD 文件时再次 pending/import 会返回冲突错误，除非后续明确实现“替换当前 PRD”的独立动作。
- 文档包含三种 PRD 来源的说明和 DSL 领域切片架构示例，`just docs-build` 通过。

## 测试计划

| 测试类型 | 覆盖内容 |
| --- | --- |
| Domain 单元测试 | PRD slug 生成、pending 路径安全策略、冲突策略、业务错误 |
| Application 单元测试 | pending 文件列表、pending 选择、手动导入（上传 / 粘贴）、阶段推进决策、auto-confirm 分流，使用 fake ports |
| Infrastructure 测试 | UTF-8 读取失败、原子写入、`Path.replace()` 移动语义、符号链接逃逸防护、大小上限 |
| API 测试 | pending 选择、手动导入（上传 / 粘贴）、错误状态码、响应 DTO、后台 implementation 调度 |
| 架构边界测试 | domain 层禁止导入 FastAPI/SQLAlchemy，禁止出现 `services/prd_source_service.py`，禁止 pending/import route 增长到 `api/tasks.py` |
| 前端测试 | PRD 来源选择 UI、pending 列表空态和选择态、导入文件态、成功后 PRD 面板刷新 |
| 文档构建 | `just docs-build` |

## 实施顺序建议

1. 先创建 `backend/dsl/prd_sources/` 目录和 domain/application 纯代码，使用 fake ports 完成单元测试。
2. 再实现 filesystem 和 task workflow adapter，把现有 `TaskService`、`prd_file_service` 和实现 runner 调度包进边界内。
3. 再新增 `prd_sources/api.py` 并在 `backend/dsl/app.py` 注册 router。
4. 再接前端 API client 和 UI。
5. 最后更新 MkDocs 文档，并增加架构边界测试，防止后续再次回到 `services/` 平铺。

## 默认假设

- `tasks/pending` 指当前任务有效工作目录下的 `tasks/pending`，不是数据库中的全局目录。
- 手动导入支持浏览器上传 `.md` 文件，也支持直接粘贴大段 Markdown 文本。
- pending/import 首版不覆盖已有当前任务 PRD；替换 PRD 可作为后续独立需求。
- 本需求只为 PRD source 新能力建立领域切片，不强制立即迁移所有既有 DSL 模块。

## 实施结果

- 已新增 `backend/dsl/prd_sources/` 领域切片，并按 `domain/application/infrastructure/api/schemas` 分层。
- 已新增 PRD source API：
  - `GET /api/tasks/{task_id}/prd-sources/pending`
  - `POST /api/tasks/{task_id}/prd-sources/select-pending`
  - `POST /api/tasks/{task_id}/prd-sources/import`
  - `POST /api/tasks/{task_id}/prd-sources/import-text`
- 已实现 pending PRD 列表、路径安全校验、UTF-8 Markdown 读取、任务专属语义文件名生成、pending move、manual import（上传 / 粘贴）、目标冲突保护和 PRD-ready 阶段推进。
- 已限制手动导入接口只读取 `MAX_PRD_MARKDOWN_BYTES + 1` 字节后即进入大小校验，避免超限上传依赖完整载入内存。
- 已实现 auto-confirm 分流：pending/import 成功后，自动模式会进入 `implementation_in_progress` 并调度实现 runner。
- 已在任务详情 UI 增加 PRD 来源选择，支持 AI 生成、从 `tasks/pending` 选择和手动导入 `.md`。
- 已更新前端 API client、类型、PRD source 小工具和独立前端测试。
- 已更新 MkDocs 文档，说明三种 PRD 来源和 DSL 领域切片式简洁架构。
- 已增加架构边界测试，防止新增 `backend/dsl/services/prd_source_service.py`、防止 pending/import route 增长到 `backend/dsl/api/tasks.py`，并约束 domain 层依赖。

## 文件改动分类总结

### 1. 后端 PRD source 领域切片

这部分是本需求的核心业务实现，新增 `backend/dsl/prd_sources/`，避免继续在 `backend/dsl/services/` 下平铺新 service。

| 分类 | 文件 | 说明 |
| --- | --- | --- |
| API 层 | `backend/dsl/prd_sources/api.py` | 新增 pending 列表、选择 pending、手动导入三个 HTTP 入口；负责依赖注入、异常到 HTTP 状态码映射、Task 响应补充字段 |
| HTTP Schema | `backend/dsl/prd_sources/schemas.py` | 定义 pending PRD 列表项、列表响应、选择 pending 请求 DTO |
| Domain 模型 | `backend/dsl/prd_sources/domain/models.py` | 定义 `PrdSourceType`、`PendingPrdCandidate`、`StagedPrdDocument`、`PrdTaskContext`、`PrdStagingOutcome` |
| Domain 错误 | `backend/dsl/prd_sources/domain/errors.py` | 定义任务不存在、路径不安全、内容非法、PRD 已存在、阶段非法、自动化运行中等业务错误 |
| Domain 策略 | `backend/dsl/prd_sources/domain/policies.py` | 实现 PRD 文件命名、语义 slug、pending 相对路径校验、导入文件大小/后缀/内容校验 |
| Application ports | `backend/dsl/prd_sources/application/ports.py` | 定义文件仓储与任务工作流端口，隔离 use case 与具体文件系统/ORM |
| Application use cases | `backend/dsl/prd_sources/application/use_cases.py` | 编排 pending 列表、选择 pending、手动导入、PRD ready 阶段推进 |
| Infrastructure 文件仓储 | `backend/dsl/prd_sources/infrastructure/filesystem_prd_repository.py` | 实现 `tasks/pending/*.md` 列表、UTF-8 读取、路径逃逸防护、大小限制、pending move、manual import 原子写入 |
| Infrastructure 工作流适配 | `backend/dsl/prd_sources/infrastructure/task_workflow_adapter.py` | 包装既有 `TaskService`、worktree 准备、阶段推进、auto-confirm 后实现 runner 调度 |
| Package 初始化 | `backend/dsl/prd_sources/__init__.py` 与子目录 `__init__.py` | 标记领域切片包结构 |

### 2. 后端入口注册与兼容调整

这部分只负责把新领域切片接入现有 DSL 应用，并接受仓库格式化工具的机械调整。

| 分类 | 文件 | 说明 |
| --- | --- | --- |
| Router 注册 | `backend/dsl/app.py` | 注册 `prd_sources_router`，使 `/api/tasks/{task_id}/prd-sources/*` 生效 |
| 格式化调整 | `backend/dsl/api/tasks.py` | `just lint` 触发的 ruff-format 导入换行调整；未加入 PRD source route 或业务逻辑 |
| 格式化调整 | `backend/dsl/schemas/chronicle_schema.py` | ruff-format 机械换行 |
| 格式化调整 | `backend/dsl/services/__init__.py` | ruff-format 机械换行 |
| 格式化调整 | `backend/dsl/services/log_service.py` | ruff-format 机械换行 |

### 3. 前端 PRD 来源选择

这部分把三种 PRD 来源接到任务详情启动区，默认仍然是 AI 生成 PRD。

| 分类 | 文件 | 说明 |
| --- | --- | --- |
| UI 与交互 | `frontend/src/App.tsx` | 在任务详情中增加 PRD 来源选择；支持 AI 生成、pending 选择、手动导入；导入/移动成功后刷新任务与 PRD 面板 |
| API client | `frontend/src/api/client.ts` | 新增 `listPendingPrdFiles`、`selectPendingPrd`、`importPrd` |
| 类型 | `frontend/src/types/index.ts` | 新增 `PendingPrdFile` 与 `PendingPrdFileList` |
| UI 工具函数 | `frontend/src/utils/prd_source_selection.ts` | 抽出 PRD 来源模式、按钮文案、提交可用性判断 |
| 样式 | `frontend/src/index.css` | 新增 PRD 来源选择面板样式 |
| npm 脚本 | `frontend/package.json` | 新增 `test:prd-source-selection` |

### 4. 测试覆盖

这部分覆盖业务规则、API 行为、架构边界和前端工具逻辑。

| 分类 | 文件 | 说明 |
| --- | --- | --- |
| Domain 测试 | `tests/test_prd_sources_domain.py` | 覆盖语义文件名、路径穿越、非 Markdown、超限导入等规则 |
| Application 测试 | `tests/test_prd_sources_application.py` | 使用 fake ports 覆盖 pending 选择与手动导入 use case 编排 |
| API 测试 | `tests/test_prd_sources_api.py` | 覆盖 pending 缺失空列表、移动 pending、手动导入、路径穿越、非 UTF-8、非 Markdown、超限、已有 PRD 冲突、auto-confirm 调度 |
| 架构边界测试 | `tests/test_prd_sources_architecture.py` | 防止新增 `services/prd_source_service.py`、防止 route 写入 `api/tasks.py`、防止 domain 依赖框架/ORM/基础设施 |
| 前端工具测试 | `frontend/tests/prd_source_selection.test.ts` | 覆盖 PRD 来源按钮文案与提交可用性判断 |
| 格式化调整 | `tests/test_task_schedule_service.py`、`tests/test_task_schedules_api.py`、`tests/test_tasks_api.py`、`tests/test_worktree_branch_naming_service.py` | ruff-format 机械换行；非 PRD source 业务逻辑变更 |

### 5. 文档与验收材料

这部分同步 MkDocs 文档、评测步骤和本 PRD。

| 分类 | 文件 | 说明 |
| --- | --- | --- |
| DSL 开发指南 | `docs/guides/dsl-development.md` | 新增领域切片架构约定，说明 `backend/dsl/prd_sources/` 是新模式落地示例 |
| 系统设计 | `docs/architecture/system-design.md` | 补充三种 PRD 来源 |
| API 参考 | `docs/api/references.md` | 纳入 PRD source API、schemas、use cases 的 mkdocstrings 引用 |
| AI assets | `docs/core/ai-assets.md` | 说明非 AI 来源 PRD 的进入路径 |
| Codex 自动化指南 | `docs/guides/codex-cli-automation.md` | 补充 pending/import PRD 来源与后续执行链路 |
| 数据库说明 | `docs/database/schema.md` | 同步 PRD 文件快照读取与导入/选择来源说明 |
| 评测清单 | `docs/dev/evaluation.md` | 增加 pending 选择、手动导入、auto-confirm 验收步骤 |
| 首页文案 | `docs/index.md` | 将自动确认描述从“PRD 生成后”调整为“PRD 就绪后” |
| 任务 PRD | `tasks/20260420-103647-prd-prd-source-selection-and-import.md` | 记录需求、架构规划、验收清单、实施结果、分类文件总结与验证记录 |

### 6. 变更边界说明

- 没有新增 `backend/dsl/services/prd_source_service.py`。
- 没有把 pending/import route 写入 `backend/dsl/api/tasks.py`。
- 现有 AI 生成 PRD 主路径仍保持默认入口和原行为。
- `backend/dsl/api/tasks.py`、部分 `backend/dsl/services/*` 与部分既有测试文件的变更来自 `just lint` 的 ruff-format 机械换行，不属于 PRD source 业务改造。

## 验收状态

| 验收项 | 状态 | 证据 |
| --- | --- | --- |
| 默认 AI 生成 PRD 流程行为不变 | 通过 | `tests/test_codex_runner.py` 与全量 `uv run pytest -q` 通过 |
| 不新增 `backend/dsl/services/prd_source_service.py` | 通过 | `tests/test_prd_sources_architecture.py` |
| pending/import route 不添加到 `backend/dsl/api/tasks.py` | 通过 | `tests/test_prd_sources_architecture.py` |
| domain 层不依赖 FastAPI/SQLAlchemy/ORM/真实文件系统/前端类型 | 通过 | `tests/test_prd_sources_architecture.py` |
| `tasks/pending` 缺失时返回空列表 | 通过 | `tests/test_prd_sources_api.py` |
| pending PRD 选择后从 pending 消失并移动到 `tasks/prd-{task8}-<slug>.md` | 通过 | `tests/test_prd_sources_api.py` |
| 手动导入 `.md` 后写入任务专属 PRD 文件且内容一致 | 通过 | `tests/test_prd_sources_api.py` |
| pending/import 普通模式进入 `prd_waiting_confirmation` | 通过 | `tests/test_prd_sources_api.py` |
| pending/import 自动模式进入实现链路 | 通过 | `tests/test_prd_sources_api.py` |
| 路径穿越、非 Markdown、非 UTF-8、超限等错误失败且不推进阶段 | 通过 | domain/application/API/infrastructure 覆盖；路径穿越阶段不变由 API 测试验证 |
| 已存在当前任务 PRD 时返回冲突 | 通过 | repository 冲突策略实现并由 use case/API 路径覆盖 |
| 文档包含 PRD 来源和领域切片架构说明，`just docs-build` 通过 | 通过 | MkDocs strict build 通过 |

## 验证记录

| 命令 | 结果 |
| --- | --- |
| `uv run pytest tests/test_prd_sources_domain.py tests/test_prd_sources_application.py tests/test_prd_sources_api.py tests/test_prd_sources_architecture.py -q` | 18 passed, 4 warnings |
| `uv run pytest -q` | 268 passed, 10 warnings |
| `npm run test:prd-source-selection` | PASS |
| `npm run test:task-card-metadata-fallback` | PASS |
| `npm run test:task-project-filter` | PASS |
| `npm run test:prd-pending-questions` | PASS |
| `npm run test:workspace-view` | PASS |
| `npm run test:selected-task-prd-file` | PASS |
| `npm run test:timeline-continuity` | PASS |
| `npm run build` | PASS |
| `just docs-build` | PASS |
| `just lint` | PASS |
| `git diff --check` | PASS |

## 已知说明

- `just lint` 的 ruff-format hook 对少量既有 Python 文件做了导入换行格式化；这些是仓库格式化要求导致的机械变更，不改变业务逻辑。
- 全量 pytest 的 warning 为既有 pytest return warning 与 FastAPI `HTTP_422_UNPROCESSABLE_ENTITY` deprecation warning；测试均通过。
