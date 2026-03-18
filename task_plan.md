# Task Plan: WSL/Linux Terminal Launch Support

**Goal**: Replace the macOS-only `open-terminal` behavior with a cross-platform launcher that works on macOS, Linux, and WSL, while keeping the behavior configurable and documented.
**Started**: 2026-03-18

## Current Phase
All phases complete ✅

## Phases

### Phase 1: Discovery
- [x] Inspect the current `open-terminal` API implementation
- [x] Identify where the raw `{"detail": ...}` error reaches the frontend
- [x] Review runtime config and docs references for terminal-launch behavior
- **Status:** complete

### Phase 2: Backend Implementation
- [x] Add a terminal-launch helper with platform detection
- [x] Support an environment-variable override for custom launch commands
- [x] Update `open-terminal` to use the helper and return clearer errors
- **Status:** complete

### Phase 3: Frontend and Docs Sync
- [x] Improve frontend API error parsing so FastAPI `detail` shows cleanly
- [x] Update docs for Linux/WSL setup and configuration
- **Status:** complete

### Phase 4: Verification
- [x] Add focused automated tests for command selection
- [x] Run relevant pytest coverage
- [x] Run `uv run mkdocs build --strict`
- **Status:** complete

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Add a dedicated terminal-launch helper instead of growing endpoint-specific subprocess logic | Keeps platform branching testable and easier to extend |
| Provide `KODA_OPEN_TERMINAL_COMMAND` as an override | Linux terminal availability varies; an override avoids hardcoding every desktop environment |
| Keep automatic defaults for macOS, WSL, and common Linux launchers | Users should get a working out-of-the-box experience in common setups |

## Completion Summary
- **Status:** Complete (2026-03-18)
- **Tests:**
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_terminal_launcher.py` -> PASS
  - `UV_CACHE_DIR=/tmp/uv-cache uv run mkdocs build --strict` -> PASS
- **Deliverables:**
  - `dsl/services/terminal_launcher.py` - cross-platform terminal launcher with macOS, WSL, Linux, and template override support
  - `dsl/api/tasks.py` - `open-terminal` now uses the launcher service
  - `frontend/src/api/client.ts` - FastAPI `detail` messages are surfaced cleanly
  - `utils/settings.py` - config hook for `KODA_OPEN_TERMINAL_COMMAND`
  - `tests/test_terminal_launcher.py` - focused platform-selection coverage
  - `docs/` updates - Linux/WSL configuration and behavior documentation
