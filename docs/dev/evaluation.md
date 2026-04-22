# 评测与验证

## 总览

当前仓库已经有基础验证手段，但还没有形成完整的 AI 评测体系。

可以把现状拆成两层：

- **工程验证**：测试、构建、文档检查
- **AI 评测**：目前仍以人工观察与任务时间线回看为主

## 当前可执行的验证项

| 类型 | 命令 | 说明 |
| --- | --- | --- |
| Python 测试 | `uv run pytest` | 当前主要覆盖日志器配置 |
| Pre-commit Lint | `uv run pre-commit run --all-files` | 检查仓库级 hook、Ruff 与本地一致性校验 |
| 前端构建 | `cd frontend && npm run build` | 检查 TypeScript 与打包是否通过 |
| 文档构建 | `just docs-build` | 严格模式构建 MkDocs |
| 本地联调 | `just dsl-dev` | 人工验证任务、日志、附件与阶段流转 |

## 已存在的测试资产

### `tests/test_logger.py`

当前默认 Pytest 用例主要覆盖：

- `TimedRotatingFileHandler` 是否存在
- 日志切分后缀是否按天设置

### `ai_agent/examples/test_utils_model_loader.py`

这个文件更像模型配置加载器的示例或手动验证脚本，而不是默认纳入主测试套件的 CI 级用例。

## 推荐的手工验证清单

### 需求卡片主链路

1. 创建一个任务
2. 为任务补充几条日志
3. 点击“开始任务”，确认是否生成 PRD
4. 检查 PRD 顶部是否同时包含 `原始需求标题` 与 `需求名称（AI 归纳）`
5. 在任务详情选择“从 tasks/pending 选择”，确认 pending Markdown PRD 会被移动到 `tasks/prd-{task_id[:8]}-<slug>.md`，原 pending 文件消失，任务进入 `prd_waiting_confirmation`
6. 在任务详情选择“手动导入 PRD”，分别验证“上传 `.md` 文件”和“粘贴 Markdown 文本 / `.md` 文件”两条路径；确认目标 PRD 都会写入 `tasks/prd-{task_id[:8]}-<slug>.md`，并能通过现有 PRD 面板读取
7. 对启用“PRD 就绪后自动确认并直接开始执行”的任务重复 pending/import，确认 PRD staging 后直接进入实现链路
8. 当上下文很少时，确认 `需求名称（AI 归纳）` 仍然非空，并回退为原始标题的规范化版本
9. 点击“开始执行”，观察时间线是否实时写入 Codex 输出
10. 检查阶段是否推进到 `self_review_in_progress`
11. 让第一轮 self-review 故意返回 blocker，确认时间线出现“review -> 自动回改 -> review”的顺序与摘要，而不是立刻进入 `changes_requested`
12. 若 self-review 闭环通过，确认任务自动推进到 `test_in_progress`，并开始写入 pre-commit lint 日志
13. 让第一次 pre-commit 执行故意触发 auto-fix hook，确认时间线出现“首次 lint -> 自动重跑 -> lint 通过/失败”的顺序
14. 若 lint 在自动重跑后仍失败，确认时间线出现“lint -> AI lint-fix -> lint”的顺序，而不是立刻进入 `changes_requested`
15. 若 lint 闭环最终通过，确认任务停留在 `test_in_progress` 并等待用户点击 `Complete`
16. 人工刷新任务列表或详情时，确认前端以 `is_codex_task_running` 而不是单纯的 `workflow_stage` 判断是否仍在执行；idle 的 `test_in_progress` 任务应显示 `Complete`
17. 若 review 或 lint 连续 blocker 直到超出自动回改上限，确认任务才进入 `changes_requested`，且日志/通知明确写明“需要人工介入”

### Sidecar Q&A

