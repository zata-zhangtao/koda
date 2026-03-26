# Prompt 管理

## 总览

当前仓库里的 Prompt 还没有独立成模板文件，而是直接写在 Python 代码里。这是一个典型的“先把自动化跑通，再逐步沉淀治理”的状态。

如果你要修改 AI 行为，第一落点不是 `prompts/` 目录，而是 `dsl/services/codex_runner.py`（执行器无关主编排）与 `dsl/services/runners/`（CLI 适配层）。

## Prompt 位置

| 位置 | 用途 | 触发时机 |
| --- | --- | --- |
| `build_codex_prompt` | 代码实现 Prompt | 点击“开始执行”后 |
| `build_codex_completion_prompt` | 完成阶段说明文本（非执行入口） | 点击“Complete”后 |
| `build_codex_prd_prompt` | PRD 生成 Prompt | 点击“开始任务”后 |

## Prompt 输入来源

### 代码实现 Prompt

`build_codex_prompt` 会使用：

- `task_title`
- 最近最多 10 条 `DevLog.text_content`
- 可选的 `worktree_path`

这些输入决定了 Codex 是否能理解当前需求上下文。

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
- 如果上下文中出现 `Attached local files:`，需要显式检查这些本地媒体文件，或在无法完整解析时至少吸收其文件名与存在性
- 真正把 PRD 写到任务专属文件 `tasks/prd-{task_id[:8]}-<english-requirement-slug>.md`

### 完成阶段说明文本

`build_codex_completion_prompt` 会使用：

- `task_title`
- 最近最多 8 条 `DevLog.text_content`
- 必填的 `worktree_path`

这些输入决定了完成阶段说明是否与真实 Git 自动化保持一致。

## Prompt 输出副作用

当前 Prompt 不是“只返回一段文本”这么简单，它们会影响真实工作流：

- 决定 runner CLI（`codex` / `claude`）在什么目录运行
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
- PRD Prompt 变更后，要确认前端仍能通过 `tasks/prd-{task_id[:8]}*.md` 读取结果

### 保持工程约束

当前实现 Prompt 已经内嵌了一些工程约束，例如：

- Python 使用 Google Style Docstring
- 文件读写显式指定 `encoding="utf-8"`
- 输出需要总结修改文件和注意事项

这些约束如果被移除，项目一致性会明显下降。

## 推荐变更流程

1. 修改 `dsl/services/codex_runner.py`
2. 为 Prompt 合同补充或更新单元测试
3. 重新启动或重新触发对应任务
4. 观察 `/tmp/koda-<task短ID>.log`
5. 检查 `DevLog` 时间线是否仍然完整
6. 如果改的是 PRD Prompt，检查 `tasks/prd-{task_id[:8]}-<english-requirement-slug>.md` 是否按预期生成，且顶部包含 `原始需求标题` 与 `需求名称（AI 归纳）`
7. 更新本文档与[Codex 自动化](../guides/codex-cli-automation.md)

## 当前缺口

### 尚未具备的治理能力

- Prompt 独立文件化
- Prompt 版本号
- Prompt A/B 对比
- 针对 Prompt 的自动化评测
- Golden dataset 回归验证

!!! note "后续建议"
    当自动化链路继续扩展到测试代理、PR 代理和验收代理时，建议把 Prompt 从 Python 字符串迁移到单独目录，并建立版本化管理。
