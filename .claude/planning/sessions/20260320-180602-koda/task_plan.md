# Task Plan: Diagnose And Reduce Koda UI Slowness

## Goal
Identify why Koda feels sluggish during normal use, implement the highest-impact low-risk fixes, and verify the behavior with targeted checks.

## Current Phase
All phases complete

## Phases
### Phase 1: Requirements & Discovery
- [x] Understand user intent
- [x] Identify constraints and requirements
- [x] Document findings in findings.md
- **Status:** complete
- **Started:** 2026-03-19 13:13:53
- **Completed:** 2026-03-19 13:18:00

### Phase 2: Planning & Structure
- [x] Define technical approach
- [x] Limit the fix to high-confidence performance bottlenecks
- [x] Document decisions with rationale
- **Status:** complete
- **Started:** 2026-03-19 13:18:00
- **Completed:** 2026-03-19 13:20:00

### Phase 3: Implementation
- [x] Reduce repeated front-end heavy polling
- [x] Remove obvious back-end N+1 / over-fetch patterns
- [x] Add or reuse low-risk query optimizations
- **Status:** complete
- **Started:** 2026-03-19 13:20:00
- **Completed:** 2026-03-19 13:33:00

### Phase 4: Testing & Verification
- [x] Run focused backend tests
- [x] Run focused frontend build/type checks
- [x] Record exact outcomes in progress.md
- [x] Fix any issues found
- **Status:** complete
- **Started:** 2026-03-19 13:33:00
- **Completed:** 2026-03-19 13:39:00

### Phase 5: Delivery
- [x] Review touched files
- [x] Summarize root causes and fixes
- [x] Deliver to user
- **Status:** complete
- **Started:** 2026-03-19 13:39:00
- **Completed:** 2026-03-19 13:41:00

### Phase 6: Incremental Log Polling Follow-up
- [x] Add a log-list API filter for incremental polling
- [x] Switch selected-task polling to overlap-based incremental fetches
- [x] Update tests and docs for the new polling contract
- **Status:** complete
- **Started:** 2026-03-19 13:42:00
- **Completed:** 2026-03-19 13:51:00

### Phase 7: Frontend Render Regression Fix
- [x] Remove no-op selected-task log state updates during overlap polling
- [x] Move feedback composer state out of the root dashboard component
- [x] Re-verify frontend build and focused regressions
- **Status:** complete
- **Started:** 2026-03-19 13:52:00
- **Completed:** 2026-03-19 13:58:00

### Phase 8: Frontend Render Volume Reduction
- [x] Limit default timeline render volume while preserving access to older history
- [x] Skip no-op task-list refresh updates from polling
- [x] Reduce fallback document derivation cost
- **Status:** complete
- **Started:** 2026-03-19 13:59:00
- **Completed:** 2026-03-19 14:06:00

## Key Questions
1. Which code paths are triggering unnecessary requests or full-list refreshes during normal UI usage?
2. Which API handlers are doing more ORM work than the UI actually needs?
3. What is the smallest safe change set that meaningfully reduces lag without changing the product workflow?

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Focus first on polling and list endpoints | The slowness is most likely caused by repeated work, not one-off actions |
| Prefer low-risk fixes over large architecture changes | The user asked why the app is slow; we can materially improve it without redesigning the app |
| Keep behavior compatible and avoid schema/API shape churn unless it directly helps performance | This keeps verification scope manageable and reduces regression risk |
| Use an overlap-based `created_after` filter rather than a strict cursor | It reduces repeated payloads while still re-fetching a small recent window that can absorb near-term log updates |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| None so far | 1 | N/A |

## Completion Summary
### FULL Format

#### Final Status
- **Completed:** YES
- **Completion Date:** 2026-03-19

#### Deliverables
| Deliverable | Location | Status |
|-------------|----------|--------|
| Performance diagnosis | `.claude/planning/current/findings.md` | complete |
| Frontend polling reduction | `frontend/src/App.tsx` | complete |
| Backend list-query optimization | `dsl/api/tasks.py`, `dsl/services/task_service.py`, `dsl/services/log_service.py` | complete |
| Hot-query indexes | `utils/database.py` | complete |
| Regression tests | `tests/test_task_service.py`, `tests/test_tasks_api.py` | complete |
| Incremental log polling follow-up | `dsl/api/logs.py`, `dsl/services/log_service.py`, `frontend/src/api/client.ts`, `frontend/src/utils/datetime.ts`, `frontend/src/App.tsx`, `tests/test_logs_api.py`, docs | complete |
| Frontend render regression fix | `frontend/src/App.tsx` plus planning logs | complete |
| Frontend render volume reduction | `frontend/src/App.tsx` plus planning logs | complete |

#### Key Achievements
- Identified high-probability sources of repeated heavy work in both frontend polling and backend list queries.

#### Challenges & Solutions
| Challenge | Solution Applied |
|-----------|------------------|
| Existing planning session belonged to prior tasks | Archived it and started a clean task-specific planning session |

#### Lessons Learned
- Performance investigation is already pointing at repeated list refreshes plus ORM over-fetching rather than one isolated slow function.

#### Follow-up Items
- [ ] If the UI still feels slow after this patch, run browser-level profiling and then split timeline / PRD panes into isolated memoized components or virtualization before considering SSE/WebSocket.
