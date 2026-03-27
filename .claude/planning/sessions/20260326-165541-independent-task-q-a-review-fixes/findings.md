# Findings & Decisions

## 2026-03-26 Independent Task Q&A Review Fix Findings
- `frontend/src/App.tsx` hid the entire sidecar region behind `canSendFeedback`, which meant a task moving to `CLOSED` immediately lost its sidecar history and feedback-draft conversion UI even though the PRD required history retention after completion.
- `TaskQaMessageCreateSchema` only enforced raw `min_length=1`; once the service trimmed the payload, whitespace-only questions could still be persisted by non-frontend clients unless the normalized string was rejected again.
- `TaskQaService` created pending assistant placeholders before invoking the model, but had no explicit timeout controls and no stale-pending recovery path, so provider hangs or interrupted workers could leave a task permanently blocked on one pending reply.
- The narrowest safe fix is to auto-release expired pending assistant replies during `list_messages()` and `create_question()` flows, while also adding timeout/retry controls to the sidecar chat-model invocation itself.

## 2026-03-26 Independent Task Q&A Sidecar Findings
- `frontend/src/App.tsx` currently exposes one bottom composer controlled by `canSendFeedback`, and its submit path persists plain text or attachments through `logApi.create(...)` / `mediaApi.upload*`.
- During `prd_waiting_confirmation`, `handleFeedbackSubmit()` can immediately call `taskApi.regeneratePrd(...)`, so the current composer is not a neutral question channel.
- The same feedback path also interprets “continue / resume / retry / 继续” style text as workflow commands and can trigger `taskApi.execute(...)` or `taskApi.resume(...)`; this is direct evidence that current feedback is coupled to execution semantics.
- `dsl/api/tasks.py` converts ordered `DevLog` entries into prompt context for PRD regeneration and coding execution, including attached-local-file contracts, which means storing casual Q&A in `DevLog` would contaminate downstream prompts.
- `dsl/models/dev_log.py` has no field that cleanly separates “sidecar chat” from “execution-relevant history”; adding such separation inside `DevLog` would still leave prompt-selection complexity and timeline clutter.
- `ai_agent/utils/model_loader.py` already provides provider/model resolution for chat-style LLM access, while `docs/core/ai-assets.md` explicitly positions it as a side-path AI asset distinct from the Codex execution chain.
- The current task workflow stages in `dsl/models/enums.py` already reserve `implementation_in_progress` for “无打扰编码”, so the new Q&A path should not add a new workflow stage; it should remain orthogonal to `workflow_stage`.
- Because the request involves cross-stage interaction behavior, the `/prd` skill's prototype branch is applicable; a real prototype file under `docs/prototypes/` plus `mkdocs.yml` nav changes should be treated as part of the artifact set.
- `just docs-build` completed successfully after adding the new prototype page and nav entry, which confirms MkDocs accepts the `.html` prototype page in navigation for this repository.
- The implemented backend uses a dedicated `task_qa_messages` table plus `TaskQaService`; this cleanly enforces `pending/completed/failed` states without touching `DevLog`.
- FR-9 is best satisfied by treating `TASK_QA_BACKEND=chat_model` as the only supported first-version backend; leaving `codex` as the default would contradict the requested AI-asset boundary.
- A background-task reply model works well here: `POST /api/tasks/{task_id}/qa/messages` returns immediately with a pending assistant placeholder, and the eventual success/failure only mutates that one message.
- The frontend can reuse the existing task-detail footer area, but the semantics have to be split visually into two tabs; changing only placeholder text would not satisfy the acceptance criteria.
- The “整理最近一次结论为反馈草稿” path is best implemented as an explicit conversion endpoint that returns draft text, not as an automatic `DevLog` write.

