# Findings & Decisions

## 2026-03-19 PRD Output Contract Findings
- `dsl/services/codex_runner.py` currently assembles the PRD prompt inline inside `run_codex_prd`, which makes the output contract harder to unit-test directly.
- The PRD generation flow already writes to `tasks/prd-{task_id[:8]}.md`, and `dsl/api/tasks.py:get_task_prd_file` reads that exact path with UTF-8 decoding.
- Existing docs describe the PRD prompt at a high level, but they do not yet explicitly state that generated PRDs must include both `原始需求标题` and `需求名称（AI 归纳）` in the top metadata area.
- The current frontend PRD panel renders raw markdown content, so adding metadata to the PRD body is compatible as long as the file path and general markdown format stay stable.
- `docs/guides/codex-cli-automation.md` still documents the old wildcard-style PRD path (`tasks/*-prd-*.md`) and "latest file" lookup, which is now inconsistent with `dsl/api/tasks.py` and should be corrected as part of this task.
- `docs/core/prompt-management.md` also still refers to `run_codex_prd`'s inline PRD prompt and wildcard PRD paths; this doc should move to a first-class `build_codex_prd_prompt(...)` contract.
- `frontend/src/App.tsx` already contains a generated markdown validation checklist, so the manual verification requirement can be satisfied by adding a PRD-specific checklist item there without changing the UI structure.
- There is currently no direct regression test for `run_codex_prd` prompt assembly or for `get_task_prd_file`; both are good low-level targets for this change because they cover the new output contract and compatibility boundary without needing end-to-end Codex execution.

## 2026-03-19 Configuration Guide Drift Follow-up Findings
- `docs/guides/configuration.md` still documented `just sync` as the contributor-facing dependency install entrypoint and omitted the required `cd frontend && npm install` step, so it no longer matched `README.md` and `docs/getting-started.md`.
- `justfile` still exposes `sync:` as a wrapper, but the PRD and the already-updated onboarding docs standardize contributor-facing guidance on `uv sync` + `cd frontend && npm install` + `just dsl-dev`.
- No navigation or additional page changes are needed for this follow-up because the blocker is isolated to one section inside `docs/guides/configuration.md`.

## 2026-03-19 Configuration Guide Drift Follow-up Decisions
| Decision | Rationale |
|----------|-----------|
| Limit the content fix to the `## 命令入口` section in `docs/guides/configuration.md` | The review blocker identified a single remaining source of command drift, and changing more pages would add unnecessary churn |
| Document the README-standard startup path explicitly before listing auxiliary commands | This makes the config guide reuse the same onboarding sequence instead of only describing `justfile` recipes in isolation |
| Keep `just docs-build` as the explicit pre-submit validation note in the same section | The PRD requires documentation maintenance and validation rules to stay visible on the core documentation path |

## 2026-03-19 Agent Guide Consistency Follow-up Findings
- `AGENTS.md` and `CLAUDE.md` were the only repository-level instruction docs still telling contributors to use `uv pip install`; the already-updated README and MkDocs onboarding pages consistently use `uv sync`.
- Those two files also lacked the explicit `cd frontend && npm install`, `just dsl-dev`, and `just docs-build` entrypoints that the rest of the onboarding path now treats as standard.
- `AGENTS.md` still referenced raw `uv run mkdocs serve` / `uv run mkdocs build` commands, which conflicted with the repository-standard `just docs-serve` / `just docs-build` wrappers defined in `justfile`.
- `CLAUDE.md` ended with a stray closing code fence, which was unrelated to the blocker itself but would leave a Markdown formatting defect in one of the touched files if ignored.

## 2026-03-19 Agent Guide Consistency Follow-up Decisions
| Decision | Rationale |
|----------|-----------|
| Update both agent guides, not only the `uv pip install` line | The review feedback explicitly framed the goal as a unified command set, so stopping at a one-line swap would leave repo-level docs partially inconsistent |
| Mirror the `justfile` entrypoints in agent-facing docs | `justfile` is the operational source of truth for `dsl-dev`, `docs-serve`, and `docs-build` |
| Keep README and MkDocs content unchanged in this follow-up | Those pages were already corrected in the prior pass and revalidated successfully |

## 2026-03-19 README And Core Docs Findings
- `README.md` is still anchored to `Zata Codes Template`, includes template-era hook and `utils/` scaffolding guidance, and uses `uv pip install`, so it directly conflicts with the PRD and current repo reality.
- `docs/index.md` already positions the repo as Koda / DevStream Log and already exposes the correct local URLs plus `just docs-build`, which makes it the best baseline for the root README rewrite.
- `docs/getting-started.md` already uses `uv sync`, `cd frontend && npm install`, and `just dsl-dev`, so the main work there is tightening wording and explicitly marking `just docs-build` as a pre-submit validation step.
- `docs/guides/configuration.md` already lists the right command names from `justfile`, but it does not yet clearly tell maintainers to sync README / onboarding docs when commands, env vars, ports, or path rules change.
- `docs/guides/dsl-development.md` still says `pr_preparing` is not fully automated, which conflicts with `docs/index.md`, `docs/architecture/system-design.md`, and `docs/guides/codex-cli-automation.md`.
- `docs/api/references.md` already behaves as the mkdocstrings-driven authority page, so it does not need structural changes unless discoverability wording elsewhere depends on it.
- `mkdocs.yml` already contains the required navigation targets and no page is being added, renamed, or moved, so nav churn would be unnecessary.

## Decisions
| Decision | Rationale |
|----------|-----------|
| Rewrite README instead of incrementally patching template paragraphs | The existing template content would otherwise keep leaking conflicting positioning into the repo entry page |
| Reuse the same command sequence and localhost addresses across README and onboarding pages | The PRD explicitly forbids divergent onboarding instructions |
| Add documentation maintenance rules in both README and docs pages | Contributors should see the rule from both the repository root and the MkDocs landing path |
| Correct the `pr_preparing` automation note in `docs/guides/dsl-development.md` while touching maintenance guidance nearby | Leaving that conflict in place would preserve internal documentation drift immediately after this refresh |

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
