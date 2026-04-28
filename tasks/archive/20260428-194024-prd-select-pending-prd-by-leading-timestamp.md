# PRD: Select Pending PRD By Leading Timestamp

**原始需求标题**：Choose the PRD from tasks/pending according to the leading timestamp

**需求名称（AI 归纳）**：按文件名前置时间戳选择 pending PRD

**创建时间**：2026-04-28 19:40:24

**状态**：Implemented

**输入上下文**：从 `tasks/pending` 选择的 PRD 要按照开头的时间戳来选。

**附件检查**：原始上下文未包含 `Attached local files:` 段落，未发现需要解析的本地附件。

## 1. Introduction & Goals

当前 Koda 支持在创建 task 前或已有 task 详情中从 `tasks/pending/*.md` 选择 PRD。后端 `FilesystemPrdRepository.list_pending_prd_candidates(...)` 会返回 pending PRD 列表，前端 `App.tsx` 在没有已恢复选择时默认选中返回列表的第一项。

现有列表排序使用文件修改时间 `updated_at` 倒序，并以文件名作为次级排序。这会让“最近被编辑过的旧 PRD”排到新 PRD 前面，和 pending PRD 文件名合同中的前置时间戳不一致。需求目标是让 `tasks/pending` 的选择顺序以文件名开头的时间戳为准，确保默认选择、列表展示和用户对时间戳文件名的理解一致。

目标：

- pending PRD 列表的主排序依据改为文件名开头的 `YYYYMMDD-HHMMSS` 时间戳。
- 保持现有“最新优先”的交互语义：没有已保存选择时，前端仍默认选择列表第一项。
- 文件名前缀时间戳相同时，使用稳定的文件名次序作为 tie-breaker。
- 不改变 pending PRD staging、手动导入、AI 生成 PRD、任务阶段推进或文件命名合同。
- 对没有合法前置时间戳的 `.md` 文件给出稳定降级排序，不让异常文件名打断列表接口。

## 2. Requirement Shape

- **Actor:** 在创建 task 面板或 task 详情页选择 `tasks/pending` PRD 的开发者。
- **Trigger:** 前端调用 `GET /api/prd-sources/pending` 或 `GET /api/tasks/{task_id}/prd-sources/pending` 获取 pending PRD 列表。
- **Expected Behavior:** 后端返回的 `files` 已按文件名前置时间戳排序；前端继续使用第一个返回项作为默认选中项，因此默认选择的是前置时间戳最新的 pending PRD，而不是文件系统最近修改的 PRD。
- **Explicit Scope Boundary:** 本需求只改变 pending PRD 候选列表的排序和默认选择依据。不新增自动 staging 入口，不改变用户手动选择某个 pending 文件后的相对路径校验，不改变 `source_updated_at` 的 stale check，也不改变最终 staged PRD 文件名。

## 3. Repository Context And Architecture Fit

Current relevant modules/files:

- `backend/dsl/prd_sources/infrastructure/filesystem_prd_repository.py`
  - `list_pending_prd_candidates(...)` 当前扫描 `workspace/tasks/pending/*.md`，读取 stat、title preview，并按 `(updated_at, file_name_str)` 倒序排序。
  - 这是最接近需求的现有路径，也是排序规则的单一推荐修改点。
- `backend/dsl/prd_sources/domain/models.py`
  - `PendingPrdCandidate` 暴露 `file_name_str`、`relative_path_str`、`size_bytes_int`、`updated_at`、`title_preview_text`。
  - 现有 API 合同只需要排序变化，不必须扩展 DTO。
- `backend/dsl/prd_sources/application/use_cases.py`
  - `ListPendingPrdFilesUseCase` 与 `ListTasklessPendingPrdFilesUseCase` 只透传 repository 返回列表。
  - `BuildPrdTaskDraftUseCase`、`CreateTaskFromPendingPrdUseCase` 依赖 `source_updated_at` 做 stale check；该字段仍应表示文件修改时间，不能被替换成文件名前缀时间。