## 2026-03-19 Public Tunnel Rebase Conflict Findings
- The interrupted `git rebase main` left four files unmerged in the index: `docs/guides/configuration.md`, `task_plan.md`, `findings.md`, and `progress.md`.
- The conflicted planning files had no inline conflict markers in the working tree; the real conflict information only existed in Git stages, so resolution required comparing `:2:` and `:3:` directly.
- `stage2` contained newer repository task history added on `main`, while `stage3` contained the public tunnel forwarding task records, so the correct merge strategy was a set-union of task sections and session logs.
- `docs/guides/configuration.md` needed a synthesized result rather than a straight pick, because one side described the standing DSL / AI / onboarding contract and the other added the new public tunnel / gateway configuration surface.
- The forwarding-service code already contained the review-fix logic for placeholder-secret rejection, duplicate response-header filtering, and the dev-safe root `.env.example`; the blocking work was merge resolution rather than fresh implementation.

## 2026-03-19 Public Tunnel Forwarding Findings
- `dsl/app.py` currently exposes API routers, `/media/original`, `/media/thumbnail`, and `/health`, but it does not yet support serving `frontend/dist` or SPA fallback from FastAPI.
- `frontend/vite.config.ts` proxies `/api` and `/media` to `http://localhost:8000`, so the public-mode design must preserve same-origin `/api` and `/media` paths without changing the frontend `API_BASE`.
- `main.py` always starts uvicorn in reload mode on port `8000`, which is suitable for local development but not yet configurable for a production-facing packaged mode.
- `utils/settings.py` already centralizes environment-backed config and is the correct place to add tunnel/public-mode settings required by the PRD.
- `utils/logger.py` already provides structured-enough central logging hooks, but the forwarding service and local agent will need their own explicit structured log payloads rather than ad-hoc prints.
- `mkdocs.yml` already has deployment/configuration guides in navigation, so the new public exposure manual can be added as a new guide and linked from nav.
- The worktree is clean aside from the user-provided untracked file `tasks/prd-cfd7faaa.md`; no existing tracked changes need special merge handling for this task.
- All current FastAPI routers use `/api/...` prefixes, and the frontend `fetchApi()` helper hard-codes `API_BASE = "/api"`, so the tunnel gateway should route requests by path prefix instead of rewriting the frontend contract.
- Existing deployment docs explicitly state the repository has no production Dockerfile, compose stack, reverse-proxy config, or FastAPI-hosted `frontend/dist`, which means this task can add those assets without conflicting with an existing release path.
- `tests/test_timezone_contract.py` already uses small `FastAPI()` + `TestClient` route-level tests, which is a good pattern for isolated SPA fallback and app-config/public-mode regressions.
- The confirmed PRD already narrows the deliverable map: `forwarding_service/server/`, `forwarding_service/agent/`, `deploy/public-forward/`, plus new tests for gateway, agent, and packaged runtime.
- The PRD explicitly recommends an HTTP-over-WebSocket design where the gateway owns the public HTTP interface and the local agent bridges every request to `http://127.0.0.1:8000`, so there is no need to design a broader TCP tunnel abstraction.
- The PRD also fixes the security split: Caddy handles HTTPS and Basic Auth for browser traffic, while the gateway enforces the per-tunnel shared token for agent registration.
- The simplest single-tenant routing model is to let the gateway expose one configured `KODA_TUNNEL_ID` to browser traffic while still keeping the WebSocket registration path parameterized; this satisfies the PRD without inventing a multi-tenant host/path router.
- `TestClient` is reliable for isolated WebSocket auth/heartbeat and packaged-runtime tests, but it is a poor fit for concurrent HTTP+WebSocket forwarding simulation in one process; the forwarding regression is more stable when the gateway request layer is tested against a fake active tunnel session.
- The gateway needs its own internal health path (`/_gateway/health`) so public `/health` can remain a forwarded DSL path; otherwise deployment health checks would conflict with the existing application route contract.
- `SERVE_FRONTEND_DIST=true` should fail fast when `frontend/dist/index.html` is missing; silent fallback to API-only mode would make public deployment errors harder to detect and document.
- `docker compose config` requires an actual `deploy/public-forward/.env` file because `env_file` is resolved from the compose file itself; a temporary copy from `.env.example` is enough for syntax verification during local validation.

