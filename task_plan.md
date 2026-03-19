# Task Plan: Merge Reusable Recipes From `justfile copy`

**Goal**: Compare `/Users/zata/code/koda/justfile copy` against the active `justfile`, import the recipes that are actually supported by this repository, and leave template-only or unsafe-to-port logic out of the main `justfile`.
**Started**: 2026-03-19

## Current Phase
All phases complete ✅

## Phases

### Phase 1: Discovery
- [x] Compare the current `justfile` and `justfile copy`
- [x] Check whether copied recipes have supporting scripts or files in this repository
- [x] Identify which copied recipes are template-specific and should be excluded
- **Status:** complete

### Phase 2: Implementation
- [x] Merge supported recipes into `justfile`
- [x] Preserve current repo-specific recipes such as `dsl-dev`, frontend helpers, and existing docs commands
- [x] Avoid importing template-only `copy` behavior
- **Status:** complete

### Phase 3: Verification
- [x] Run `just --list`
- [x] Run a targeted `just` recipe check for the merged commands
- [x] Record which recipes were merged versus skipped
- **Status:** complete

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Treat repo-local support files under `scripts/` as the gate for importing copied recipes | A recipe without its backing script or files would just add dead commands |
| Skip the `copy` recipe from `justfile copy` | It is still template-oriented, references `config.toml`, and hard-codes the old template project name |
| Keep existing `dsl-dev`, frontend, and basic sync recipes as the base | They already match this repository's current workflow and docs |

## Completion Summary
- **Status:** Complete (2026-03-19)
- **Tests:**
  - `just --list` -> PASS
  - `just --summary` -> PASS
  - `just --dry-run export-env-zip /tmp/koda-env.zip` -> PASS
  - `just --dry-run worktree-doctor demo-branch` -> PASS
  - `just --dry-run full-sync true` -> PASS
  - `git diff --check -- justfile task_plan.md findings.md progress.md` -> PASS
- **Deliverables:**
  - `justfile` - merged reusable recipes from `justfile copy`, upgraded `docs-serve`, added optional completion support to `full-sync`, and imported release/worktree/test/env helper recipes without the template-only `copy` recipe
  - `task_plan.md`, `findings.md`, `progress.md` - recorded merge scope, rationale, and verification evidence

---

# Task Plan: PRD Output Must Include AI-Summarized Requirement Name

**Goal**: Make the PRD generation contract explicitly require both the original requirement title and an AI-summarized requirement name at the top of the generated PRD, with prompt logic that is testable, documented, and compatible with the existing `tasks/prd-{task_id[:8]}.md` file flow and stage transitions.
**Started**: 2026-03-19

## Phases

### Phase 1: Discovery
- [x] Inspect the PRD generation entrypoint and current PRD file read path
- [x] Identify the best extraction point for a testable prompt builder
- [x] Locate docs and tests that define or should define the PRD output contract
- **Status:** complete

### Phase 2: Implementation
- [x] Add a dedicated PRD prompt builder that encodes AI-generated name, original title, fallback behavior, and fixed output path
- [x] Switch PRD generation to reuse the prompt builder without changing stage flow
- [x] Keep `get_task_prd_file` compatibility intact and add regression coverage around it
- **Status:** complete

### Phase 3: Verification
- [x] Add regression tests for the prompt contract and PRD file path expectations
- [x] Update operator docs and manual validation checklist
- [x] Run focused tests and `uv run mkdocs build`
- **Status:** complete

## Current Phase
All phases complete ✅

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Preserve the existing PRD file path contract `tasks/prd-{task_id[:8]}.md` | Frontend polling and API reading already depend on that exact location |
| Make the new behavior prompt-contract based instead of adding structured persistence | The requirement explicitly says no new DB/API field is needed and no frontend structural change is required |
| Validate compatibility by testing both the prompt builder and `get_task_prd_file` directly | This locks the new output contract and the unchanged read path without needing a full Codex integration test |

