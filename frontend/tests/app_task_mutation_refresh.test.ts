import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { Simulate } from "react-dom/test-utils";

type TaskSnapshot = {
  id: string;
  run_account_id: string;
  project_id: string | null;
  task_title: string;
  lifecycle_status: string;
  workflow_stage: string;
  last_ai_activity_at: string | null;
  stage_updated_at: string;
  worktree_path: string | null;
  worktree_base_branch_name: string;
  requirement_brief: string | null;
  auto_confirm_prd_and_execute: boolean;
  business_sync_original_workflow_stage: string | null;
  business_sync_original_lifecycle_status: string | null;
  business_sync_restored_at: string | null;
  business_sync_status_note: string | null;
  destroy_reason: string | null;
  destroyed_at: string | null;
  created_at: string;
  closed_at: string | null;
  log_count: number;
  is_codex_task_running: boolean;
  branch_health: {
    expected_branch_name: string;
    branch_exists: boolean | null;
    worktree_exists: boolean;
    manual_completion_candidate: boolean;
    status_message: string | null;
  } | null;
};

type FetchCall = {
  method: string;
  pathname: string;
  search: string;
  bodyText: string | null;
};

type FetchHarness = {
  readonly observedCallList: FetchCall[];
  readonly stalledDashboardRefreshCount: number;
  fetch: typeof fetch;
};

type FetchResponseOverride = (
  fetchCall: FetchCall,
  requestUrl: URL
) => Response | Promise<Response>;

const TEST_TIMESTAMP_TEXT = "2026-04-24T17:54:00+08:00";
const RUN_ACCOUNT_ID_TEXT = "run-account-1";

function buildTaskSnapshot(
  taskIdText: string,
  overrides: Partial<TaskSnapshot> = {}
): TaskSnapshot {
  return {
    id: taskIdText,
    run_account_id: RUN_ACCOUNT_ID_TEXT,
    project_id: null,
    task_title: `Task ${taskIdText}`,
    lifecycle_status: "OPEN",
    workflow_stage: "test_in_progress",
    last_ai_activity_at: null,
    stage_updated_at: TEST_TIMESTAMP_TEXT,
    worktree_path: `/tmp/${taskIdText}`,
    worktree_base_branch_name: "main",
    requirement_brief: `Requirement brief for ${taskIdText}`,
    auto_confirm_prd_and_execute: false,
    business_sync_original_workflow_stage: null,
    business_sync_original_lifecycle_status: null,
    business_sync_restored_at: null,
    business_sync_status_note: null,
    destroy_reason: null,
    destroyed_at: null,
    created_at: TEST_TIMESTAMP_TEXT,
    closed_at: null,
    log_count: 0,
    is_codex_task_running: false,
    branch_health: null,
    ...overrides,
  };
}

function buildJsonResponse(responsePayload: unknown, statusCode = 200): Response {
  return new Response(JSON.stringify(responsePayload), {
    status: statusCode,
    headers: {
      "Content-Type": "application/json",
    },
  });
}

function buildRunAccountResponse(): Record<string, unknown> {
  return {
    id: RUN_ACCOUNT_ID_TEXT,
    account_display_name: "zata @ Darwin",
    user_name: "zata",
    environment_os: "Darwin",
    git_branch_name: "main",
    created_at: TEST_TIMESTAMP_TEXT,
    is_active: true,
  };
}

function buildDevLogResponse(taskSnapshot: TaskSnapshot): Record<string, unknown> {
  return {
    id: `log-${taskSnapshot.id}`,
    task_id: taskSnapshot.id,
    run_account_id: RUN_ACCOUNT_ID_TEXT,
    created_at: TEST_TIMESTAMP_TEXT,
    text_content: `Log for ${taskSnapshot.task_title}`,
    state_tag: "NONE",
    media_original_image_path: null,
    media_thumbnail_path: null,
    task_title: taskSnapshot.task_title,
  };
}

