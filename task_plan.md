# Task Plan: Requirement Workflow Implementation

**Goal**: Implement the complete requirement card automation workflow per `tasks/20260317-174953-prd-requirement-workflow.md`
**Started**: 2026-03-17
**Completed**: 2026-03-17

## Current Phase
All phases complete ✅

## Phases

### Phase 1: Backend — Enums & Model
- [x] Add `WorkflowStage` enum to `dsl/models/enums.py`
- [x] Add `workflow_stage` field to `dsl/models/task.py` (with `values_callable` fix)
- [x] Update `dsl/schemas/task_schema.py` — TaskResponseSchema + TaskStageUpdateSchema
- **Status:** complete

### Phase 2: Backend — Service & API
- [x] Update `dsl/services/task_service.py` — new `update_workflow_stage`, `execute_task`
- [x] Update `dsl/api/tasks.py` — `PUT /{id}/stage` and `POST /{id}/execute`
- **Status:** complete

### Phase 3: Database Migration
- [x] ALTER TABLE tasks ADD COLUMN workflow_stage VARCHAR(50) DEFAULT 'backlog' NOT NULL
- [x] Existing rows verified with default 'backlog'
- **Status:** complete

### Phase 4: Frontend — Types & API Client
- [x] `WorkflowStage` enum added to `frontend/src/types/index.ts`
- [x] `workflow_stage` field added to Task interface
- [x] `taskApi.execute()` and `taskApi.updateStage()` added to `frontend/src/api/client.ts`
- **Status:** complete

### Phase 5: Frontend — App.tsx Refactor
- [x] RequirementStage → type alias of WorkflowStage
- [x] deriveRequirementStage simplified to `return taskItem.workflow_stage`
- [x] 「开始执行」button added at prd_waiting_confirmation stage
- [x] handleStartExecution, handleAcceptTask, handleRequestChanges added
- [x] All button visibility conditions updated
- [x] formatStageLabel updated for 10 stages
- [x] RocketIcon SVG added
- [x] ActionButton variant extended with "execute"
- [x] MutationName type updated
- **Status:** complete

### Phase 6: Verification
- [x] Backend: all endpoints tested (200/422 correct)
- [x] TypeScript: `npx tsc --noEmit` → PASS (0 errors)
- **Status:** complete

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Keep TaskLifecycleStatus unchanged | Backward compat |
| workflow_stage is new source of truth | Replaces log-count heuristic |
| values_callable on Enum column | SQLAlchemy uses str values not names |
| 「开始执行」uses purple execute variant | Distinguishable from Confirm PRD (green) |

## Completion Summary
- **Status:** Complete (2026-03-17)
- **Tests:**
  - `npx tsc --noEmit` → PASS
  - Backend smoke test → all endpoints 200/422 as expected
- **Deliverables:**
  - `dsl/models/enums.py` — WorkflowStage (10 values)
  - `dsl/models/task.py` — workflow_stage field
  - `dsl/schemas/task_schema.py` — TaskStageUpdateSchema, workflow_stage in response
  - `dsl/services/task_service.py` — update_workflow_stage, execute_task
  - `dsl/api/tasks.py` — PUT /stage, POST /execute
  - `frontend/src/types/index.ts` — WorkflowStage enum, Task.workflow_stage
  - `frontend/src/api/client.ts` — taskApi.execute, taskApi.updateStage
  - `frontend/src/App.tsx` — 「开始执行」button + all handlers + simplified deriveRequirementStage
  - `frontend/src/index.css` — execute button + 10 badge classes
  - DB migration applied (workflow_stage column)
