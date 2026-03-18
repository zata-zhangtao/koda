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
