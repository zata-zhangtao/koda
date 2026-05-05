# Prompt 管理

## 总览

当前仓库里的长 Prompt 文案已经从服务编排代码中抽离出来，放在 `backend/dsl/prompts/templates/`；Python builder 负责准备上下文、执行截断、选择条件分支，再把变量渲染进模板。

这里说的“长 Prompt 文案”主要指主流程的人类可读 Prompt。像提交信息生成这类只要求输出单行结构化结果的 helper prompt，也可以放在 prompt 层，但建议单独放在 `backend/dsl/prompts/templates/helpers/`，不要和主流程模板混在同一级目录。

如果你要修改 AI 行为，通常有两个落点：

- `backend/dsl/prompts/templates/`：修改 Prompt 文案结构
- `backend/dsl/services/codex_runner.py` 与 `backend/dsl/prd_sources/infrastructure/draft_suggestion_adapter.py`：修改上下文来源、截断逻辑、条件分支和调用编排

## Prompt 位置

| 位置 | 用途 | 触发时机 |
| --- | --- | --- |
| `backend/dsl/prompts/templates/implementation_prompt.txt` + `build_codex_prompt` | 代码实现 Prompt | 点击“开始执行”后 |
| `backend/dsl/prompts/templates/completion_prompt.txt` + `build_codex_completion_prompt` | 完成阶段说明文本（非执行入口） | 点击“Complete”后 |
| `backend/dsl/prompts/templates/prd_prompt.txt` + `build_codex_prd_prompt` | PRD 生成 Prompt | 点击“开始任务”后 |
| `backend/dsl/prompts/templates/review_prompt.txt` + `build_codex_review_prompt` | 自检 Prompt | 实现完成后 |
| `backend/dsl/prompts/templates/review_fix_prompt.txt` + `build_codex_review_fix_prompt` | 自动回改 Prompt | 自检发现 blocker 后 |
| `backend/dsl/prompts/templates/lint_fix_prompt.txt` + `build_codex_lint_fix_prompt` | Lint 定向修复 Prompt | post-review lint 失败后 |

## Prompt 输入来源

### 代码实现 Prompt

`build_codex_prompt` 会使用：

- `task_title`
- 最近最多 10 条 `DevLog.text_content`
- 可选的 `worktree_path`
- 当前任务已落盘 PRD 的仓库相对路径（若存在）
- 当前任务已落盘 PRD 的 Markdown 正文（若存在，超长时会截断后注入）

这些输入决定了 Codex 是否能理解当前需求上下文。

当前实现 Prompt 还会显式要求：

- 开始编码前先阅读当前任务 PRD，并默认以 PRD 作为实现范围、验收标准和约束条件的主合同
- 如果 PRD 与历史日志摘要不一致，以当前任务 PRD 文件为准
- 如果实际编码时发现明显更优于 PRD 当前写法的实现方式，可以采用更优方案，但不得偷换需求范围
- 一旦采用了更优方案，必须同步更新任务 PRD，使 PRD 与最终实现保持一致

### PRD 生成 Prompt

`build_codex_prd_prompt` 会使用：

- 任务标题
- 最近最多 5 条日志
- 最近日志里解析出的本地图片/附件路径
- 任务 ID
- worktree 路径说明
- 强制要求的 PRD 输出合同

它不仅要求生成文案，还要求：

- 在顶部元数据区域保留 `原始需求标题`
- 同时输出 `需求名称（AI 归纳）`
- 在上下文不足时回退为原始标题的规范化版本
- 当 PRD 仍有待确认决策时，输出固定章节 `## 0. 待确认问题（结构化）`
- 该章节必须包含 fenced `json` code block，顶层键为 `pending_questions`
- 每个待确认问题至少包含 `id`、`title`、`required`、`recommended_option_key`、`recommendation_reason`、`options`
- 如果上下文中出现 `Attached local files:`，需要显式检查这些本地媒体文件，或在无法完整解析时至少吸收其文件名与存在性
- 真正把 PRD 写到任务专属文件 `tasks/YYYYMMDD-HHMMSS-prd-<requirement-slug>.md`
- `<requirement-slug>` 必须是语义化、非随机、中文输入兼容的安全文件名；如果模型先写错，runner 会做自动修正

### 完成阶段说明文本

`build_codex_completion_prompt` 会使用：

- `task_title`
- 最近最多 8 条 `DevLog.text_content`
- 必填的 `worktree_path`

这些输入决定了完成阶段说明是否与真实 Git 自动化保持一致。

## Prompt 输出副作用

当前 Prompt 不是“只返回一段文本”这么简单，它们会影响真实工作流：

- 决定 runner CLI（`codex` / `claude`）在什么目录运行
- 决定 Prompt 是通过 argv 还是 `stdin` 传给 CLI（当前内置执行器统一走 `stdin`，以规避超长参数失败）
- 决定是否会生成 PRD 文件
- 决定点击 `Complete` 后后台 Git 自动化如何描述 `commit`、`rebase`、Codex 冲突修复与 merge
- 决定哪些内容被写回 `DevLog`
- 决定任务阶段是否推进或回退

因此任何 Prompt 改动都应该被当成业务逻辑改动，而不是普通文案调整。

## 修改原则

### 保持输入稳定

- 不要随意改变任务标题、日志摘要、worktree 说明的拼接位置
- 如果新增上下文字段，要确认前端和后端是否都能稳定提供

### 保持输出可观察

- Prompt 变更后，要确保当前 runner 的关键输出仍然会写回 `DevLog`
- PRD Prompt 变更后，要确认前端仍能通过 `tasks/YYYYMMDD-HHMMSS-prd-<requirement-slug>.md` 读取结果，并能解析结构化待确认问题块

### 保持工程约束

当前实现 Prompt 已经内嵌了一些工程约束，例如：

- Python 使用 Google Style Docstring
- 文件读写显式指定 `encoding="utf-8"`
- 输出需要总结修改文件和注意事项

这些约束如果被移除，项目一致性会明显下降。

## 推荐变更流程

1. 优先判断是改“文案”还是改“逻辑”
2. 文案改动优先修改 `backend/dsl/prompts/templates/*.txt`
3. 逻辑改动修改 `backend/dsl/services/codex_runner.py` 或 `backend/dsl/prd_sources/infrastructure/draft_suggestion_adapter.py`
4. 为 Prompt 合同补充或更新单元测试
5. 重新启动或重新触发对应任务
6. 观察 `/tmp/koda-<task短ID>.log`
7. 检查 `DevLog` 时间线是否仍然完整
8. 如果改的是 PRD Prompt，检查 `tasks/YYYYMMDD-HHMMSS-prd-<requirement-slug>.md` 是否按预期生成，且顶部包含 `原始需求标题`、`需求名称（AI 归纳）` 和结构化待确认问题块（如适用）
9. 如果故意让模型先写出旧的 task-id 前缀文件名或随机后缀文件名，确认后端日志中出现自动修正记录
10. 更新本文档与[Codex 自动化](../guides/codex-cli-automation.md)

## 当前缺口

### 尚未具备的治理能力

- Prompt 独立文件化
- Prompt 版本号
- Prompt A/B 对比
- 针对 Prompt 的自动化评测
- Golden dataset 回归验证

!!! note "后续建议"
    当自动化链路继续扩展到测试代理、PR 代理和验收代理时，建议把 Prompt 从 Python 字符串迁移到单独目录，并建立版本化管理。