- `backend/dsl/prd_sources/api.py`
  - `_build_pending_prd_file_list_schema(...)` 把 candidate 映射为响应 DTO。
  - 不建议在 API 层排序，避免 HTTP 层承载业务规则。
- `frontend/src/App.tsx`
  - `loadPendingPrdFilesForCreate(...)` 和 `loadPendingPrdFilesForTask(...)` 使用返回列表第一项作为默认选中项。
  - 只要后端返回顺序正确，前端不需要重新实现排序。
- `frontend/src/types/index.ts`
  - `PendingPrdFile.updated_at` 当前用于展示和 stale check 来源；保持不变。
- Existing tests:
  - `tests/test_prd_sources_api.py` 已覆盖 pending list、pending draft、pending staging。
  - `tests/test_prd_sources_application.py` 覆盖 use case 透传与 stale check。
  - `frontend/tests/prd_source_selection.test.ts` 覆盖提交启用条件，不直接覆盖列表排序。
- Existing docs:
  - `docs/guides/dsl-development.md` 已说明 pending PRD 列表和 staging 语义。
  - `docs/dev/evaluation.md` 已有 pending PRD 手工评测步骤，需要补充时间戳排序检查。

Existing path:

```text
GET /api/prd-sources/pending
  -> ListTasklessPendingPrdFilesUseCase.execute(...)
  -> FilesystemPrdRepository.list_pending_prd_candidates(...)
  -> sort by updated_at desc
  -> App.tsx defaults to files[0]

GET /api/tasks/{task_id}/prd-sources/pending
  -> ListPendingPrdFilesUseCase.execute(...)
  -> FilesystemPrdRepository.list_pending_prd_candidates(...)
  -> sort by updated_at desc
  -> App.tsx defaults to files[0]
```

Target path:

```text
GET /api/prd-sources/pending
  -> ListTasklessPendingPrdFilesUseCase.execute(...)
  -> FilesystemPrdRepository.list_pending_prd_candidates(...)
  -> sort by parsed leading timestamp desc, then filename desc
  -> App.tsx defaults to files[0]

GET /api/tasks/{task_id}/prd-sources/pending
  -> same repository ordering rule
  -> App.tsx defaults to files[0]
```

Existing path:

- The repository already centralizes pending file scanning and is shared by taskless and task-scoped routes.
- The front end already treats backend order as authoritative.
- The stale check already stores `source_updated_at`; that should remain file mtime because it detects file content changes after draft generation.

Reuse candidates:

- Reuse `FilesystemPrdRepository.list_pending_prd_candidates(...)` as the only sorting owner.
- Add a small pure helper in `filesystem_prd_repository.py` or `domain/policies.py` to parse leading timestamps.
- Reuse existing `PendingPrdCandidate` DTO; no API schema change is required for the recommended target state.

Architecture constraints:

- Do not put sorting in FastAPI route handlers.
- Do not duplicate sort logic in front-end TypeScript.
- Do not reinterpret `updated_at`; it remains filesystem modification time.
- Any new Python docstrings and public helpers must use type annotations and Google-style docstrings.
- Any file reads must keep explicit `encoding="utf-8"`.
- Documentation updates are required because behavior of pending PRD selection changes.

Potential redundancy risks:

- Adding a new service for pending sorting would duplicate the existing `prd_sources` repository boundary.
- Adding a new API field such as `leading_timestamp` is unnecessary unless the UI needs to display it separately.
- Sorting in both backend and frontend would create divergent behavior when project and task-scoped pending lists evolve.

## 4. Recommendation

### Recommended Approach

Extend `FilesystemPrdRepository.list_pending_prd_candidates(...)` so it sorts candidates by a parsed leading filename timestamp before returning. Preserve the current descending “newest first” behavior, but derive newest from the filename prefix instead of `stat().st_mtime`.

Recommended parsing rule:

- Recognize filenames beginning with `YYYYMMDD-HHMMSS`, such as `20260428-150952-prd-auditable-auto-conflict-resolution.md`.
- Parse the prefix as a naive local `datetime` for ordering only.
- Sort valid timestamped filenames before non-timestamped filenames.
- For valid timestamped files, sort by parsed timestamp descending.
- For identical parsed timestamps, sort by `file_name_str` descending to keep deterministic ordering.
- For non-timestamped files, sort after timestamped files, then by `updated_at` descending and `file_name_str` descending as a stable legacy fallback.

