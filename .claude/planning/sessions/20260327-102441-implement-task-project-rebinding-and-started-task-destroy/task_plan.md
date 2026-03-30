# Task Plan: Implement Task Project Rebinding And Started-Task Destroy

**Goal**: Implement the approved PRD at `tasks/prd-df3b22d8.md` by adding backlog-only project rebinding, a started-task destroy flow with required reason and cleanup semantics, synchronized frontend/detail rendering, regression tests, and documentation updates.
**Started**: 2026-03-26

## Phases

### Phase 1: Discovery
- [x] Read the current backend task update/delete/start flows and the frontend task detail/edit actions
- [x] Identify the existing database migration pattern, worktree cleanup hooks, and task log conventions
- [x] Confirm which docs and tests must change with the implementation
- **Status:** complete

### Phase 2: Backend Implementation
- [x] Extend task persistence/schema for `destroy_reason` and `destroyed_at`
- [x] Support backlog-only `project_id` updates with explicit lock errors
- [x] Add `POST /api/tasks/{task_id}/destroy` with running-task cancellation and worktree cleanup
- **Status:** complete

### Phase 3: Frontend Implementation
- [x] Add project rebinding controls and lock messaging to the requirement revision panel
- [x] Add started-task destroy UX with required reason input
- [x] Surface `destroy_reason` and `destroyed_at` in task detail/history views
- **Status:** complete

### Phase 4: Verification And Sync
- [x] Add or update regression tests for API/service behavior
- [x] Run relevant backend/frontend/doc validation
- [x] Sync `tasks/prd-df3b22d8.md` with actual delivery details
- **Status:** complete

## Current Phase
All phases complete ✅

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Reuse the existing `tasks/prd-df3b22d8.md` instead of creating a new PRD | The approved PRD already defines the scope for this implementation turn |
| Keep the old backlog delete path unless the task has already started | The PRD explicitly keeps lightweight delete for backlog and introduces destroy only for started tasks |
| Treat project rebinding as a backend-enforced lock, not only a frontend affordance | `start_task(...)` binds runtime worktree state to `project_id`, so the server must remain authoritative |

## Completion Summary
- **Status:** Complete (2026-03-27)
- **Tests:**
  - `uv run pytest tests/test_task_service.py tests/test_tasks_api.py -q` -> PASS (`28 passed, 2 warnings`)
  - `cd frontend && npm run build` -> PASS
  - `just docs-build` -> PASS
  - `git diff --check -- dsl/models/task.py dsl/schemas/task_schema.py dsl/services/task_service.py dsl/services/git_worktree_service.py dsl/api/tasks.py frontend/src/App.tsx frontend/src/api/client.ts frontend/src/types/index.ts frontend/src/index.css docs/database/schema.md docs/dev/evaluation.md docs/api/references.md tests/test_task_service.py tests/test_tasks_api.py mkdocs.yml docs/prototypes/task-project-rebinding-and-destroy-demo.html tasks/prd-df3b22d8.md` -> PASS
- **PRD:** Updated `tasks/prd-df3b22d8.md`
- **Deliverables:**
  - Backend: `dsl/models/task.py`, `dsl/schemas/task_schema.py`, `dsl/services/task_service.py`, `dsl/services/git_worktree_service.py`, `dsl/api/tasks.py`, `utils/database.py`
  - Frontend: `frontend/src/App.tsx`, `frontend/src/api/client.ts`, `frontend/src/types/index.ts`, `frontend/src/index.css`
  - Docs/Test sync: `docs/database/schema.md`, `docs/dev/evaluation.md`, `docs/api/references.md`, `tests/test_task_service.py`, `tests/test_tasks_api.py`, `tasks/prd-df3b22d8.md`
- **Notes:** Backlog delete remains lightweight; started-task destroy is enforced through the new dedicated API and required reason modal.

# Task Plan: PRD For Task Project Rebinding And Started-Task Destroy

