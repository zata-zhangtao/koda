# PRD: Dashboard Auto Refresh After Task Mutations

**Original Need:** 完成、销毁、删除或变更任务状态后，dashboard 不应停留在旧列表/旧详情，需要自动刷新。
**AI-Normalized Name:** Keep task list, selected detail, and timeline synchronized after task mutation responses.
**Date:** 2026-04-24
**Status:** Implemented
**Related Context:** `tasks/archive/20260424-173053-prd-manual-complete-from-changes-requested.md`

## 1. Introduction & Goals

The dashboard had a stale-state gap after task finalization: the selected task timeline could show terminal completion logs while the task list/detail snapshot still relied on a slower dashboard refresh. The same pattern can affect Destroy, Delete, Restore, Request Changes, Accept, Cancel, Force Interrupt, and PRD regeneration flows.

Goals:

- Apply mutation API responses to the local task list immediately.
- Keep dashboard polling alive while a task is open in `pr_preparing`, even if the transient runtime flag is lost.
- Remove hard-deleted unstarted drafts locally because the hard-delete endpoint returns HTTP 204.
- Keep full dashboard refresh as a consistency backfill rather than the only visible state update.

## 2. Requirement Shape

- **Actor:** Task owner using the dashboard.
- **Trigger:** A task mutation succeeds, such as `Complete`, `Destroy`, `Delete`, `Request Changes`, `Accept`, `Restore`, `Cancel`, `Force Interrupt`, `Start`, `Execute`, PRD source import, or PRD regeneration.
- **Expected Behavior:** The visible task list and selected detail update immediately from the authoritative response or local deletion rule; background refresh then fills in logs, metadata, and global consistency.
- **Scope Boundary:** This does not add server-sent events or change backend workflow transitions.

## 3. Delivered Changes

| Area | Delivered Behavior | Files |
| --- | --- | --- |
| Task list reconciliation | Centralized returned-task replacement and local hard-delete removal | `frontend/src/utils/task_list.ts` |
| Dashboard polling | Continue polling when any task is running or open in `pr_preparing` | `frontend/src/App.tsx` |
| Mutation handlers | Reconcile task snapshots for start, execute, complete, destroy, abandon, restore, accept, request changes, cancel, force interrupt, PRD import, and regeneration | `frontend/src/App.tsx` |
| Hard delete | Remove unstarted drafts locally after 204 success | `frontend/src/App.tsx` |
| Regression tests | Covered utility-level `pr_preparing` polling, destroy/request-changes reconciliation, hard-delete local removal, and App-level handler behavior before full refresh resolves | `frontend/tests/task_list.test.ts`, `frontend/tests/app_task_mutation_refresh.test.ts` |
| Documentation | Documented the refresh contract and `pr_preparing` polling exception | `docs/architecture/system-design.md`, `docs/dev/evaluation.md`, `docs/guides/dsl-development.md`, `docs/index.md` |

## 4. Acceptance Criteria

- [x] `Complete` writes the returned `pr_preparing` snapshot into the local list before full refresh.
- [x] Open `pr_preparing` tasks keep dashboard polling active until `done / CLOSED` is observed.
- [x] Destroy and Request Changes returned snapshots replace the local task immediately.
- [x] Hard-deleted backlog drafts disappear from the local list immediately.
- [x] Cross-workspace actions still set the intended workspace (`completed`, `changes`, or `active`).
- [x] Full dashboard refresh remains as background consistency backfill.

## 5. Validation

- [x] `npm run test:task-list`
- [x] `node --experimental-strip-types --experimental-specifier-resolution=node tests/app_task_mutation_refresh.test.ts`
- [x] `npm run test`
- [x] `npm run build`
- [x] `just docs-build`
- [x] `just lint`

## 6. Non-Goals

- No backend API changes.
- No new websocket/SSE stream.
- No continuous polling of all idle `changes_requested`, abandoned, deleted, or completed tasks.

## 7. Follow-Up

- If stale-state reports continue after this fix, add an explicit task mutation integration test around the full `App` component with mocked `taskApi` responses.
