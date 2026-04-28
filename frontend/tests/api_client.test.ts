import assert from "node:assert/strict";

import { ApiClientError, taskApi } from "../src/api/client.ts";

const originalFetch = globalThis.fetch;

try {
  const observedRequestList: Array<{
    input: RequestInfo | URL;
    init?: RequestInit;
  }> = [];

  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    value: async (input: RequestInfo | URL, init?: RequestInit) => {
      observedRequestList.push({ input, init });
      return new Response(null, { status: 204 });
    },
  });

  await taskApi.deleteUnstarted("task-1");

  assert.equal(observedRequestList.length, 1);
  assert.equal(String(observedRequestList[0].input), "/api/tasks/task-1");
  assert.equal(observedRequestList[0].init?.method, "DELETE");

  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    value: async () =>
      new Response(
        JSON.stringify({
          detail: "Started tasks must use the destroy flow.",
        }),
        { status: 422 },
      ),
  });

  await assert.rejects(
    () => taskApi.deleteUnstarted("task-started"),
    /Started tasks must use the destroy flow\./,
  );

  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    value: async () =>
      new Response(
        JSON.stringify({
          detail: {
            message:
              "Completion checklist is stale. Refresh the checklist and confirm it again.",
            refresh_required: true,
            missing_checklist_item_ids: ["system-complete-worktree-ready"],
          },
        }),
        { status: 409 },
      ),
  });

  await assert.rejects(
    () =>
      taskApi.complete("task-stale", {
        checklist_mode: "complete",
        checklist_signature: "sha256:stale",
        confirmed_checklist_item_ids: ["system-complete-timeline-reviewed"],
      }),
    (apiError: unknown) => {
      assert.ok(apiError instanceof ApiClientError);
      assert.equal(apiError.statusCode, 409);
      assert.equal(apiError.refreshRequired, true);
      assert.deepEqual(apiError.missingChecklistItemIds, [
        "system-complete-worktree-ready",
      ]);
      assert.match(apiError.message, /Completion checklist is stale/);
      return true;
    },
  );
} finally {
  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    value: originalFetch,
  });
}

console.log("api_client.test.ts: PASS");
