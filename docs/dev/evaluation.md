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
4. 点击“开始执行”，观察时间线是否实时写入 Codex 输出
5. 检查阶段是否推进到 `self_review_in_progress`

### 项目与 Worktree

1. 创建 `Project`
2. 将任务绑定到该项目
3. 启动任务，确认是否生成 `worktree_path`，且新目录位于项目父目录的 `task/` 下
4. 用一个明确例子核对路径规则：若项目仓库是 `/Users/zata/code/my-app`，则新 worktree 应落在 `/Users/zata/code/task/my-app-wt-12345678`
5. 验证 `open-in-trae` 是否能打开 `worktree_path` 指向的真实目录

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
