# Progress Log

## Session: 2026-03-19 PRD Output Contract

### Current Status
- **Phase:** complete
- **Started:** 2026-03-19

### Actions Taken
- Read the current planning files and confirmed they belonged to prior tasks, then initialized a new plan section for this PRD output-contract task.
- Located the current PRD generation path in `dsl/services/codex_runner.py` and confirmed the prompt is built inline in `run_codex_prd`.
- Confirmed the API compatibility point in `dsl/api/tasks.py:get_task_prd_file`, which reads `tasks/prd-{task_id[:8]}.md` with UTF-8 decoding.
- Identified documentation areas that mention PRD prompt behavior but do not yet codify the new AI-summarized requirement name contract.
- Verified that `tests/test_codex_runner.py` already covers prompt-builder helpers, making it the right place to add regression assertions for a new PRD prompt builder.
- Found a doc drift in `docs/guides/codex-cli-automation.md`: it still claims wildcard PRD file discovery instead of the fixed filename contract used by the backend.
- Confirmed a second doc drift in `docs/core/prompt-management.md`, which still treats the PRD prompt as inline-only and references wildcard PRD filenames.
- Located an existing generated validation checklist in `frontend/src/App.tsx`; it is a low-risk place to add the manual check for `需求名称（AI 归纳）`.
- Confirmed there is no direct test coverage yet for PRD prompt assembly or `get_task_prd_file`, so both need focused regression tests as part of the verification phase.
- Chosen verification split: add prompt-contract assertions in `tests/test_codex_runner.py` and add a direct compatibility test around `dsl/api/tasks.py:get_task_prd_file`.

### Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_codex_runner.py tests/test_tasks_api.py -q` | Prompt contract and PRD file lookup regressions pass | `9 passed` | passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_task_service.py tests/test_codex_runner.py tests/test_tasks_api.py -q` | Prompt contract, task workflow compatibility, and PRD file lookup regressions pass | `14 passed` | passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build` | Documentation remains valid after contract updates | Build succeeded (upstream Material 2.0 warning only) | passed |
| `npm ci` | Frontend dependencies install successfully | Installed 211 packages | passed |
| `npm run build` | Frontend compiles after checklist update | Build succeeded | passed |

### Errors
| Error | Resolution |
|-------|------------|
| `npm run build` initially failed with `sh: tsc: command not found` | Installed frontend dependencies with `npm ci` and reran the build successfully |

## Session: 2026-03-19 Worktree Root Migration

### Current Status
- **Phase:** complete
- **Started:** 2026-03-19

### Actions Taken
- Read the current planning skill instructions and confirmed the project already has persistent planning files.
- Scanned the repo for all worktree-related code paths, tests, API consumers, and docs references.
- Verified the current implementation centralizes worktree creation in `dsl/services/git_worktree_service.py`.
- Confirmed the only uncommitted workspace file before changes is the new PRD `tasks/prd-7e932cad.md`.
- Verified that no existing docs already describe `../task`, so the new root rule must be introduced explicitly rather than corrected in place.
- Added a new `build_task_worktree_root_path()` helper and changed the default task worktree path to `<repo-parent>/task/<repo>-wt-<task8>`.
- Updated `create_task_worktree()` to pre-create `../task/`, keep path-aware script arguments aligned with the new root, and resolve branch-only results from `git worktree list --porcelain`.
- Added containment validation so branch-only scripts now fail with a direct error when the actual created path is outside `../task/`.
- Added real Git regressions for fallback creation, path-aware script invocation, branch-only invalid path rejection, and `TaskService.start_task()` path persistence.
- Synchronized docs with the new default path example and explicit manual verification guidance.

### Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| `UV_CACHE_DIR=/tmp/uv-cache uv run python -m py_compile dsl/services/git_worktree_service.py tests/test_git_worktree_service.py tests/test_task_service.py` | Edited backend files and tests compile | Passed | passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_git_worktree_service.py tests/test_task_service.py -q` | Worktree creation + task persistence regressions pass | `10 passed` | passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_git_worktree_service.py tests/test_task_service.py tests/test_codex_runner.py -q` | Worktree path change does not regress completion/task orchestration flows | `17 passed` | passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build` | Docs remain valid after path-rule updates | Build succeeded; Material 2.0 upstream warning banner only | passed |

### Errors
| Error | Resolution |
|-------|------------|
| None | N/A |

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

## Session: 2026-03-18 Deterministic Complete Flow

### Current Status
- **Phase:** complete
- **Started:** 2026-03-18

### Actions Taken
- Confirmed that `Complete` currently relies on a Codex prompt and only covers `commit` plus `git rebase main`.
- Inspected `TaskService.start_task` and verified worktree creation only probes a narrow subset of script names.
- Reviewed `~/code/zata_code_template/scripts/git_worktree.sh` and `git_worktree_merge.sh` to mirror their create/cleanup patterns without introducing an unwanted push step.
- Chose to move completion into backend-controlled Git commands so the requested sequence is exact and testable.
- Added `dsl/services/git_worktree_service.py` to centralize task branch naming, worktree creation, and cleanup-script lookup.
- Switched `TaskService.start_task` to the shared worktree helper so repo-local template-style scripts can be reused consistently.
- Replaced prompt-driven completion with deterministic Git automation: `git add .`, summary-based `git commit -m ...`, `git rebase main`, merge through the worktree already holding `main`, then cleanup.
- Added automatic Codex conflict resolution when `git rebase main` or the final merge enters a real conflict state.
- Updated the completion API, UI copy, and operator docs to reflect summary-based commits, main-worktree merging, and Codex conflict repair.

### Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| `UV_CACHE_DIR=/tmp/uv-cache uv run python -m py_compile dsl/services/git_worktree_service.py dsl/services/task_service.py dsl/services/codex_runner.py dsl/api/tasks.py tests/test_codex_runner.py tests/test_git_worktree_service.py` | Edited backend files and tests compile | Passed | passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_codex_runner.py tests/test_git_worktree_service.py tests/test_task_service.py -q` | Completion orchestration, real Git worktree flow, and task stage regressions pass | `14 passed` | passed |
| `UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build` | Documentation remains valid after completion-flow updates | Build succeeded; Material 2.0 upstream warning only | passed |

### Errors
| Error | Resolution |
|-------|------------|
| Original design assumed Koda could always `checkout main` in a chosen worktree | Switched merge execution to reuse the worktree that already has `main` checked out, with checkout only as a fallback |
| Initial completion design used the raw task title as the commit message | Changed commit-subject generation to prefer `requirement_brief` / task summary, then fall back through recent logs only if needed |
