/** Workspace view utilities
 *
 * Centralizes header workspace bucket rules and transition decisions so the
 * dashboard can keep detail content stable while tabs change.
 */

import type { Task } from "../types/index.ts";

export type WorkspaceView = "active" | "completed" | "changes";

export interface WorkspaceTaskBuckets {
  activeTaskList: Task[];
  completedTaskList: Task[];
  changedTaskList: Task[];
}

export interface BuildWorkspaceTaskBucketsParams {
  taskList: Task[];
  changedTaskIdSet: ReadonlySet<string>;
}

export interface ResolveWorkspaceSelectedTaskIdParams {
  candidateSelectedTaskId: string | null;
  visibleTaskList: Task[];
}

export interface ResolveWorkspaceDetailSelectionParams {
  deferredSelectedTaskId: string | null;
  selectedTaskId: string | null;
  visibleTaskList: Task[];
}

export interface ResolveManualWorkspaceSwitchParams {
  currentSelectedTaskId: string | null;
  targetWorkspaceView: WorkspaceView;
  workspaceTaskBuckets: WorkspaceTaskBuckets;
}

export interface ResolveAutoWorkspaceSwitchTargetViewParams {
  changedTaskIdSet: ReadonlySet<string>;
  currentTimestamp: number;
  currentWorkspaceView: WorkspaceView;
  lastManualWorkspaceSwitchAt: number | null;
  selectedTaskId: string | null;
  taskList: Task[];
  visibleTaskList: Task[];
  guardWindowMs?: number;
}

export interface ManualWorkspaceSwitchResult {
  nextSelectedTaskId: string | null;
  nextWorkspaceView: WorkspaceView;
}

export interface WorkspaceDetailSelection {
  detailTaskId: string | null;
  isTaskSelectionPending: boolean;
}

export const MANUAL_WORKSPACE_AUTO_SWITCH_GUARD_MS = 1_500;
const CLOSED_TASK_LIFECYCLE_STATUS = "CLOSED";
const DELETED_TASK_LIFECYCLE_STATUS = "DELETED";
const ABANDONED_TASK_LIFECYCLE_STATUS = "ABANDONED";

export function resolveWorkspaceViewForTask(
  taskItem: Task,
  changedTaskIdSet: ReadonlySet<string>
): WorkspaceView {
  if (taskItem.lifecycle_status === CLOSED_TASK_LIFECYCLE_STATUS) {
    return "completed";
  }

  if (
    taskItem.lifecycle_status === DELETED_TASK_LIFECYCLE_STATUS ||
    taskItem.lifecycle_status === ABANDONED_TASK_LIFECYCLE_STATUS ||
    changedTaskIdSet.has(taskItem.id)
  ) {
    return "changes";
  }

  return "active";
}

export function buildWorkspaceTaskBuckets(
  params: BuildWorkspaceTaskBucketsParams
): WorkspaceTaskBuckets {
  const { changedTaskIdSet, taskList } = params;
  const activeTaskList = taskList.filter(
    (taskItem) => resolveWorkspaceViewForTask(taskItem, changedTaskIdSet) === "active"
  );
  const completedTaskList = taskList.filter(
    (taskItem) => resolveWorkspaceViewForTask(taskItem, changedTaskIdSet) === "completed"
  );
  const changedTaskList = taskList.filter(
    (taskItem) => resolveWorkspaceViewForTask(taskItem, changedTaskIdSet) === "changes"
  );

  return {
    activeTaskList,
    completedTaskList,
    changedTaskList,
  };
}

export function resolveWorkspaceViewTaskList(
  workspaceView: WorkspaceView,
  workspaceTaskBuckets: WorkspaceTaskBuckets
): Task[] {
  if (workspaceView === "completed") {
    return workspaceTaskBuckets.completedTaskList;
  }

  if (workspaceView === "changes") {
    return workspaceTaskBuckets.changedTaskList;
  }

  return workspaceTaskBuckets.activeTaskList;
}

export function resolveWorkspaceSelectedTaskId(
  params: ResolveWorkspaceSelectedTaskIdParams
): string | null {
  const { candidateSelectedTaskId, visibleTaskList } = params;
  if (visibleTaskList.length === 0) {
    return null;
  }

  if (
    candidateSelectedTaskId &&
    visibleTaskList.some((taskItem) => taskItem.id === candidateSelectedTaskId)
  ) {
    return candidateSelectedTaskId;
  }

  return visibleTaskList[0]?.id ?? null;
}

export function resolveWorkspaceDetailSelection(
  params: ResolveWorkspaceDetailSelectionParams
): WorkspaceDetailSelection {
  const { deferredSelectedTaskId, selectedTaskId, visibleTaskList } = params;
  const shouldRenderStableEmptyDetailState =
    selectedTaskId === null && visibleTaskList.length === 0;
  if (shouldRenderStableEmptyDetailState) {
    return {
      detailTaskId: null,
      isTaskSelectionPending: false,
    };
  }

  return {
    detailTaskId: deferredSelectedTaskId,
    isTaskSelectionPending:
      selectedTaskId !== null && selectedTaskId !== deferredSelectedTaskId,
  };
}

export function resolveManualWorkspaceSwitch(
  params: ResolveManualWorkspaceSwitchParams
): ManualWorkspaceSwitchResult {
  const targetVisibleTaskList = resolveWorkspaceViewTaskList(
    params.targetWorkspaceView,
    params.workspaceTaskBuckets
  );
  const nextSelectedTaskId = resolveWorkspaceSelectedTaskId({
    candidateSelectedTaskId: params.currentSelectedTaskId,
    visibleTaskList: targetVisibleTaskList,
  });

  return {
    nextSelectedTaskId,
    nextWorkspaceView: params.targetWorkspaceView,
  };
}

export function hasRecentManualWorkspaceSwitch(
  currentTimestamp: number,
  lastManualWorkspaceSwitchAt: number | null,
  guardWindowMs = MANUAL_WORKSPACE_AUTO_SWITCH_GUARD_MS
): boolean {
  if (lastManualWorkspaceSwitchAt === null) {
    return false;
  }

  return currentTimestamp - lastManualWorkspaceSwitchAt < guardWindowMs;
}

export function resolveAutoWorkspaceSwitchTargetView(
  params: ResolveAutoWorkspaceSwitchTargetViewParams
): WorkspaceView | null {
  const {
    changedTaskIdSet,
    currentTimestamp,
    currentWorkspaceView,
    guardWindowMs,
    lastManualWorkspaceSwitchAt,
    selectedTaskId,
    taskList,
    visibleTaskList,
  } = params;
  if (!selectedTaskId) {
    return null;
  }

  if (visibleTaskList.some((taskItem) => taskItem.id === selectedTaskId)) {
    return null;
  }

  if (
    hasRecentManualWorkspaceSwitch(
      currentTimestamp,
      lastManualWorkspaceSwitchAt,
      guardWindowMs
    )
  ) {
    return null;
  }

  const selectedTask = taskList.find((taskItem) => taskItem.id === selectedTaskId);
  if (!selectedTask) {
    return null;
  }

  const resolvedWorkspaceView = resolveWorkspaceViewForTask(
    selectedTask,
    changedTaskIdSet
  );
  if (
    resolvedWorkspaceView === "active" ||
    resolvedWorkspaceView === currentWorkspaceView
  ) {
    return null;
  }

  return resolvedWorkspaceView;
}
