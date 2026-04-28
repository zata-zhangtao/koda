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
5. 在任务详情选择“从 tasks/pending 选择”，确认详情 action 区仍显示“使用选中的 PRD”；刷新页面后仍恢复 pending 来源草稿与已选文件，再点击后确认 pending Markdown PRD 会被移动到目标 workspace 的 `tasks/YYYYMMDD-HHMMSS-prd-<slug>.md`，原 pending 文件消失，任务进入 `prd_waiting_confirmation`
6. 在任务详情选择“手动导入 PRD”，分别验证“上传 `.md` 文件”和“粘贴 Markdown 文本 / `.md` 文件”两条路径；确认目标 PRD 都会写入 `tasks/YYYYMMDD-HHMMSS-prd-<slug>.md`，并能通过现有 PRD 面板读取
7. 在创建面板选择“从 tasks/pending 选择”，确认列表项同时显示标题/文件名、大小和 Updated 时间戳；准备两个 mtime 与文件名前置时间戳相反的 pending PRD，确认下拉默认选择的是 `YYYYMMDD-HHMMSS` 前置时间戳最新的文件，而不是最近修改的文件；点击“生成草稿”后 title 与 description 被预填，未勾选确认项时不能创建 task
8. 修改 pending PRD 文件后，使用旧草稿点击“Create from PRD”，确认接口返回冲突错误并提示刷新草稿，不应显示创建成功
9. 在创建面板选择“手动导入 PRD”，分别验证上传 `.md` 与粘贴 Markdown；确认 AI/回退预填 title 与 description，用户勾选确认后创建 task，并进入 `prd_waiting_confirmation`
10. 对启用“PRD 就绪后自动确认并直接开始执行”的任务重复 pending/import，确认 PRD staging 后直接进入实现链路
11. 当上下文很少时，确认 `需求名称（AI 归纳）` 仍然非空，并回退为原始标题的规范化版本
12. 点击“开始执行”，观察时间线是否实时写入 Codex 输出
13. 检查阶段是否推进到 `self_review_in_progress`
14. 让第一轮 self-review 故意返回 blocker，确认时间线出现“review -> 自动回改 -> review”的顺序与摘要，而不是立刻进入 `changes_requested`
15. 若 self-review 闭环通过，确认任务自动推进到 `test_in_progress`，并开始写入 pre-commit lint 日志
16. 让第一次 pre-commit 执行故意触发 auto-fix hook，确认时间线出现“首次 lint -> 自动重跑 -> lint 通过/失败”的顺序
17. 若 lint 在自动重跑后仍失败，确认时间线出现“lint -> AI lint-fix -> lint”的顺序，而不是立刻进入 `changes_requested`
18. 若 lint 闭环最终通过，确认任务停留在 `test_in_progress` 并等待用户点击 `Complete`
19. 点击 `Complete` 后，确认前端先展示最多 5 项 completion checklist；未勾选全部展示项时最终提交按钮禁用，勾选后才会发送 `/complete` 且请求体包含 `checklist_mode`、`checklist_signature`、`confirmed_checklist_item_ids`
20. 人工刷新任务列表或详情时，确认前端以 `is_codex_task_running` 判断是否仍在执行；idle 的 `test_in_progress` 任务应显示 `Complete`，但 open 的 `pr_preparing` 会继续触发 dashboard 轮询，直到任务列表自动观察到最终 `done / CLOSED` 快照
21. 修改 PRD acceptance checklist 或用旧 signature 重放 `/complete`，确认后端返回 refresh-required 冲突；漏传任一展示 item id 时返回 422
22. 若 review 或 lint 连续 blocker 直到超出自动回改上限，确认任务才进入 `changes_requested`，且日志/通知明确写明“需要人工介入”
23. 在桌面宽屏下点击左侧需求卡片区的折叠按钮，确认左列变为窄栏，显示恢复按钮和当前视图卡片数，详情区获得更多横向空间；再次点击恢复后，项目筛选、选中任务和已打开的创建面板草稿保持不变，且不会触发任务列表重新加载
24. 在移动宽度下重复折叠/恢复，确认页面保持单列，需求列表主体隐藏但顶部恢复按钮可见，没有文本重叠或不可恢复状态
### Sidecar Q&A

