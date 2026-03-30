import type { Task } from "../types/index.ts";
import { toTimestampValue } from "./datetime.ts";

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
