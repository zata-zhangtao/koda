# Findings & Decisions

## Requirements
- `just dsl-dev` should start the backend and frontend dev servers reliably for local development.
- The fix should avoid destructive behavior against unrelated local processes.
- Documentation must stay in sync with behavior changes.

## Research Findings
- `Justfile` currently starts both services in the background and then `wait`s, but it does not install any `trap`/cleanup logic.
- `main.py` binds Uvicorn to fixed port `8000` with `reload=True`.
- Active listeners were present on both `8000` and `5173` during investigation:
  - `lsof -nP -iTCP:8000 -sTCP:LISTEN`
  - `lsof -nP -iTCP:5173 -sTCP:LISTEN`
- This strongly suggests previous `dsl-dev` runs can leave child processes alive, causing the next run to collide with its own stale listeners.
- After the patch, `just dsl-dev` now stops immediately during preflight when `8000` is occupied and prints the owning listeners instead of leaving the frontend running.
- Documentation build passed with `uv run mkdocs build --strict`.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Add explicit port-availability checks to the launcher | Users get an immediate actionable error instead of partial startup then opaque bind failures |
| Add `trap`-driven cleanup for recipe-owned child processes | Solves the likely stale-process root cause without killing unrelated apps |
| Keep port numbers unchanged | Frontend proxy, CORS, and docs already assume `8000`/`5173`; changing ports would create unnecessary config churn |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Sandbox denied `ps` during process inspection | Used `lsof` evidence and code inspection instead; no blocker |
| Existing local listeners prevented a full clean boot verification run | Verified the fail-fast path instead and documented the remaining manual cleanup step |

## Resources
- `Justfile`
- `main.py`
- `docs/guides/dsl-development.md`
- `docs/getting-started.md`
- `docs/guides/configuration.md`
