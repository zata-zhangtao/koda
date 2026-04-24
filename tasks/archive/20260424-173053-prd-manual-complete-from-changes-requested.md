# PRD: Manual Complete from Changes Requested

**Original Need:** 用户在 `changes_requested` 任务的 worktree 中已经人工修复问题，但详情页没有 `Complete`，只能看到“重新执行”。
**AI-Normalized Name:** Allow manual Complete after a worktree-backed `changes_requested` task is fixed by the user.
**Date:** 2026-04-24
**Status:** Implemented
**Related Archive:** `tasks/archive/20260423-154500-prd-complete-retry-after-main-worktree-dirty.md`

## 1. Introduction & Goals

When automation gives up and moves a worktree-backed task to `changes_requested`, the user may fix the worktree directly. The UI and API must let that user proceed to the existing deterministic `Complete` Git finalization flow without forcing another full implementation run.

Goals:

- Show `Complete` for idle, worktree-backed `changes_requested` tasks.
- Allow `POST /api/tasks/{task_id}/complete` to move such tasks into `pr_preparing`.
- Write an audit `DevLog` stating that the user manually took over after `changes_requested`.
- Preserve the existing branch-missing `/manual-complete` checklist path.

## 2. Requirement Shape

- **Actor:** Task owner.
- **Trigger:** Task is `workflow_stage=changes_requested`, has a `worktree_path`, automation is idle, and the user has repaired the worktree manually.
- **Expected Behavior:** The task detail header exposes `Complete`; clicking it calls the normal `/complete` endpoint, writes a manual takeover log, and schedules `run_codex_completion`.
- **Scope Boundary:** This does not auto-mark the task done, bypass missing-branch safety, or change the deterministic Git finalization sequence.

## 3. Repository Context And Architecture Fit

Existing path:

- Frontend action gating lived in `frontend/src/App.tsx::canCompleteTask(...)`.
- Backend transition gating lived in `backend/dsl/services/task_service.py::TaskService.prepare_task_completion(...)`.
- Route-level eligibility lived in `backend/dsl/api/tasks.py::complete_task(...)`.
- Prior behavior only restored `Complete` for `changes_requested` tasks whose latest BUG log matched a prior Complete/Git finalization failure.

Architecture constraints:

- Route handlers may coordinate service calls, but persistent task transition rules remain in `TaskService`.
- Branch-missing completion remains separate through `/manual-complete`.
- Documentation must be synchronized with workflow behavior.

## 4. Recommendation

Recommended approach:

- Keep `TaskService.prepare_task_completion(...)` strict by default.
- Rename its opt-in switch to `allow_complete_from_changes_requested_bool`.
- Let `/complete` pass that opt-in whenever the source task is `changes_requested`; service-level lifecycle, worktree, stage, and branch-health guards still apply.
- Move frontend Complete visibility into `frontend/src/utils/task_completion.ts` and allow `changes_requested` there.
- Delete the older log-marker-based frontend retry helper because eligibility is no longer marker-specific.

Rejected alternative:

- Add a new persisted “manual fix ready” flag. This would add UI and storage state for a condition that is already represented by explicit user action on `Complete` plus the audit `DevLog`.

## 5. Implementation Guide

Core logic:

```mermaid
flowchart TD
    A[Task is changes_requested and has worktree_path] --> B[User fixes worktree manually]
    B --> C[Frontend canCompleteTask shows Complete]
    C --> D[POST /api/tasks/{task_id}/complete]
    D --> E[TaskService allows changes_requested with explicit route opt-in]
    E --> F[Audit DevLog records manual takeover]
    F --> G[Task moves to pr_preparing and run_codex_completion starts]
```

Change Matrix:

| Area | Change | Files |
| --- | --- | --- |
| Frontend CTA | Extract Complete action rules and allow `changes_requested` | `frontend/src/App.tsx`, `frontend/src/utils/task_completion.ts` |
| Backend API | Allow `/complete` route to opt into `changes_requested` finalization | `backend/dsl/api/tasks.py` |
| Service contract | Rename opt-in parameter and keep default strict | `backend/dsl/services/task_service.py` |
| Auditability | Add manual takeover `DevLog` for `changes_requested -> Complete` | `backend/dsl/api/tasks.py` |
| Tests | Add backend and frontend regressions | `tests/test_tasks_api.py`, `tests/test_task_service.py`, `frontend/tests/task_completion.test.ts` |
| Docs | Update workflow docs | `docs/architecture/system-design.md`, `docs/guides/dsl-development.md`, `docs/guides/codex-cli-automation.md`, `docs/index.md` |

