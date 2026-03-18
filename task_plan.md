# Task Plan: Execute Real Self Review in `self_review_in_progress`

**Goal**: Ensure that after implementation finishes, Koda actually runs a Codex-powered code review during `self_review_in_progress` instead of only flipping the workflow stage.
**Started**: 2026-03-18

## Current Phase
All phases complete ✅

## Phases

### Phase 1: Discovery
- [x] Inspect the current implementation-to-review handoff
- [x] Identify the safest place to trigger a dedicated review run
- [x] Define review outcomes and their stage/log effects
- **Status:** complete

### Phase 2: Implementation
- [x] Add a dedicated self-review Codex prompt and runner
- [x] Reuse existing retry, logging, and cancellation behavior
- [x] Ensure implementation success transitions into a real review run
- [x] Keep failure behavior coherent for review findings vs execution failures
- [x] Remove default auto-commit instructions and require user confirmation before commit
- **Status:** complete

### Phase 3: Verification
- [x] Add focused tests for review execution and outcome handling
- [x] Run relevant automated checks
- [x] Run `uv run mkdocs build --strict`
- **Status:** complete

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Reuse the existing Codex subprocess pattern for self review | Keeps cancellation, retry, stdout streaming, and DevLog behavior consistent across phases |
| Treat implementation and self review as separate phase executions | Preserves the semantics of `self_review_in_progress` as an actual running phase instead of a passive label |
| Keep successful reviews in `self_review_in_progress` and only auto-regress on blocking findings | Avoids pretending that tests are running before the project has a real automated `test_in_progress` executor |
| Remove default `git commit` instructions from the implementation prompt | PRD completion and implementation output should still require explicit user confirmation before code submission |

## Completion Summary
- **Status:** Complete (2026-03-18)
- **Tests:**
  - `uv run python -m py_compile dsl/services/codex_runner.py dsl/api/tasks.py tests/test_codex_runner.py` -> PASS
  - `UV_CACHE_DIR=/tmp/uv-cache uv run python - <<'PY' ... pytest.main(['tests/test_codex_runner.py', 'tests/test_task_service.py', '-vv', '-s']) ... PY` -> PASS
  - `UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build --strict` -> PASS
- **Deliverables:**
  - `dsl/services/codex_runner.py` - real self-review phase runner, structured review status parsing, no default auto-commit instruction
  - `tests/test_codex_runner.py` - regression coverage for passing and failing self-review flows plus prompt confirmation requirements
  - `dsl/api/tasks.py` - updated execute-task contract comments/docstring
  - `docs/guides/codex-cli-automation.md`, `docs/guides/dsl-development.md`, `docs/architecture/system-design.md`, `docs/index.md` - synchronized workflow and confirmation docs
