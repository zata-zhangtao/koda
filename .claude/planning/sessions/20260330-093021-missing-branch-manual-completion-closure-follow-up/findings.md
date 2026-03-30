# Findings & Decisions

## 2026-03-30 Missing Branch Manual Completion Closure Follow-up Findings
- `frontend/src/App.tsx` already polls `/api/tasks/card-metadata`, but the selected-task detail banner, checklist gating, and complete CTA still read `selectedTask.branch_health`, so a stale task snapshot prevents the missing-branch state from surfacing without a full task-list refresh.
- `resolveTaskCardMetadataFromSnapshot()` currently rejects cached `branch_missing` metadata unless the task snapshot itself already has `branch_health.manual_completion_candidate=true`; this defeats the whole metadata-polling design for idle tasks whose `taskList` never refreshes.
- The narrowest frontend fix is to derive selected-task branch health from `selectedTaskCardMetadata.branch_health` first, while only retaining cached `branch_missing` metadata when that metadata still marks a manual-completion candidate and the task snapshot is not already closed/deleted.
- `dsl/api/tasks.py:complete_task()` still calls `TaskService.prepare_task_completion()` without any missing-branch guard, and `TaskService.prepare_task_completion()` still lacks a `manual_completion_candidate` rejection, so direct `/complete` callers can still enter the normal Git finalization flow incorrectly.
- Existing task-API coverage exercises `/manual-complete`, but there is no regression asserting that ordinary `/complete` rejects missing-branch candidates with a clear error message.

## 2026-03-27 Missing Branch Manual Completion Review Fix Findings
- The blocking review note is valid: `manual_completion_candidate` currently becomes `true` for any non-closed task with `branch_exists is False`, even if the task never created a task worktree/branch.
- `TaskService.start_task()` is the point where linked tasks first receive a persisted `worktree_path`, so that field is the narrowest durable signal that the task entered the git-backed Koda flow.
- `TaskService.build_task_branch_health()` may still legitimately report `branch_exists=False` for non-eligible tasks; only the derived `manual_completion_candidate` flag and downstream `branch_missing` display/manual-close path need tightening.
- The required regression is a linked backlog task with a project repo but no `worktree_path`; it should keep `branch_health.branch_exists=False` while staying out of `branch_missing` and rejecting `/manual-complete`.

## 2026-03-27 Missing Branch Manual Completion Implementation Findings
- `tasks/prd-0fd7ed62.md` 已把实现范围锁定为“branch-health 派生读模型 + 手动确认完成接口 + 前端检查单解锁”，明确要求正常 `/api/tasks/{id}/complete` 流程保持不变。
- `dsl/services/git_worktree_service.py` 已经提供 canonical branch 规则 `task/{task_id[:8]}`，但目前只用于 worktree 创建，没有分支存在性探针或 repo-root 解析辅助方法。
- `dsl/services/task_service.py` 目前只负责真实生命周期/阶段切换；新增 manual-complete 更适合在这里实现统一校验与 `done/CLOSED` 收敛，而不是让前端串多个接口。
- `dsl/schemas/task_schema.py` 与 `frontend/src/types/index.ts` 目前都没有 branch-health 结构；前端卡片展示态只有 `waiting_user` 这一种展示型 override。
- `frontend/src/api/client.ts` 只有普通 `complete` 接口，没有 manual-complete 专用 API。
- `frontend/src/App.tsx` 仍以 `lifecycle_status` 决定 Active/Completed 视图，以 `canCompleteTask()` 决定是否显示 `Complete`，这意味着只要后端把 manual-complete 成功收敛到 `CLOSED`，任务就会自动从 Active 移到 Completed。
- `tests/test_tasks_api.py` 已覆盖 card metadata 派生和普通 complete 的人工接管日志，是新增 branch-health 序列化与 manual-complete API 回归的首选测试入口。
- `dsl/api/tasks.py` 中 `_build_task_card_metadata()` 是展示态 override 的唯一后端入口，适合在这里新增 `branch_missing` 展示态，而不污染真实 `workflow_stage`。
- 普通 `complete_task()` 已严格依赖 `worktree_path` 存在且目录存在，因此“分支被手动 merge/删除但任务还显示”这个问题不能靠放宽现有 `/complete` 解决，必须新增独立 manual-complete 接口。
- `ProjectService` 已能验证 `project.repo_path` 是有效仓库，并统一执行 `git -C <repo>`；branch probe 可以复用同样的 repo-root 语义，但更适合保持在 `GitWorktreeService` 里以贴近 branch/worktree 规则。

## 2026-03-26 Missing Branch Completion Confirmation Findings
- The current active/completed/changes workspace split in `frontend/src/App.tsx` depends on `lifecycle_status` and requirement-change logs; it does not derive visibility from actual Git branch existence.
- `frontend/src/App.tsx` allows `Complete` for worktree-backed tasks only from `self_review_in_progress`, `test_in_progress`, `pr_preparing`, or `acceptance_in_progress`, and then calls the backend completion flow when `worktree_path` exists.
- `dsl/api/tasks.py` and `dsl/services/task_service.py` model completion as a worktree-backed Git finalization flow; there is no read-only branch-health probe or dedicated manual-complete path for the case where the branch was already merged/deleted outside Koda.
- `dsl/services/git_worktree_service.py` already owns canonical task branch naming (`task/{task_id[:8]}`), which makes it the right place to anchor any future branch-existence checks.
- `dsl/services/project_service.py` only clears missing `worktree_path` values when a project is rebound; missing branch state is currently not reconciled anywhere in normal task polling.
- Because this requirement is about state transitions and button flows, the `/prd` skill requires an interactive prototype file change instead of PRD-only text output.

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
