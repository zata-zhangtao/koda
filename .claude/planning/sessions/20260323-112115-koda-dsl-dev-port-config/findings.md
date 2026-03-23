# Findings & Decisions

## Requirements
- Explain why the project feels slow and where the bottleneck is.
- Base the answer on local repository evidence rather than generic performance advice.
- Distinguish likely bottlenecks by layer if needed: development startup, backend runtime, frontend runtime, and background task execution.

## Research Findings
- The repository has multiple moving parts that can contribute to perceived slowness: `dsl/`, `frontend/`, `forwarding_service/`, background task runners, docs tooling, and Docker deployment assets.
- The active planning session before this investigation belonged to a previous SQLite lock analysis, so it had to be archived to keep this task isolated.
- The previous performance-related findings in the archived session already suggest one likely backend issue class: SQLite reader/writer contention during active runs.
- `README.md` and `justfile` show the primary local workflow is `just dsl-dev`, which means the user is likely feeling slowness in a development environment rather than only in a production build.
- The codebase clearly mixes three performance-sensitive patterns:
  - React frontend with repeated `useEffect` polling and multiple `setInterval` timers in `frontend/src/App.tsx`.
  - FastAPI backend on SQLite in `dsl/` and `utils/database.py`.
  - Long-running background Codex subprocesses and Git/bootstrap shell calls in `dsl/services/codex_runner.py` and related services.
- `frontend/src/App.tsx` contains polling loops at 2-second intervals for task data and PRD loading, which makes repeated backend reads a prime candidate for perceived UI sluggishness under load.
- The repository still contains many synchronous `subprocess.run(...)` usages in API/service code, so some endpoints may block request handling while shell commands execute.
- `just dsl-dev` starts both `uv run python main.py` and `npm run dev`; that is normal for local development, but it means the user is paying the cost of both Vite HMR and the Python backend simultaneously.
- `initializeDashboard()` triggers `loadAppConfig()` and `loadDashboardData()`, and `loadDashboardData()` concurrently requests four endpoints: current account, task list, global log list, and project list.
- During active execution, `frontend/src/App.tsx` adds an extra 1-second polling loop that reruns `loadDashboardData(true)`, so the full four-request dashboard refresh happens every second while a task is running.
- The selected task view adds two more 2-second polling loops:
  - `logApi.list(selectedTaskId, 2000)` fetches up to 2000 logs for the selected task.
  - `taskApi.getPrdFile(selectedTaskId)` polls PRD file content while the task is in PRD-related stages.
- `dsl/services/codex_runner.py` batches Codex output into the database every 5 lines or 1.5 seconds (`_LOG_BATCH_SIZE = 5`, `_LOG_FLUSH_INTERVAL_SECONDS = 1.5`), which creates a steady stream of SQLite writes during execution.
- `utils/database.py` now enables WAL and busy timeout for SQLite, which reduces lock failures, but the app still uses SQLite plus `NullPool`, so the architecture remains vulnerable to mixed high-frequency read/write load compared with a real client/server database.
- `dsl/api/tasks.py` no longer lazily loads task logs for list responses if `log_count_override` is provided, so one previously known N+1-style problem has already been mitigated.
- The current local dataset is already large enough for these polling choices to hurt:
  - `dev_logs`: 145153 rows
  - `tasks`: 8 rows
  - `projects`: 2 rows
  - `data/dsl.db`: 89 MB
- The largest single task currently has 60969 logs, so repeated timeline polling is reading from a genuinely hot and large table, not a toy dataset.
- Focused local benchmarks on the current database show:
  - `TaskService.get_task_log_count_map(...)`: about 94.87 ms average
  - `LogService.get_logs(..., limit=2000)` for the selected task: about 159.43 ms average
  - `LogService.get_logs(..., limit=100)` for the global dashboard list: about 4.08 ms average
  - `/api/projects` response shaping for 2 projects: about 13.14 ms average
- These numbers point to the main steady-state bottleneck: the UI keeps issuing expensive log-table reads against SQLite, especially the selected-task 2000-log polling path and the dashboard's per-task log-count aggregation.
- A secondary bottleneck exists in `/api/projects`: every dashboard refresh calls `projectApi.list()`, and each project response recomputes repo consistency by running synchronous Git subprocesses (`git config --get remote.origin.url` and `git rev-parse HEAD`). With only 2 projects this is modest, but the cost scales linearly with project count and filesystem latency.
- `just dsl-dev` does incur the normal cost of running both Vite and the Python backend, but that explains startup/dev-mode overhead more than the ongoing in-app lag after the page is already open.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Audit hot paths before editing code | The user asked for diagnosis rather than a blind optimization pass |
| Consider SQLite locking history as a lead, not a conclusion | It may explain API lag during active runs, but not startup or frontend sluggishness |
| Treat frontend polling load as a first-class bottleneck candidate | The frontend currently multiplies backend pressure during the exact periods when Codex is generating logs |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Existing planning files were for another task | Archived the prior session and created a fresh planning workspace |
| One inline benchmark script failed with a Python syntax error | Fixed the script and reran the benchmark successfully |

## Resources
- `justfile`
- `README.md`
- `pyproject.toml`
- `frontend/src/App.tsx`
- `dsl/app.py`
- `dsl/services/codex_runner.py`
- `dsl/api/tasks.py`
- `dsl/api/logs.py`
- `dsl/services/log_service.py`
- `utils/database.py`
- `.claude/planning/sessions/20260323-104420-koda/`

## Visual/Browser Findings
- None.

## Ranked Bottlenecks
1. Selected-task log polling in `frontend/src/App.tsx` requests up to 2000 logs every 2 seconds whenever a task is selected, even outside active execution.
2. Dashboard task refresh recomputes per-task log counts from the large `dev_logs` table on each refresh cycle.
3. Codex execution writes fresh `DevLog` batches into SQLite every 1.5 seconds or every 5 lines, colliding with the read-heavy polling pattern.
4. Dashboard project refresh recomputes Git consistency snapshots through synchronous subprocess calls on every refresh cycle.
5. Development-mode overhead from `just dsl-dev` exists, but it is a smaller contributor than the runtime polling and SQLite traffic.