1. 选择一个处于 `prd_waiting_confirmation` 的任务，切换到底部的“问 AI”通道
2. 提交一个澄清问题，确认页面出现一条用户消息和一条 `pending` 的 AI 回复
3. 在回复生成期间，确认任务的 `workflow_stage` 和 `is_codex_task_running` 没有因为提问而变化
4. 在 PRD 文件存在时，确认回答能引用当前 PRD 语境；在 PRD 文件不存在时，确认回答优雅降级且不会整条问答失败
5. 在同一任务上连续点击发送，确认当前已有 `pending` 回复时第二次提交会被拦截
6. 在“问 AI”通道点击“整理最近一次结论为反馈草稿”，确认只是把文本带入反馈 composer，而不是自动写入 `DevLog`
7. 手动发送该反馈草稿后，再确认只有这一步才会影响主执行链路
8. 把任务推进到 `CLOSED` 后重新打开详情，确认历史 sidecar Q&A 仍可查看，且“整理最近一次结论为反馈草稿”仍可用；新提问与正式反馈发送在前端被禁用，若直接调后端日志/附件入口也会被拒绝
9. 分别走“验收通过”“无 worktree 的完成”“删除需求”三条归档动作，确认操作本身不会因额外写反馈而报错，且时间线里仍能看到对应的内部留痕日志
10. 对已归档任务尝试上传图片或附件，确认接口被拒绝后 `data/media/` 不会留下孤立文件
11. 模拟 sidecar 回复超时或后台中断后刷新详情，确认旧 `pending` 回复会转为 `failed`，随后允许再次提问；并发提交提问时仍只能保留 1 条 `pending` 回复

### 项目与 Worktree

1. 创建 `Project`
2. 将任务绑定到该项目
3. 在任务仍处于 `backlog` 时打开 `Requirement Revision`，确认可以修改 `project_id`，保存后详情区立即回显新的关联项目，并追加一条项目改绑审计日志
4. 启动任务，确认是否生成 `worktree_path`，且新目录位于项目父目录的 `task/` 下
5. 用一个明确例子核对路径规则：若项目仓库是 `/Users/zata/code/my-app`，则新 worktree 应落在 `/Users/zata/code/task/my-app-wt-12345678`
6. 任务启动后再次打开编辑面板，确认项目选择器变为锁定态，并明确提示“任务开始后项目绑定已锁定”
7. 验证 `open-in-editor` 是否能打开 `worktree_path` 指向的真实目录，并确认兼容别名 `open-in-trae` 仍可调用
8. 对已启动任务点击 `Destroy`，确认必须填写至少 5 个字符的销毁原因才能提交
9. 提交 destroy 后，确认任务进入 deleted history 且在 `Completed` 视图可见，详情区显示 `destroy_reason` / `destroyed_at`，时间线追加一条 `Requirement Destroyed` 系统日志
10. 若任务启动前已有后台自动化或 worktree，确认 destroy 完成后不会再显示“打开 Worktree”入口，且后台运行态已清除
11. 对 `Abandoned` 任务确认详情区可见 `Restore`；恢复后任务回到 `Active` 视图，backlog 任务回到 `PENDING`，已启动任务回到 `OPEN`
12. 对已启动且处于 `Abandoned` 的任务确认仍可直接走 `Destroy`，不必先恢复

### 媒体与导出

1. 上传图片或附件
2. 检查 `data/media/` 是否生成文件
3. 检查前端是否能正常展示
4. 测试 `chronicle/export` 导出的 Markdown 是否包含对应记录

## AI 评测现状

当前还没有：

- Golden dataset
- Prompt 回归测试
- 自动化评分脚本
- PRD 质量评测
- Codex 输出结构化审计

这意味着 AI 效果的验证目前依赖：

- 任务时间线回看
- `/tmp/koda-<task短ID>.log`
- 人工检查生成的 PRD 与代码结果

## 后续建议

如果要把 Koda 演化成更稳定的自动化研发平台，建议下一步补齐：

1. PRD 生成的黄金样例集
2. Prompt 级回归测试
3. 针对 `WorkflowStage` 推进的端到端场景测试
4. 对 `codex_runner` 的最小集成测试

!!! note "结论"
    当前仓库已经具备工程验证底座，但 AI 评测体系仍处于空白阶段。本页的价值是把“哪些已经可验证，哪些还没有”说清楚。