Rationale:

- This is the smallest change that directly affects both create-panel and task-detail pending selection paths.
- It preserves current UX expectations that the first returned file is the newest candidate.
- It avoids API churn and keeps `updated_at` available for display and stale-source validation.
- It keeps business ordering in the backend source repository, where pending filesystem facts are already assembled.

### Alternatives Considered

| Alternative | Reason Rejected |
| --- | --- |
| Sort in `App.tsx` after fetching files | Duplicates backend behavior in the UI, risks taskless and task-scoped views diverging, and makes API order misleading. |
| Replace `updated_at` with parsed filename timestamp in the API response | Breaks stale-source checks and mislabels mtime as filename time. |
| Add a new `leading_timestamp` response field now | Useful for future display, but unnecessary for the required selection behavior. It adds schema, frontend type and docs churn without changing the core outcome. |
| Reject pending files without leading timestamp | Too disruptive; existing manually named pending PRDs should remain selectable with a deterministic fallback order. |

## 5. Implementation Guide

### Core Logic

1. Add a pure helper for parsing the leading timestamp:

```python
_PENDING_PRD_LEADING_TIMESTAMP_PATTERN = re.compile(
    r"^(?P<timestamp>\d{8}-\d{6})"
)

def _parse_pending_prd_leading_timestamp(file_name_str: str) -> datetime | None:
    """Parse a pending PRD filename prefix timestamp for ordering.

    Args:
        file_name_str: Pending PRD filename.

    Returns:
        datetime | None: Parsed timestamp when the filename starts with
            ``YYYYMMDD-HHMMSS``; otherwise ``None``.
    """
```

2. Replace the current final `sorted(...)` key in `list_pending_prd_candidates(...)` with a named sort key helper.

3. Keep `PendingPrdCandidate.updated_at` as `datetime.fromtimestamp(st_mtime)` for display and stale validation.

4. Add tests that make mtime conflict with filename timestamp:

```text
tasks/pending/
  20260428-150952-prd-newer-by-name.md      # older mtime
  20260428-135738-prd-older-by-name.md      # newer mtime
```

Expected order: `20260428-150952...` appears first.

5. Add tests for non-timestamp fallback:

```text
tasks/pending/
  manual.md
  20260428-150952-prd-newer-by-name.md
```

Expected order: timestamped file appears before `manual.md`; `manual.md` remains selectable.

### Affected Files

| Path | Change |
| --- | --- |
| `backend/dsl/prd_sources/infrastructure/filesystem_prd_repository.py` | Add leading timestamp parser and update pending candidate sorting. |
| `tests/test_prd_sources_api.py` or new focused repository test | Assert API/list order follows filename leading timestamp, not mtime. |
| `tests/test_prd_sources_application.py` | Optional use-case-level regression if fake repository ordering is not enough; not required if repository/API tests cover behavior. |
| `docs/guides/dsl-development.md` | Document that pending list/default selection is sorted by leading filename timestamp, with mtime only as metadata/fallback. |
| `docs/dev/evaluation.md` | Add a manual validation step for conflicting mtime vs filename timestamp. |

### Change Matrix

| Area | Current Behavior | Target Behavior | Validation |
| --- | --- | --- | --- |
| Pending list sorting | `updated_at` desc, then filename desc | Valid leading timestamp desc, then filename desc; non-timestamp fallback after timestamped files | Backend API/repository test with conflicting mtimes |
| Default pending selection | Frontend uses `files[0]` | Unchanged, but `files[0]` is now newest by filename timestamp | Frontend behavior remains covered by backend order test and existing UI logic |
| `updated_at` response | Filesystem modification time | Unchanged | Existing stale check tests continue passing |
| Pending staging | Selected relative path is staged into task `tasks/` root | Unchanged | Existing pending staging tests continue passing |
| Non-timestamp filenames | Sorted by mtime as part of all candidates | Still selectable, sorted after timestamped candidates with legacy fallback | New fallback test |
| Docs | Mentions pending source, not timestamp ordering | Explicitly documents leading timestamp sort | `just docs-build` |

