# Task Plan: Preserve Repo Fingerprints Across WebDAV Restore

**Goal**: Make cross-computer WebDAV restores verify more than `repo_path` by persisting project Git fingerprints (`origin` remote + `HEAD` commit), comparing them against the current machine, and surfacing actionable repair states in the UI.
**Started**: 2026-03-18

## Current Phase
All phases complete ✅

## Phases

### Phase 1: Discovery
- [x] Inspect the existing WebDAV restore flow and current `Project` persistence model
- [x] Confirm how schema changes are applied to existing SQLite databases
- [x] Decide how remote/commit verification should behave during relink
- **Status:** complete

### Phase 2: Implementation
- [x] Add persisted project Git fingerprint columns and startup migration/backfill support
- [x] Refresh stored fingerprints before WebDAV upload so synced DB snapshots stay current
- [x] Reject relinking to a different remote while allowing same-remote commit drift to remain visible
- [x] Expose path/remote/head consistency in project API responses
- [x] Update the project management UI with distinct states for relink, wrong repo, and commit drift
- **Status:** complete

### Phase 3: Verification
- [x] Replace path-only project tests with real Git-backed fingerprint tests
- [x] Run focused backend tests, frontend build, and MkDocs build
- [x] Synchronize operator-facing docs
- **Status:** complete

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Store normalized `origin` remote plus `HEAD` commit in `Project` | Path alone is machine-local and cannot prove the restored repo is the same codebase or revision |
| Refresh project fingerprints just before WebDAV upload | Ensures the synced database represents the latest accepted local repo baseline |
| Reject remote mismatch but only warn on commit drift | Binding the wrong repo is unsafe, but being on a newer commit of the same repo can be legitimate |
| Preserve stored fingerprint during relink when remote matches | Keeps the synced baseline available for comparison instead of immediately overwriting it |
| Add lightweight startup migration/backfill for the new nullable columns | Existing SQLite databases need these fields without requiring manual rebuilds |

## Completion Summary
- **Status:** Complete (2026-03-18)
- **Tests:**
  - `UV_CACHE_DIR=/tmp/uv-cache uv run python -m py_compile dsl/models/project.py dsl/schemas/project_schema.py dsl/services/project_service.py dsl/api/projects.py dsl/services/task_service.py dsl/services/webdav_service.py dsl/app.py tests/test_project_service.py` -> PASS
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_project_service.py tests/test_task_service.py -q` -> PASS
  - `npm run build` -> PASS
  - `UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build` -> PASS
- **Deliverables:**
  - `dsl/models/project.py`, `dsl/schemas/project_schema.py`, `dsl/services/project_service.py`, `dsl/api/projects.py` - persisted repo fingerprints plus consistency comparison API
  - `dsl/app.py` - startup migration and missing-fingerprint backfill
  - `dsl/services/webdav_service.py` - fingerprint refresh before upload plus richer restore hint
  - `frontend/src/App.tsx`, `frontend/src/types/index.ts`, `frontend/src/index.css` - UI states for relink / wrong repo / commit drift
  - `tests/test_project_service.py` - Git-backed regression coverage for normalized remote, relink validation, commit drift, and fingerprint refresh
  - `docs/database/schema.md`, `docs/database/migrations.md`, `docs/guides/configuration.md` - synchronized operator docs

---

# Task Plan: Defensive SQLite Bootstrap For Empty Databases

**Goal**: Prevent API requests such as `POST /api/projects` and `GET /api/email-settings` from failing with `sqlite3.OperationalError: no such table ...` when a fresh SQLite file exists before the FastAPI lifespan hook creates tables.
**Started**: 2026-03-18

## Current Phase
All phases complete with one unrelated residual test hang noted below ✅

## Phases

### Phase 1: Discovery
- [x] Confirm the live SQLite file was empty and missing all tables
- [x] Verify the ORM models were registered and the failure was bootstrap timing, not missing model definitions
- [x] Decide to centralize schema initialization instead of relying only on FastAPI lifespan
- **Status:** complete

### Phase 2: Implementation
- [x] Move reusable schema initialization and lightweight column patches into `utils.database`
- [x] Make `SessionLocal` self-bootstrap via a custom `DatabaseSession`
- [x] Reuse the shared initializer from `dsl.app` startup
- [x] Update operator documentation to reflect the new fallback path
- **Status:** complete

### Phase 3: Verification
- [x] Add regression coverage for opening a session against a brand-new SQLite file
- [x] Run targeted backend tests covering database, project, and task flows
- [x] Run `uv run mkdocs build`
- [ ] Get a clean completion from `tests/test_codex_runner.py` during full-suite execution
- **Status:** complete with residual unrelated hang

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Put schema bootstrap in `utils.database` instead of only `dsl.app` | Direct `SessionLocal()` usage exists in multiple services, so a lifespan-only fix would stay fragile |
| Keep the initialization idempotent and engine-scoped | Repeated calls from startup and session creation should be safe and cheap |
| Reuse the same helper for lightweight `ALTER TABLE` patches | Prevents startup and fallback paths from drifting apart |
| Add a regression test around a fresh SQLite file | This matches the reported failure mode more closely than unit-testing the helper in isolation |

## Completion Summary
- **Status:** Complete with residual unrelated test hang (2026-03-18)
- **Tests:**
  - `UV_CACHE_DIR=/tmp/uv-cache uv run python -m py_compile utils/database.py dsl/app.py tests/test_database.py` -> PASS
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_database.py tests/test_project_service.py tests/test_task_service.py -q` -> PASS (`12 passed`)
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_terminal_launcher.py tests/test_logger.py -q` -> PASS (`7 passed`)
  - `UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build` -> PASS
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` -> HANGS while reaching `tests/test_codex_runner.py`; not traced to this database patch
- **Deliverables:**
  - `utils/database.py` - shared schema bootstrap, incremental patches, and `DatabaseSession`
  - `dsl/app.py` - startup now reuses the shared bootstrap helper
  - `tests/test_database.py` - regression coverage for fresh SQLite session bootstrap
  - `docs/getting-started.md`, `docs/database/migrations.md`, `docs/database/schema.md`, `docs/guides/dsl-development.md` - synchronized bootstrap documentation