1. 选择一个处于 `prd_waiting_confirmation` 的任务，切换到底部的“问 AI”通道
2. 提交一个澄清问题，确认页面出现一条用户消息和一条 `pending` 的 AI 回复
3. 在回复生成期间，确认任务的 `workflow_stage` 和 `is_codex_task_running` 没有因为提问而变化
4. 在 PRD 文件存在时，确认回答能引用当前 PRD 语境；在 PRD 文件不存在时，确认回答优雅降级且不会整条问答失败
5. 在同一任务上连续点击发送，确认当前已有 `pending` 回复时第二次提交会被拦截
6. 在“问 AI”通道点击“整理最近一次结论为反馈草稿”，确认只是把文本带入反馈 composer，而不是自动写入 `DevLog`
7. 手动发送该反馈草稿后，再确认只有这一步才会影响主执行链路
8. 把任务推进到 `CLOSED` 后重新打开详情，确认历史 sidecar Q&A 仍可查看，且“整理最近一次结论为反馈草稿”仍可用；新提问与正式反馈发送在前端被禁用，若直接调后端日志/附件入口也会被拒绝
9. 分别走“验收通过”“无 worktree 的 Complete 尝试”“放弃需求”三条归档相关动作，确认“验收通过”会打开 completion checklist 而不是直接调用 `PUT /stage` 关单；无 worktree 任务不会显示或执行 Complete，直接调用 `PUT /api/tasks/{id}/status` 提交 `CLOSED` 或调用 `PUT /api/tasks/{id}/stage` 提交 `done` 都会返回 422；Abandon 仍可用，且时间线里仍能看到对应的内部留痕日志
10. 对已归档任务尝试上传图片或附件，确认接口被拒绝后 `data/media/` 不会留下孤立文件
11. 模拟 sidecar 回复超时或后台中断后刷新详情，确认旧 `pending` 回复会转为 `failed`，随后允许再次提问；并发提交提问时仍只能保留 1 条 `pending` 回复

### 项目与 Worktree

