# Findings & Decisions

## Requirements
- `POST /api/tasks/{task_id}/open-terminal` should stop failing on non-macOS environments.
- WSL/Linux users need a way to define their own terminal command when the default launcher is not available.
- Documentation must explain both the default behavior and the override path.

## Research Findings
- `dsl/api/tasks.py` currently shells out only to `osascript`, so the endpoint is hard-failed outside macOS.
- The frontend API client currently throws the raw response body text, which is why FastAPI JSON errors appear in the UI as `{"detail":"..."}`.
- Project/worktree opening already uses `trae-cn`; the platform gap is isolated to the terminal-launch path.
- `utils/settings.py` currently has no runtime setting for terminal launch customization.
- Docs mention `osascript` in multiple places:
  - `docs/getting-started.md`
  - `docs/guides/deployment.md`
  - `docs/guides/codex-cli-automation.md`
  - `docs/architecture/system-design.md`

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Add a small `terminal_launcher` service module | Makes platform detection and subprocess command building independently testable |
| Support `KODA_OPEN_TERMINAL_COMMAND` with placeholders | Lets WSL/Linux users set a launcher without patching source code |
| Detect WSL separately from generic Linux | WSL often has no local X terminal, so it needs a different default strategy than desktop Linux |
| Improve frontend error parsing while touching this flow | Prevents raw JSON blobs from being shown to users for this and other API errors |

## Resources
- `dsl/api/tasks.py`
- `frontend/src/api/client.ts`
- `utils/settings.py`
- `docs/getting-started.md`
- `docs/guides/configuration.md`
- `docs/guides/deployment.md`
- `docs/guides/codex-cli-automation.md`
- `docs/architecture/system-design.md`