### Flow Diagram

```mermaid
flowchart TD
    A[User opens pending PRD source] --> B[Frontend requests pending list]
    B --> C[Use case resolves source workspace]
    C --> D[Filesystem repository scans tasks/pending/*.md]
    D --> E[Read size, mtime, title preview]
    E --> F{Filename starts with YYYYMMDD-HHMMSS?}
    F -->|Yes| G[Parse leading timestamp]
    F -->|No| H[Mark as non-timestamp fallback]
    G --> I[Sort timestamped files newest first]
    H --> J[Sort fallback files after timestamped files]
    I --> K[Return ordered files]
    J --> K
    K --> L[Frontend keeps restored selection or defaults to files[0]]
    L --> M[User confirms selected PRD]
```

### External Validation

No web research is required. The behavior depends on repository-local filename contracts and existing code paths, not on external APIs or changing third-party behavior.

## 6. Definition Of Done

- Pending PRD list order is based on file name leading timestamp for both taskless and task-scoped APIs.
- Existing pending staging, import, stale check and PRD ready flow continue to pass without behavioral regression.
- Non-timestamped pending Markdown files remain selectable with deterministic fallback ordering.
- Documentation states the new ordering rule and clarifies that `updated_at` remains modification time.
- `just docs-build` passes after documentation changes.

## 7. Acceptance Checklist

### Architecture Acceptance

- [ ] Sorting logic lives in `backend/dsl/prd_sources/infrastructure/filesystem_prd_repository.py` or a pure policy helper used by that repository, not in FastAPI route handlers.
- [ ] `frontend/src/App.tsx` does not implement a duplicate pending PRD sort.
- [ ] `PendingPrdCandidate.updated_at` and `PendingPrdFile.updated_at` continue to represent filesystem modification time.

### Behavior Acceptance

- [ ] Given `tasks/pending/20260428-150952-prd-new.md` has an older mtime than `tasks/pending/20260428-135738-prd-old.md`, `GET /api/prd-sources/pending` returns `20260428-150952-prd-new.md` first.
- [ ] Given the same files in a task-scoped or project-linked source workspace, `GET /api/tasks/{task_id}/prd-sources/pending` returns the newest leading timestamp first.
- [ ] Given a pending file named `manual.md`, it remains in the list and can still be selected.
- [ ] Given at least one valid timestamped pending file and one non-timestamped pending file, valid timestamped files sort before `manual.md`.
- [ ] Selecting a returned relative path still stages the selected PRD and transitions the task to `prd_waiting_confirmation`.

### Dependency Acceptance

- [ ] No new runtime dependency is added for timestamp parsing.
- [ ] No API response field is added unless implementation discovers a concrete UI display requirement.

### Documentation Acceptance

- [ ] `docs/guides/dsl-development.md` documents that pending PRDs are ordered by filename leading timestamp.
- [ ] `docs/dev/evaluation.md` includes a manual check where mtime and filename timestamp disagree.

### Validation Acceptance

- [ ] `uv run pytest tests/test_prd_sources_api.py tests/test_prd_sources_application.py tests/test_prd_sources_domain.py` passes.
- [ ] `cd frontend && npm test` passes if frontend files are touched.
- [ ] `just docs-build` passes.

## 8. User Stories

1. As a developer creating a task from pending PRDs, I want the newest timestamped pending PRD to be selected by default so that I do not accidentally run an older edited PRD.
2. As a developer reviewing the pending dropdown, I want the list order to match the timestamp prefix in file names so that the newest document is obvious.
3. As a maintainer, I want `updated_at` to remain mtime so stale draft validation still detects file edits after draft generation.
4. As a maintainer, I want non-standard pending filenames to remain selectable so existing local workflows do not break abruptly.

## 9. Functional Requirements

