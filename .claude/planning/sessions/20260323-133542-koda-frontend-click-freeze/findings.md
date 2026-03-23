# Findings & Decisions

## Requirements
- Let `just dsl-dev` support manual port selection.
- Preserve the current default behavior for users who keep running plain `just dsl-dev`.
- Keep the effective frontend/backend wiring working when ports change, including the Vite proxy and backend CORS.
- Update the user-facing docs because command behavior is changing.

## Research Findings
- `justfile` defines `dsl-dev` without parameters today.
- The current `dsl-dev` behavior is asymmetric:
  - Backend uses `find_free_port 8000`, so it already falls forward automatically if `8000` is busy.
  - Frontend requires `5173` to be free and exits otherwise.
- `frontend/vite.config.ts` hard-codes:
  - `server.port = 5173`
  - `/api` proxy target `http://localhost:8000`
  - `/media` proxy target `http://localhost:8000`
- `dsl/app.py` hard-codes CORS origins for `http://localhost:5173` and `http://127.0.0.1:5173`.
- `main.py` already reads `KODA_SERVER_PORT`, so the backend server port can be steered externally without changing application startup code.
- The user-facing command contract appears in `README.md`, `docs/getting-started.md`, and `docs/guides/configuration.md`, all of which currently describe fixed ports and plain `just dsl-dev`.
- `just` recipe parameters are positional in practice here, so a call like `just dsl-dev backend_port=8100 frontend_port=5174` passes literal strings unless the recipe explicitly parses them.
- After the implementation, `dsl-dev` supports both named-style tokens (`backend_port=8100 frontend_port=5174`) and plain positional ports (`8100 5174`).

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Add optional `backend_port` and `frontend_port` parameters to `dsl-dev` | This is the smallest user-facing change that makes the command configurable |
| Still validate the requested ports before starting processes | Explicit overrides should fail fast instead of silently switching to another port |
| Use environment variables to feed the chosen ports into Vite and FastAPI | Avoid duplicating port knowledge across independent startup commands |
| Keep the named-token syntax documented even though `just` itself is positional | The recipe can parse the tokens explicitly, which preserves a clearer user-facing interface |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Active planning session was for another task | Archived it and created a fresh planning workspace for this change |

## Resources
- `justfile`
- `frontend/vite.config.ts`
- `dsl/app.py`
- `main.py`
- `README.md`
- `docs/getting-started.md`
- `docs/guides/configuration.md`

## Visual/Browser Findings
- None.

*Update this file after every 2 view/browser/search operations*
*This prevents visual information from being lost*
