# Task Plan: Configurable Worktree / Project Path Opener
<!--
  WHAT: This is your roadmap for the entire task. Think of it as your "working memory on disk."
  WHY: After 50+ tool calls, your original goals can get forgotten. This file keeps them fresh.
  WHEN: Create this FIRST, before starting any work. Update after each phase completes.
-->

## Goal
<!--
  WHAT: One clear sentence describing what you're trying to achieve.
  WHY: This is your north star. Re-reading this keeps you focused on the end state.
  EXAMPLE: "Create a Python CLI todo app with add, list, and delete functionality."
-->
Replace the hard-coded `trae-cn` worktree/project opener with a configurable editor command template, add neutral `open-in-editor` routes with `open-in-trae` compatibility aliases, and ship synchronized tests and docs.

## Current Phase
<!--
  WHAT: Which phase you're currently working on (e.g., "Phase 1", "Phase 3").
  WHY: Quick reference for where you are in the task. Update this as you progress.
-->
All phases complete

## Phases
<!--
  WHAT: Break your task into 3-7 logical phases. Each phase should be completable.
  WHY: Breaking work into phases prevents overwhelm and makes progress visible.
  WHEN: Update status after completing each phase: pending → in_progress → complete
-->

### Phase 1: Requirements & Discovery
<!--
  WHAT: Understand what needs to be done and gather initial information.
  WHY: Starting without understanding leads to wasted effort. This phase prevents that.
-->
- [x] Understand user intent
- [x] Identify constraints and requirements
- [x] Document findings in findings.md
- **Status:** complete
- **Started:** 2026-03-27 01:16:16
- **Completed:** 2026-03-27 01:19:30
<!--
  STATUS VALUES:
  - pending: Not started yet
  - in_progress: Currently working on this
  - complete: Finished this phase
-->

### Phase 2: Planning & Structure
<!--
  WHAT: Decide how you'll approach the problem and what structure you'll use.
  WHY: Good planning prevents rework. Document decisions so you remember why you chose them.
-->
- [x] Define technical approach
- [x] Confirm file/test/doc touch points
- [x] Document decisions with rationale
- **Status:** complete
- **Started:** 2026-03-27 01:19:30
- **Completed:** 2026-03-27 01:34:00

### Phase 3: Implementation
<!--
  WHAT: Actually build/create/write the solution.
  WHY: This is where the work happens. Break into smaller sub-tasks if needed.
-->
- [x] Add shared `path_opener` service and config
- [x] Refactor task/project routes to reuse the shared service
- [x] Switch frontend API and user-facing copy to neutral editor wording
- [x] Test incrementally
- **Status:** complete
- **Started:** 2026-03-27 01:34:00
- **Completed:** 2026-03-27 01:41:00

### Phase 4: Testing & Verification
<!--
  WHAT: Verify everything works and meets requirements.
  WHY: Catching issues early saves time. Document test results in progress.md.
-->
- [x] Run focused backend tests (`pytest`)
- [x] Run frontend build if UI code changes
- [x] Run docs build
- [x] Verify all requirements met
- [x] Document test results in progress.md
- [x] Fix any issues found
- **Status:** complete
- **Started:** 2026-03-27 01:41:00
- **Completed:** 2026-03-27 01:52:00

### Phase 5: Delivery
<!--
  WHAT: Final review and handoff to user.
  WHY: Ensures nothing is forgotten and deliverables are complete.
-->
- [x] Review all output files
- [x] Ensure deliverables are complete
- [x] Review the matching PRD in `tasks/` and update it with actual outcomes
- [x] Record the final PRD path in the Completion Summary
- [x] Deliver to user
- **Status:** complete
- **Started:** 2026-03-27 01:52:00
- **Completed:** 2026-03-27 01:55:00

## Key Questions
<!--
  WHAT: Important questions you need to answer during the task.
  WHY: These guide your research and decision-making. Answer them as you go.
  EXAMPLE:
    1. Should tasks persist between sessions? (Yes - need file storage)
    2. What format for storing tasks? (JSON file)
-->
1. How should the new opener service mirror the existing terminal template behavior without over-generalizing it?
2. Which backend and frontend tests give the best coverage for route compatibility and command-template failures?

## Decisions Made
<!--
  WHAT: Technical and design decisions you've made, with the reasoning behind them.
  WHY: You'll forget why you made choices. This table helps you remember and justify decisions.
  WHEN: Update whenever you make a significant choice (technology, approach, structure).
  EXAMPLE:
    | Use JSON for storage | Simple, human-readable, built-in Python support |
