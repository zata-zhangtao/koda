# Findings & Decisions

## Requirements
- Creating a task with a selected project must persist the exact selected `project_id`.
- The UI must not silently carry an older project selection into a new task.
- The backend must reject nonexistent project IDs instead of storing stale values.

## Research Findings
- `frontend/src/App.tsx` submitted `newRequirementProjectId` directly, but the create-task draft was never reset when reopening or dismissing the create panel.
- The create-task panel and the project-management panel can be used in the same session, which makes stale `newRequirementProjectId` state a realistic failure mode.
- `dsl/api/tasks.py` and `dsl/services/task_service.py` previously accepted any `project_id` string without validating that the project still existed.
- The backend create path had no logic that intentionally remapped `project2` to `project1`; the credible bug source was stale frontend state plus missing backend validation.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Reset the create-task draft on open/close and when task context changes | Removes stale project carry-over between different task creation attempts |
| Clear `newRequirementProjectId` when the selected project disappears from `projectList` | Prevents the UI from holding invalid project references |
| After creating a project, select it in the create-task form only if that form is already open | Aligns with the in-progress user flow without surprising users elsewhere |
| Validate project existence in `TaskService.create_task` | Ensures persistence matches real project records and surfaces bad state as `422` |

## Resources
- `frontend/src/App.tsx`
- `dsl/api/tasks.py`
- `dsl/services/task_service.py`
- `tests/test_task_service.py`