## 2026-03-19 Public Tunnel Review Fix Findings
- `forwarding_service/server/app.py` currently creates a fresh FastAPI `Response` and then appends every agent-returned header, which allows duplicate framework-owned entity headers such as `content-length`.
- `forwarding_service/shared/http.py` already strips hop-by-hop headers, but it does not distinguish headers that should be regenerated by FastAPI/Starlette for the final browser response.
- `tests/test_public_gateway_server.py` covers the happy-path forwarding contract and is the right place to pin a regression that asserts duplicate `content-length` replay does not occur.
- `forwarding_service/server/config.py` currently falls back to `"change-me"` when `KODA_TUNNEL_SHARED_TOKEN` is unset or blank, which leaves a known credential on the unauthenticated tunnel-registration path if operators miss the setting.
- The docs already describe `KODA_TUNNEL_SHARED_TOKEN` as empty by default on the local side, so making the gateway fail fast is consistent with the security model and mainly needs test/doc/example alignment.
- The root `.env.example` currently enables `SERVE_FRONTEND_DIST=true`, but `docs/guides/configuration.md` still says the default is `false` and `just dsl-dev` should remain Vite-based, so the sample file is the drift point rather than the docs.
- Once gateway config became strict, the module-level `app = create_application()` in `forwarding_service/server/app.py` turned into an import-time failure for tests and any passive module introspection; explicit startup paths should own env validation instead.

## 2026-03-19 PRD Output Contract Findings
- `dsl/services/codex_runner.py` currently assembles the PRD prompt inline inside `run_codex_prd`, which makes the output contract harder to unit-test directly.
- The PRD generation flow already writes to `tasks/prd-{task_id[:8]}.md`, and `dsl/api/tasks.py:get_task_prd_file` reads that exact path with UTF-8 decoding.
- Existing docs describe the PRD prompt at a high level, but they do not yet explicitly state that generated PRDs must include both `原始需求标题` and `需求名称（AI 归纳）` in the top metadata area.
- The current frontend PRD panel renders raw markdown content, so adding metadata to the PRD body is compatible as long as the file path and general markdown format stay stable.
- `docs/guides/codex-cli-automation.md` still documents the old wildcard-style PRD path (`tasks/*-prd-*.md`) and "latest file" lookup, which is now inconsistent with `dsl/api/tasks.py` and should be corrected as part of this task.
- `docs/core/prompt-management.md` also still refers to `run_codex_prd`'s inline PRD prompt and wildcard PRD paths; this doc should move to a first-class `build_codex_prd_prompt(...)` contract.
- `frontend/src/App.tsx` already contains a generated markdown validation checklist, so the manual verification requirement can be satisfied by adding a PRD-specific checklist item there without changing the UI structure.
- There is currently no direct regression test for `run_codex_prd` prompt assembly or for `get_task_prd_file`; both are good low-level targets for this change because they cover the new output contract and compatibility boundary without needing end-to-end Codex execution.

## 2026-03-19 Worktree Root Findings
- `dsl/services/git_worktree_service.py` is the only place that computes default task worktree paths and selects between fallback, path-aware scripts, and branch-only scripts.
- The current default path is `repo_root_path.parent / "<repo>-wt-<task8>"`, so both fallback Git and path-aware scripts still create sibling directories directly under the repo parent.
- The existing branch-only `git_worktree.sh` compatibility path is inferred as `repo_root_path.parent / "task/<task8>"`, which is both inconsistent with the new PRD and too brittle because it does not inspect the actual created worktree.
- `TaskService.start_task()` only needs the returned absolute path and already writes it into `Task.worktree_path`; `/prd-file`, `/open-in-trae`, and completion logic all continue to read that stored field directly.
- Existing real-Git regression coverage lives in `tests/test_git_worktree_service.py`; there is currently no path-aware script test and no explicit branch-only containment validation test.
- The docs do not currently mention the new `../task` root at all, so at least `docs/index.md`, `docs/architecture/system-design.md`, `docs/database/schema.md`, and `docs/dev/evaluation.md` need synchronized wording/examples for the acceptance criteria.
- The implementation can stay localized by introducing `build_task_worktree_root_path()` and reusing it from `build_task_worktree_path()` plus `create_task_worktree()`.
- Branch-only compatibility should not assume a folder name; the reliable source is `git worktree list --porcelain`, filtered by `refs/heads/task/<task8>`.
- For branch-only scripts that create worktrees outside the new root, the failure should happen after creation with a direct containment error, not by silently accepting the path or rewriting it.

