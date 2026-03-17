# Task Plan: Rewrite Frontend Against `ai-devflow.zip`

## Goal
Replace the current `frontend/` Vite app with an implementation that mirrors the structure, visual design, and interaction model of `ai-devflow.zip` as closely as possible within the existing project.

## Current Phase
Phase 5

## Phases

### Phase 1: Requirements & Discovery
- [x] Understand user intent
- [x] Identify constraints
- [x] Document initial findings in `findings.md`
- **Status:** complete

### Phase 2: Planning & Structure
- [x] Inspect the reference app file-by-file
- [x] Inspect the current frontend entry points and integration boundaries
- [x] Decide replacement strategy for components, styles, and data flow
- **Status:** complete

### Phase 3: Implementation
- [x] Replace the current page/component tree with the reference-driven UI
- [x] Port styles, layout, assets, and interaction details for visual parity
- [x] Reconcile or stub data dependencies required for the current repo
- **Status:** complete

### Phase 4: Testing & Verification
- [x] Run the frontend build
- [x] Fix regressions surfaced by the build
- [x] Record verification results in `progress.md`
- **Status:** complete

### Phase 5: Delivery
- [x] Summarize deliverables and tradeoffs
- [x] Deliver status and verification details to the user
- **Status:** complete

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Use the reference zip as the primary source of truth for UI rewrite | The user asked for a complete rewrite and pixel-level restoration based on that frontend folder. |
| Treat the current `frontend/` app as replaceable rather than incrementally editable | The existing app is structurally different from the reference, so incremental patching would add unnecessary mismatch risk. |
| Recreate the reference UI with the current frontend stack instead of importing the reference dependencies wholesale | The reference app depends on Tailwind 4, Firebase, Motion, Lucide, and Gemini-specific services that are not part of the current project and would add avoidable migration risk. |
| Map current repo data into the reference app's information architecture | The current backend exposes tasks and logs, so the rewritten UI should keep those data sources while changing the presentation layer to match the reference design. |

## Errors Encountered
| Error | Resolution |
|-------|------------|
| `npm run build` failed because `InputBox.tsx` and `Sidebar.tsx` still contained unused symbols under strict TypeScript settings | Removed the unused prop/import so the rewritten frontend could build cleanly without changing runtime behavior. |

## Completion Summary
- **Status:** Complete (2026-03-17)
- **Tests:** Passed (`npm run build` in `/Users/zata/code/koda/frontend`)
- **Deliverables:** `frontend/src/App.tsx`, `frontend/src/index.css`, `frontend/src/components/InputBox.tsx`, `frontend/src/components/Sidebar.tsx`
- **Notes:** Recreated the reference dashboard with the existing React/Vite stack and mapped current task/log APIs into the reference app's requirement list, timeline, PRD panel, feedback flow, sticky header, and footer layout.

## Follow-up Extension: 2026-03-17

### Goal
- Keep the desktop requirement rail and feedback composer fixed while adjacent detail content scrolls.
- Support direct paste of images or files into the feedback composer.
- Split active and completed work into separate dashboard views.
- Preserve deleted and modified requirements, with modifications appended to history instead of overwriting prior execution context.

### Current Phase
- Phase 5 - Delivery

### Planned Phases

#### Phase 1: Discovery
- [x] Inspect the current dashboard layout and composer implementation
- [x] Inspect task/media backend capabilities and schema constraints
- [x] Confirm how modified requirements should affect history
- **Status:** complete

#### Phase 2: Planning & Structure
- [x] Finalize Active / Completed / Changes view behavior
- [x] Finalize requirement-change log format for append-only history
- [x] Finalize attachment upload flow for images and generic files
- **Status:** complete

#### Phase 3: Implementation
- [x] Add dedicated completed-task and changed-task views
- [x] Add requirement edit/delete flows with append-only change logs
- [x] Add desktop-fixed feedback composer behavior
- [x] Add pasted image/file attachment support
- **Status:** complete

#### Phase 4: Testing & Verification
- [x] Run frontend build
- [x] Run relevant automated tests
- [x] Record results in `progress.md`
- **Status:** complete

#### Phase 5: Delivery
- [x] Summarize the archive/composer/attachment changes
- [x] Deliver status, verification, and residual caveats
- **Status:** complete

### Follow-up Decisions
| Decision | Rationale |
|----------|-----------|
| Use separate dashboard modes for active, completed, and changed requirements | This gives completed work its own interface and keeps deleted/modified requirements visible without mixing them into the active queue. |
| Record requirement edits as appended history entries instead of overwriting the original brief | The user explicitly wants prior executed context preserved when a requirement changes. |
| Implement generic file paste as attachment uploads that create markdown links in the log body | The current schema only models image fields, so markdown links add file support without a risky database migration. |

### Follow-up Completion Summary
- **Status:** Complete (2026-03-17)
- **Tests:** Passed (`npm run build` in `/Users/zata/code/koda/frontend`; `uv run pytest -q`; `PYTHONPYCACHEPREFIX=/tmp/koda-pyc python3 -m py_compile dsl/api/media.py dsl/api/tasks.py dsl/services/media_service.py dsl/services/task_service.py dsl/schemas/task_schema.py dsl/models/enums.py`)
- **Deliverables:** `frontend/src/App.tsx`, `frontend/src/index.css`, `frontend/src/api/client.ts`, `frontend/src/types/index.ts`, `dsl/api/media.py`, `dsl/api/tasks.py`, `dsl/services/media_service.py`, `dsl/services/task_service.py`, `dsl/schemas/task_schema.py`, `dsl/models/enums.py`