function createFetchHarness(
  initialTaskList: TaskSnapshot[],
  mutationResponseByRequestKey: Record<string, TaskSnapshot>,
  responseOverrideByRequestKey: Record<string, FetchResponseOverride> = {}
): FetchHarness {
  let currentTaskList = initialTaskList;
  let taskListFetchCount = 0;
  let hasObservedMutation = false;
  let stalledDashboardRefreshCount = 0;
  const observedCallList: FetchCall[] = [];

  const fetchHarness: FetchHarness = {
    get observedCallList() {
      return observedCallList;
    },
    get stalledDashboardRefreshCount() {
      return stalledDashboardRefreshCount;
    },
    fetch: async (input: RequestInfo | URL, init?: RequestInit) => {
      const requestUrl = new URL(String(input), "http://localhost");
      const requestMethod = (init?.method ?? "GET").toUpperCase();
      const requestKey = `${requestMethod} ${requestUrl.pathname}`;
      observedCallList.push({
        method: requestMethod,
        pathname: requestUrl.pathname,
        search: requestUrl.search,
        bodyText: typeof init?.body === "string" ? init.body : null,
      });
      const fetchCall = observedCallList[observedCallList.length - 1];

      if (requestMethod === "GET" && requestUrl.pathname === "/api/app-config") {
        return buildJsonResponse({
          app_timezone: "Asia/Shanghai",
          app_timezone_offset: "+08:00",
        });
      }

      if (
        requestMethod === "GET" &&
        requestUrl.pathname === "/api/run-accounts/current"
      ) {
        return buildJsonResponse(buildRunAccountResponse());
      }

      if (requestMethod === "GET" && requestUrl.pathname === "/api/projects") {
        return buildJsonResponse([]);
      }

      if (requestMethod === "GET" && requestUrl.pathname === "/api/tasks") {
        taskListFetchCount += 1;
        if (hasObservedMutation && taskListFetchCount > 1) {
          stalledDashboardRefreshCount += 1;
          return new Promise<Response>(() => {
            // Keep the full dashboard refresh pending so the assertions must
            // observe the immediate local reconciliation path.
          });
        }
        return buildJsonResponse(currentTaskList);
      }

      if (
        requestMethod === "GET" &&
        requestUrl.pathname === "/api/tasks/card-metadata"
      ) {
        return buildJsonResponse([]);
      }

      if (requestMethod === "GET" && requestUrl.pathname === "/api/logs") {
        return buildJsonResponse([]);
      }

      if (requestMethod === "POST" && requestUrl.pathname === "/api/logs") {
        const targetTaskSnapshot = currentTaskList[0] ?? initialTaskList[0];
        return buildJsonResponse(buildDevLogResponse(targetTaskSnapshot), 201);
      }

      if (
        requestMethod === "GET" &&
        requestUrl.pathname.endsWith("/schedules")
      ) {
        return buildJsonResponse([]);
      }

      if (
        requestMethod === "GET" &&
        requestUrl.pathname.endsWith("/schedules/runs")
      ) {
        return buildJsonResponse([]);
      }

      if (
        requestMethod === "GET" &&
        requestUrl.pathname.endsWith("/qa/messages")
      ) {
        return buildJsonResponse([]);
      }

      if (requestMethod === "GET" && requestUrl.pathname.endsWith("/prd-file")) {
        return buildJsonResponse({ content: null, path: null });
      }

      if (
        requestMethod === "GET" &&
        requestUrl.pathname.endsWith("/completion-checklist")
      ) {
        const requestedModeText =
          requestUrl.searchParams.get("mode") ?? "complete";
        return buildJsonResponse({
          task_id: requestUrl.pathname.split("/")[3],
          mode: requestedModeText,
          checklist_signature: `sha256:${requestedModeText}-signature`,
          items: [
            {
              item_id: `${requestedModeText}-timeline-reviewed`,
              label: "Review latest Timeline and result evidence.",
              group: "Completion Safety",
              required: true,
              source: "system_safety",
              covered_source_item_count: null,
            },
            {
              item_id: `${requestedModeText}-worktree-ready`,
              label: "Confirm worktree/code state is ready.",
              group: "Completion Safety",
              required: true,
              source: "system_safety",
              covered_source_item_count: null,
            },
          ],
        });
      }

      if (requestMethod === "DELETE" && requestUrl.pathname.startsWith("/api/tasks/")) {
        hasObservedMutation = true;
        const removedTaskIdText = requestUrl.pathname.split("/")[3];
        currentTaskList = currentTaskList.filter(
          (taskSnapshot) => taskSnapshot.id !== removedTaskIdText
        );
        return new Response(null, { status: 204 });
      }

      const responseOverride = responseOverrideByRequestKey[requestKey];
      if (responseOverride) {
        return responseOverride(fetchCall, requestUrl);
      }

      if (
        requestMethod === "GET" &&
        requestUrl.pathname.startsWith("/api/tasks/") &&
        requestUrl.pathname.endsWith("/preview-sandbox")
      ) {
        const taskIdText = requestUrl.pathname.split("/")[3];
        return buildJsonResponse({
          task_id: taskIdText,
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
        });
      }

      const mutationResponse = mutationResponseByRequestKey[requestKey];
      if (mutationResponse) {
        hasObservedMutation = true;
        currentTaskList = [
          mutationResponse,
          ...currentTaskList.filter(
            (taskSnapshot) => taskSnapshot.id !== mutationResponse.id
          ),
        ];
        return buildJsonResponse(mutationResponse);
      }

      throw new Error(`Unexpected request: ${requestKey}${requestUrl.search}`);
    },
  };

  return fetchHarness;
}

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
  jsdomWindow.confirm = () => true;
  setGlobalProperty("window", jsdomWindow);
  setGlobalProperty("document", jsdomWindow.document);
  setGlobalProperty("navigator", jsdomWindow.navigator);
  setGlobalProperty("HTMLElement", jsdomWindow.HTMLElement);
  setGlobalProperty("HTMLTextAreaElement", jsdomWindow.HTMLTextAreaElement);
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

