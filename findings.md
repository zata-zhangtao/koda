# Findings & Decisions

## Requirements
- `self_review_in_progress` must represent an actual review activity, not only a stage update.
- The review should run automatically after implementation succeeds.
- Review output must be visible in the existing DevLog timeline.
- The implementation phase must not default to `git commit`; code submission requires user confirmation.
- Documentation must reflect the new runtime behavior.

## Research Findings
- `dsl/services/codex_runner.py` currently advances the task to `self_review_in_progress` immediately after `run_codex_task` exits successfully, but it does not start any follow-up review executor.
- `docs/architecture/system-design.md` and `docs/guides/dsl-development.md` already describe `self_review_in_progress` as part of the automated mainline, which makes the missing review runner a real behavior/documentation mismatch.
- `docs/architecture/technical-route-20260317.md` defines the intended self-review scope as PRD coverage, regressions, documentation sync, and error-path checks.
- `build_codex_prompt` previously told Codex to commit after implementation inside a worktree, which conflicts with the requirement that submission must wait for user confirmation.
- There are no existing tests for `dsl/services/codex_runner.py`, so this change needs new focused coverage around subprocess orchestration and stage/log side effects.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Add a dedicated self-review prompt builder | Keeps implementation instructions separate from review instructions and makes review behavior testable |
| Run self review automatically after implementation succeeds | Makes `self_review_in_progress` correspond to real work in the backend |
| Parse a structured review status marker from Codex output | Allows review findings to influence stage handling without needing JSON event streaming |
| Keep review output in the same task log stream | Preserves the existing operator workflow based on DevLog plus `/tmp/koda-<task>.log` |
| Leave passing tasks in `self_review_in_progress` for now | Prevents a false transition to `test_in_progress` before test automation exists |
| Make PRD completion and implementation completion separate from code submission | Matches the requirement that users confirm before any commit-style handoff |

## Resources
- `dsl/services/codex_runner.py`
- `dsl/api/tasks.py`
- `docs/guides/codex-cli-automation.md`
- `docs/architecture/system-design.md`
- `docs/guides/dsl-development.md`
