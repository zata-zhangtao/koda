import type { Task } from "../types/index.ts";
import { toTimestampValue } from "./datetime.ts";

const OPEN_TASK_LIFECYCLE_STATUS = "OPEN";
const PR_PREPARING_WORKFLOW_STAGE = "pr_preparing";

/**
 * Reconcile an in-memory task list with the latest server-returned task snapshot.
 *
 * The returned snapshot replaces any existing entry with the same task ID. If the
 * task is not present, it is inserted and the full list is resorted by `created_at`
 * descending to preserve the dashboard contract.
 */
export function reconcileTaskListWithReturnedTaskSnapshot(
  currentTaskList: Task[],
  returnedTaskSnapshot: Task
): Task[] {
  const nextTaskListWithoutReturnedSnapshot = currentTaskList.filter(
    (taskItem) => taskItem.id !== returnedTaskSnapshot.id
  );
  const nextTaskListWithReturnedSnapshot = [
    ...nextTaskListWithoutReturnedSnapshot,
    returnedTaskSnapshot,
  ];

  return nextTaskListWithReturnedSnapshot.sort(
    (leftTaskSnapshot, rightTaskSnapshot) =>
      toTimestampValue(rightTaskSnapshot.created_at) -
      toTimestampValue(leftTaskSnapshot.created_at)
  );
}

/**
 * Remove a task snapshot from the in-memory task list.
 *
 * Hard-deleting an unstarted draft returns HTTP 204, so the dashboard needs a
 * deterministic local removal path while the full refresh catches up.
 */
export function removeTaskSnapshotFromTaskList(
  currentTaskList: Task[],
  removedTaskId: string
): Task[] {
  return currentTaskList.filter((taskItem) => taskItem.id !== removedTaskId);
}

/**
 * Return whether a task should keep the dashboard task-list poll alive.
 *
 * `is_codex_task_running` is still the primary runtime signal. `pr_preparing`
 * is also treated as refresh-active because the completion runner can finish
 * quickly while the selected log poll has already appended terminal logs; a
 * stage-based fallback lets the task list observe the final `done / CLOSED`
 * snapshot without a manual browser refresh.
 */
export function shouldPollDashboardForTaskRefresh(
  taskSnapshot: Task
): boolean {
  if (taskSnapshot.is_codex_task_running) {
    return true;
  }

  return (
    taskSnapshot.lifecycle_status === OPEN_TASK_LIFECYCLE_STATUS &&
    taskSnapshot.workflow_stage === PR_PREPARING_WORKFLOW_STAGE
  );
}