-->
| Decision | Rationale |
|----------|-----------|
| Add a dedicated `dsl.services.path_opener` module instead of embedding template logic in two routers | Centralizes placeholder rendering, command splitting, process spawning, and error translation for both task and project open actions |
| Keep `open-in-trae` as a compatibility alias that forwards to the neutral implementation | Matches the PRD rollout plan and avoids breaking existing frontend or external callers during migration |
| Use a new config key `KODA_OPEN_PATH_COMMAND_TEMPLATE` with default `trae-cn {target_path_shell}` | Preserves current behavior for existing users while allowing arbitrary editor launch commands |

## Errors Encountered
<!--
  WHAT: Every error you encounter, what attempt number it was, and how you resolved it.
  WHY: Logging errors prevents repeating the same mistakes. This is critical for learning.
  WHEN: Add immediately when an error occurs, even if you fix it quickly.
  EXAMPLE:
    | FileNotFoundError | 1 | Check if file exists, create empty list if not |
    | JSONDecodeError | 2 | Handle empty file case explicitly |
-->
| Error | Attempt | Resolution |
|-------|---------|------------|
| Existing migrated planning session was unrelated to this task | 1 | Archived it with `init-session.sh --force` and started a clean planning workspace |
| Full `uv run pytest -q` picked up a local SOCKS proxy env and failed unrelated tunnel-agent tests | 1 | Re-ran the suite with proxy env vars unset; the repository tests then passed without code changes |

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
- **PRD:** Updated `tasks/YYYYMMDD-HHMMSS-prd-feature-name.md` or created a new PRD there
- **Deliverables:** `path/to/file1`, `path/to/file2`
- **Notes:** [任何值得记录的关键决策或坑点]
-->

### FULL Format (for complex tasks)
<!-- Use this for multi-phase tasks that need detailed retrospective -->

#### Final Status
- **Completed:** YES
- **Completion Date:** 2026-03-27

#### Deliverables
<!-- List all files, documents, or outputs produced -->
| Deliverable | Location | Status |
|-------------|----------|--------|
| Shared path opener service | `dsl/services/path_opener.py` | complete |
| Backend config + routes | `utils/settings.py`, `dsl/api/tasks.py`, `dsl/api/projects.py`, `dsl/services/__init__.py` | complete |
| Frontend API + UI copy migration | `frontend/src/api/client.ts`, `frontend/src/App.tsx` | complete |
| Regression coverage | `tests/test_path_opener.py`, `tests/test_tasks_api.py`, `tests/test_projects_api.py` | complete |
| Documentation + config samples | `.env.example`, `docs/getting-started.md`, `docs/guides/configuration.md`, `docs/api/references.md`, `docs/dev/evaluation.md`, `docs/architecture/system-design.md` | complete |
| Synced PRD | `tasks/prd-e84b5309.md` | complete |

#### Key Achievements
<!-- What was successfully accomplished -->
- Replaced hard-coded `trae-cn` launching with a configurable command-template service shared by task and project open actions.
- Added neutral `open-in-editor` routes while keeping deprecated `open-in-trae` aliases functional.
- Shipped tests, frontend copy updates, config examples, and synchronized documentation for the new launcher behavior.

#### Challenges & Solutions
<!-- Major obstacles encountered and how they were resolved -->
| Challenge | Solution Applied |
|-----------|------------------|
| Route behavior needed neutral naming without breaking existing callers | Added new `open-in-editor` routes and kept deprecated `open-in-trae` aliases that forward to the same helper |
| Full test suite was polluted by local SOCKS proxy environment variables | Re-ran full `pytest` with proxy environment variables unset and recorded the environment-specific caveat |

#### PRD Sync
<!-- Record how the final implementation was reconciled with the PRD -->
- **PRD Path:** `tasks/prd-e84b5309.md`
- **Action:** updated existing PRD
- **Variances:** None at the feature level; verification required unsetting local proxy environment variables to avoid unrelated `httpx` SOCKS transport failures

#### Lessons Learned
<!-- Insights for future similar tasks -->
- Reusing the terminal launcher's template conventions made the new opener service easier to explain, test, and document.
- Capturing local-environment noise during verification is important so unrelated proxy state does not look like a product regression.

#### Follow-up Items
<!-- Anything that needs to be done later -->
- [ ] Add a future Settings UI field for `KODA_OPEN_PATH_COMMAND_TEMPLATE` so users do not need to edit `.env` manually.

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
- Matching PRD for this task: `tasks/prd-e84b5309.md`
- Before final delivery, sync the task PRD in `tasks/`
