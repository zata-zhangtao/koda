# PRD: Backend DSL Package Move

**需求名称（AI 归纳）**：后端包目录迁移与架构规约固化

**原始需求标题**：新建 backend 文件夹，移动 dsl，并规定后续后端架构

**创建日期**：2026-04-20

## 背景

当前 FastAPI 后端应用位于仓库根目录 `dsl/`，后端代码边界和前端、工具脚本、公共转发服务处于同级。用户要求新增 `backend/` 目录，将现有 `dsl` 移入其中，并明确后续后端开发采用领域分层架构，模块内部采用简洁架构。

## 目标

1. 将根目录 `dsl/` 迁移为 `backend/dsl/`。
2. 将 Python 导入路径和 Uvicorn 启动路径统一更新为 `backend.dsl...`。
3. 更新测试、文档和 MkDocs API 引用，避免保留旧 `dsl...` 导入。
4. 在仓库规范中固化后端架构规则：后端使用领域分层架构，模块内部使用简洁架构。
5. 验证全量 Python 测试和文档构建通过。

## 非目标

- 不重构现有业务模块的内部代码结构。
- 不引入新的框架、依赖或数据库迁移工具。
- 不改变现有 `just dsl-dev`、`uv run python main.py` 等启动命令的用户入口。

## 交付范围

| 范围 | 交付 |
| --- | --- |
| 目录结构 | 新增 `backend/` 包，并将 `dsl/` 移动到 `backend/dsl/` |
| Python 导入 | 后端、测试和工具代码统一使用 `backend.dsl...` |
| 运行入口 | `main.py` 的 Uvicorn target 改为 `backend.dsl.app:app` |
| 文档 | 更新 README、MkDocs 指南、架构说明和 API 引用 |
| 架构规约 | `AGENTS.md` 与 `CLAUDE.md` 增加后端根目录、领域分层架构、模块内简洁架构和边界纪律 |
| 回归修复 | `GitWorktreeService` 改为向上查找仓库级 `scripts/bootstrap_worktree_env.sh`，避免包层级变化导致路径推导错误 |

## 验收标准

- `backend/__init__.py` 存在，`backend.dsl` 可导入。
- 仓库中运行时代码和测试不再依赖顶层 `dsl...` 导入路径。
- `uv run python -m py_compile ...` 能编译关键后端入口和迁移相关测试。
- `uv run pytest -q` 全量通过。
- `just docs-build` 严格模式通过。
- 架构规则在 `AGENTS.md`、`CLAUDE.md` 和 MkDocs 架构/开发文档中可见。

## 实施结果

- 已完成目录移动：`dsl/` -> `backend/dsl/`。
- 已更新 `main.py`、`utils/database.py`、后端包内部导入、测试导入和 monkeypatch 路径。
- 已更新 `docs/api/references.md` 的 `mkdocstrings` 引用到 `backend.dsl...`。
- 已补充 `AGENTS.md`、`CLAUDE.md`、`docs/architecture/system-design.md`、`docs/guides/dsl-development.md` 的架构规则。
- 已修复迁移后暴露的 bootstrap 脚本路径推导问题。

## 验证记录

| 命令 | 结果 |
| --- | --- |
| `uv run python -m py_compile main.py utils/database.py backend/dsl/app.py backend/dsl/services/task_service.py backend/dsl/services/codex_runner.py tests/test_database.py tests/test_packaged_runtime.py` | 通过 |
| `uv run pytest tests/test_database.py tests/test_packaged_runtime.py tests/test_media_api.py tests/test_task_qa_api.py -q` | 23 passed |
| `uv run pytest tests/test_git_worktree_service.py tests/test_task_service.py -q` | 23 passed |
| `uv run pytest -q` | 250 passed, 6 warnings |
| `just docs-build` | 通过 |

## 已知说明

- 全量测试中的 6 个 warning 为既有测试/依赖警告，本次迁移未引入新的失败。
- `frontend/package-lock.json` 在开始本任务前已处于修改状态，本任务未依赖或调整该文件。
