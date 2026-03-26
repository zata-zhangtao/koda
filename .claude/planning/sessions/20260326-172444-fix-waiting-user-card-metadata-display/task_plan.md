# Task Plan: Fix Waiting-User Card Metadata Display

**Goal**: Resolve the issue where a task has already entered the derived display state `waiting_user` but the left sidebar card still shows `testing`, without breaking existing workflow-stage behavior or polling cadence.
**Started**: 2026-03-26
**PRD**: `tasks/prd-ac901b14.md`

## Phases

### Phase 1: Discovery
- [x] Inspect backend task/card-metadata response building and derived display-stage logic
- [x] Inspect frontend sidebar card and detail badge data sources plus polling cadence
- [x] Confirm whether the bug is caused by stale polling, inconsistent API consumption, or incorrect stage derivation
- **Status:** complete

### Phase 2: Implementation
- [x] Fix multi-task waiting-user refresh so non-selected tasks also get prompt card-metadata reconciliation
- [x] Add metadata-failure fallback so stale cached card metadata cannot outlive a failed request
- [x] Preserve compatible cached `waiting_user` metadata when `/api/tasks/card-metadata` fails
- [x] Keep action gating based on real workflow stages, not display-stage overrides
- [x] Sync docs/PRD if behavior or contract changes need to be clarified
- **Status:** complete

### Phase 3: Verification
- [x] Run focused verification for the revised frontend metadata refresh/fallback logic
- [x] Record final behavior and any remaining caveats
- **Status:** complete

## Current Phase
Complete

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Use the existing PRD `tasks/prd-ac901b14.md` as the source of truth | The user explicitly referenced it and the requirement scope is already defined there |
| Keep `waiting_user` as API/UI metadata instead of touching `WorkflowStage` | Resume / Complete / automation transitions already rely on real workflow stages and must not regress |
| Trigger the one-shot metadata refresh from task-list transitions, not selected-task state | Non-selected tasks must also reconcile their sidebar badge as soon as automation settles |
| Extend the active `/tasks` polling trigger from “selected task running” to “any task running” | Non-selected tasks also need timely task-list updates so their waiting-user transition can be detected |
| Fall back to task-derived card metadata whenever `/api/tasks/card-metadata` fails | A failed metadata request must not leave stale waiting-user/testing badges on screen |
| Reject cached card metadata when it contradicts the latest task snapshot | Stale `waiting_user` badges and older AI activity timestamps should not outlive fresher `/tasks` data |
| On metadata-fetch failure, merge fallback entries with any still-compatible cached metadata instead of replacing the whole map | Replacing the entire cache erases valid derived `waiting_user` display states and regresses the original bug on transient errors |

## Completion Summary
- **Status:** Complete (2026-03-26)
- **Tests:** Passed (`cd frontend && npm run build`)
- **PRD:** Updated `tasks/prd-ac901b14.md`
- **Deliverables:** `frontend/src/App.tsx`
- **Notes:** Sidebar/detail card metadata now self-heals against stale cache and multi-task waiting-user transitions, and transient `/api/tasks/card-metadata` failures no longer erase valid cached `waiting_user` display state.