External Validation: Not used; this behavior is repository-local workflow logic.

## 6. Definition Of Done

- `changes_requested` tasks with valid worktrees can be completed manually.
- Existing `/manual-complete` missing-branch behavior is unchanged.
- The task timeline records the human takeover before Git finalization.
- Backend, frontend, and docs checks pass.

## 7. Acceptance Checklist

### Architecture Acceptance

- [x] Service layer remains the owner of workflow transition validation.
- [x] Route layer performs only explicit source-stage opt-in and orchestration.
- [x] No new persisted state or redundant workflow abstraction was added.

### Behavior Acceptance

- [x] Frontend shows `Complete` for `changes_requested` worktree-backed tasks.
- [x] Backend allows `/complete` from `changes_requested`.
- [x] Backend records a manual takeover `DevLog`.
- [x] Branch-missing tasks still route through the existing manual-complete checklist.

### Documentation Acceptance

- [x] Workflow docs describe `changes_requested` as supporting rerun or manual Complete after worktree repair.
- [x] Overview docs mention the broader retry/finalization path.

### Validation Acceptance

- [x] `uv run pytest tests/test_tasks_api.py::test_complete_task_allows_manual_takeover_from_changes_requested_after_worktree_fix tests/test_tasks_api.py::test_complete_task_allows_retry_from_changes_requested_after_completion_failure tests/test_task_service.py::test_prepare_task_completion_allows_changes_requested_retry_when_enabled -q`
- [x] `npm test`
- [x] `uv run pytest -q`
- [x] `npm run build`
- [x] `just docs-build`
- [x] `just lint`
- [x] `git diff --check`

## 8. User Stories

### US-001: Complete After Manual Worktree Fix

As a task owner, I want to click `Complete` after manually fixing a `changes_requested` worktree so that I can finish the task without rerunning the whole implementation chain.

### US-002: Auditable Human Takeover

As a maintainer, I want the timeline to show when a user manually completed from `changes_requested` so that later debugging can distinguish automated success from human takeover.

## 9. Functional Requirements

1. **FR-1:** The frontend must expose `Complete` for non-archived `changes_requested` tasks when automation is idle.
2. **FR-2:** The backend `/complete` route must explicitly allow `changes_requested` as a source stage.
3. **FR-3:** `TaskService.prepare_task_completion(...)` must continue rejecting `changes_requested` unless the caller opts in.
4. **FR-4:** The backend must write an `OPTIMIZATION` audit log when the source stage is `changes_requested`.
5. **FR-5:** Missing branch candidates must continue to use `/manual-complete`.
6. **FR-6:** Documentation must describe both rerun and manual Complete options for `changes_requested`.

## 10. Non-Goals

- Automatically deciding that the manual fix is correct.
- Skipping the normal Git add/commit/rebase/merge/cleanup finalization sequence.
- Changing task notification semantics.
- Adding a new database field for manual-fix readiness.

## 11. Risks And Follow-Ups

- Risk: A user can manually complete a worktree that still contains review or lint issues. Mitigation: the action is explicit, audited, and still goes through deterministic Git finalization.
- Follow-up: If product needs finer control later, add a typed API field explaining why a task is eligible for manual Complete instead of relying only on current workflow state.

## 12. Decision Log

| Decision | Rationale |
| --- | --- |
| Broaden `changes_requested` Complete eligibility beyond prior Complete failures | The user can repair implementation/review/lint failures in the worktree and should not be forced to rerun automation. |
| Keep service default strict | Prevents accidental internal transitions; only the `/complete` route can opt in. |
| Add an audit `DevLog` | Preserves traceability for human takeover. |
| Delete log-marker frontend retry helper | Marker-based eligibility no longer matches the business rule. |
