# AI 资产

## 总览

这个仓库里的 AI 相关资产分成两层：

- **主业务链路中的自动化能力**：围绕任务卡片调用可配置 runner CLI（`codex` / `claude`）
- **旁路工具能力**：围绕模型注册表、凭据解析，以及任务内独立问答的聊天模型分支

两者都与 AI 有关，但职责不同，不能混为一谈。

## 已识别 AI 资产

| 位置 | 类型 | 作用 |
| --- | --- | --- |
| `backend/dsl/services/automation_runner.py` | 统一入口 | API 层使用的执行器无关编排入口 |
| `backend/dsl/services/codex_runner.py` | 自动化编排器 | 构造 Prompt、统一阶段编排、按配置调度 runner |
| `backend/dsl/services/runners/` | CLI 适配层 | Runner 协议、注册中心与 Codex / Claude 实现 |
| `backend/dsl/models/enums.py` | 工作流状态 | 定义 `WorkflowStage` 与 `AIProcessingStatus` |
| `ai_agent/utils/model_loader.py` | 工具库 | 读取模型配置，并为 sidecar Q&A 提供聊天模型实例化能力 |
| `ai_agent/utils/models.json` | 模型注册表 | 声明提供商、模型类别与基础 URL |
| `ai_agent/.env.example` | 配置样例 | 提供 DashScope、OpenRouter 等密钥占位项 |

## 任务流中的 AI 能力

### PRD 生成

`run_codex_prd` 会调用 `build_codex_prd_prompt`，要求当前 runner（默认 `codex`）在 worktree 中生成包含 `原始需求标题`、`需求名称（AI 归纳）` 与结构化待确认问题块（如适用）的 PRD，并写入任务专属文件 `tasks/prd-{task_id[:8]}-<requirement-slug>.md`。该 slug 必须语义化、非随机，并兼容中文输入；若模型先写错文件名，runner 会自动修正。

PRD 也可以不经过 AI 生成：任务详情中的 PRD 来源选择支持从 `tasks/pending/*.md` 移动既有 Markdown PRD，或手动上传 / 粘贴 Markdown PRD。非 AI 来源由 `backend/dsl/prd_sources/` 领域切片处理，最终仍写入同一任务专属 PRD 文件合同，因此后续 PRD 确认、结构化待确认问题解析和编码执行链路保持一致。

### 编码执行

`run_codex_task` 会把任务标题、历史日志和 worktree 路径拼成实现 Prompt，要求当前 runner 在现有项目结构中完成改动，并把结果实时写回 `DevLog`。

### AI 字段预留

`DevLog` 模型中已经包含以下 AI 相关字段：

- `ai_processing_status`
- `ai_generated_title`
- `ai_analysis_text`
- `ai_extracted_code`
- `ai_confidence_score`

这些字段说明项目已经为图片解析、AI 校正和后续多模型工作流预留了数据位，但目前主工作流仍以 Codex 文本执行为主。

## `ai_agent/` 工具层

`ai_agent/utils/model_loader.py` 的定位更像可复用工具模块，而不是 DSL 主请求链路的一部分。它主要完成：

- 读取 `models.json`
- 解析 `api_key_env` 或默认环境变量
- 根据模型名推断提供商
- 创建 `ChatOpenAI` 或 `ChatAnthropic` 等 LangChain 模型实例
- 为任务内独立问答提供 `chat_model` 分支 helper

对于任务内独立问答，当前工程约定是：

- 默认通过 `TASK_QA_BACKEND=chat_model` 走 `model_loader.py`
- `TASK_QA_MODEL_NAME` 与 `TASK_QA_MODEL_TEMPERATURE` 只作用于 sidecar Q&A，不改变主业务链路的 Codex 默认策略
- 任务内 sidecar Q&A 与 `backend/dsl/services/codex_runner.py` 的主执行链路解耦，不共享 `is_codex_task_running` 语义

当前 `models.json` 中已声明的提供商包括：

- `dashscope`
- `openrouter`
- `vectorengine`
- `azhexing`
- `redbox`

## 当前缺口

以下 AI 资产在仓库中还没有形成稳定工程约定：

- 独立的 Prompt 文件目录
- Golden dataset
- 自动化评测脚本
- 面向生产环境的模型路由与回退策略
- 自动化测试代理、PR 代理、验收代理

## 维护建议

- 新增 AI 提供商时，同时更新 `models.json`、`.env.example` 和文档。
- 修改 Prompt 时，优先同步更新[Prompt 管理](prompt-management.md)。
- 新增 AI 工作流前，先明确它属于“业务主链路”还是“旁路工具层”，避免职责混乱。