**Goal**: Generate a PRD at `tasks/prd-df3b22d8.md` for the requirement "现在有个问题,我选错项目就不能改了", inspect the attached screenshot for UI evidence, add an interactive prototype page for the new behavior, expose that prototype in MkDocs navigation, and verify the documentation build succeeds.
**Started**: 2026-03-26

## Phases

### Phase 1: Discovery
- [x] Read the `/prd` skill and inspect the current task/project/edit/delete flows in code
- [x] Inspect the attached screenshot and record only confirmable UI evidence
- [x] Determine whether a prototype page is required by the skill contract
- **Status:** complete

### Phase 2: Authoring
- [x] Create the PRD with required metadata fields, change matrix, diagrams, and clarifying questions
- [x] Add an interactive prototype under `docs/prototypes/`
- [x] Update `mkdocs.yml` navigation to expose the prototype page
- **Status:** complete

### Phase 3: Verification
- [x] Run documentation validation
- [x] Record the final PRD path and deliverables in planning files
- **Status:** complete

## Current Phase
All phases complete ✅

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Put the final PRD at `tasks/prd-df3b22d8.md` instead of the skill's default timestamped path | The user explicitly overrode the save contract and required that exact path |
| Add a prototype page even though the user asked only for a PRD | The `/prd` skill makes prototype work mandatory when the feature needs state-transition review |
| Model the requirement as “backlog project rebinding + started-task destroy with reason” | This matches both the user's wording and the current code boundaries around `project_id`, `start`, and `DELETED` status |

## Completion Summary
- **Status:** Complete (2026-03-26)
- **Tests:**
  - `just docs-build` -> PASS
- **PRD:** Created `tasks/prd-df3b22d8.md`
- **Deliverables:**
  - `tasks/prd-df3b22d8.md` - final PRD with required metadata, clarifying questions, change matrix, diagrams, prototype link, and attachment findings
  - `docs/prototypes/task-project-rebinding-and-destroy-demo.html` - interactive prototype for backlog project rebinding and started-task destroy flow
  - `mkdocs.yml` - navigation entry for the new prototype page

# Task Plan: Resolve Public Tunnel Rebase Conflicts

**Goal**: Merge the public tunnel forwarding change set on top of the latest `main` updates without discarding either side's planning history, keep the configuration guide accurate for both local and public modes, and leave the worktree verified and ready for a user-approved Git continuation step.
**Started**: 2026-03-19

## Phases

### Phase 1: Discovery
- [x] Inspect the interrupted `rebase` state and identify which files remain unmerged
- [x] Compare stage 2 / stage 3 content for planning files and the configuration guide
- [x] Confirm whether the forwarding-service implementation itself still needs code fixes
- **Status:** complete

### Phase 2: Merge Resolution
- [x] Merge `task_plan.md`, `findings.md`, and `progress.md` by preserving both the newer repo history and the public-tunnel task records
- [x] Rewrite `docs/guides/configuration.md` so it covers the existing DSL/AI config plus the new public tunnel / gateway settings
- [x] Avoid `git rebase --continue` because that would implicitly create a commit before user approval
- **Status:** complete

### Phase 3: Verification
- [x] Re-run the public tunnel regression tests
- [x] Re-run MkDocs strict build and Compose config validation
- [x] Check the merged files for whitespace / patch-format issues
- **Status:** complete

## Current Phase
All phases complete ✅

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Treat the planning-file conflict as a history merge, not a winner-take-all overwrite | `stage2` carried newer repo task history while `stage3` carried the public tunnel task records, so either side alone would lose information |
| Synthesize `docs/guides/configuration.md` from both sides instead of choosing one version | The upstream file still documented core DSL and AI settings, while the rebased change added the new tunnel / gateway surface |
| Stop before `git rebase --continue` | The user explicitly asked not to create commits by default, and continuing the rebase would recreate a commit |

