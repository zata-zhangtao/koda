import assert from "node:assert/strict";

import type { PreviewSandboxStatus, Task } from "../src/types/index.ts";
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
    worktree_base_branch_name: "main",
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

function buildPreviewSandboxStatus(
  overrides: Partial<PreviewSandboxStatus> = {}
): PreviewSandboxStatus {
  return {
    task_id: "task-1",
    status: "not_started",
    applicability: null,
    preview_url: null,
    profile_summary: null,
    failure_kind: null,
    failure_summary: null,
    bypass_confirmed: false,
    log_tail: null,
    container_id: null,
    host_port: null,
    internal_port: null,
    started_at: null,
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
      worktree_path: null,
      workflow_stage: "backlog" as Task["workflow_stage"],
    }),
    taskStage: "backlog",
    taskBranchHealth: null,
  }),
  false,
  "no-worktree tasks should not expose Complete"
);

assert.equal(
  canCompleteTask({
    taskItem: buildTask({
      worktree_path: "/tmp/koda-task-worktree",
      workflow_stage: "implementation_in_progress" as Task["workflow_stage"],
      branch_health: {
        expected_branch_name: "task/12345678",
        branch_exists: false,
        worktree_exists: false,
        manual_completion_candidate: true,
        status_message: "Branch missing",
      },
    }),
    taskStage: "implementation_in_progress",
    taskBranchHealth: {
      expected_branch_name: "task/12345678",
      branch_exists: false,
      worktree_exists: false,
      manual_completion_candidate: true,
      status_message: "Branch missing",
    },
  }),
  true,
  "manual completion candidates should expose Complete confirmation"
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

assert.equal(
  canCompleteTask({
    taskItem: buildTask({
      worktree_path: "/tmp/koda-task-worktree",
      workflow_stage: "test_in_progress" as Task["workflow_stage"],
    }),
    taskStage: "test_in_progress",
    taskBranchHealth: null,
    previewSandboxStatus: buildPreviewSandboxStatus({
      status: "needs_human_action",
      failure_kind: "sandbox_error",
      failure_summary: "Docker daemon unavailable",
    }),
  }),
  false,
  "non-code preview failures without bypass should block Complete"
);

assert.equal(
  canCompleteTask({
    taskItem: buildTask({
      worktree_path: "/tmp/koda-task-worktree",
      workflow_stage: "test_in_progress" as Task["workflow_stage"],
    }),
    taskStage: "test_in_progress",
    taskBranchHealth: null,
    previewSandboxStatus: buildPreviewSandboxStatus({
      status: "needs_human_action",
      failure_kind: "sandbox_error",
      failure_summary: "Docker daemon unavailable",
      bypass_confirmed: true,
    }),
  }),
  true,
  "preview bypass should restore Complete availability"
);

assert.equal(
  canCompleteTask({
    taskItem: buildTask({
      worktree_path: "/tmp/koda-task-worktree",
      workflow_stage: "test_in_progress" as Task["workflow_stage"],
    }),
    taskStage: "test_in_progress",
    taskBranchHealth: null,
    previewSandboxStatus: buildPreviewSandboxStatus({
      status: "runtime_state_lost",
      failure_kind: null,
    }),
  }),
  true,
  "runtime-state-lost without a blocking failure should still allow Complete"
);

console.log("task_completion.test.ts: PASS");
