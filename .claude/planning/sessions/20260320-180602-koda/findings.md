# Findings & Decisions

## Requirements
- Explain why the project feels very slow during use.
- Confirm the main bottlenecks from the actual codebase instead of guessing.
- Apply the highest-value fixes if the bottlenecks are clear and low risk.

## Research Findings
- `frontend/src/App.tsx` currently triggers multiple overlapping polling loops:
  - When the selected task is in an active execution stage, it calls `loadDashboardData(true)` every 1 second.
  - Selecting any task starts a `logApi.list(selectedTaskId, 2000)` poll every 2 seconds.
  - PRD content polling also runs every 2 seconds when the task is in PRD-related stages.
- `loadDashboardData()` fetches four resources together: current run account, full task list, global log list, and project list. During active execution this means the UI refreshes all of them every second.
- `dsl/api/tasks.py:list_tasks()` computes `task_item.log_count = len(task_item.dev_logs)`, which can lazily load each task's full log relationship just to count rows.
- `dsl/api/logs.py:list_logs()` iterates over returned logs and touches `log.task.task_title`, which can cause N+1 relationship loading unless the task relationship is eagerly loaded.
- `frontend/src/App.tsx` asks for up to 2000 logs for the selected task on every poll, even though older log items are effectively immutable.
- The ORM models do not declare supporting indexes for the hottest filters/sorts (`tasks.run_account_id`, `dev_logs.task_id`, `dev_logs.run_account_id`, `created_at` orderings), so repeated polling gets more expensive as data grows.
- The local database currently contains `2` tasks and `20177` logs. The two tasks hold `12443` and `7734` logs respectively, so a repeated selected-task fetch is already operating at large-history scale.
- Average `dev_logs.text_content` length in the local database is about `230.89` characters, with a max of `1571`, so polling `2000` logs repeatedly moves a meaningful payload even before JSON/object overhead.
- `utils.helpers.parse_iso_datetime_text()` already parses offset-bearing ISO timestamps safely, so the log API can accept a frontend `created_after` cursor without inventing a new timestamp format.
- `frontend/src/utils/datetime.ts` already normalizes API datetime strings to real `Date` objects, so the frontend can derive a small overlap window from the latest loaded log timestamp.
- `docs/guides/dsl-development.md` and `docs/architecture/system-design.md` still describe the old “every second full refresh” behavior and need to be synchronized with the lighter polling model.
- The implemented fix set now does the following:
  - Replaces the 1-second full-dashboard active-execution poll with a 3-second task-list-only poll.
  - Keeps one full selected-task log fetch on task switch, then polls only a recent log window (`120`) instead of re-fetching `2000` rows every cycle.
  - Slows non-active task log polling to 6 seconds while keeping active-task polling at 2 seconds.
  - Replaces task log counting via `len(task_item.dev_logs)` with a grouped aggregate query.
  - Eager-loads `DevLog.task` title data for log listing to avoid per-log lazy relationship fetches.
  - Adds incremental `CREATE INDEX IF NOT EXISTS` patches for the hottest task/log queries.
- The follow-up incremental polling layer now does the following:
  - `/api/logs` accepts an optional `created_after` ISO 8601 query parameter.
  - When `created_after` is present, the backend returns logs in ascending `created_at` order so the frontend can advance its cursor without gaps.
  - The frontend derives a small 15-second overlap window from the latest loaded log and merges results locally by log ID, reducing payload size while still re-reading a tiny recent slice.
- The likely regression source after that change was front-end render churn, not the network request alone:
  - `mergeDevLogLists(...)` always returned a fresh array even when the overlap poll only returned already-known logs, which forced unnecessary `selectedTaskLogList` state updates and a full `App.tsx` rerender on every poll.
  - The feedback composer state lived inside the root `App` component, so each keystroke re-ran timeline grouping, PRD fallback markdown generation, and large JSX subtree reconciliation.
- Remaining lag after that fix still pointed at render volume:
  - The dashboard still rendered the entire currently loaded task timeline, which can be hundreds or thousands of Markdown blocks.
  - Active task polling still replaced `taskList` with a fresh array even when task data was effectively identical, causing background rerenders.
  - Fallback task-document generation still scanned a large selected-task log set even though only a recent summary is needed for the empty-PRD state.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Split heavy full-dashboard refresh from lightweight live task refresh | The active execution poll should not refetch projects, run account, and global logs every second |
| Keep one full selected-task log load, then poll only a recent window during active execution | This preserves full history view without repeatedly transferring 2000 entries |
| Fix task/log list ORM behavior on the backend before deeper architecture work | This directly removes obvious N+1 and over-fetch issues with minimal user-visible change |
| Add low-risk database indexes via incremental schema patches | Existing user databases can benefit without manual migration steps |
| Add `created_after` to `/api/logs` and use it from the selected-task poller | This removes repeated transfer of already-loaded logs while keeping the API surface simple |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Active planning files initially belonged to a different task | Archived the old planning session and created a fresh one |
| Switching workspace tabs clears selected-task logs before the next fetch | Made the full selected-task log fetch rerun on `workspaceView` changes as well |
| Local shell does not provide `sqlite3` | Used `uv run python` to inspect the SQLite database directly |
| Initial compile check accidentally passed TypeScript files to `py_compile` | Reran the Python compile check with Python files only; frontend syntax remained covered by `npm run build` |
| Incremental polling reduced payload size but still felt slower in practice | Traced the regression to no-op array replacement plus root-level feedback state causing unnecessary whole-page rerenders |
| The app still felt sluggish after removing the first rerender regression | Limited timeline render volume, skipped no-op task-list updates, and narrowed fallback document summarization to recent logs |

## Resources
- `frontend/src/App.tsx`
- `frontend/src/api/client.ts`
- `dsl/api/tasks.py`
- `dsl/api/logs.py`
- `dsl/services/task_service.py`
- `dsl/services/log_service.py`
- `utils/database.py`

## Visual/Browser Findings
- None. This investigation is code-path based.
