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
