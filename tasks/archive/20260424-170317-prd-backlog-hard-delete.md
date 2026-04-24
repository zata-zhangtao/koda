# PRD: Backlog Draft Hard Delete

## 0. Metadata

- 原始需求标题: 未启动任务删除应直接抹去
- 需求名称（AI 归纳）: Backlog Draft Hard Delete
- 日期: 2026-04-24
- 状态: Delivered

## 1. Background

未启动的 backlog 任务没有 worktree、分支、PRD 执行链路或自动化副作用。旧行为把这类任务通过 `lifecycle_status=DELETED` 放进 `Changes`，会让草稿垃圾和真正需要保留历史的 abandon/delete 记录混在一起。

## 2. Goal

让普通 `Delete` 只用于未启动 backlog 草稿的硬删除：删除 `Task` 及其本地子记录，不进入 `Changes`；已启动任务继续通过 `Destroy` 清理 worktree/分支并保留销毁审计；`Abandon` 继续进入 `Changes` 并支持 `Restore`。

## 3. Delivered Behavior

- 新增 `DELETE /api/tasks/{task_id}`，仅允许未启动任务硬删除。
- 硬删除会移除任务、日志、调度、通知、QA、artifact 等 ORM 子记录。
- 硬删除会显式移除涉及该任务的 `TaskReferenceLink`。
- 硬删除会清理日志图片字段和附件 Markdown 链接中引用的本地媒体文件。
- 前端 `Delete` 按钮改为调用硬删除接口，成功后停留在 `Active`。
- 已启动任务仍只能走 `Destroy`；`CLOSED`、`DELETED`、`ABANDONED` 等归档/历史态任务不能被硬删除。
- 需求改动仍留在 `Active`，不进入 `Changes`。

## 4. Validation

- `uv run pytest tests/test_task_service.py tests/test_tasks_api.py -q` -> `81 passed`
- `uv run pytest -q` -> `294 passed`
- `npm test` -> passed
- `npm run build` -> passed
- `just docs-build` -> passed
- `git diff --check` -> passed

## 5. Notes

全量 pytest 暴露了一个既有测试隔离问题：Sidecar Q&A 的 no-PRD 测试会回退读取仓库 `tasks/archive/`。本次一并把该测试隔离到 `tmp_path`，避免随机 task id 前缀撞到历史 PRD 文件。