---

# Task Plan: Deterministic Complete Flow With Git Merge And Worktree Cleanup

**Goal**: Change the `Complete` action so Koda performs a deterministic Git sequence for worktree-backed tasks: `git add .`, `git commit -m "<task summary>"`, `git rebase main`, automatically let Codex resolve rebase/merge conflicts when they happen, then merge via the worktree that already holds `main`, and finally clean up the task worktree and branch. Align worktree lifecycle behavior with the reference scripts in `~/code/zata_code_template/scripts`.
**Started**: 2026-03-18

## Current Phase
All phases complete ✅

## Phases

### Phase 1: Discovery
- [x] Inspect the current `Complete` flow and confirm it only asks Codex to commit then rebase
- [x] Inspect task worktree creation behavior and current script detection
- [x] Review the reference worktree create/merge-cleanup scripts in `~/code/zata_code_template/scripts`
- **Status:** complete

### Phase 2: Implementation
- [x] Introduce shared worktree helpers for task branch naming and creation
- [x] Replace prompt-driven completion with backend-controlled Git commands and merge cleanup
- [x] Add Codex-assisted conflict resolution for `git rebase main` / merge conflicts
- [x] Update API/frontend copy and docs to reflect the new sequence
- **Status:** complete

### Phase 3: Verification
- [x] Add or update regression tests for completion success/failure and worktree creation
- [x] Run focused backend tests and `uv run mkdocs build`
- **Status:** complete

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Make `Complete` backend-driven instead of relying on Codex prompt execution | The requested Git order is exact and should be deterministic rather than prompt-dependent |
| Keep commit/rebase inside the task worktree but merge from whichever worktree already has `main` checked out | A Git worktree setup may not allow arbitrary `checkout main` in another worktree |
| Reuse the reference script pattern for cleanup when available, but keep a built-in fallback | The template repo already encodes worktree cleanup behavior, but Koda still needs to work when those scripts are absent |
| Use task summary / requirement brief as the primary commit subject source | The user explicitly asked not to reuse the raw task title as the commit message |
| Invoke Codex only when `rebase` / `merge` actually enters conflict state | Deterministic Git should remain the default, while Codex handles the ambiguous conflict-resolution step |

## Completion Summary
- **Status:** Complete (2026-03-18)
- **Tests:**
  - `UV_CACHE_DIR=/tmp/uv-cache uv run python -m py_compile dsl/services/git_worktree_service.py dsl/services/task_service.py dsl/services/codex_runner.py dsl/api/tasks.py tests/test_codex_runner.py tests/test_git_worktree_service.py` -> PASS
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_codex_runner.py tests/test_git_worktree_service.py tests/test_task_service.py -q` -> PASS (`14 passed`)
  - `UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build` -> PASS (upstream Material 2.0 warning only)
- **Deliverables:**
  - `dsl/services/git_worktree_service.py` - shared task branch naming, worktree creation, and cleanup-script discovery
  - `dsl/services/task_service.py` - task start flow now uses the shared worktree creation helper
  - `dsl/services/codex_runner.py` - deterministic completion flow, main-worktree merge routing, and Codex-assisted conflict resolution
  - `dsl/api/tasks.py` - completion API now passes task summary / requirement brief into the background Git flow
  - `frontend/src/App.tsx`, `frontend/src/api/client.ts` - updated user-facing completion messaging
  - `tests/test_codex_runner.py`, `tests/test_git_worktree_service.py` - regression coverage for completion orchestration and real Git worktree merge/cleanup
  - `docs/index.md`, `docs/architecture/system-design.md`, `docs/guides/codex-cli-automation.md`, `docs/core/prompt-management.md` - synchronized operator documentation
