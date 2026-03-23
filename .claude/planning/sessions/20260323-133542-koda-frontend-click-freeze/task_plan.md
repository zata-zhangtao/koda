# Task Plan: Add Manual Port Overrides To `just dsl-dev`

## Goal
Allow `just dsl-dev` to accept manual backend and frontend port overrides without breaking the existing default development workflow, and document the new usage.

## Current Phase
Phase 5

## Phases
<!--
  WHAT: Break your task into 3-7 logical phases. Each phase should be completable.
  WHY: Breaking work into phases prevents overwhelm and makes progress visible.
  WHEN: Update status after completing each phase: pending → in_progress → complete
-->

### Phase 1: Requirements & Discovery
- [x] Understand user intent
- [x] Identify constraints and requirements
- [x] Document findings in findings.md
- **Status:** complete
- **Started:** 2026-03-23 11:21:15
- **Completed:** 2026-03-23 11:28:00

### Phase 2: Planning & Structure
- [x] Define technical approach
- [x] Confirm all affected runtime surfaces
- [x] Document decisions with rationale
- **Status:** complete
- **Started:** 2026-03-23 11:28:00
- **Completed:** 2026-03-23 11:31:00

### Phase 3: Implementation
- [x] Add `just dsl-dev` parameters for backend/frontend ports
- [x] Propagate frontend port/backend target into Vite and backend CORS
- [x] Update docs for the new invocation and behavior
- **Status:** complete
- **Started:** 2026-03-23 11:31:00
- **Completed:** 2026-03-23 11:42:00

### Phase 4: Testing & Verification
- [x] Run focused checks for `justfile` and Vite config changes
- [x] Run `just docs-build`
- [x] Document verification outcomes in progress.md
- [x] Fix any issues found
- **Status:** complete
- **Started:** 2026-03-23 11:42:00
- **Completed:** 2026-03-23 11:47:00

### Phase 5: Delivery
- [x] Review changed files and verification results
- [x] Summarize the new usage and defaults
- [ ] Deliver to user with file references
- **Status:** in_progress
- **Started:** 2026-03-23 11:47:00
- **Completed:**

## Key Questions
1. Which runtime surfaces must receive the override so the development flow actually works end-to-end?
2. How can the new port controls remain backward compatible with the current `just dsl-dev` defaults?
3. Which docs need updating so the command contract stays in sync?

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Keep `just dsl-dev` defaults at backend `8000` and frontend `5173` | Existing workflows and docs should continue to work unchanged |
| Expose ports as `just` recipe parameters instead of only environment variables | This keeps the user-facing entrypoint simple and discoverable |
| Pass the chosen ports into both Vite and FastAPI via environment variables | The frontend proxy target and backend CORS must stay aligned with the override |
| Parse both `backend_port=...` / `frontend_port=...` tokens and positional ports | `just` does not natively interpret those named tokens for recipe parameters, so explicit parsing keeps the UX intuitive |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| Existing planning session belonged to a previous performance task | 1 | Archived it with `init-session.sh --force` before starting this work |
| `just --dry-run dsl-dev backend_port=8100 frontend_port=5174` initially passed literal `name=value` strings into the recipe | 1 | Reworked the recipe to parse both named-style tokens and positional port arguments |

## Completion Summary
<!--
  WHAT: A retrospective summary written after the task is fully completed.
  WHY: Captures lessons learned, final state, and deliverables for future reference.
  WHEN: Fill this in AFTER all phases are marked complete, before delivering to user.

  CHOOSE YOUR FORMAT:
  - Simple tasks (< 10 tool calls, single change): Use SIMPLE format
  - Complex tasks (multi-phase, research, features): Use FULL format
-->

### SIMPLE Format (for quick tasks)
<!-- Uncomment and fill this for simple tasks -->
<!--
- **Status:** ✅ Complete (YYYY-MM-DD)
- **Deliverables:** `path/to/file1`, `path/to/file2`
- **Notes:** [任何值得记录的关键决策或坑点]
-->

### FULL Format (for complex tasks)
<!-- Use this for multi-phase tasks that need detailed retrospective -->

#### Final Status
<!-- Overall completion status -->
- **Completed:** [YES / PARTIAL / BLOCKED]
- **Completion Date:** [YYYY-MM-DD]

#### Deliverables
<!-- List all files, documents, or outputs produced -->
| Deliverable | Location | Status |
|-------------|----------|--------|
|             |          |        |

#### Key Achievements
<!-- What was successfully accomplished -->
-

#### Challenges & Solutions
<!-- Major obstacles encountered and how they were resolved -->
| Challenge | Solution Applied |
|-----------|------------------|
|           |                  |

#### Lessons Learned
<!-- Insights for future similar tasks -->
-

#### Follow-up Items
<!-- Anything that needs to be done later -->
- [ ] [Follow-up task or improvement idea]

---

## Notes
<!--
  REMINDERS:
  - Update phase status as you progress: pending → in_progress → complete
  - Re-read this plan before major decisions (attention manipulation)
  - Log ALL errors - they help avoid repetition
  - Never repeat a failed action - mutate your approach instead
-->
- Update phase status as you progress: pending → in_progress → complete
- Re-read this plan before major decisions (attention manipulation)
- Log ALL errors - they help avoid repetition
