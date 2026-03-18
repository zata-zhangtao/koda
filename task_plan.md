# Task Plan: Fix Incorrect Task-to-Project Linking

**Goal**: Ensure that when a user selects `project2` while creating a task, the task persists and later resolves against `project2` instead of being associated with `project1`.
**Started**: 2026-03-18

## Current Phase
All phases complete ✅

## Phases

### Phase 1: Discovery
- [x] Inspect the task creation API and service path
- [x] Inspect the frontend create-task form state and payload
- [x] Reproduce the fault domain and isolate the stale-selection risk
- [x] Identify the exact layers that needed protection
- **Status:** complete

### Phase 2: Implementation
- [x] Patch the frontend create-task form to avoid stale project selection
- [x] Patch the backend task creation path to validate submitted project IDs
- [x] Preserve existing task creation behavior for unlinked tasks
- **Status:** complete

### Phase 3: Verification
- [x] Add focused regression tests
- [x] Run relevant automated checks
- [x] Run `uv run mkdocs build --strict`
- **Status:** complete

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Reset the create-task draft whenever the panel is reopened or dismissed | Prevents a prior project choice from silently carrying into a new task |
| Auto-select a newly created project only when the create-task panel is already open | Matches the active user flow without changing behavior for unrelated cases |
| Validate `project_id` in `TaskService.create_task` | Rejects stale or deleted project IDs instead of persisting invalid foreign-key-like references |

## Completion Summary
- **Status:** Complete (2026-03-18)
- **Tests:**
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_task_service.py tests/test_terminal_launcher.py` -> PASS
  - `npm run build` (in `frontend/`) -> PASS
  - `UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build --strict` -> PASS
- **Deliverables:**
  - `frontend/src/App.tsx` - create-task form now resets stale project state and syncs with newly added projects
  - `dsl/services/task_service.py` - validates submitted project IDs before persisting tasks
  - `dsl/api/tasks.py` - returns `422` for invalid project IDs during task creation
  - `tests/test_task_service.py` - regression coverage for valid, invalid, and unlinked task creation
