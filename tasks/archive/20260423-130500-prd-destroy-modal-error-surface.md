# PRD：销毁弹窗错误就地展示与清理失败细节补全

**原始需求标题**：点击确认销毁的时候出现这个问题，同时，如果有错误，为什么不显示在弹窗里面
**需求名称（AI 归纳）**：销毁弹窗错误就地展示与清理失败细节补全
**文件路径**：`tasks/20260423-130500-prd-destroy-modal-error-surface.md`
**创建时间**：2026-04-23 13:05:00 CST
**参考上下文**：`frontend/src/App.tsx`, `frontend/src/api/client.ts`, `backend/dsl/api/tasks.py`, `backend/dsl/services/git_worktree_service.py`, `tests/test_tasks_api.py`

---

## 1. Background

当前 “Destroy Task” 交互存在两个问题：

- 前端 destroy 请求失败时，错误只写入页面级 `errorMessage`，`DestroyTaskModal` 内没有任何错误展示区域。
- 后端 destroy cleanup 失败时虽然返回了 `422 detail=...`，但默认 detail 主要是稳定概述，例如 `task worktree directory still exists`，缺少最近的 git 输出，定位成本偏高。

这会导致用户在销毁弹窗里点击“确认销毁”后，看起来像是“没有报错”或“报错不在当前上下文”。

## 2. Goals

- [x] 销毁失败时，在销毁弹窗内直接显示错误。
- [x] 保留并显示后端返回的真实 `detail` 文案，而不是吞掉或泛化成前端固定提示。
- [x] destroy cleanup 失败时，把最近有效的 git 输出摘要拼进 detail，提升可诊断性。
- [x] 保持现有 destroy 成功路径、HTTP 状态码和页面级成功提示不变。

## 3. Delivered Changes

### Frontend

- 在 `frontend/src/App.tsx` 新增 `destroyModalErrorMessage` 局部状态，专门承接 destroy 失败。
- `handleConfirmDestroyTask()` 的校验错误和接口异常改为写入 `destroyModalErrorMessage`，不再只走页面级 `errorMessage`。
- `DestroyTaskModal` 新增错误展示区域，使用现有 `devflow-inline-message--error` 样式，在 modal 内就地渲染错误。
- 打开或关闭 destroy modal 时会重置该局部错误状态，避免旧错误残留到下一次销毁尝试。

### Backend

- 在 `backend/dsl/api/tasks.py` 增加 destroy cleanup 错误拼装 helper。
- 当 worktree cleanup 失败时，后端除了稳定失败概述，还会从 `output_line_list` 中提取最近有效 git 输出，追加到 `detail`。
- 内部 fallback 提示行会被过滤，避免把框架性噪音直接暴露给用户。

### Regression Coverage

- 更新 `tests/test_tasks_api.py`，校验 destroy cleanup 失败时返回 detail 既包含稳定概述，也包含最近 git 输出摘要。

## 4. Verification Evidence

| Check | Command | Result |
|---|---|---|
| Backend API regression | `uv run pytest tests/test_tasks_api.py -q` | Passed (`56 passed, 5 warnings`) |
| Frontend tests | `npm test` | Passed |
| Frontend build | `npm run build` | Passed |
| Docs build | `just docs-build` | Passed |

## 5. Notes

- 本次未修改 `frontend/src/api/client.ts` 的错误解析逻辑，因为它原本就会把 FastAPI `detail` 透传成 `Error.message`；问题在于 UI 没有在 modal 内消费这个错误。
- 本次未改 destroy 的业务条件、返回状态码或成功后的归档语义，仅修复错误可见性与错误可操作性。
