# Task Plan: DSL Dev Startup Port Collision

**Goal**: Fix `just dsl-dev` so local development starts reliably and does not fail with stale `Address already in use` collisions on the backend/frontend ports.
**Started**: 2026-03-18

## Current Phase
All phases complete ✅

## Phases

### Phase 1: Discovery
- [x] Inspect `Justfile` `dsl-dev` recipe
- [x] Inspect backend bind config in `main.py`
- [x] Check active listeners on ports `8000` and `5173`
- [x] Determine likely root cause: stale processes remain after prior `dsl-dev` runs
- **Status:** complete

### Phase 2: Launcher Fix
- [x] Add deterministic port checks before starting services
- [x] Add cleanup/trap handling so started dev processes are terminated on exit
- [x] Preserve readable startup output for backend/frontend processes
- **Status:** complete

### Phase 3: Documentation Sync
- [x] Update docs for revised `dsl-dev` behavior
- **Status:** complete

### Phase 4: Verification
- [x] Reproduce/verify `just dsl-dev`
- [x] Run `uv run mkdocs build --strict`
- **Status:** complete

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Fix `dsl-dev` in `Justfile` instead of changing backend port defaults | The failure is orchestration/process-lifecycle related, not an app-level bind configuration bug |
| Prefer fail-fast port detection over force-killing unknown processes | Avoids killing unrelated user services bound to the same ports |
| Add signal/exit cleanup for launched child processes | Prevents the recipe from leaving stale backend/frontend processes behind |

## Completion Summary
- **Status:** Complete (2026-03-18)
- **Tests:**
  - `just dsl-dev` -> PASS for occupied-port preflight; exits with a clear listener report instead of partially starting the stack
  - `uv run mkdocs build --strict` -> PASS
- **Deliverables:**
  - `Justfile` - robust `dsl-dev` preflight and cleanup behavior
  - `docs/getting-started.md` - startup and troubleshooting notes for port collisions
  - `docs/guides/configuration.md` - command behavior update
- **Notes:**
  - Existing listeners on `8000` and `5173` still need to be stopped manually before the next successful `just dsl-dev` run
