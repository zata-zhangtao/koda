# Findings & Decisions

## Requirements
- Fix the backend failures shown in the user-provided stack trace.
- Eliminate or materially reduce `sqlite3.OperationalError: database is locked` during active task execution.
- Keep the fix low risk and verify it with focused tests.

## Research Findings
- `/api/tasks` still calls `_hydrate_task_response(task_item)` for each task, and `_hydrate_task_response(...)` still computes `len(task_obj.dev_logs)`. That lazily loads full task log collections on the hot task-list path.
- `/api/logs` calls `LogService.get_logs(...)`, and `LogService.get_logs(...)` currently uses `selectinload(DevLog.task).load_only(Task.id, Task.task_title)`. That produces an extra follow-up query for task titles during log-list reads.
- The stack trace shows lock failures in both lazy task-log loading and the active-account lookup, which means the issue is not limited to one endpoint.
- `utils/database.py` currently builds SQLite engines with `check_same_thread=False` and `NullPool`, but it does not set a custom SQLite timeout or any connection PRAGMAs such as WAL or busy timeout.
- `dsl/services/codex_runner.py` writes DevLog rows through independent `SessionLocal()` sessions while the UI polls `/api/tasks` and `/api/logs`, so the runtime pattern is mixed background writes plus hot foreground reads.
- The combination of rollback-journal SQLite defaults plus relationship-driven extra reads is a credible explanation for the repeated lock failures shown by the user.
- The implemented patch now does the following:
  - Merges SQLite `timeout` into `connect_args`, sets `PRAGMA busy_timeout`, enables `foreign_keys=ON`, and attempts `journal_mode=WAL` plus `synchronous=NORMAL` for app-managed SQLite connections.
  - Changes `/api/tasks` list and detail hydration to consume grouped log counts instead of loading `Task.dev_logs`.
  - Changes log listing eager loading from `selectinload` to `joinedload`, keeping task-title access in the main query path.
  - Adds regression coverage for SQLite engine pragmas, task-list grouped count usage, and the log-list query count.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Add SQLite PRAGMA setup at engine connect time | This centralizes WAL and busy-timeout configuration for all app sessions |
| Keep `NullPool` for SQLite but extend connection settings | Separate connections are still desirable; they just need safer SQLite defaults |
| Change task-list hydration to consume precomputed counts | This removes the highest-cost lazy relationship access visible in the stack trace |
| Switch log-list task eager loading from `selectinload` to `joinedload` | It collapses the task-title fetch into one query and avoids a second read under contention |
| Update backend docs with the new SQLite behavior | The project instructions require documentation to stay synchronized with backend changes |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Existing active planning files described a different performance task | Archived and reinitialized planning state before continuing |
| `just docs-build` used a read-only default `uv` cache path inside the sandbox | Reran the docs build with `UV_CACHE_DIR=/tmp/uv-cache` |

## Resources
- `utils/database.py`
- `dsl/api/tasks.py`
- `dsl/api/logs.py`
- `dsl/services/task_service.py`
- `dsl/services/log_service.py`
- `dsl/services/codex_runner.py`
- `docs/guides/dsl-development.md`
- `docs/architecture/system-design.md`

## Visual/Browser Findings
- None. This investigation is based on the provided runtime trace and local code inspection.