- **FR-1:** The system must parse a pending PRD filename leading prefix in the exact format `YYYYMMDD-HHMMSS`.
- **FR-2:** The system must sort pending PRD candidates with valid leading timestamps before candidates without valid leading timestamps.
- **FR-3:** The system must sort valid timestamped candidates by parsed leading timestamp descending.
- **FR-4:** The system must use `file_name_str` as a deterministic tie-breaker when parsed leading timestamps are equal.
- **FR-5:** The system must keep non-timestamped `.md` candidates selectable and sort them with legacy fallback rules after timestamped candidates.
- **FR-6:** The system must keep `updated_at` as the file modification timestamp in API responses.
- **FR-7:** The system must apply the same ordering through both taskless and task-scoped pending PRD list endpoints.
- **FR-8:** The front end must continue to use backend response order as authoritative for default pending selection.
- **FR-9:** Pending path validation must continue to accept only `tasks/pending/<file>.md` and reject traversal.
- **FR-10:** Documentation must describe the new leading timestamp ordering contract.

## 10. Non-Goals

- Do not add automatic “select and stage newest pending PRD” without user confirmation.
- Do not change final staged PRD filenames under `tasks/`.
- Do not remove support for non-timestamped pending `.md` files.
- Do not change stale detection from mtime to filename timestamp.
- Do not add subdirectory scanning under `tasks/pending`.
- Do not add a database table or persistent preference for pending sort order.
- Do not redesign the pending PRD dropdown UI.

## 11. Risks And Follow-Ups

- **Malformed timestamp prefixes:** Files like `20261399-999999-prd-demo.md` should not crash list loading. Treat parse failures as non-timestamp fallback.
- **Timezone interpretation:** The filename prefix should be treated as an ordering token, not converted across time zones. Avoid mixing it with `APP_TIMEZONE` unless a future display field is added.
- **User expectation for oldest-first:** This PRD recommends preserving the current newest-first semantics. If users later ask for FIFO processing, implement it as an explicit sort-mode change rather than silently reversing this behavior.
- **Future UI clarity:** If users need to see the parsed timestamp separately from mtime, add an optional API field in a follow-up. It is not required for this behavior fix.

## 12. Decision Log

| Date | Decision | Rationale |
| --- | --- | --- |
| 2026-04-28 | Preserve newest-first default selection. | Current backend sorting and frontend default selection already use descending recency; only the recency source should change from mtime to filename prefix. |
| 2026-04-28 | Keep `updated_at` as mtime. | Existing stale checks depend on file modification time after draft generation. |
| 2026-04-28 | Do not add frontend sorting. | Backend repository is the existing shared source of pending file ordering for taskless and task-scoped flows. |
| 2026-04-28 | Keep non-timestamped pending files selectable. | Rejecting existing files would be a larger compatibility break than the requested ordering fix. |

## 13. Implementation Notes

- `FilesystemPrdRepository.list_pending_prd_candidates(...)` now delegates final ordering to a shared helper that parses valid leading `YYYYMMDD-HHMMSS` filename timestamps.
- Valid timestamped candidates sort before invalid or non-timestamped candidates, newest parsed timestamp first, then `file_name_str` descending for equal parsed timestamps.
- Invalid timestamp tokens such as `20261399-999999` fall back with non-timestamped files instead of failing list loading.
- Non-timestamped `.md` files remain selectable and continue to use the legacy fallback order: `updated_at` descending, then `file_name_str` descending.
- `updated_at` remains populated from `stat().st_mtime` and no API response fields or frontend sorting were added.
- Documentation now describes the backend ordering contract and adds a manual validation step for mtime-vs-filename-timestamp conflicts.

## 14. Verification Evidence

- `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check backend/dsl/prd_sources/infrastructure/filesystem_prd_repository.py tests/test_prd_sources_api.py` -> PASS
- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_prd_sources_api.py tests/test_prd_sources_application.py tests/test_prd_sources_domain.py -q` -> PASS (`36 passed`)
- `just docs-build` -> PASS

## 15. Deviations And Follow-Ups

- No deviations from the confirmed scope.
- No follow-up is required unless the UI later needs to display the parsed filename timestamp as a separate field.