async function flushMicrotasks(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

async function waitForAssertion(
  assertionCallback: () => void,
  labelText: string
): Promise<void> {
  let latestError: unknown = null;
  for (let attemptIndex = 0; attemptIndex < 80; attemptIndex += 1) {
    try {
      assertionCallback();
      return;
    } catch (assertionError) {
      latestError = assertionError;
    }
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
      await flushMicrotasks();
    });
  }

  throw new Error(`${labelText}: ${String(latestError)}`);
}

function findButtonByText(
  documentRoot: Document,
  buttonText: string
): HTMLButtonElement {
  const matchingButton = getButtonByText(documentRoot, buttonText);
  assert.ok(matchingButton, `Expected button with text "${buttonText}" to exist.`);
  return matchingButton;
}

function getButtonByText(
  documentRoot: Document,
  buttonText: string
): HTMLButtonElement | null {
  return (
    Array.from(documentRoot.querySelectorAll("button")).find(
      (buttonElement) => buttonElement.textContent?.trim() === buttonText
    ) ?? null
  );
}

function findDialogButtonByText(
  documentRoot: Document,
  buttonText: string
): HTMLButtonElement {
  const dialogElement = documentRoot.querySelector("[role='dialog']");
  assert.ok(dialogElement, "Expected dialog to exist.");
  const matchingButton = Array.from(dialogElement.querySelectorAll("button")).find(
    (buttonElement) => buttonElement.textContent?.trim() === buttonText
  );
  assert.ok(
    matchingButton,
    `Expected dialog button with text "${buttonText}" to exist.`
  );
  return matchingButton;
}

function getDialogButtonByText(
  documentRoot: Document,
  buttonText: string
): HTMLButtonElement | null {
  const dialogElement = documentRoot.querySelector("[role='dialog']");
  if (!dialogElement) {
    return null;
  }
  return (
    Array.from(dialogElement.querySelectorAll("button")).find(
      (buttonElement) => buttonElement.textContent?.trim() === buttonText
    ) ?? null
  );
}

async function clickButton(
  jsdomWindow: Window,
  buttonElement: HTMLButtonElement
): Promise<void> {
  await act(async () => {
    buttonElement.dispatchEvent(
      new jsdomWindow.MouseEvent("click", {
        bubbles: true,
        cancelable: true,
      })
    );
    await flushMicrotasks();
  });
}

async function checkAllCheckboxes(jsdomWindow: Window): Promise<void> {
  const checkboxElementList = Array.from(
    jsdomWindow.document.querySelectorAll<HTMLInputElement>(
      "input[type='checkbox']"
    )
  );
  assert.ok(checkboxElementList.length > 0, "Expected checklist checkboxes.");
  for (const checkboxElement of checkboxElementList) {
    await act(async () => {
      checkboxElement.dispatchEvent(
        new jsdomWindow.MouseEvent("click", {
          bubbles: true,
          cancelable: true,
        })
      );
      await flushMicrotasks();
    });
  }
}

async function updateTextareaValue(
  jsdomWindow: Window,
  textareaElement: HTMLTextAreaElement,
  nextValueText: string
): Promise<void> {
  const textareaValueSetter = Object.getOwnPropertyDescriptor(
    jsdomWindow.HTMLTextAreaElement.prototype,
    "value"
  )?.set;
  assert.ok(textareaValueSetter, "Expected textarea value setter to exist.");

  await act(async () => {
    textareaValueSetter.call(textareaElement, nextValueText);
    Simulate.change(textareaElement, {
      target: {
        value: nextValueText,
      },
    } as unknown as Event);
    await flushMicrotasks();
  });
}