1. 创建 `Project`
2. 在 Project 面板点击“选择资源”，确认候选列表不显示 Git 已追踪文件，也不显示 `__pycache__`、`.pytest_cache`、coverage、logs、dist/build/site 等纯生成产物；只显示需要策略选择的本地 untracked/ignored 资源，包括 `.env*` secret copy 警告、数据库/上传目录 shared mutable link 警告、`node_modules` / `.venv` large dependency 警告，以及未知 untracked/ignored 的 manual review 提示。
3. 分别验证 `Use defaults`、自定义 `Copy` / `Link` / `Skip`、`Skip for now` 三条路径；`Skip for now` 的 Project 应显示需要 Worktree Resource confirmation，并且不能作为 task start 的有效候选。
4. 在仓库中准备 `.env.local` 和 `data/app.sqlite`，启动绑定该 Project 的任务，确认 worktree 中 `.env.local` 是真实复制文件，`data/app.sqlite` 或 `data/` 按策略链接，并且 `Task.worktree_path` 只在准备成功后落库。
5. 在仓库中准备一个同时包含 Git 已追踪文件和本地 runtime 子目录的 `.claude` 目录，把 `.claude` 配成 `Link`，把 `.claude/runtime` 配成 `Link`，确认任务启动不会因为已检出的 `.claude` 目录失败，且 `.claude/runtime` 仍被链接。
6. 人为制造 materialization 失败（例如在目标 worktree 预置未跟踪冲突文件，或删除 required `.env`），确认任务启动失败、不会写入 `Task.worktree_path`，错误中包含原始失败与 rollback 结果，本地 worktree/branch 被清理或明确提示需要手动清理。
7. 执行 WebDAV business sync 导出/恢复，确认 `worktree_resource_policy_json` 和本地 runtime 资源内容不会进入业务快照，恢复到已有 Project 时保留本机已有策略。
8. 将任务绑定到该项目
9. 在任务仍处于 `backlog` 时打开 `Requirement Revision`，确认可以修改 `project_id`，保存后详情区立即回显新的关联项目，并追加一条项目改绑审计日志
10. 对未启动的 backlog 任务点击 `Delete`，确认任务和关联日志/附件从列表中直接消失，不进入 `Changes` 归档视图
11. 启动任务，确认是否生成 `worktree_path`，且新目录位于项目父目录的 `task/` 下
12. 对 backlog 项目任务使用 `tasks/pending/*.md` PRD 启动，确认 pending 列表来自项目仓库模板池；创建或复用 task worktree 后，系统会把 worktree 中同名 pending 副本移动到 worktree 的 `tasks/` 根目录，项目仓库里的 pending 模板仍保留；如果 worktree 中没有同名副本，则只把项目模板内容写入 worktree 的 `tasks/` 根目录
13. 用一个明确例子核对路径规则：若项目仓库是 `/Users/zata/code/my-app`，则新 worktree 应落在 `/Users/zata/code/task/my-app-wt-12345678`
14. 在绑定项目中临时放置一个不支持 `--base` 的旧式 `scripts/git_worktree.sh`，启动任务仍应走 Koda 内置创建流程并生成上述默认路径；只有 `scripts/new-worktree.sh` / `scripts/create-worktree.sh` 这类显式接收目标路径的脚本才可覆盖创建命令
15. 任务启动后再次打开编辑面板，确认项目选择器变为锁定态，并明确提示“任务开始后项目绑定已锁定”
16. 验证 `open-in-editor` 是否能打开 `worktree_path` 指向的真实目录，并确认兼容别名 `open-in-trae` 仍可调用
17. 对已启动任务点击 `Destroy`，确认必须填写至少 5 个字符的销毁原因才能提交
18. 提交 destroy 后，确认任务进入 deleted history 且在 `Completed` 视图可见，详情区显示 `destroy_reason` / `destroyed_at`，时间线追加一条 `Requirement Destroyed` 系统日志
19. 若任务启动前已有后台自动化或 worktree，确认 destroy 完成后不会再显示“打开 Worktree”入口，后台运行态已清除，且本地不会残留孤立的 task 目录或语义 task 分支
20. 对 `Abandoned` 任务确认详情区可见 `Restore`；恢复后任务回到 `Active` 视图，backlog 任务回到 `PENDING`，已启动任务回到 `OPEN`
21. 对已启动且处于 `Abandoned` 的任务确认仍可直接走 `Destroy`，不必先恢复
22. 手动 merge 并删除任务分支，确认详情页进入“缺失分支待确认”；点击“确认 Complete”后同样先展示 `manual_complete` checklist，未全选不能提交，全选后 `/manual-complete` 写入 checklist confirmation 与人工完成审计日志

### 远程需求分支与 PR handoff

1. 在项目面板启用 `GitHub-backed requirement branches`，填写 remote 名称、分支前缀和 GitHub 仓库全名
2. 创建绑定该项目的需求卡片，确认远程仓库出现 `task/<task_id[:8]>-<slug>` 分支
3. 在远程分支中确认 `.koda/requirements/<task_id>.json` 存在，且包含标题、摘要、阶段、分支名和基底分支
4. 点击“开始任务”，确认 worktree 检出的分支是 `Task.task_branch_name`，不是重新生成的新分支
5. 在 worktree 中修改文件后点击 `Push Progress`，确认远程分支推进，且 GitHub PR 不会被创建
6. 在另一台机器或清空本地任务记录后点击项目 `Sync Remote`，确认 manifest-backed 任务会被导入本地卡片列表
7. 对远程协作任务点击 `Complete / Create PR`，确认任务分支被 push，GitHub PR 被创建或复用，任务进入 `acceptance_in_progress` 而不是直接关闭
8. PR merge 后点击 `Sync PR`，确认任务进入 `done / CLOSED`
9. 人为让远程任务分支在本地 sync cursor 之外前进，再点击 `Push Progress`，确认接口返回冲突而不是覆盖远程更新
10. 在未配置 `KODA_GITHUB_TOKEN` / `GITHUB_TOKEN` / `GH_TOKEN` 但本机 `gh auth status --active` 成功的环境中重复第 7-8 步，确认 PR 创建、复用和状态同步走 `gh` CLI fallback
11. 在未配置 token 且 `gh` 未安装或未登录的环境中点击 `Complete / Create PR`，确认错误提示同时说明 token 路径和 `gh auth login` 路径，且任务分支 push 逻辑不被误描述为需要 token

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