## Completion Summary
- **Status:** Complete (2026-03-19)
- **Tests:**
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_codex_runner.py tests/test_tasks_api.py -q` -> PASS (`9 passed`)
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_task_service.py tests/test_codex_runner.py tests/test_tasks_api.py -q` -> PASS (`14 passed`)
  - `UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build` -> PASS (upstream Material 2.0 warning only)
  - `npm ci` -> PASS
  - `npm run build` -> PASS
- **Deliverables:**
  - `dsl/services/codex_runner.py` - extracted `build_codex_prd_prompt(...)` and wired `run_codex_prd` to reuse it
  - `tests/test_codex_runner.py`, `tests/test_tasks_api.py` - regression coverage for prompt contract and fixed PRD file lookup
  - `docs/guides/codex-cli-automation.md`, `docs/core/prompt-management.md`, `docs/core/ai-assets.md`, `docs/architecture/system-design.md`, `docs/dev/evaluation.md` - synchronized PRD output contract and manual verification guidance
  - `frontend/src/App.tsx` - validation checklist now mentions `需求名称（AI 归纳）`

---

# Task Plan: Resolve Configuration Guide Command Drift

**Goal**: Remove the last README/onboarding command inconsistency by updating `docs/guides/configuration.md` to use the same contributor-facing startup path and validation wording as `README.md` and `docs/getting-started.md`.
**Started**: 2026-03-19

## Current Phase
All phases complete ✅

## Phases

### Phase 1: Discovery
- [x] Re-read the review blocker and confirm which command description still drifts
- [x] Compare `README.md`, `docs/getting-started.md`, `docs/guides/configuration.md`, and `justfile`
- **Status:** complete

### Phase 2: Implementation
- [x] Replace the outdated `just sync` onboarding row with the README-standard install commands
- [x] Add the missing frontend install step so the config guide mirrors the documented quick-start path
- **Status:** complete

### Phase 3: Verification
- [x] Run `just docs-build`
- [x] Run `git diff --check` on the touched files
- [x] Re-scan the command strings across the affected docs
- **Status:** complete

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Keep the follow-up scoped to `docs/guides/configuration.md` plus planning logs | The blocker is a single remaining command-drift defect, not a broader doc rewrite |
| Promote the README-standard startup path directly in the config guide before the supporting command table | This satisfies the PRD requirement that core onboarding docs use the same command names and descriptions |
| Preserve the explicit `just docs-build` maintenance reminder in the same section | The review and PRD both require documentation validation to remain visible |

## Completion Summary
- **Status:** Complete (2026-03-19)
- **Tests:**
  - `just docs-build` -> PASS
  - `git diff --check -- docs/guides/configuration.md task_plan.md findings.md progress.md` -> PASS
  - `rg -n "just sync|uv sync|cd frontend && npm install|just dsl-dev|just docs-build" docs/guides/configuration.md README.md docs/getting-started.md` -> PASS
- **Deliverables:**
  - `docs/guides/configuration.md` - command section now mirrors the README/getting-started onboarding path and includes the missing frontend install step
  - `task_plan.md`, `findings.md`, `progress.md` - recorded the blocker analysis, implementation scope, and verification evidence for this follow-up

# Task Plan: Close Agent Guide Command Drift

**Goal**: Align `AGENTS.md` and `CLAUDE.md` with the repository-standard onboarding and documentation commands already used by `README.md` and the core MkDocs pages, so no repo-level guide still points contributors or AI agents at `uv pip install` or raw MkDocs commands.
**Started**: 2026-03-19

## Current Phase
All phases complete ✅

## Phases

### Phase 1: Discovery
- [x] Confirm which repository-level docs still diverge from the updated README / MkDocs onboarding flow
- [x] Re-check `justfile` so the repair uses the real command entrypoints
- **Status:** complete

### Phase 2: Implementation
- [x] Replace outdated dependency-install guidance in `AGENTS.md` and `CLAUDE.md`
- [x] Add the matching frontend install, local dev, and docs validation commands so the repo-level guides stay aligned with README
- [x] Fix any adjacent Markdown formatting issue encountered while touching the same docs
- **Status:** complete

