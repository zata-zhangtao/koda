import assert from "node:assert/strict";

import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";

import { useInertSubtree } from "../src/hooks/useInertSubtree.ts";
import {
  MANUAL_WORKSPACE_AUTO_SWITCH_GUARD_MS,
  buildWorkspaceTaskBuckets,
  hasRecentManualWorkspaceSwitch,
  resolveAutoWorkspaceSwitchTargetView,
  resolveWorkspaceDetailSelection,
  resolveManualWorkspaceSwitch,
  resolveWorkspaceSelectedTaskId,
  resolveWorkspaceViewForTask,
} from "../src/utils/workspace_view.ts";

function setGlobalProperty(
  propertyName: string,
  propertyValue: unknown
): void {
  Object.defineProperty(globalThis, propertyName, {
    configurable: true,
    value: propertyValue,
    writable: true,
  });
}

function installDomGlobals(jsdomWindow: Window): void {
  setGlobalProperty("window", jsdomWindow);
  setGlobalProperty("document", jsdomWindow.document);
  setGlobalProperty("navigator", jsdomWindow.navigator);
  setGlobalProperty("HTMLElement", jsdomWindow.HTMLElement);
  setGlobalProperty("Node", jsdomWindow.Node);
  setGlobalProperty("Event", jsdomWindow.Event);
  setGlobalProperty("KeyboardEvent", jsdomWindow.KeyboardEvent);
  setGlobalProperty("MouseEvent", jsdomWindow.MouseEvent);
  setGlobalProperty(
    "requestAnimationFrame",
    jsdomWindow.requestAnimationFrame.bind(jsdomWindow)
  );
  setGlobalProperty(
    "cancelAnimationFrame",
    jsdomWindow.cancelAnimationFrame.bind(jsdomWindow)
  );
  setGlobalProperty("IS_REACT_ACT_ENVIRONMENT", true);
}

function buildTask(taskId: string, lifecycleStatus: string) {
  return {
    id: taskId,
    run_account_id: "run-account-1",
    project_id: null,
    task_title: `Task ${taskId}`,
    lifecycle_status: lifecycleStatus,
    workflow_stage: "backlog",
    last_ai_activity_at: null,
    stage_updated_at: "2026-03-30T08:00:00+08:00",
    worktree_path: null,
    requirement_brief: null,
    auto_confirm_prd_and_execute: false,
    destroy_reason: null,
    destroyed_at: null,
    created_at: "2026-03-30T08:00:00+08:00",
    closed_at: null,
    log_count: 0,
    is_codex_task_running: false,
    branch_health: null,
  };
}

const activeTask = buildTask("task-active", "OPEN");
const completedTask = buildTask("task-completed", "CLOSED");
const changedTask = buildTask("task-changed", "OPEN");
const deletedTask = buildTask("task-deleted", "DELETED");
const changedTaskIdSet = new Set<string>(["task-changed"]);
const workspaceTaskBuckets = buildWorkspaceTaskBuckets({
  taskList: [activeTask, completedTask, changedTask, deletedTask],
  changedTaskIdSet,
});

assert.equal(resolveWorkspaceViewForTask(activeTask, changedTaskIdSet), "active");
assert.equal(resolveWorkspaceViewForTask(completedTask, changedTaskIdSet), "completed");
assert.equal(resolveWorkspaceViewForTask(changedTask, changedTaskIdSet), "changes");
assert.equal(resolveWorkspaceViewForTask(deletedTask, changedTaskIdSet), "changes");

assert.deepEqual(
  workspaceTaskBuckets.activeTaskList.map((taskItem) => taskItem.id),
  ["task-active"]
);
assert.deepEqual(
  workspaceTaskBuckets.completedTaskList.map((taskItem) => taskItem.id),
  ["task-completed"]
);
assert.deepEqual(
  workspaceTaskBuckets.changedTaskList.map((taskItem) => taskItem.id),
  ["task-changed", "task-deleted"]
);

assert.equal(
  resolveWorkspaceSelectedTaskId({
    candidateSelectedTaskId: "task-active",
    visibleTaskList: workspaceTaskBuckets.activeTaskList,
  }),
  "task-active"
);
assert.equal(
  resolveWorkspaceSelectedTaskId({
    candidateSelectedTaskId: "task-missing",
    visibleTaskList: workspaceTaskBuckets.completedTaskList,
  }),
  "task-completed"
);
assert.equal(
  resolveWorkspaceSelectedTaskId({
    candidateSelectedTaskId: null,
    visibleTaskList: [],
  }),
  null
);
assert.deepEqual(
  resolveWorkspaceDetailSelection({
    deferredSelectedTaskId: "task-active",
    selectedTaskId: null,
    visibleTaskList: [],
  }),
  {
    detailTaskId: null,
    isTaskSelectionPending: false,
  }
);
assert.deepEqual(
  resolveWorkspaceDetailSelection({
    deferredSelectedTaskId: "task-active",
    selectedTaskId: "task-completed",
    visibleTaskList: workspaceTaskBuckets.completedTaskList,
  }),
  {
    detailTaskId: "task-active",
    isTaskSelectionPending: true,
  }
);
assert.deepEqual(
  resolveWorkspaceDetailSelection({
    deferredSelectedTaskId: "task-completed",
    selectedTaskId: "task-completed",
    visibleTaskList: workspaceTaskBuckets.completedTaskList,
  }),
  {
    detailTaskId: "task-completed",
    isTaskSelectionPending: false,
  }
);