## Requirements
- WebDAV-restored projects must survive a machine change without blindly trusting stale absolute paths.
- Project rebinding should verify both repository identity and revision consistency.
- Operators need explicit UI states for path problems, wrong-repo problems, and commit drift.
- Existing SQLite databases must gain the new fields without forcing a rebuild.

## Research Findings
- `Project` previously stored only `repo_path`, so a restored DB could not tell whether a new local path pointed to the same repository.
- The app already has a small startup migration hook in `dsl.app`, so adding nullable `Project` columns is feasible without Alembic.
- WebDAV upload happens from the local DB file directly, which makes it the correct place to refresh project fingerprints before syncing.
- The earlier relink flow only repaired paths; it had no way to reject a different remote or highlight a same-remote commit drift.
- Existing project tests used fake `.git` directories, which are insufficient once fingerprint logic depends on real Git metadata.
- A zero-byte `data/dsl.db` means SQLite created the file on first connect, but the schema bootstrap path never ran before request handling.
- `Base.metadata` already contains `projects` and `email_settings`, so the production failure is not missing model imports inside the codebase; it is missing or bypassed initialization timing.
- Multiple services instantiate `SessionLocal()` directly, so fixing only FastAPI `lifespan` would leave the database bootstrap path fragile.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Persist normalized `repo_remote_url` and `repo_head_commit_hash` on `Project` | This is the minimum durable fingerprint needed to compare restored projects across machines |
| Normalize remote URLs before storing/comparing | Lets `git@host:org/repo.git` and `https://host/org/repo.git` compare as the same repository |
| Refresh fingerprints before WebDAV upload | Keeps the synced database aligned with the latest accepted local repo state |
| Reject relink when remote mismatches, but allow commit drift with a warning | Wrong repo is unsafe; newer commit on the same repo can be intentional |
| Backfill only missing fingerprints on startup | Avoids destroying the previously synced baseline while still upgrading old databases |
| Replace fake-repo tests with real Git repos | Needed to validate remote normalization, HEAD drift, and refresh behavior accurately |
| Centralize schema initialization in `utils.database` and reuse it from both startup and session creation | Prevents empty or partially initialized SQLite databases from reaching request handlers |

## Resources
- `dsl/models/project.py`
- `dsl/schemas/project_schema.py`
- `dsl/services/project_service.py`
- `dsl/api/projects.py`
- `dsl/services/webdav_service.py`
- `dsl/app.py`
- `frontend/src/App.tsx`
- `tests/test_project_service.py`

## 2026-03-18 Complete Flow Findings
- `dsl/services/codex_runner.py` currently models `Complete` as a Codex prompt that only covers `commit` then `git rebase main`; there is no real `checkout main`, `merge`, or worktree cleanup.
- `dsl/api/tasks.py` already routes worktree-backed completion through `run_codex_completion`, so the backend has a single place to replace prompt-driven Git finalization with deterministic commands.
- `dsl/services/task_service.py` computes task branches as `task/<task_id[:8]>` and worktree paths as `<repo>-wt-<task_short_id>`, but its external script detection only covers `new-worktree.sh` / `create-worktree.sh`.
- `~/code/zata_code_template/scripts/git_worktree.sh` is the reference create script; `git_worktree_merge.sh` provides cleanup logic and a delete-only mode that is useful after a separate local merge.
- The template merge script pushes by default, so Koda should not call it for the merge itself; it should only reuse the cleanup pattern after the local merge succeeds.
- In a multi-worktree repo, `main` may already be checked out elsewhere, so assuming Koda can always `git checkout main` in an arbitrary worktree is unsafe.
- The user explicitly requires automatic conflict handling during `git rebase main`, which makes Codex a targeted conflict-repair tool rather than the primary executor of the whole completion flow.
- The commit subject should come from the task summary / requirement brief rather than the raw task title.

