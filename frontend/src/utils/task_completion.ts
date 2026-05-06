/** Task completion action rules.
 *
 * Keeps the dashboard Complete button conditions aligned with backend task
 * finalization semantics.
 */

import type { PreviewSandboxStatus, Task } from "../types/index.ts";

const CLOSED_TASK_LIFECYCLE_STATUS = "CLOSED";
const DELETED_TASK_LIFECYCLE_STATUS = "DELETED";
const ABANDONED_TASK_LIFECYCLE_STATUS = "ABANDONED";
const SELF_REVIEW_WORKFLOW_STAGE = "self_review_in_progress";
const TEST_WORKFLOW_STAGE = "test_in_progress";
const PR_PREPARING_WORKFLOW_STAGE = "pr_preparing";
const ACCEPTANCE_WORKFLOW_STAGE = "acceptance_in_progress";
const CHANGES_REQUESTED_WORKFLOW_STAGE = "changes_requested";

export interface CanCompleteTaskParams {
  taskItem: Task;
  taskStage: string | null;
  taskBranchHealth: Task["branch_health"];
  previewSandboxStatus?: PreviewSandboxStatus | null;
}

const BLOCKING_PREVIEW_FAILURE_KIND_SET = new Set([
  "dependency_error",
  "environment_error",
  "sandbox_error",
  "unknown",
]);

/**
 * Return whether the dashboard should show a Complete action.
 *
 * The backend still validates the final transition, but the frontend should not
 * hide Complete after a human manually fixes a worktree-backed
 * `changes_requested` task.
 */
export function canCompleteTask(params: CanCompleteTaskParams): boolean {
  const { previewSandboxStatus, taskBranchHealth, taskItem, taskStage } = params;

  if (
    taskItem.lifecycle_status === CLOSED_TASK_LIFECYCLE_STATUS ||
    taskItem.lifecycle_status === DELETED_TASK_LIFECYCLE_STATUS ||
    taskItem.lifecycle_status === ABANDONED_TASK_LIFECYCLE_STATUS
  ) {
    return false;
  }

  if (taskBranchHealth?.manual_completion_candidate) {
    return true;
  }

  if (
    previewSandboxStatus?.status === "needs_human_action" &&
    !previewSandboxStatus.bypass_confirmed &&
    previewSandboxStatus.failure_kind !== null &&
    BLOCKING_PREVIEW_FAILURE_KIND_SET.has(previewSandboxStatus.failure_kind)
  ) {
    return false;
  }

  if (!taskItem.worktree_path) {
    return false;
  }

  if (taskStage === CHANGES_REQUESTED_WORKFLOW_STAGE) {
    return true;
  }

  if (taskStage === SELF_REVIEW_WORKFLOW_STAGE) {
    return true;
  }

  return (
    taskStage === TEST_WORKFLOW_STAGE ||
    taskStage === PR_PREPARING_WORKFLOW_STAGE ||
    taskStage === ACCEPTANCE_WORKFLOW_STAGE
  );
}