## Completion Summary
- **Status:** Complete (2026-03-19)
- **Tests:**
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_public_gateway_server.py tests/test_public_tunnel_agent.py tests/test_packaged_runtime.py -q` -> PASS (`17 passed`)
  - `UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build --strict` -> PASS
  - `docker compose -f deploy/public-forward/docker-compose.yml --env-file deploy/public-forward/.env.example config` -> PASS
  - `git diff --check -- docs/guides/configuration.md task_plan.md findings.md progress.md` -> PASS
- **Deliverables:**
  - `task_plan.md`, `findings.md`, `progress.md` - merged planning history plus a new conflict-resolution record
  - `docs/guides/configuration.md` - unified DSL / AI / public-tunnel configuration guide
  - Git index/worktree state ready for user-approved next Git steps

---

# Task Plan: Public Tunnel Forwarding Service For DSL

**Goal**: Add a server-side forwarding service under `forwarding_service/server/` plus a reconnecting local agent, make DSL support same-origin frontend dist hosting for public mode, and ship deployment assets, tests, and MkDocs documentation that satisfy the confirmed PRD for secure public exposure.
**Started**: 2026-03-19

## Phases

### Phase 1: Discovery
- [x] Inspect existing FastAPI routes, config surface, frontend API assumptions, and test conventions
- [x] Decide how the tunnel server, gateway, and local agent integrate without breaking `just dsl-dev`
- [x] Identify required deployment artifacts and docs navigation changes
- **Status:** complete

### Phase 2: Implementation
- [x] Add forwarding service server code at `forwarding_service/server/` with WebSocket tunnel registration, shared-token auth, heartbeat, reconnection handling, and offline `503`
- [x] Add local agent forwarding code targeting `KODA_TUNNEL_UPSTREAM_URL`
- [x] Add DSL public-mode frontend dist hosting controlled by `SERVE_FRONTEND_DIST`
- [x] Add deployment assets (`Dockerfile`, `docker-compose.yml`, `Caddyfile`, env example files)
- **Status:** complete

### Phase 3: Verification
- [x] Add regression coverage for auth, offline handling, request forwarding, and SPA fallback
- [x] Run focused backend tests, frontend build, and `uv run mkdocs build`
- **Status:** complete

## Current Phase
All phases complete ✅

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Keep the tunnel solution HTTP-focused rather than general TCP | The PRD explicitly scopes this work to the current DSL HTTP/HTTPS traffic |
| Preserve the existing `/api` frontend contract and `just dsl-dev` flow | The new public mode must not break the current local development workflow |
| Use a single FastAPI gateway app for both `/ws/tunnels/{tunnel_id}` and forwarded public HTTP paths | This keeps session state in one process, minimizes moving parts, and maps cleanly to isolated tests |
| Put browser-facing HTTPS/Basic Auth in Caddy and keep tunnel-token auth in the gateway | This follows the confirmed PRD security split and avoids coupling browser auth to the local agent |
| Route all public browser traffic to one configured `KODA_TUNNEL_ID` | The PRD explicitly excludes multi-tenant SaaS, so a single public tunnel target keeps deployment and operations simpler |

## Completion Summary
- **Status:** Complete (2026-03-19)
- **Tests:**
  - `UV_CACHE_DIR=/tmp/uv-cache uv run python -m py_compile main.py dsl/app.py utils/settings.py forwarding_service/... tests/test_public_gateway_server.py tests/test_public_tunnel_agent.py tests/test_packaged_runtime.py` -> PASS
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_public_gateway_server.py tests/test_public_tunnel_agent.py tests/test_packaged_runtime.py -q` -> PASS (`10 passed`)
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` -> PASS (`54 passed, 1 warning`)
  - `cd frontend && npm ci` -> PASS
  - `cd frontend && npm run build` -> PASS
  - `UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build --strict` -> PASS
  - `docker compose -f deploy/public-forward/docker-compose.yml --env-file deploy/public-forward/.env.example config` -> PASS
- **Deliverables:**
  - `forwarding_service/server/` - gateway app, config, tunnel registry, health endpoint, offline `503`, and WebSocket auth/session handling
  - `forwarding_service/agent/` - reconnecting local agent, heartbeat loop, upstream HTTP bridge, and stable upstream-failure handling
  - `dsl/app.py`, `main.py`, `utils/settings.py`, `justfile`, `.env.example` - packaged runtime mode and operator commands/config
  - `deploy/public-forward/` and `.dockerignore` - Dockerized server deployment assets for Caddy + gateway
  - `tests/test_public_gateway_server.py`, `tests/test_public_tunnel_agent.py`, `tests/test_packaged_runtime.py` - regression coverage for auth, offline handling, forwarding, reconnect logic, and SPA fallback
  - `docs/guides/deployment.md`, `docs/guides/configuration.md`, `docs/guides/public-exposure.md`, `mkdocs.yml` - synchronized deployment/config/runbook docs

# Task Plan: Public Tunnel Forwarding Review Fixes

**Goal**: Resolve the three blocking review findings in the public tunnel forwarding implementation: prevent invalid replayed entity headers on gateway responses, restore a development-safe root `.env.example`, and make the gateway reject missing or placeholder shared tokens at startup.
**Started**: 2026-03-19

## Phases

### Phase 1: Discovery
- [x] Re-read the blocking review notes and inspect the affected gateway/config/example files
- [x] Confirm which tests exist and where new regression coverage should live
- **Status:** complete

### Phase 2: Implementation
- [x] Filter framework-owned entity headers when replaying agent responses from the gateway
- [x] Change the root `.env.example` back to a dev-safe `SERVE_FRONTEND_DIST=false` default while leaving public-mode examples in deployment assets
- [x] Fail fast when `KODA_TUNNEL_SHARED_TOKEN` is missing or still set to a placeholder value
- **Status:** complete

### Phase 3: Verification
- [x] Add or update regression tests for response-header replay and shared-token validation
- [x] Run focused `pytest` coverage for public gateway behavior plus `uv run mkdocs build`
- **Status:** complete

## Current Phase
All phases complete ✅

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Filter entity headers at response replay time instead of changing the wire format globally | Request/response serialization can still preserve useful metadata, while the FastAPI gateway must avoid duplicate framework-owned headers such as `content-length` |
| Keep root `.env.example` development-safe and point public deployments to `deploy/public-forward/agent.env.example` | The repo root example should not break `just dsl-dev` for a fresh checkout |
| Treat blank and placeholder tunnel tokens as invalid configuration | A public gateway must not come up with a known default credential on the tunnel registration endpoint |
| Remove the module-level gateway `app` singleton | Strict env validation should only happen in explicit runtime entrypoints, not during test-module import or passive code introspection |

## Completion Summary
- **Status:** Complete (2026-03-19)
- **Tests:**
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_public_gateway_server.py tests/test_public_tunnel_agent.py -q` -> PASS (`16 passed`)
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_packaged_runtime.py -q` -> PASS (`1 passed`)
  - `UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build --strict` -> PASS
- **Deliverables:**
  - `forwarding_service/shared/http.py`, `forwarding_service/server/app.py` - safe response-header replay that drops framework-owned `content-length` before returning browser responses
  - `forwarding_service/shared/config_utils.py`, `forwarding_service/server/config.py`, `forwarding_service/agent/config.py` - fail-fast secret validation for missing or placeholder tunnel tokens
  - `.env.example` - restored development-safe `SERVE_FRONTEND_DIST=false` default with a pointer to `deploy/public-forward/agent.env.example`
  - `tests/test_public_gateway_server.py`, `tests/test_public_tunnel_agent.py` - regression coverage for duplicate response headers and placeholder-token rejection
  - `docs/guides/configuration.md`, `docs/guides/deployment.md` - synchronized operator guidance for dev-safe defaults and required real tunnel secrets

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