async function compileAppBundle(): Promise<string> {
  const temporaryDirectoryPath = mkdtempSync(
    path.join(process.cwd(), ".app-mutation-test-")
  );
  const bundledAppPath = path.join(temporaryDirectoryPath, "App.bundle.mjs");
  await build({
    entryPoints: [path.resolve("src/App.tsx")],
    outfile: bundledAppPath,
    bundle: true,
    format: "esm",
    platform: "node",
    jsx: "automatic",
    external: [
      "react",
      "react-dom",
      "react-dom/client",
      "react/jsx-runtime",
    ],
    logLevel: "silent",
  });

  return pathToFileURL(bundledAppPath).href;
}

async function renderDashboardScenario(
  AppComponent: React.ComponentType,
  initialTaskList: TaskSnapshot[],
  mutationResponseByRequestKey: Record<string, TaskSnapshot>,
  responseOverrideByRequestKey: Record<string, FetchResponseOverride> = {}
): Promise<{
  containerElement: HTMLElement;
  fetchHarness: FetchHarness;
  jsdomWindow: Window;
  root: Root;
}> {
  const jsdomInstance = new JSDOM(
    "<!doctype html><html><body><div id=\"root\"></div></body></html>",
    {
      pretendToBeVisual: true,
      url: "http://localhost/",
    }
  );
  installDomGlobals(jsdomInstance.window);

  const fetchHarness = createFetchHarness(
    initialTaskList,
    mutationResponseByRequestKey,
    responseOverrideByRequestKey
  );
  setGlobalProperty("fetch", fetchHarness.fetch);

  const containerElement = jsdomInstance.window.document.getElementById("root");
  assert.ok(containerElement, "Expected root test container to exist.");

  const root = createRoot(containerElement);
  await act(async () => {
    root.render(createElement(AppComponent));
    await flushMicrotasks();
  });
  await waitForAssertion(() => {
    assert.match(
      containerElement.textContent ?? "",
      new RegExp(initialTaskList[0]?.task_title ?? "Task")
    );
  }, "dashboard initial render");

  return {
    containerElement,
    fetchHarness,
    jsdomWindow: jsdomInstance.window,
    root,
  };
}

async function cleanupDashboardScenario(root: Root): Promise<void> {
  await act(async () => {
    root.unmount();
    await flushMicrotasks();
  });
}

const bundledAppUrl = await compileAppBundle();
const { default: App } = await import(bundledAppUrl);

