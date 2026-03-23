# Task Plan: Fix SQLite Lock Failures On Task And Log Endpoints

## Goal
Stop the recurring `sqlite3.OperationalError: database is locked` failures during active Koda runs by reducing lock-amplifying ORM reads and hardening the SQLite engine configuration, then verify the affected paths with focused tests.

## Current Phase
All phases complete

## Phases
### Phase 1: Requirements & Discovery
- [x] Understand user intent
- [x] Identify constraints and requirements
- [x] Document findings in findings.md
- **Status:** complete
- **Started:** 2026-03-20 18:06:02
- **Completed:** 2026-03-20 18:08:30

### Phase 2: Planning & Structure
- [x] Define technical approach
- [x] Limit the fix to high-confidence backend changes
- [x] Document decisions with rationale
- **Status:** complete
- **Started:** 2026-03-20 18:08:30
- **Completed:** 2026-03-20 18:08:50

### Phase 3: Implementation
- [x] Update SQLite engine configuration for mixed read/write traffic
- [x] Remove lock-amplifying lazy loads from `/api/tasks` and `/api/logs`
- [x] Add focused regression tests
- **Status:** complete
- **Started:** 2026-03-20 18:08:50
- **Completed:** 2026-03-20 18:10:10

### Phase 4: Testing & Verification
- [x] Run focused pytest coverage for database/tasks/logs behavior
- [x] Run docs build if docs change
- [x] Document exact outcomes in progress.md
- [x] Fix any issues found
- **Status:** complete
- **Started:** 2026-03-20 18:10:10
- **Completed:** 2026-03-20 18:11:19

### Phase 5: Delivery
- [x] Review touched files
- [x] Summarize root causes and fixes
- [x] Deliver to user
- **Status:** complete
- **Started:** 2026-03-20 18:11:19
- **Completed:** 2026-03-20 18:11:19

## Key Questions
1. Which list-endpoint code paths are still triggering extra SQL during active log writing?
2. What SQLite connection settings are missing for concurrent readers and background log writers?
3. What is the smallest safe patch set that reduces lock frequency without redesigning persistence?

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Fix both query shape and engine configuration in the same patch | Either change alone would leave part of the locking pattern intact |
| Prefer aggregate counts and eager joins over lazy relationship access on list endpoints | The stack trace shows lazy loads happening during hot reads |
| Use SQLite WAL and a longer busy timeout rather than adding broad retry loops first | WAL directly addresses reader/writer contention, and timeout makes short lock windows survivable |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| Existing planning session belonged to a previous task | 1 | Archived it with `init-session.sh --force` and started a fresh planning session |
| `just docs-build` failed in sandbox because `uv` tried to write to `/home/atahang/.cache/uv` | 1 | Reran the docs build with `UV_CACHE_DIR=/tmp/uv-cache` |

## Completion Summary
### FULL Format

#### Final Status
- **Completed:** YES
- **Completion Date:** 2026-03-20

#### Deliverables
| Deliverable | Location | Status |
|-------------|----------|--------|
| SQLite lock diagnosis | `.claude/planning/current/findings.md` | complete |
| SQLite engine hardening | `utils/database.py` | complete |
| Task/log hot read query fixes | `dsl/api/tasks.py`, `dsl/services/log_service.py` | complete |
| Regression coverage | `tests/test_database.py`, `tests/test_logs_api.py`, `tests/test_tasks_api.py` | complete |
| Docs synchronization | `docs/guides/dsl-development.md`, `docs/architecture/system-design.md` | complete |

#### Key Achievements
- Identified the reported lock pattern as a combination of SQLite default journal behavior and extra ORM reads on hot list endpoints.
- Hardened SQLite connections with WAL and a 30-second busy timeout.
- Removed relationship-driven log counting from task reads and collapsed log task-title loading into the main query.

#### Challenges & Solutions
| Challenge | Solution Applied |
|-----------|------------------|
| Active planning files were for a different task | Reinitialized the planning workspace before continuing |
| Sandbox `just docs-build` used a read-only default `uv` cache path | Reused the writable `/tmp/uv-cache` override for docs verification |

#### Lessons Learned
- SQLite lock errors in this app were not just a database setting issue; the hot endpoint query shape was part of the lock amplification.

#### Follow-up Items
- [ ] Monitor whether any remaining lock failures come only from write/write contention in background runner paths
