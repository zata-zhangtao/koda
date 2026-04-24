import assert from "node:assert/strict";

import type { Task } from "../src/types/index.ts";
import { canCompleteTask } from "../src/utils/task_completion.ts";

function buildTask(overrides: Partial<Task> = {}): Task {
  return {
    id: "task-1",
    run_account_id: "run-account-1",
    project_id: null,
    task_title: "Task 1",
    lifecycle_status: "OPEN" as Task["lifecycle_status"],
    workflow_stage: "backlog" as Task["workflow_stage"],
    last_ai_activity_at: null,
    stage_updated_at: "2026-04-24T17:30:00+08:00",
    worktree_path: null,
    requirement_brief: null,
    auto_confirm_prd_and_execute: false,
    business_sync_original_workflow_stage: null,
    business_sync_original_lifecycle_status: null,
    business_sync_restored_at: null,
    business_sync_status_note: null,
    destroy_reason: null,
    destroyed_at: null,
    created_at: "2026-04-24T17:30:00+08:00",
    closed_at: null,
    log_count: 0,
    is_codex_task_running: false,
    branch_health: null,
    ...overrides,
  };
}

assert.equal(
  canCompleteTask({
    taskItem: buildTask({
      worktree_path: "/tmp/koda-task-worktree",
      workflow_stage: "changes_requested" as Task["workflow_stage"],
    }),
    taskStage: "changes_requested",
    taskBranchHealth: null,
  }),
  true,
  "manual fixes in a changes_requested worktree should be completable"
);

assert.equal(
  canCompleteTask({
    taskItem: buildTask({
      worktree_path: "/tmp/koda-task-worktree",
      workflow_stage: "self_review_in_progress" as Task["workflow_stage"],
    }),
    taskStage: "self_review_in_progress",
    taskBranchHealth: null,
  }),
  true,
  "self-review tasks can still be manually completed"
);

assert.equal(
  canCompleteTask({
    taskItem: buildTask({
      lifecycle_status: "CLOSED" as Task["lifecycle_status"],
      worktree_path: "/tmp/koda-task-worktree",
      workflow_stage: "changes_requested" as Task["workflow_stage"],
    }),
    taskStage: "changes_requested",
    taskBranchHealth: null,
  }),
  false,
  "archived tasks should not expose Complete"
);

console.log("task_completion.test.ts: PASS");
