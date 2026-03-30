import assert from "node:assert/strict";

import { createElement } from "react";
import TestRenderer, { act } from "react-test-renderer";

import {
  useSelectedTaskPrdFile,
  type SelectedTaskPrdFileSnapshot,
  type UseSelectedTaskPrdFileParams,
  type UseSelectedTaskPrdFileResult,
} from "../src/hooks/useSelectedTaskPrdFile.ts";

interface DeferredPromise<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (error: unknown) => void;
}

function createDeferredPromise<T>(): DeferredPromise<T> {
  let resolvePromise!: (value: T) => void;
  let rejectPromise!: (error: unknown) => void;
  const deferredPromise = new Promise<T>((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });

  return {
    promise: deferredPromise,
    resolve: resolvePromise,
    reject: rejectPromise,
  };
}

async function flushMicrotasks(): Promise<void> {
  await Promise.resolve();
}

let latestSelectedTaskPrdFileResult: UseSelectedTaskPrdFileResult | null = null;

function HookHarness(props: UseSelectedTaskPrdFileParams): null {
  latestSelectedTaskPrdFileResult = useSelectedTaskPrdFile(props);
  return null;
}

const firstPrdFileDeferredPromise =
  createDeferredPromise<SelectedTaskPrdFileSnapshot>();
const secondPrdFileDeferredPromise =
  createDeferredPromise<SelectedTaskPrdFileSnapshot>();
const queuedPrdFileDeferredPromiseList = [
  firstPrdFileDeferredPromise,
  secondPrdFileDeferredPromise,
];
const prdFileFetchTaskIdList: string[] = [];

const getPrdFile: UseSelectedTaskPrdFileParams["getPrdFile"] = async (
  taskId
) => {
  prdFileFetchTaskIdList.push(taskId);
  const nextDeferredPromise = queuedPrdFileDeferredPromiseList.shift();
  assert.ok(nextDeferredPromise, "Unexpected getPrdFile call.");
  return nextDeferredPromise.promise;
};

const stableTaskIdText = "task-1";
const stableWorktreePathText = "/tmp/task-1";

let hookRenderer: TestRenderer.ReactTestRenderer | null = null;

await act(async () => {
  hookRenderer = TestRenderer.create(
    createElement(HookHarness, {
      detailTaskId: stableTaskIdText,
      selectedTaskStage: "prd_waiting_confirmation",
      selectedTaskStageUpdatedAt: "2026-03-30T08:00:00+08:00",
      selectedTaskWorktreePath: stableWorktreePathText,
      getPrdFile,
      pollIntervalMs: 60_000,
    })
  );
  await flushMicrotasks();
});

assert.deepEqual(prdFileFetchTaskIdList, [stableTaskIdText]);
assert.equal(
  latestSelectedTaskPrdFileResult?.currentWaitingConfirmationLoadCycleKey,
  "task-1:2026-03-30T08:00:00+08:00"
);
assert.equal(
  latestSelectedTaskPrdFileResult?.isCurrentWaitingConfirmationPrdFileInitialLoadPending,
  true
);
assert.equal(
  latestSelectedTaskPrdFileResult?.hasLoadedCurrentWaitingConfirmationPrdFile,
  false
);

await act(async () => {
  firstPrdFileDeferredPromise.resolve({
    content: "# PRD v1",
    path: "/tmp/task-1/tasks/prd-task-1-v1.md",
  });
  await firstPrdFileDeferredPromise.promise;
  await flushMicrotasks();
});

assert.equal(
  latestSelectedTaskPrdFileResult?.hasLoadedCurrentWaitingConfirmationPrdFile,
  true
);
assert.equal(
  latestSelectedTaskPrdFileResult?.isCurrentWaitingConfirmationPrdFileInitialLoadPending,
  false
);
assert.equal(
  latestSelectedTaskPrdFileResult?.path,
  "/tmp/task-1/tasks/prd-task-1-v1.md"
);

await act(async () => {
  hookRenderer?.update(
    createElement(HookHarness, {
      detailTaskId: stableTaskIdText,
      selectedTaskStage: "prd_generating",
      selectedTaskStageUpdatedAt: "2026-03-30T08:01:00+08:00",
      selectedTaskWorktreePath: stableWorktreePathText,
      getPrdFile,
      pollIntervalMs: 60_000,
    })
  );
  await flushMicrotasks();
});

assert.equal(
  latestSelectedTaskPrdFileResult?.currentWaitingConfirmationLoadCycleKey,
  null
);
assert.equal(
  latestSelectedTaskPrdFileResult?.hasLoadedCurrentWaitingConfirmationPrdFile,
  false
);

await act(async () => {
  hookRenderer?.update(
    createElement(HookHarness, {
      detailTaskId: stableTaskIdText,
      selectedTaskStage: "prd_waiting_confirmation",
      selectedTaskStageUpdatedAt: "2026-03-30T08:02:00+08:00",
      selectedTaskWorktreePath: stableWorktreePathText,
      getPrdFile,
      pollIntervalMs: 60_000,
    })
  );
  await flushMicrotasks();
});

assert.deepEqual(prdFileFetchTaskIdList, [stableTaskIdText, stableTaskIdText]);
assert.equal(
  latestSelectedTaskPrdFileResult?.currentWaitingConfirmationLoadCycleKey,
  "task-1:2026-03-30T08:02:00+08:00"
);
assert.equal(
  latestSelectedTaskPrdFileResult?.hasLoadedCurrentWaitingConfirmationPrdFile,
  false
);
assert.equal(
  latestSelectedTaskPrdFileResult?.isCurrentWaitingConfirmationPrdFileInitialLoadPending,
  true
);

await act(async () => {
  secondPrdFileDeferredPromise.resolve({
    content: "# PRD v2",
    path: "/tmp/task-1/tasks/prd-task-1-v2.md",
  });
  await secondPrdFileDeferredPromise.promise;
  await flushMicrotasks();
});

assert.equal(
  latestSelectedTaskPrdFileResult?.hasLoadedCurrentWaitingConfirmationPrdFile,
  true
);
assert.equal(
  latestSelectedTaskPrdFileResult?.isCurrentWaitingConfirmationPrdFileInitialLoadPending,
  false
);
assert.equal(
  latestSelectedTaskPrdFileResult?.path,
  "/tmp/task-1/tasks/prd-task-1-v2.md"
);

await act(async () => {
  hookRenderer?.unmount();
  await flushMicrotasks();
});

console.log("use_selected_task_prd_file.test.ts: PASS");