## 2026-03-19 Timezone Contract Findings
- `utils/helpers.py` already defines `utc_now_naive()`, which confirms database `DateTime` columns are intentionally stored as UTC-semantic naive values.
- `dsl/services/chronicle_service.py` currently emits raw `datetime.isoformat()` strings and later slices those strings (`[:10]`, `[11:19]`) for export/grouping, so it will misrepresent cross-day values once display timezone changes.
- FastAPI response models still expose bare `datetime` fields in multiple Pydantic schemas (`task`, `dev_log`, `project`, `run_account`, `email_settings`, `webdav_settings`), so API responses likely serialize without explicit timezone offsets today.
- Frontend time formatting is fragmented: `frontend/src/App.tsx`, `frontend/src/components/LogCard.tsx`, `frontend/src/components/StreamView.tsx`, and `frontend/src/components/ChronicleView.tsx` each parse/format timestamps independently.
- `frontend/src/components/StreamView.tsx` groups logs by `created_at.split("T")[0]`, which uses the raw serialized date prefix instead of the UTC+8 natural day required by the PRD.
- There is no existing `APP_TIMEZONE` configuration entry in `utils/settings.py`, so application timezone behavior is not centralized yet.
- A shared Pydantic response base with `field_serializer("*", when_used="json")` is sufficient to push explicit-offset serialization across the existing API response schemas without rewriting every route.
- Frontend grouping can stay lightweight and dependency-free by treating naive timestamp strings as UTC during parsing, then formatting and grouping exclusively through `Intl.DateTimeFormat(..., { timeZone: "Asia/Shanghai" })`.
- `chronicle` export can avoid requerying raw ORM data by parsing its own ISO strings through a shared helper instead of slicing `YYYY-MM-DD` / `HH:MM:SS` substrings.
- The runtime log formatter is safely aligned with the business timezone by overriding `logging.Formatter.formatTime()` instead of relying on host-local `utc=False` behavior.

## 2026-03-19 Timezone Blocker Fix Findings
- The self-review correctly identified that `ZoneInfo(Config.APP_TIMEZONE)` is now part of import-time config validation, so missing IANA timezone data becomes a startup failure rather than a deferred runtime edge case.
- The repository guidelines explicitly require Windows compatibility, which makes a declared `tzdata` dependency part of the runtime contract once `zoneinfo` validation is used.
- The timezone implementation goal for this card is fixed to UTC+8, so leaving `Asia/Shanghai` / `+08:00` literals in user-facing code is acceptable only if they derive from the same configuration source; otherwise the code and documentation contract drift apart.
- There is currently no backend config endpoint and no frontend `VITE_...` injection for timezone settings, so the UI has no supported way to follow `APP_TIMEZONE` unless it keeps hard-coded values.
- The narrowest end-to-end fix is to expose a read-only API config payload (timezone name plus current offset label) and let the frontend datetime utility use that as its runtime source of truth, while still defaulting to `Asia/Shanghai` during bootstrap.
- Frontend day-group labels should treat `YYYY-MM-DD` keys as already-normalized calendar days; re-parsing those keys as timestamps reintroduces timezone drift and is the wrong abstraction boundary.
- A lightweight `get_app_timezone_display_label()` helper keeps chronicle export copy aligned with the configured timezone without duplicating string formatting rules in service code.

## 2026-03-26 Sidecar Q&A Round-2 Blocker Findings
- `dsl/services/log_service.py` still accepted formal feedback writes for `CLOSED` / `DELETED` tasks because the backend only checked task existence; `dsl/api/media.py` reused that same service path, so attachment feedback was bypassing the product rule too.
- A pure “query pending, then insert” flow in `dsl/services/task_qa_service.py` is not atomic on SQLite; the real fix needs a database-level invariant plus service-level conflict translation, not just another pre-check.
- Adding a partial unique index directly to the SQLAlchemy model with only `sqlite_where=...` is unsafe because non-SQLite dialects compile it into a plain unique index on `task_id`; the SQLite-only invariant must therefore be created through SQLite-specific DDL/migration hooks.
- Existing SQLite files may already contain duplicate pending assistant rows from the earlier race window, so schema bootstrap has to repair those rows before attempting to create the unique partial index.