assert.deepEqual(
  resolveManualWorkspaceSwitch({
    currentSelectedTaskId: "task-changed",
    targetWorkspaceView: "changes",
    workspaceTaskBuckets,
  }),
  {
    nextSelectedTaskId: "task-changed",
    nextWorkspaceView: "changes",
  }
);
assert.deepEqual(
  resolveManualWorkspaceSwitch({
    currentSelectedTaskId: "task-active",
    targetWorkspaceView: "completed",
    workspaceTaskBuckets,
  }),
  {
    nextSelectedTaskId: "task-completed",
    nextWorkspaceView: "completed",
  }
);
assert.deepEqual(
  resolveManualWorkspaceSwitch({
    currentSelectedTaskId: "task-active",
    targetWorkspaceView: "changes",
    workspaceTaskBuckets,
  }),
  {
    nextSelectedTaskId: "task-changed",
    nextWorkspaceView: "changes",
  }
);

const stableCurrentTimestamp = 10_000;
assert.equal(
  hasRecentManualWorkspaceSwitch(
    stableCurrentTimestamp,
    stableCurrentTimestamp - 400
  ),
  true
);
assert.equal(
  hasRecentManualWorkspaceSwitch(
    stableCurrentTimestamp,
    stableCurrentTimestamp - MANUAL_WORKSPACE_AUTO_SWITCH_GUARD_MS - 1
  ),
  false
);

assert.equal(
  resolveAutoWorkspaceSwitchTargetView({
    changedTaskIdSet,
    currentTimestamp: stableCurrentTimestamp,
    currentWorkspaceView: "active",
    lastManualWorkspaceSwitchAt: stableCurrentTimestamp - 300,
    selectedTaskId: "task-completed",
    taskList: [activeTask, completedTask, changedTask, deletedTask],
    visibleTaskList: workspaceTaskBuckets.activeTaskList,
  }),
  null
);
assert.equal(
  resolveAutoWorkspaceSwitchTargetView({
    changedTaskIdSet,
    currentTimestamp: stableCurrentTimestamp,
    currentWorkspaceView: "active",
    lastManualWorkspaceSwitchAt: null,
    selectedTaskId: "task-completed",
    taskList: [activeTask, completedTask, changedTask, deletedTask],
    visibleTaskList: workspaceTaskBuckets.activeTaskList,
  }),
  "completed"
);
assert.equal(
  resolveAutoWorkspaceSwitchTargetView({
    changedTaskIdSet,
    currentTimestamp: stableCurrentTimestamp,
    currentWorkspaceView: "active",
    lastManualWorkspaceSwitchAt: null,
    selectedTaskId: "task-changed",
    taskList: [activeTask, completedTask, changedTask, deletedTask],
    visibleTaskList: workspaceTaskBuckets.activeTaskList,
  }),
  "changes"
);
assert.equal(
  resolveAutoWorkspaceSwitchTargetView({
    changedTaskIdSet: new Set<string>(),
    currentTimestamp: stableCurrentTimestamp,
    currentWorkspaceView: "completed",
    lastManualWorkspaceSwitchAt: null,
    selectedTaskId: "task-active",
    taskList: [activeTask, completedTask, changedTask, deletedTask],
    visibleTaskList: workspaceTaskBuckets.completedTaskList,
  }),
  null
);
assert.equal(
  resolveAutoWorkspaceSwitchTargetView({
    changedTaskIdSet,
    currentTimestamp: stableCurrentTimestamp,
    currentWorkspaceView: "active",
    lastManualWorkspaceSwitchAt: null,
    selectedTaskId: "task-active",
    taskList: [activeTask, completedTask, changedTask, deletedTask],
    visibleTaskList: workspaceTaskBuckets.activeTaskList,
  }),
  null
);

function InertSubtreeHarness({
  isSubtreeInteractionLocked,
}: {
  isSubtreeInteractionLocked: boolean;
}) {
  const lockedSubtreeElementRef = useInertSubtree<HTMLDivElement>(
    isSubtreeInteractionLocked
  );

  return createElement(
    "div",
    {
      ref: lockedSubtreeElementRef,
      "data-testid": "detail-body",
    },
    createElement(
      "button",
      {
        type: "button",
      },
      "Start Task"
    )
  );
}

const workspaceLockDom = new JSDOM(
  "<!doctype html><html><body><div id=\"root\"></div></body></html>",
  {
    pretendToBeVisual: true,
    url: "http://localhost/",
  }
);
installDomGlobals(workspaceLockDom.window);

const workspaceLockContainer =
  workspaceLockDom.window.document.getElementById("root");
assert.ok(workspaceLockContainer, "Expected DOM test container to exist.");

const workspaceLockRoot = createRoot(workspaceLockContainer);
await act(async () => {
  workspaceLockRoot.render(
    createElement(InertSubtreeHarness, {
      isSubtreeInteractionLocked: false,
    })
  );
});

const staleDetailActionButton =
  workspaceLockDom.window.document.querySelector("button");
assert.ok(staleDetailActionButton, "Expected detail action button to render.");
staleDetailActionButton.focus();
assert.equal(
  workspaceLockDom.window.document.activeElement,
  staleDetailActionButton
);

await act(async () => {
  workspaceLockRoot.render(
    createElement(InertSubtreeHarness, {
      isSubtreeInteractionLocked: true,
    })
  );
});

const lockedDetailBodyElement = workspaceLockDom.window.document.querySelector(
  '[data-testid="detail-body"]'
);
assert.ok(lockedDetailBodyElement, "Expected locked detail body to render.");
assert.equal(lockedDetailBodyElement.hasAttribute("inert"), true);
assert.equal(
  lockedDetailBodyElement.contains(workspaceLockDom.window.document.activeElement),
  false
);

await act(async () => {
  workspaceLockRoot.unmount();
});
workspaceLockDom.window.close();

console.log("workspace_view.test.ts: PASS");