### Phase 3: Verification
- [x] Run `just docs-build`
- [x] Run `git diff --check` on the touched documentation files
- [x] Re-scan the relevant docs for the expected command set and confirm `uv pip install` no longer appears there
- **Status:** complete

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Keep the fix limited to `AGENTS.md` and `CLAUDE.md` plus planning logs | The README / MkDocs pages were already aligned; the remaining blocker was isolated to repository-level agent guidance |
| Standardize on `just` entrypoints for docs commands in agent-facing guidance | The repo already exposes `docs-serve`, `docs-build`, and `dsl-dev` via `justfile`, so repeating raw underlying commands reintroduces drift risk |
| Fix the stray trailing code fence in `CLAUDE.md` while already editing that file | It was a localized Markdown bug in the same touched doc and leaving it would preserve avoidable formatting noise |

## Completion Summary
- **Status:** Complete (2026-03-19)
- **Tests:**
  - `just docs-build` -> PASS
  - `git diff --check -- AGENTS.md CLAUDE.md README.md docs/index.md docs/getting-started.md docs/guides/configuration.md docs/guides/dsl-development.md` -> PASS
  - `rg -n "uv pip install|uv sync|cd frontend && npm install|just dsl-dev|just docs-build" AGENTS.md CLAUDE.md README.md docs/getting-started.md docs/guides/configuration.md docs/guides/dsl-development.md` -> PASS
- **Deliverables:**
  - `AGENTS.md` - repository-level agent guide now matches the unified Python install, frontend install, local dev, and docs validation commands
  - `CLAUDE.md` - companion agent guide now matches the same command set and no longer ends with a stray Markdown code fence

# Task Plan: Refresh README And Core Docs

**Goal**: Replace the outdated template-oriented README narrative with a Koda / DevStream Log workspace entry point, align the core MkDocs onboarding pages with the same commands and addresses, and make documentation maintenance plus `just docs-build` verification explicit.
**Started**: 2026-03-19

## Current Phase
All phases complete ✅

## Phases

### Phase 1: Discovery
- [x] Read the PRD and identify the required entry-path pages
- [x] Compare `README.md`, `docs/index.md`, `docs/getting-started.md`, and `docs/guides/configuration.md` against `justfile`
- [x] Confirm whether `mkdocs.yml` nav changes are needed for this scope
- **Status:** complete

### Phase 2: Implementation
- [x] Rewrite `README.md` as the repository landing page for Koda / DevStream Log
- [x] Synchronize `docs/index.md`, `docs/getting-started.md`, and `docs/guides/configuration.md` with the same startup commands and maintenance rules
- [x] Update any nearby guide content that still conflicts with the current documented workflow
- **Status:** complete

### Phase 3: Verification
- [x] Run `just docs-build`
- [x] Review final diffs for command, address, and navigation consistency
- **Status:** complete

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Keep the change set focused on README plus core onboarding/overview docs | The PRD explicitly treats this as a documentation realignment, not a full-site rewrite |
| Treat `justfile` as the command source of truth | The PRD requires command consistency across README and MkDocs pages |
| Leave `mkdocs.yml` nav unchanged unless a page path/title actually changes | FR-11 forbids meaningless navigation churn |
| Preserve `docs/api/references.md` as a linked deep-reference page instead of duplicating API member details elsewhere | FR-8 defines it as the sole object-level authority |

## Completion Summary
- **Status:** Complete (2026-03-19)
- **Tests:**
  - `just docs-build` -> PASS
  - `git diff --check -- README.md docs/index.md docs/getting-started.md docs/guides/configuration.md docs/guides/dsl-development.md` -> PASS
- **Deliverables:**
  - `README.md` - rewritten as the Koda / DevStream Log repository landing page with quick start, project map, docs map, and documentation maintenance rules
  - `docs/index.md` - aligned site overview, current capability summary, documentation map, and maintenance rules
  - `docs/getting-started.md` - synchronized minimal startup path, addresses, and pre-submit docs validation rule
  - `docs/guides/configuration.md` - synchronized command source-of-truth guidance plus documentation update checklist
  - `docs/guides/dsl-development.md` - corrected workflow-stage reality and tightened documentation update expectations

