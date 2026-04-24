import assert from "node:assert/strict";

import type { Task } from "../src/types/index.ts";
import {
  reconcileTaskListWithReturnedTaskSnapshot,
  removeTaskSnapshotFromTaskList,
  shouldPollDashboardForTaskRefresh,
} from "../src/utils/task_list.ts";

function buildTaskSnapshot(taskId: string, overrides?: Partial<Task>): Task {
  return {
    id: taskId,
    run_account_id: "run-account-1",
    project_id: "project-1",
    task_title: `Task ${taskId}`,
    lifecycle_status: "OPEN" as Task["lifecycle_status"],
    workflow_stage: "test_in_progress" as Task["workflow_stage"],
    last_ai_activity_at: "2026-03-30T08:00:00+08:00",
    stage_updated_at: "2026-03-30T08:10:00+08:00",
    worktree_path: `/tmp/${taskId}`,
    requirement_brief: "Verify manual complete refresh handling",
    auto_confirm_prd_and_execute: false,
    destroy_reason: null,
    destroyed_at: null,
    created_at: "2026-03-30T08:00:00+08:00",
    closed_at: null,
    log_count: 3,
    is_codex_task_running: false,
    branch_health: {
      expected_branch_name: `task/${taskId}`,
      branch_exists: false,
      worktree_exists: false,
      manual_completion_candidate: true,
      status_message: "Task branch is missing.",
    },
    ...overrides,
  };
}

const olderOpenTaskSnapshot = buildTaskSnapshot("task-older", {
  created_at: "2026-03-30T07:00:00+08:00",
});
const targetOpenTaskSnapshot = buildTaskSnapshot("task-target", {
  created_at: "2026-03-30T08:00:00+08:00",
  workflow_stage: "test_in_progress" as Task["workflow_stage"],
  lifecycle_status: "OPEN" as Task["lifecycle_status"],
  closed_at: null,
});
const newerClosedTaskSnapshot = buildTaskSnapshot("task-newer", {
  created_at: "2026-03-30T09:00:00+08:00",
  lifecycle_status: "CLOSED" as Task["lifecycle_status"],
  workflow_stage: "done" as Task["workflow_stage"],
  closed_at: "2026-03-30T09:05:00+08:00",
  branch_health: {
    expected_branch_name: "task/task-newer",
    branch_exists: false,
    worktree_exists: false,
    manual_completion_candidate: false,
    status_message: null,
  },
});

const manuallyCompletedTaskSnapshot = buildTaskSnapshot("task-target", {
  created_at: "2026-03-30T08:00:00+08:00",
  lifecycle_status: "CLOSED" as Task["lifecycle_status"],
  workflow_stage: "done" as Task["workflow_stage"],
  closed_at: "2026-03-30T08:30:00+08:00",
  worktree_path: null,
  branch_health: {
    expected_branch_name: "task/task-target",
    branch_exists: false,
    worktree_exists: false,
    manual_completion_candidate: false,
    status_message: "Task manually completed after branch-missing confirmation.",
  },
});
const changesRequestedTaskSnapshot = buildTaskSnapshot("task-target", {
  created_at: "2026-03-30T08:00:00+08:00",
  lifecycle_status: "OPEN" as Task["lifecycle_status"],
  workflow_stage: "changes_requested" as Task["workflow_stage"],
  is_codex_task_running: false,
});
const destroyedTaskSnapshot = buildTaskSnapshot("task-target", {
  created_at: "2026-03-30T08:00:00+08:00",
  lifecycle_status: "DELETED" as Task["lifecycle_status"],
  workflow_stage: "done" as Task["workflow_stage"],
  destroy_reason: "User destroyed a started task.",
  destroyed_at: "2026-03-30T08:45:00+08:00",
});

const reconciledTaskList = reconcileTaskListWithReturnedTaskSnapshot(
  [olderOpenTaskSnapshot, targetOpenTaskSnapshot, newerClosedTaskSnapshot],
  manuallyCompletedTaskSnapshot
);

assert.equal(reconciledTaskList.length, 3);
assert.deepEqual(
  reconciledTaskList.map((taskSnapshot) => taskSnapshot.id),
  ["task-newer", "task-target", "task-older"]
);
assert.equal(
  reconciledTaskList.find((taskSnapshot) => taskSnapshot.id === "task-target")
    ?.lifecycle_status,
  "CLOSED"
);
assert.equal(
  reconciledTaskList.find((taskSnapshot) => taskSnapshot.id === "task-target")
    ?.workflow_stage,
  "done"
);

const changesRequestedTaskList = reconcileTaskListWithReturnedTaskSnapshot(
  [olderOpenTaskSnapshot, targetOpenTaskSnapshot],
  changesRequestedTaskSnapshot
);

assert.equal(
  changesRequestedTaskList.find((taskSnapshot) => taskSnapshot.id === "task-target")
    ?.workflow_stage,
  "changes_requested",
  "request-changes snapshots should replace the selected task immediately"
);

const destroyedTaskList = reconcileTaskListWithReturnedTaskSnapshot(
  [olderOpenTaskSnapshot, targetOpenTaskSnapshot],
  destroyedTaskSnapshot
);

assert.equal(
  destroyedTaskList.find((taskSnapshot) => taskSnapshot.id === "task-target")
    ?.destroy_reason,
  "User destroyed a started task.",
  "destroy snapshots should replace the selected task immediately"
);

const insertedTaskSnapshot = buildTaskSnapshot("task-inserted", {
  created_at: "2026-03-30T08:30:00+08:00",
});
const taskListWithInsertedSnapshot = reconcileTaskListWithReturnedTaskSnapshot(
  [olderOpenTaskSnapshot, targetOpenTaskSnapshot],
  insertedTaskSnapshot
);

assert.deepEqual(
  taskListWithInsertedSnapshot.map((taskSnapshot) => taskSnapshot.id),
  ["task-inserted", "task-target", "task-older"]
);

const taskListAfterHardDelete = removeTaskSnapshotFromTaskList(
  [olderOpenTaskSnapshot, targetOpenTaskSnapshot, newerClosedTaskSnapshot],
  targetOpenTaskSnapshot.id
);

assert.deepEqual(
  taskListAfterHardDelete.map((taskSnapshot) => taskSnapshot.id),
  ["task-older", "task-newer"],
  "hard-deleted drafts should disappear from the local list immediately"
);

assert.equal(
  shouldPollDashboardForTaskRefresh(
    buildTaskSnapshot("task-running", {
      is_codex_task_running: true,
      workflow_stage: "implementation_in_progress" as Task["workflow_stage"],
    })
  ),
  true,
  "running tasks should keep dashboard polling active"
);

assert.equal(
  shouldPollDashboardForTaskRefresh(
    buildTaskSnapshot("task-pr-preparing", {
      is_codex_task_running: false,
      lifecycle_status: "OPEN" as Task["lifecycle_status"],
      workflow_stage: "pr_preparing" as Task["workflow_stage"],
    })
  ),
  true,
  "open pr_preparing tasks should keep polling until the final done snapshot appears"
);

assert.equal(
  shouldPollDashboardForTaskRefresh(
    buildTaskSnapshot("task-closed", {
      is_codex_task_running: false,
      lifecycle_status: "CLOSED" as Task["lifecycle_status"],
      workflow_stage: "done" as Task["workflow_stage"],
    })
  ),
  false,
  "closed tasks should not keep dashboard polling active"
);

console.log("task_list.test.ts: PASS");
