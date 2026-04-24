import assert from "node:assert/strict";

import { taskApi } from "../src/api/client.ts";

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
} finally {
  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    value: originalFetch,
  });
}

console.log("api_client.test.ts: PASS");