try {
  const initialCompleteTask = buildTaskSnapshot("task-complete", {
    task_title: "Complete refresh task",
    workflow_stage: "test_in_progress",
    worktree_path: "/tmp/task-complete",
  });
  const completionTaskSnapshot = {
    ...initialCompleteTask,
    workflow_stage: "pr_preparing",
    is_codex_task_running: true,
    stage_updated_at: "2026-04-24T17:55:00+08:00",
  };
  const completeScenario = await renderDashboardScenario(App, [initialCompleteTask], {
    "POST /api/tasks/task-complete/complete": completionTaskSnapshot,
  });
  await clickButton(
    completeScenario.jsdomWindow,
    findButtonByText(completeScenario.jsdomWindow.document, "Complete")
  );
  await waitForAssertion(() => {
    assert.match(
      completeScenario.containerElement.textContent ?? "",
      /Review latest Timeline/
    );
    assert.equal(
      completeScenario.fetchHarness.observedCallList.some(
        (fetchCall) =>
          fetchCall.method === "POST" &&
          fetchCall.pathname === "/api/tasks/task-complete/complete"
      ),
      false
    );
    assert.equal(
      getDialogButtonByText(completeScenario.jsdomWindow.document, "Complete")
        ?.disabled,
      true
    );
  }, "complete checklist opens before mutation");
  await checkAllCheckboxes(completeScenario.jsdomWindow);
  await clickButton(
    completeScenario.jsdomWindow,
    findDialogButtonByText(completeScenario.jsdomWindow.document, "Complete")
  );
  await waitForAssertion(() => {
    assert.match(completeScenario.containerElement.textContent ?? "", /PR Prep/);
    assert.equal(completeScenario.fetchHarness.stalledDashboardRefreshCount, 1);
    const completionFetchCall = completeScenario.fetchHarness.observedCallList.find(
      (fetchCall) =>
        fetchCall.method === "POST" &&
        fetchCall.pathname === "/api/tasks/task-complete/complete"
    );
    assert.ok(completionFetchCall);
    assert.deepEqual(JSON.parse(completionFetchCall.bodyText ?? "{}"), {
      checklist_mode: "complete",
      checklist_signature: "sha256:complete-signature",
      confirmed_checklist_item_ids: [
        "complete-timeline-reviewed",
        "complete-worktree-ready",
      ],
    });
  }, "complete handler local refresh");
  await cleanupDashboardScenario(completeScenario.root);

  const initialAcceptanceTask = buildTaskSnapshot("task-accept", {
    task_title: "Acceptance checklist task",
    workflow_stage: "acceptance_in_progress",
    worktree_path: "/tmp/task-accept",
  });
  const acceptedCompletionTaskSnapshot = {
    ...initialAcceptanceTask,
    workflow_stage: "pr_preparing",
    is_codex_task_running: true,
    stage_updated_at: "2026-04-24T17:55:00+08:00",
  };
  const acceptanceScenario = await renderDashboardScenario(
    App,
    [initialAcceptanceTask],
    {
      "POST /api/tasks/task-accept/complete": acceptedCompletionTaskSnapshot,
    }
  );
  await clickButton(
    acceptanceScenario.jsdomWindow,
    findButtonByText(acceptanceScenario.jsdomWindow.document, "验收通过")
  );
  await waitForAssertion(() => {
    assert.match(
      acceptanceScenario.containerElement.textContent ?? "",
      /Review latest Timeline/
    );
    assert.equal(
      acceptanceScenario.fetchHarness.observedCallList.some(
        (fetchCall) =>
          fetchCall.method === "PUT" &&
          fetchCall.pathname === "/api/tasks/task-accept/stage"
      ),
      false
    );
    assert.equal(
      getDialogButtonByText(acceptanceScenario.jsdomWindow.document, "Complete")
        ?.disabled,
      true
    );
  }, "acceptance checklist opens before mutation");
  await checkAllCheckboxes(acceptanceScenario.jsdomWindow);
  await clickButton(
    acceptanceScenario.jsdomWindow,
    findDialogButtonByText(acceptanceScenario.jsdomWindow.document, "Complete")
  );
  await waitForAssertion(() => {
    assert.match(acceptanceScenario.containerElement.textContent ?? "", /PR Prep/);
    const acceptanceCompletionFetchCall =
      acceptanceScenario.fetchHarness.observedCallList.find(
        (fetchCall) =>
          fetchCall.method === "POST" &&
          fetchCall.pathname === "/api/tasks/task-accept/complete"
      );
    assert.ok(acceptanceCompletionFetchCall);
    assert.deepEqual(
      JSON.parse(acceptanceCompletionFetchCall.bodyText ?? "{}"),
      {
        checklist_mode: "complete",
        checklist_signature: "sha256:complete-signature",
        confirmed_checklist_item_ids: [
          "complete-timeline-reviewed",
          "complete-worktree-ready",
        ],
      }
    );
  }, "acceptance checklist payload");
  await cleanupDashboardScenario(acceptanceScenario.root);

  const noWorktreeAcceptanceTask = buildTaskSnapshot(
    "task-accept-no-worktree",
    {
      task_title: "No worktree acceptance task",
      workflow_stage: "acceptance_in_progress",
      worktree_path: null,
    }
  );
  const noWorktreeAcceptanceScenario = await renderDashboardScenario(
    App,
    [noWorktreeAcceptanceTask],
    {}
  );
  await waitForAssertion(() => {
    assert.equal(
      getButtonByText(
        noWorktreeAcceptanceScenario.jsdomWindow.document,
        "验收通过"
      ),
      null
    );
    assert.equal(
      getButtonByText(
        noWorktreeAcceptanceScenario.jsdomWindow.document,
        "Complete"
      ),
      null
    );
    assert.ok(
      getButtonByText(
        noWorktreeAcceptanceScenario.jsdomWindow.document,
        "请求修改"
      )
    );
    assert.equal(
      noWorktreeAcceptanceScenario.fetchHarness.observedCallList.some(
        (fetchCall) => fetchCall.pathname.endsWith("/completion-checklist")
      ),
      false
    );
  }, "no-worktree acceptance hides completion actions");
  await cleanupDashboardScenario(noWorktreeAcceptanceScenario.root);

  const initialStaleChecklistTask = buildTaskSnapshot("task-stale-checklist", {
    task_title: "Stale checklist refresh task",
    workflow_stage: "test_in_progress",
    worktree_path: "/tmp/task-stale-checklist",
  });
  const staleChecklistScenario = await renderDashboardScenario(
    App,
    [initialStaleChecklistTask],
    {},
    {
      "POST /api/tasks/task-stale-checklist/complete": () =>
        buildJsonResponse(
          {
            detail: {
              message:
                "Completion checklist is stale. Refresh the checklist and confirm it again.",
              refresh_required: true,
            },
          },
          409
        ),
    }
  );
  await clickButton(
    staleChecklistScenario.jsdomWindow,
    findButtonByText(staleChecklistScenario.jsdomWindow.document, "Complete")
  );
  await waitForAssertion(() => {
    assert.match(
      staleChecklistScenario.containerElement.textContent ?? "",
      /Review latest Timeline/
    );
  }, "stale checklist initial modal");
  await checkAllCheckboxes(staleChecklistScenario.jsdomWindow);
  await clickButton(
    staleChecklistScenario.jsdomWindow,
    findDialogButtonByText(
      staleChecklistScenario.jsdomWindow.document,
      "Complete"
    )
  );
  await waitForAssertion(() => {
    assert.match(
      staleChecklistScenario.containerElement.textContent ?? "",
      /检查单已更新/
    );
    assert.equal(
      getDialogButtonByText(
        staleChecklistScenario.jsdomWindow.document,
        "Complete"
      )?.disabled,
      true
    );
    assert.equal(
      staleChecklistScenario.fetchHarness.observedCallList.filter(
        (fetchCall) =>
          fetchCall.method === "GET" &&
          fetchCall.pathname ===
            "/api/tasks/task-stale-checklist/completion-checklist"
      ).length,
      2
    );
    assert.equal(
      staleChecklistScenario.fetchHarness.observedCallList.filter(
        (fetchCall) =>
          fetchCall.method === "POST" &&
          fetchCall.pathname === "/api/tasks/task-stale-checklist/complete"
      ).length,
      1
    );
  }, "stale checklist refreshes modal");
  await cleanupDashboardScenario(staleChecklistScenario.root);

  const initialPreviewTask = buildTaskSnapshot("task-preview-running", {
    task_title: "Preview running task",
    workflow_stage: "test_in_progress",
    worktree_path: "/tmp/task-preview-running",
  });
  const previewScenario = await renderDashboardScenario(
    App,
    [initialPreviewTask],
    {},
    {
      "GET /api/tasks/task-preview-running/preview-sandbox": () =>
        buildJsonResponse({
          task_id: "task-preview-running",
          status: "running",
          applicability: "applicable",
          preview_url: "http://127.0.0.1:35173/",
          profile_summary: "Applicability: `applicable`",
          failure_kind: null,
          failure_summary: null,
          bypass_confirmed: false,
          log_tail: "runtime-started",
          container_id: "container-123",
          host_port: 35173,
          internal_port: 5173,
          started_at: null,
        }),
    }
  );
  await waitForAssertion(() => {
    assert.match(
      previewScenario.containerElement.textContent ?? "",
      /Preview Sandbox/
    );
    assert.match(
      previewScenario.containerElement.textContent ?? "",
      /Open Preview/
    );
    assert.equal(
      getButtonByText(previewScenario.jsdomWindow.document, "Start Preview")
        ?.disabled,
      true
    );
    assert.equal(
      getButtonByText(previewScenario.jsdomWindow.document, "Restart")?.disabled,
      false
    );
    assert.equal(
      getButtonByText(previewScenario.jsdomWindow.document, "Stop")?.disabled,
      false
    );
  }, "preview running panel actions");
  await cleanupDashboardScenario(previewScenario.root);

  const initialUncertainPreviewTask = buildTaskSnapshot("task-preview-uncertain", {
    task_title: "Preview uncertain task",
    workflow_stage: "test_in_progress",
    worktree_path: "/tmp/task-preview-uncertain",
  });
  const uncertainPreviewScenario = await renderDashboardScenario(
    App,
    [initialUncertainPreviewTask],
    {},
    {
      "GET /api/tasks/task-preview-uncertain/preview-sandbox": () =>
        buildJsonResponse({
          task_id: "task-preview-uncertain",
          status: "uncertain",
          applicability: "uncertain",
          preview_url: null,
          profile_summary: "Applicability: `uncertain`",
          failure_kind: null,
          failure_summary: null,
          bypass_confirmed: false,
          log_tail: null,
          container_id: null,
          host_port: null,
          internal_port: null,
          started_at: null,
        }),
    }
  );
  await waitForAssertion(() => {
    assert.equal(
      getButtonByText(
        uncertainPreviewScenario.jsdomWindow.document,
        "Start Preview"
      )?.disabled,
      false
    );
  }, "preview uncertain panel enables start");
  await cleanupDashboardScenario(uncertainPreviewScenario.root);

  const initialManualCompleteTask = buildTaskSnapshot("task-manual-complete", {
    task_title: "Manual Complete refresh task",
    workflow_stage: "implementation_in_progress",
    worktree_path: "/tmp/task-manual-complete",
    branch_health: {
      expected_branch_name: "task/manual-complete",
      branch_exists: false,
      worktree_exists: false,
      manual_completion_candidate: true,
      status_message: "Branch missing.",
    },
  });
  const manuallyCompletedTaskSnapshot = {
    ...initialManualCompleteTask,
    workflow_stage: "done",
    lifecycle_status: "CLOSED",
    closed_at: "2026-04-24T17:55:00+08:00",
  };
  const manualCompleteScenario = await renderDashboardScenario(
    App,
    [initialManualCompleteTask],
    {
      "POST /api/tasks/task-manual-complete/manual-complete":
        manuallyCompletedTaskSnapshot,
    }
  );
  await clickButton(
    manualCompleteScenario.jsdomWindow,
    findButtonByText(manualCompleteScenario.jsdomWindow.document, "确认 Complete")
  );
  await waitForAssertion(() => {
    assert.equal(
      getDialogButtonByText(
        manualCompleteScenario.jsdomWindow.document,
        "Confirm Complete"
      )?.disabled,
      true
    );
  }, "manual complete checklist submit disabled");
  await checkAllCheckboxes(manualCompleteScenario.jsdomWindow);
  await clickButton(
    manualCompleteScenario.jsdomWindow,
    findDialogButtonByText(
      manualCompleteScenario.jsdomWindow.document,
      "Confirm Complete"
    )
  );
  await waitForAssertion(() => {
    assert.match(
      manualCompleteScenario.containerElement.textContent ?? "",
      /Completed/
    );
    const manualCompletionFetchCall =
      manualCompleteScenario.fetchHarness.observedCallList.find(
        (fetchCall) =>
          fetchCall.method === "POST" &&
          fetchCall.pathname ===
            "/api/tasks/task-manual-complete/manual-complete"
      );
    assert.ok(manualCompletionFetchCall);
    assert.deepEqual(JSON.parse(manualCompletionFetchCall.bodyText ?? "{}"), {
      checklist_mode: "manual_complete",
      checklist_signature: "sha256:manual_complete-signature",
      confirmed_checklist_item_ids: [
        "manual_complete-timeline-reviewed",
        "manual_complete-worktree-ready",
      ],
    });
  }, "manual complete checklist payload");
  await cleanupDashboardScenario(manualCompleteScenario.root);

  const initialRequestChangesTask = buildTaskSnapshot("task-request-changes", {
    task_title: "Request changes refresh task",
    workflow_stage: "acceptance_in_progress",
  });
  const changesRequestedTaskSnapshot = {
    ...initialRequestChangesTask,
    workflow_stage: "changes_requested",
    stage_updated_at: "2026-04-24T17:55:00+08:00",
  };
  const requestChangesScenario = await renderDashboardScenario(
    App,
    [initialRequestChangesTask],
    {
      "PUT /api/tasks/task-request-changes/stage": changesRequestedTaskSnapshot,
    }
  );
  await clickButton(
    requestChangesScenario.jsdomWindow,
    findButtonByText(requestChangesScenario.jsdomWindow.document, "请求修改")
  );
  await waitForAssertion(() => {
    assert.match(
      requestChangesScenario.containerElement.textContent ?? "",
      /Changes Requested/
    );
    assert.equal(
      requestChangesScenario.fetchHarness.stalledDashboardRefreshCount,
      1
    );
  }, "request-changes handler local refresh");
  await cleanupDashboardScenario(requestChangesScenario.root);

  const initialEditRequirementTask = buildTaskSnapshot("task-edit-requirement", {
    task_title: "Edit requirement without PRD regeneration",
    workflow_stage: "implementation_in_progress",
    worktree_path: "/tmp/task-edit-requirement",
    requirement_brief: "Original implementation-stage requirement.",
  });
  const updatedEditRequirementTask = {
    ...initialEditRequirementTask,
    requirement_brief: "Refined implementation-stage requirement.",
  };
  const editRequirementScenario = await renderDashboardScenario(
    App,
    [initialEditRequirementTask],
    {
      "PATCH /api/tasks/task-edit-requirement": updatedEditRequirementTask,
    }
  );
  await clickButton(
    editRequirementScenario.jsdomWindow,
    findButtonByText(
      editRequirementScenario.jsdomWindow.document,
      "Edit Requirement"
    )
  );
  const editRequirementTextarea =
    editRequirementScenario.jsdomWindow.document.querySelector<HTMLTextAreaElement>(
      "textarea[placeholder='Updated requirement summary']"
    );
  assert.ok(
    editRequirementTextarea,
    "Expected requirement revision textarea to exist."
  );
  await updateTextareaValue(
    editRequirementScenario.jsdomWindow,
    editRequirementTextarea,
    "Refined implementation-stage requirement."
  );
  await clickButton(
    editRequirementScenario.jsdomWindow,
    findButtonByText(editRequirementScenario.jsdomWindow.document, "Append Change")
  );
  await waitForAssertion(() => {
    assert.match(
      editRequirementScenario.containerElement.textContent ?? "",
      /Refined implementation-stage requirement\./
    );
    const requirementPatchCall =
      editRequirementScenario.fetchHarness.observedCallList.find(
        (fetchCall) =>
          fetchCall.method === "PATCH" &&
          fetchCall.pathname === "/api/tasks/task-edit-requirement"
      );
    assert.ok(requirementPatchCall);
    assert.equal(
      JSON.parse(requirementPatchCall.bodyText ?? "{}").requirement_brief,
      "Refined implementation-stage requirement."
    );
    assert.equal(
      editRequirementScenario.fetchHarness.observedCallList.some(
        (fetchCall) =>
          fetchCall.method === "POST" &&
          fetchCall.pathname ===
            "/api/tasks/task-edit-requirement/regenerate-prd"
      ),
      false
    );
  }, "implementation-stage requirement edit does not regenerate PRD");
  await cleanupDashboardScenario(editRequirementScenario.root);

  const initialDestroyTask = buildTaskSnapshot("task-destroy", {
    task_title: "Destroy refresh task",
    workflow_stage: "test_in_progress",
    worktree_path: "/tmp/task-destroy",
  });
  const destroyedTaskSnapshot = {
    ...initialDestroyTask,
    lifecycle_status: "DELETED",
    workflow_stage: "done",
    destroy_reason: "Wrong repository binding confirmed.",
    destroyed_at: "2026-04-24T17:56:00+08:00",
  };
  const destroyScenario = await renderDashboardScenario(App, [initialDestroyTask], {
    "POST /api/tasks/task-destroy/destroy": destroyedTaskSnapshot,
  });
  await clickButton(
    destroyScenario.jsdomWindow,
    findButtonByText(destroyScenario.jsdomWindow.document, "Destroy")
  );
  const destroyReasonTextarea =
    destroyScenario.jsdomWindow.document.querySelector<HTMLTextAreaElement>(
      "#destroy-reason"
    );
  assert.ok(destroyReasonTextarea, "Expected destroy reason textarea to exist.");
  await updateTextareaValue(
    destroyScenario.jsdomWindow,
    destroyReasonTextarea,
    "Wrong repository binding confirmed."
  );
  await clickButton(
    destroyScenario.jsdomWindow,
    findButtonByText(destroyScenario.jsdomWindow.document, "确认销毁")
  );
  await waitForAssertion(() => {
    assert.match(
      destroyScenario.containerElement.textContent ?? "",
      /Wrong repository binding confirmed\./
    );
    assert.equal(destroyScenario.fetchHarness.stalledDashboardRefreshCount, 1);
  }, "destroy handler local refresh");
  await cleanupDashboardScenario(destroyScenario.root);

  const initialDeleteTask = buildTaskSnapshot("task-delete", {
    task_title: "Delete refresh task",
    workflow_stage: "backlog",
    worktree_path: null,
  });
  const deleteScenario = await renderDashboardScenario(App, [initialDeleteTask], {});
  await clickButton(
    deleteScenario.jsdomWindow,
    findButtonByText(deleteScenario.jsdomWindow.document, "Delete")
  );
  await waitForAssertion(() => {
    assert.doesNotMatch(
      deleteScenario.containerElement.textContent ?? "",
      /Delete refresh task/
    );
    assert.equal(deleteScenario.fetchHarness.stalledDashboardRefreshCount, 1);
  }, "hard-delete handler local refresh");
  await cleanupDashboardScenario(deleteScenario.root);
} finally {
  const bundledAppPath = new URL(bundledAppUrl).pathname;
  rmSync(path.dirname(bundledAppPath), {
    force: true,
    recursive: true,
  });
}

console.log("app_task_mutation_refresh.test.ts: PASS");