---

# Task Plan: Put All New Worktrees Under ../task

**Goal**: Change new task worktree creation so the default root is always `repo_root_path.parent / "task"`, while keeping downstream consumers on `Task.worktree_path`, preserving branch-only script compatibility, and aligning tests/docs with the new path rule.
**Started**: 2026-03-19

## Current Phase
All phases complete ✅

## Phases

### Phase 1: Discovery
- [x] Inspect the current worktree path builder and creation strategies
- [x] Identify downstream flows that depend on stored `Task.worktree_path`
- [x] Confirm which docs and tests must change with the new root rule
- **Status:** complete

### Phase 2: Implementation
- [x] Add a shared helper for the `../task` root and ensure the directory exists before creation
- [x] Update fallback, path-aware script, and branch-only script behaviors to use or validate the new root
- [x] Keep `TaskService.start_task()` persisting the returned absolute path without schema changes
- **Status:** complete

### Phase 3: Verification
- [x] Add regression coverage for fallback, path-aware script, and branch-only path validation behavior
- [x] Run focused backend tests for worktree/task flows
- [x] Run `uv run mkdocs build`
- **Status:** complete

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Treat `dsl/services/git_worktree_service.py` as the single path-policy source | The PRD explicitly keeps downstream APIs and completion logic transparent to the root-directory strategy |
| Keep `Task.worktree_path` unchanged as the stored field | Existing APIs, completion flow, and historical records already depend on this absolute path |
| Resolve branch-only script results from `git worktree list --porcelain` instead of guessing a path | Compatibility scripts may choose their own child directory names, so Koda must validate the real created path rather than infer one |

## Completion Summary
- **Status:** Complete (2026-03-19)
- **Tests:**
  - `UV_CACHE_DIR=/tmp/uv-cache uv run python -m py_compile dsl/services/git_worktree_service.py tests/test_git_worktree_service.py tests/test_task_service.py` -> PASS
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_git_worktree_service.py tests/test_task_service.py -q` -> PASS (`10 passed`)
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_git_worktree_service.py tests/test_task_service.py tests/test_codex_runner.py -q` -> PASS (`17 passed`)
  - `UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build` -> PASS (Material 2.0 upstream warning banner only)
- **Deliverables:**
  - `dsl/services/git_worktree_service.py` - centralized `../task` root helper, pre-create root directory, branch-only runtime path resolution, and containment validation
  - `tests/test_git_worktree_service.py` - fallback, path-aware script, branch-only path validation, and real Git completion regressions
  - `tests/test_task_service.py` - `TaskService.start_task()` persistence coverage for the new `../task/...` path
  - `docs/index.md`, `docs/architecture/system-design.md`, `docs/database/schema.md`, `docs/dev/evaluation.md` - synchronized path examples and manual verification guidance

---

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

---

# Task Plan: Application Timezone Contract To UTC+8

**Goal**: Keep database timestamps as UTC-semantic naive datetimes while making backend API output, frontend rendering/grouping, chronicle export, and related docs consistently use `APP_TIMEZONE=Asia/Shanghai` with explicit `+08:00` offsets.
**Started**: 2026-03-19

## Current Phase
All phases complete ✅

## Phases

### Phase 1: Discovery
- [x] Read the confirmed PRD and extract the storage-vs-display timezone contract
- [x] Locate backend time helpers, chronicle service, and response schema/API serialization points
- [x] Locate frontend task/log/timeline/chronicle time formatting and grouping logic
- [x] Confirm test/doc surfaces that must move with the code changes
- **Status:** complete

### Phase 2: Backend Implementation
- [x] Add `APP_TIMEZONE` setting and shared timezone conversion/serialization helpers
- [x] Route API-facing datetime fields through explicit `+08:00` serialization
- [x] Replace direct `isoformat()` / string slicing in `dsl/services/chronicle_service.py`
- [x] Decide and implement run-log timezone formatter or explicit documentation
- **Status:** complete

