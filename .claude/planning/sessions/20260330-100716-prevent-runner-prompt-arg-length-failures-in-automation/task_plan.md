# Task Plan: Prevent Runner Prompt Arg-Length Failures In Automation

## Goal
Fix the automation runner so large Codex/Claude prompts no longer fail with `Errno 7 Argument list too long`, while preserving existing retry, cancel, stage-transition, and logging behavior.

## Current Phase
Complete

## Phases

### Phase 1: Discovery
- [x] Confirm the user-facing symptom from the screenshot and map it to backend code paths
- [x] Identify the exact subprocess launch sites that pass prompt text through argv
- [x] Identify the prompt builders and context assembly paths that can produce oversized payloads
- [x] Record the current PRD/test landscape in `findings.md`
- **Status:** complete
- **Started:** 2026-03-30 09:23:00
- **Completed:** 2026-03-30 09:36:00

### Phase 2: Technical Plan
- [x] Choose the safe prompt transport contract for each runner (`stdin`, temp file, or supported CLI flag)
- [x] Decide whether a secondary prompt-length guard is still required after transport changes
- [x] Define the regression-test shape for launch-time failures and large prompt inputs
- [x] Document the chosen approach and rationale in `findings.md`
- **Status:** complete
- **Started:** 2026-03-30 09:36:00
- **Completed:** 2026-03-30 09:46:00

### Phase 3: Implementation
- [x] Update runner subprocess creation so prompt delivery no longer depends on argv length
- [x] Keep Codex/Claude runner abstractions coherent if the shared runner contract changes
- [x] Add or update targeted tests in `tests/test_codex_runner.py` and related runner tests
- [x] Update docs if the operational contract or troubleshooting guidance changes
- **Status:** complete
- **Started:** 2026-03-30 09:46:00
- **Completed:** 2026-03-30 10:01:00

### Phase 4: Verification
- [x] Run targeted runner tests
- [x] Run any additional documentation validation required by touched files
- [x] Confirm the failure path is covered by regression tests and record results in `progress.md`
- **Status:** complete
- **Started:** 2026-03-30 10:01:00
- **Completed:** 2026-03-30 10:04:00

### Phase 5: Delivery
- [x] Update or create the matching PRD under `tasks/`
- [x] Fill the Completion Summary with deliverables and exact verification evidence
- [x] Explicitly archive the planning session when the task is complete
- **Status:** complete
- **Started:** 2026-03-30 10:04:00
- **Completed:** 2026-03-30 10:08:00

## Key Questions
1. Which prompt transport mechanism is actually supported by the installed `codex` and `claude` CLIs without changing external behavior?
2. Should the fix be runner-specific inside `_create_codex_subprocess` / `_create_claude_subprocess`, or pushed into the shared runner contract?
3. After prompt transport is fixed, do we still need prompt-size truncation to avoid excessive context cost and unstable retries?
4. Which existing tests best cover `_run_codex_phase` and multi-runner behavior, and what new regression should be added?
5. Since `tasks/` is currently empty, what PRD slug should be created for this bug fix at delivery time?

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Archive the existing active planning session before starting this task | The active notes belonged to a completed March 25 requirement-media task and would otherwise contaminate this bug investigation |
| Treat the screenshot as evidence of an orchestration-layer launch failure, not a frontend rendering bug | The displayed text matches backend exception logging from `_run_codex_phase`, and the UI is only surfacing stored DevLog content |
| Start a fresh planning workspace under `.claude/planning/current/` for this issue | The planning skill requires task-specific persistent state on disk |
| Defer the final prompt-transport implementation choice to Phase 2 | The code clearly shows argv-based prompt passing, but the safest replacement depends on actual CLI support and testability |
| Plan to create a new PRD in `tasks/` unless a better current PRD appears during implementation | `tasks/` has no active PRD files; only archived related design documents exist |
| Use stdin as the shared prompt transport for built-in runners and both launch modes | Codex explicitly documents stdin support, local Claude probing accepted stdin without usage failure, and this fixes both async and sync argv-size failures |
| Skip prompt truncation in this fix | The immediate production issue is launch-time argv overflow, and truncation would silently discard context without first proving it is necessary |
| Update docs together with the runner contract | The prompt transport moved from argv examples to stdin examples, so leaving docs unchanged would mislead future debugging |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| Active planning session belonged to an unrelated completed task | 1 | Archived the previous session and initialized a new `.claude/planning/current/` workspace |
| Automation retries repeated the same `Errno 7 Argument list too long` failure | 1 | Confirmed the exception happens before the runner starts, so the real fix must change prompt transport rather than retry logic |
| Some pytest runs against `tests/test_automation_runner_registry.py` and exact node-id selection stalled at `collecting ...` in the local environment | 1 | Used targeted `tests/test_codex_runner.py` regressions plus `mkdocs build` as primary verification evidence and recorded the collection issue as residual test-environment risk |

## Completion Summary

### FULL Format

#### Final Status
- **Completed:** YES
- **Completion Date:** 2026-03-30

#### Deliverables
| Deliverable | Location | Status |
|-------------|----------|--------|
| Runner stdin transport fix | `dsl/services/codex_runner.py` | complete |
| Runner protocol update | `dsl/services/runners/base.py` | complete |
| Codex CLI adapter stdin contract | `dsl/services/runners/codex_cli_runner.py` | complete |
| Claude CLI adapter stdin contract | `dsl/services/runners/claude_cli_runner.py` | complete |
| Regression tests for stdin prompt transport | `tests/test_codex_runner.py` | complete |
| Docs sync for prompt transport | `docs/guides/codex-cli-automation.md`, `docs/core/prompt-management.md` | complete |
| Delivery PRD | `tasks/20260330-100300-prd-runner-argv-length-fix.md` | complete |

#### Key Achievements
- Eliminated argv-sized prompt transport from the built-in Codex and Claude runner launch paths.
- Covered the same transport change in the sync conflict-resolution path so rebase/merge repair is not left behind.
- Added explicit regression tests proving prompt bytes are written to stdin and not kept in argv for the key launch sites.
- Synced the operator docs so troubleshooting now matches the delivered runtime contract.

#### Challenges & Solutions
| Challenge | Solution Applied |
|-----------|------------------|
| Codex and Claude prompt transport was duplicated across async and sync launch sites | Standardized the built-in runner contract around stdin-based prompt delivery and updated both paths |
| Local pytest environment was unstable for some registry/node-id runs | Relied on passing targeted regressions plus successful MkDocs build, and documented the verification limitation explicitly |

#### PRD Sync
- **PRD Path:** `tasks/20260330-100300-prd-runner-argv-length-fix.md`
- **Action:** created new PRD
- **Variances:** Did not add prompt truncation in this fix; retained full context and solved the reported failure by changing transport from argv to stdin.

#### Lessons Learned
- When prompt assembly is shared across multiple automation stages, transport details belong in the runner contract, not in one-off wrappers.
- File-count limits on recent logs are not a safe substitute for transport-safe prompt delivery.

#### Follow-up Items
- [ ] Investigate why some local pytest runs stall at `collecting ...` for `tests/test_automation_runner_registry.py` and exact node-id invocation.
- [ ] Decide later whether token-budget safeguards or prompt summarization should be added on top of the transport fix.
