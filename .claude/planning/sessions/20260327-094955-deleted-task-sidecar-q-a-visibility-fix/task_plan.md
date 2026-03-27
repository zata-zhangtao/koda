# Task Plan: Deleted Task Sidecar Q&A Visibility Fix

## Goal
Restore the task-sidecar Q&A read-only experience for `DELETED` tasks so archived history and the feedback-draft conversion entry remain available, matching the existing PRD and architecture docs.

## Current Phase
Complete

## Phases

### Phase 1: Scope Confirmation
- [ ] Re-read the blocker finding and inspect the relevant `frontend/src/App.tsx` branches
- [ ] Confirm whether docs/PRD already describe the intended `DELETED` behavior
- [ ] Record concrete findings and affected lines in `findings.md`
- **Status:** complete
- **Started:** 2026-03-26 17:46:37
- **Completed:** 2026-03-26 18:05:00

### Phase 2: Implementation
- [ ] Decouple sidecar history visibility from submit permissions for `DELETED` tasks
- [ ] Preserve read-only Q&A history loading plus “整理最近一次结论为反馈草稿” entry for archived tasks
- [ ] Avoid expanding scope into unrelated backend or workflow behavior
- **Status:** complete
- **Started:** 2026-03-26 18:05:00
- **Completed:** 2026-03-27 09:48:01

### Phase 3: Verification
- [ ] Add or update focused regression coverage for deleted-task details
- [ ] Run the relevant frontend/backend verification commands
- [ ] Record exact outcomes in `progress.md`
- **Status:** complete
- **Started:** 2026-03-27 09:48:01
- **Completed:** 2026-03-27 09:48:01

### Phase 4: PRD Sync & Delivery
- [ ] Review `tasks/prd-514e2c11.md` against the delivered fix
- [ ] Update PRD/progress notes with actual outcomes
- [ ] Run a code-review pass on the final diff
- [ ] Fill the completion summary before handoff
- **Status:** complete
- **Started:** 2026-03-27 09:48:01
- **Completed:** 2026-03-27 09:49:23

## Key Questions
1. Which `App.tsx` conditions currently suppress sidecar history and feedback-draft conversion for `DELETED` tasks?
2. Is the correct behavior “read-only visible for `DELETED`” or should docs be narrowed instead?
3. What is the narrowest regression test that prevents this from breaking again?

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Assume `DELETED` should keep read-only sidecar history unless the code proves the docs/PRD were intentionally narrowed later | The latest review finding explicitly cites current PRD and architecture text promising archived-task history retention |
| Keep the fix limited to `frontend/src/App.tsx` and leave backend/service code untouched | The deleted-task read contract already passes at the API/service layer, so the regression lives only in the front-end visibility gate |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| None | 1 | N/A |

## Completion Summary

### SIMPLE Format
<!--
- **Status:** ✅ Complete (YYYY-MM-DD)
- **PRD:** Updated `tasks/prd-514e2c11.md`
- **Deliverables:** `frontend/src/App.tsx`, `...`
- **Notes:** ...
-->

### FULL Format

#### Final Status
- **Completed:** YES
- **Completion Date:** 2026-03-27

#### Deliverables
| Deliverable | Location | Status |
|-------------|----------|--------|
| Front-end deleted-task visibility fix | `frontend/src/App.tsx` | complete |
| Deleted-task history regression test | `tests/test_task_qa_api.py` | complete |
| PRD sync note | `tasks/prd-514e2c11.md` | complete |

#### Key Achievements
- Restored archived-task sidecar visibility for `DELETED` tasks without reopening any write path.
- Confirmed the backend archived-history contract with focused regression coverage and broader related pytest coverage.
- Revalidated the front-end build and strict docs build after the review-fix.

#### Challenges & Solutions
| Challenge | Solution Applied |
|-----------|------------------|
| The failure surfaced as a UI regression, but the backend contract was already correct | Kept the fix limited to the `canRenderComposer` guard and added a deleted-task history read regression test instead of changing service behavior |

#### PRD Sync
- **PRD Path:** `tasks/prd-514e2c11.md`
- **Action:** updated existing PRD
- **Variances:** No scope expansion beyond the deleted-task archived-history review-fix.

#### Lessons Learned
- When archived behavior is already documented and covered at the service layer, a UI-only guard can still silently break the contract; the cheapest fix is often to restore visibility while keeping existing write gates intact.

#### Follow-up Items
- [ ] Add a front-end integration test for archived-task composer visibility if the project introduces a stable UI test harness.
