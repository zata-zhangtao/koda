# Progress Log

## Session: 2026-03-18

### Current Status
- **Phase:** complete
- **Started:** 2026-03-18

### Actions Taken
- Inspected the current WebDAV restore behavior and confirmed that only `repo_path` was persisted for projects.
- Confirmed the app already uses a lightweight startup migration hook and extended it for new `Project` columns.
- Added stored Git fingerprint fields (`repo_remote_url`, `repo_head_commit_hash`) plus consistency comparison helpers in `ProjectService`.
- Updated project create/relink behavior to capture fingerprints, reject wrong-remote relinks, and preserve synced commit baselines for drift comparison.
- Refreshed project fingerprints before WebDAV upload so synced DB snapshots carry fresh repo metadata.
- Extended project API responses with current-vs-stored consistency fields and blocked unsafe “open project” / worktree-start flows on wrong-repo bindings.
- Updated the frontend project panel to show `Need relink`, `Wrong repo`, `Commit drift`, and `Pending sync` states.
- Replaced the old fake `.git` tests with real temporary Git repositories.
- Synchronized schema, configuration, and migration documentation.

### Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| `UV_CACHE_DIR=/tmp/uv-cache uv run python -m py_compile dsl/models/project.py dsl/schemas/project_schema.py dsl/services/project_service.py dsl/api/projects.py dsl/services/task_service.py dsl/services/webdav_service.py dsl/app.py tests/test_project_service.py` | Edited Python files compile | Passed | passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_project_service.py tests/test_task_service.py -q` | Project fingerprint + task regressions pass | 11 tests passed | passed |
| `npm run build` | Frontend compiles with new project consistency states | Build succeeded | passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build` | Documentation remains valid | Build succeeded | passed |

### Errors
| Error | Resolution |
|-------|------------|
| Initial backend patch used nested dataclasses with an invalid decorator combination | Removed the incorrect `@staticmethod` wrapping and rechecked compile/tests |

## Session: 2026-03-18 Database Bootstrap Hotfix

### Current Status
- **Phase:** complete with residual unrelated test hang
- **Started:** 2026-03-18

### Actions Taken
- Reproduced the failure signature indirectly by confirming `data/dsl.db` existed as a zero-byte file while requests were already reaching SQLAlchemy.
- Verified `Base.metadata` already included `projects` and `email_settings`, which ruled out missing ORM model registration.
- Moved schema bootstrap and lightweight column patches into a shared `ensure_database_schema_ready()` helper in `utils.database`.
- Introduced `DatabaseSession` so first-use `SessionLocal()` creation now bootstraps missing tables even if FastAPI lifespan is skipped or delayed.
- Updated `dsl.app` startup to reuse the same shared bootstrap path before running project fingerprint backfill.
- Added `tests/test_database.py` to cover a brand-new SQLite file opened only through a session factory.
- Synchronized bootstrap behavior in the operator docs.

### Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| `UV_CACHE_DIR=/tmp/uv-cache uv run python -m py_compile utils/database.py dsl/app.py tests/test_database.py` | Edited backend files compile | Passed | passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_database.py tests/test_project_service.py tests/test_task_service.py -q` | Database bootstrap regression and affected backend flows pass | `12 passed` | passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_terminal_launcher.py tests/test_logger.py -q` | Unrelated backend utility tests still pass | `7 passed` | passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build` | Docs remain valid after bootstrap doc updates | Build succeeded | passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` | Entire backend suite passes | Hung while reaching `tests/test_codex_runner.py` | blocked |

### Errors
| Error | Resolution |
|-------|------------|
| Initial smoke test script failed with `KeyError: 'TEMP_REPO_PATH'` | Exported the temp shell variables before invoking Python |
| Full `pytest -q` did not terminate once it reached `tests/test_codex_runner.py` | Isolated the DB-related suites and recorded the remaining hang as unrelated residual risk |