### Phase 3: Frontend Implementation
- [x] Add shared datetime utility for parsing, formatting, day grouping, and duration calculation
- [x] Replace time formatting logic in task cards, log cards, stream view, and chronicle view
- [x] Ensure grouping uses UTC+8 natural days instead of raw string prefixes
- **Status:** complete

### Phase 4: Verification
- [x] Add regression coverage for legacy UTC naive records, cross-day boundaries, export formatting, and sorting/grouping stability
- [x] Update docs and release-facing notes for the UTC storage / UTC+8 display contract
- [x] Run focused backend tests, frontend build, and `uv run mkdocs build`
- **Status:** complete

### Phase 5: Blocking Review Fixes
- [x] Add missing timezone data/runtime compatibility for Windows or hosts without a system IANA database
- [x] Remove remaining hard-coded `Asia/Shanghai` / `+08:00` assumptions outside the configuration contract
- [x] Re-run focused verification for backend tests, frontend build, and MkDocs build after the fixes
- **Status:** complete

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Preserve UTC-semantic naive datetimes in the database | Existing models and helper semantics already rely on this contract; bulk-shifting stored data would corrupt history |
| Centralize timezone handling in shared backend/frontend utilities | Current formatting/grouping logic is duplicated and inconsistent across APIs, markdown export, and UI components |
| Treat explicit offset serialization as the API contract | Avoids browser/host locale guessing and gives the frontend deterministic input |

## Completion Summary
- **Status:** Complete (2026-03-19)
- **Tests:**
  - `UV_CACHE_DIR=/tmp/uv-cache uv run python -m py_compile utils/settings.py utils/helpers.py utils/logger.py dsl/schemas/base.py dsl/schemas/task_schema.py dsl/schemas/dev_log_schema.py dsl/schemas/project_schema.py dsl/schemas/run_account_schema.py dsl/schemas/email_settings_schema.py dsl/schemas/webdav_settings_schema.py dsl/services/codex_runner.py dsl/services/chronicle_service.py dsl/api/chronicle.py tests/test_logger.py tests/test_timezone_contract.py` -> PASS
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_timezone_contract.py tests/test_logger.py tests/test_project_service.py tests/test_task_service.py tests/test_codex_runner.py -q` -> PASS (`25 passed`)
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` -> PASS (`38 passed, 1 warning`)
  - `cd frontend && npm run build` -> PASS
  - `UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build` -> PASS (upstream Material 2.0 warning only)
- **Deliverables:**
  - `utils/settings.py`, `utils/helpers.py`, `utils/logger.py` - app timezone config, shared datetime conversion helpers, and explicit-offset log formatter
  - `dsl/schemas/base.py`, `dsl/schemas/*.py` - shared response datetime serialization for API models
  - `dsl/api/chronicle.py`, `dsl/services/chronicle_service.py`, `dsl/services/codex_runner.py` - timezone-normalized chronicle filters/export and task log headers
  - `frontend/src/utils/datetime.ts`, `frontend/src/App.tsx`, `frontend/src/components/*.tsx` - shared UTC+8 parsing/display/grouping/duration logic

## Reopened Notes (2026-03-19)
- Self-review found two blocking gaps after the initial completion record:
  1. `APP_TIMEZONE` validation depends on `zoneinfo` data, but `tzdata` was not declared for Windows / stripped environments.
  2. The configuration contract is not fully end-to-end because some frontend utilities and chronicle export copy still hard-code `Asia/Shanghai` or `+08:00`.
- Resolution:
  - Added `tzdata` to runtime dependencies and refreshed `uv.lock`.
  - Added a read-only `/api/app-config` route, switched chronicle timezone copy to shared helpers, and made the frontend datetime utility consume runtime timezone config.
  - Reran backend tests, full `pytest`, frontend build, and MkDocs build successfully.
  - `tests/test_timezone_contract.py`, `tests/test_logger.py` - regression coverage for UTC storage semantics, cross-day export/grouping, and log formatter offsets
  - `docs/guides/configuration.md`, `docs/database/schema.md`, `docs/guides/dsl-development.md`, `docs/dev/release-notes.md`, `mkdocs.yml` - synchronized contract and release documentation
