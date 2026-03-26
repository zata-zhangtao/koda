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
- [x] Fix backend/frontend card-metadata flow so sidebar and header badge both use the same derived display-state source
- [x] Keep action gating based on real workflow stages, not display-stage overrides
- [x] Sync docs/PRD if behavior or contract changes need to be clarified
- **Status:** complete

### Phase 3: Verification
- [x] Run focused tests for task/card metadata APIs and affected frontend/backend logic
- [x] Run docs build if docs are touched
- [x] Record final behavior and any remaining caveats
- **Status:** complete

## Current Phase
All phases complete ✅

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Use the existing PRD `tasks/prd-ac901b14.md` as the source of truth | The user explicitly referenced it and the requirement scope is already defined there |
| Keep `waiting_user` as API/UI metadata instead of touching `WorkflowStage` | Resume / Complete / automation transitions already rely on real workflow stages and must not regress |
| Add a one-shot metadata refresh when a selected task first settles into waiting-user | This keeps the UI responsive at the state boundary without moving card metadata onto the existing 3-second hot poll |

## Completion Summary
- **Status:** Complete (2026-03-26)
- **Tests:**
  - `uv run pytest tests/test_tasks_api.py tests/test_codex_runner.py -q` -> PASS (`32 passed`)
  - `uv run pytest -q` -> PASS (`103 passed, 1 pre-existing warning`)
  - `cd frontend && npm run build` -> PASS
  - `uv run mkdocs build` -> PASS
- **PRD:** Updated `tasks/prd-ac901b14.md`
- **Deliverables:**
  - `dsl/models/task.py`, `utils/database.py`, `dsl/schemas/task_schema.py`, `dsl/api/tasks.py`, `dsl/services/codex_runner.py`
  - `frontend/src/App.tsx`, `frontend/src/api/client.ts`, `frontend/src/types/index.ts`, `frontend/src/index.css`
  - `tests/test_tasks_api.py`, `tests/test_codex_runner.py`
  - `docs/database/schema.md`, `docs/api/references.md`, `docs/architecture/system-design.md`
- **Notes:**
  - Sidebar cards and the detail header now read the same `GET /api/tasks/card-metadata` display source.
  - `Task.last_ai_activity_at` is refreshed only from automated Codex log writes; no filesystem timestamp heuristics were added.
