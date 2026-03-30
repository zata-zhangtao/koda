# Findings & Decisions

## Requirements
- Fix the failure where the automation runner logs `Errno 7 Argument list too long` during AI auto-fix / self-review follow-up stages.
- Preserve current workflow semantics: retries, cancellation handling, stage rollback to `changes_requested`, and DevLog visibility.
- Keep the multi-runner design coherent for both Codex and Claude execution paths.
- Add regression coverage so large prompts do not silently reintroduce launch-time failures.
- Update or create a matching PRD under `tasks/` before delivery.

## Research Findings
- The screenshot shows a `System` abnormal-handling card at `10:32` with repeated entries like `runner kind=codex AI 自动回改（第 1 轮）阶段意外异常（Errno 7 Argument list too long），自动重试...`, followed by a fallback entry saying the task is waiting for manual or next-round handling.
- `dsl/services/codex_runner.py` launches Codex by calling `asyncio.create_subprocess_exec(...)` with the entire prompt text as a positional argv entry at line 1454.
- `dsl/services/runners/codex_cli_runner.py` and `dsl/services/runners/claude_cli_runner.py` both model prompt delivery as a CLI argument, so the abstraction currently assumes argv-based prompt transport.
- `_run_codex_phase(...)` catches generic exceptions around subprocess creation and logs them as phase-level unexpected errors before re-entering the automatic retry loop.
- The failing stage in the screenshot is consistent with the self-review auto-fix path that builds a prompt from recent logs plus the full latest review findings.
- `build_codex_review_fix_prompt(...)` includes the recent context block and the full self-review findings block; `_build_recent_context_block(...)` limits only the number of log entries, not total byte length.
- Local CLI help confirms `codex exec [PROMPT]` supports stdin input when the prompt argument is omitted or set to `-`, so Codex has a documented non-argv path for large prompts.
- Local Claude help does not state stdin behavior as explicitly, but `claude -p/--print` is documented as "useful for pipes", which makes stdin-based prompt delivery a plausible transport to validate.
- There is a second runner launch site in `dsl/services/codex_runner.py` conflict-resolution flow that uses synchronous `subprocess.run([... *build_exec_argument_list(prompt) ...])`; fixing only `_create_codex_subprocess` / `_create_claude_subprocess` would leave this path vulnerable to the same argv-size failure.
- A controlled local probe with `printf 'stdin prompt probe' | claude -p --dangerously-skip-permissions` did not fail with a usage error; it stayed running until `timeout` terminated it after 5 seconds, which is strong practical evidence that the installed Claude CLI accepts prompt text from stdin when no positional prompt argument is provided.
- `tasks/` currently contains no active PRD files. Relevant historical context only exists in archived PRDs such as `tasks/archive/20260319-020538-prd-ai-self-review-no-manual-confirmation.md` and `tasks/archive/20260326-234524-prd-multi-executor-claude-code-support.md`.
- Relevant regression surfaces already exist in `tests/test_codex_runner.py` and `tests/test_automation_runner_registry.py`.
- The delivered fix now covers three launch shapes: async Codex phases, async Claude phases, and sync runner conflict resolution for rebase/merge recovery.
- `docs/guides/codex-cli-automation.md` previously documented prompt transport as direct quoted argv strings; that guidance now needed to change to stdin examples to match runtime behavior.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Use a new planning session for this bug instead of reusing the previous one | The prior planning state was for a different completed feature and would pollute this investigation |
| Diagnose this as a process-launch / argv-size bug first | The exception text and subprocess call sites point to operating-system argument limits, not to prompt content correctness |
| Consider both transport fix and prompt-size guard in the design phase | Changing transport removes the immediate crash, but a length guard may still be useful for cost and stability |
| Treat `tests/test_codex_runner.py` and `tests/test_automation_runner_registry.py` as the primary verification targets | They already exercise orchestration behavior and runner selection, so they are the natural place for regressions |
| Plan to create a new PRD in `tasks/` at delivery unless a better active PRD emerges | There is no current non-archived PRD covering this issue |
| Favor stdin-based prompt delivery over argv where the CLI supports it | This directly removes the operating-system argv limit without forcing prompt truncation or shell redirection hacks |
| Push the transport change through the shared runner contract rather than patching only one async wrapper | Both async phase execution and sync conflict resolution use runner prompt arguments today |
| Do not add prompt truncation in the first fix | The reported production failure is specifically argv-size at process launch; stdin transport removes that failure without silently discarding runner context |
| Keep generic runner fallback compatible with the new contract | Once the runner protocol exposes stdin prompt transport, the fallback async launcher should honor it instead of assuming argv-only behavior |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Existing planning workspace was still occupied by an unrelated completed task | Archived it to `.claude/planning/sessions/20260330-093206-enable-image-and-video-input-in-requirement-create-edit-flows` and reinitialized `.claude/planning/current/` |
| `tasks/` has no active PRD files for this bug | Recorded archived context sources and planned a new PRD creation during delivery |
| Some local pytest invocations stalled during collection instead of failing fast | Used passing targeted regressions and successful docs build as the main verification set, and recorded the collection instability as residual environment risk |

## Resources
- `dsl/services/codex_runner.py`
- `dsl/services/runners/codex_cli_runner.py`
- `dsl/services/runners/claude_cli_runner.py`
- `tests/test_codex_runner.py`
- `tests/test_automation_runner_registry.py`
- `docs/guides/codex-cli-automation.md`
- `docs/core/prompt-management.md`
- `frontend/src/App.tsx`
- `tasks/archive/20260319-020538-prd-ai-self-review-no-manual-confirmation.md`
- `tasks/archive/20260326-234524-prd-multi-executor-claude-code-support.md`

## Visual/Browser Findings
- The user-provided screenshot is not a browser/network error view; it is the application’s own abnormal-handling log UI.
- The visible sequence is: two auto-retry entries for `AI 自动回改（第 1 轮）`, one final failure entry with `Errno 7 Argument list too long`, then a workflow-state message saying the task entered a waiting-for-modification stage.
- The screenshot therefore confirms that the system currently treats this launch error as a recoverable phase exception until retries are exhausted, even though the root cause is deterministic.
- The local archived PRD pattern is metadata-heavy and implementation-oriented; the new delivery PRD should record both the technical root cause and the actual shipped verification evidence.
