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
  task_branch_name: string | null;
  remote_requirement_manifest_path: string | null;
  remote_requirement_synced_commit_hash: string | null;
  remote_requirement_sync_status: string | null;
  remote_requirement_last_error: string | null;
  remote_requirement_last_synced_at: string | null;
  github_pr_url: string | null;
  github_pr_number: number | null;
  github_pr_state: string | null;
  last_progress_pushed_at: string | null;
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
};

const TEST_TIMESTAMP_TEXT = "2026-04-28T20:10:00+08:00";
const RUN_ACCOUNT_ID_TEXT = "run-account-collapse-test";

function buildTaskSnapshot(
  taskIdText: string,
  taskTitleText: string
): TaskSnapshot {
  return {
    id: taskIdText,
    run_account_id: RUN_ACCOUNT_ID_TEXT,
    project_id: null,
    task_title: taskTitleText,
    lifecycle_status: "OPEN",
    workflow_stage: "test_in_progress",
    last_ai_activity_at: null,
    stage_updated_at: TEST_TIMESTAMP_TEXT,
    worktree_path: `/tmp/${taskIdText}`,
    worktree_base_branch_name: "main",
    task_branch_name: null,
    remote_requirement_manifest_path: null,
    remote_requirement_synced_commit_hash: null,
    remote_requirement_sync_status: null,
    remote_requirement_last_error: null,
    remote_requirement_last_synced_at: null,
    github_pr_url: null,
    github_pr_number: null,
    github_pr_state: null,
    last_progress_pushed_at: null,
    requirement_brief: `Requirement brief for ${taskTitleText}`,
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

function createFetchHarness(initialTaskList: TaskSnapshot[]): {
  readonly observedCallList: FetchCall[];
  fetch: typeof fetch;
} {
  const observedCallList: FetchCall[] = [];

  return {
    get observedCallList() {
      return observedCallList;
    },
    fetch: async (input: RequestInfo | URL, init?: RequestInit) => {
      const requestUrl = new URL(String(input), "http://localhost");
      const requestMethod = (init?.method ?? "GET").toUpperCase();
      observedCallList.push({
        method: requestMethod,
        pathname: requestUrl.pathname,
        search: requestUrl.search,
      });

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
        return buildJsonResponse({
          id: RUN_ACCOUNT_ID_TEXT,
          account_display_name: "Collapse Test",
          user_name: "collapse-test",
          environment_os: "Darwin",
          git_branch_name: "main",
          created_at: TEST_TIMESTAMP_TEXT,
          is_active: true,
        });
      }

      if (requestMethod === "GET" && requestUrl.pathname === "/api/projects") {
        return buildJsonResponse([]);
      }

      if (requestMethod === "GET" && requestUrl.pathname === "/api/tasks") {
        return buildJsonResponse(initialTaskList);
      }

      if (
        requestMethod === "GET" &&
        requestUrl.pathname === "/api/tasks/card-metadata"
      ) {
        return buildJsonResponse([]);
      }

      if (requestMethod === "GET" && requestUrl.pathname === "/api/logs") {
        return buildJsonResponse(initialTaskList.map(buildDevLogResponse));
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

      throw new Error(`Unexpected request: ${requestMethod} ${requestUrl.pathname}`);
    },
  };
}

function setGlobalProperty(propertyName: string, propertyValue: unknown): void {
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
  setGlobalProperty("HTMLInputElement", jsdomWindow.HTMLInputElement);
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

function findButtonByAriaLabel(
  documentRoot: Document,
  ariaLabelText: string
): HTMLButtonElement {
  const matchingButton = documentRoot.querySelector<HTMLButtonElement>(
    `button[aria-label="${ariaLabelText}"]`
  );
  assert.ok(matchingButton, `Expected button "${ariaLabelText}" to exist.`);
  return matchingButton;
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

async function updateInputValue(
  jsdomWindow: Window,
  inputElement: HTMLInputElement,
  nextValueText: string
): Promise<void> {
  const inputValueSetter = Object.getOwnPropertyDescriptor(
    jsdomWindow.HTMLInputElement.prototype,
    "value"
  )?.set;
  assert.ok(inputValueSetter, "Expected input value setter to exist.");

  await act(async () => {
    inputValueSetter.call(inputElement, nextValueText);
    Simulate.change(inputElement, {
      target: {
        value: nextValueText,
      },
    } as unknown as Event);
    await flushMicrotasks();
  });
}

async function compileAppBundle(): Promise<{
  bundledAppUrl: string;
  temporaryDirectoryPath: string;
}> {
  const temporaryDirectoryPath = mkdtempSync(
    path.join(process.cwd(), ".requirement-zone-collapse-test-")
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

  return {
    bundledAppUrl: pathToFileURL(bundledAppPath).href,
    temporaryDirectoryPath,
  };
}

async function renderDashboardScenario(
  AppComponent: React.ComponentType,
  initialTaskList: TaskSnapshot[]
): Promise<{
  containerElement: HTMLElement;
  fetchHarness: ReturnType<typeof createFetchHarness>;
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

  const fetchHarness = createFetchHarness(initialTaskList);
  setGlobalProperty("fetch", fetchHarness.fetch);

  const containerElement = jsdomInstance.window.document.getElementById("root");
  assert.ok(containerElement, "Expected root test container to exist.");

  const root = createRoot(containerElement);
  await act(async () => {
    root.render(createElement(AppComponent));
    await flushMicrotasks();
  });
  await waitForAssertion(() => {
    assert.match(containerElement.textContent ?? "", /Alpha collapse task/);
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

const { bundledAppUrl, temporaryDirectoryPath } = await compileAppBundle();
const { default: App } = await import(bundledAppUrl);

const initialTaskList = [
  buildTaskSnapshot("task-alpha", "Alpha collapse task"),
  buildTaskSnapshot("task-beta", "Beta collapse task"),
];
const dashboardScenario = await renderDashboardScenario(App, initialTaskList);

try {
  const documentRoot = dashboardScenario.jsdomWindow.document;
  const layoutElement = documentRoot.querySelector(".devflow-layout");
  const requirementsColumnElement = documentRoot.querySelector(
    ".devflow-column--requirements"
  );
  const requirementZoneBodyElement = documentRoot.querySelector<HTMLElement>(
    ".devflow-requirements-zone__body"
  );
  assert.ok(layoutElement, "Expected dashboard layout element.");
  assert.ok(requirementsColumnElement, "Expected requirements column element.");
  assert.ok(requirementZoneBodyElement, "Expected requirement zone body element.");
  assert.equal(requirementZoneBodyElement.hidden, false);

  await clickButton(
    dashboardScenario.jsdomWindow,
    findButtonByAriaLabel(documentRoot, "Create requirement")
  );
  await waitForAssertion(() => {
    const matchingInput = documentRoot.querySelector<HTMLInputElement>(
      'input[placeholder="Requirement Title"]'
    );
    assert.ok(matchingInput, "Expected create requirement title input.");
  }, "create panel opened");
  const draftTitleInput = documentRoot.querySelector<HTMLInputElement>(
    'input[placeholder="Requirement Title"]'
  );
  assert.ok(draftTitleInput, "Expected create requirement title input.");
  await updateInputValue(
    dashboardScenario.jsdomWindow,
    draftTitleInput,
    "Draft title survives collapse"
  );

  const initialFetchCallCount = dashboardScenario.fetchHarness.observedCallList.length;
  const collapseButton = findButtonByAriaLabel(
    documentRoot,
    "Collapse requirements list"
  );
  assert.equal(collapseButton.getAttribute("aria-expanded"), "true");

  await clickButton(dashboardScenario.jsdomWindow, collapseButton);

  await waitForAssertion(() => {
    assert.equal(
      layoutElement.classList.contains("devflow-layout--requirements-collapsed"),
      true
    );
    assert.equal(
      requirementsColumnElement.classList.contains(
        "devflow-column--requirements-collapsed"
      ),
      true
    );
    assert.equal(requirementZoneBodyElement.hidden, true);
    assert.match(dashboardScenario.containerElement.textContent ?? "", /Requirements/);
    assert.match(dashboardScenario.containerElement.textContent ?? "", /2/);
    assert.match(dashboardScenario.containerElement.textContent ?? "", /Alpha collapse task/);
    assert.equal(
      findButtonByAriaLabel(documentRoot, "Expand requirements list").getAttribute(
        "aria-expanded"
      ),
      "false"
    );
    assert.equal(
      dashboardScenario.fetchHarness.observedCallList.length,
      initialFetchCallCount
    );
  }, "requirements zone collapsed state");

  await clickButton(
    dashboardScenario.jsdomWindow,
    findButtonByAriaLabel(documentRoot, "Expand requirements list")
  );

  await waitForAssertion(() => {
    assert.equal(
      layoutElement.classList.contains("devflow-layout--requirements-collapsed"),
      false
    );
    assert.equal(
      requirementsColumnElement.classList.contains(
        "devflow-column--requirements-collapsed"
      ),
      false
    );
    assert.equal(requirementZoneBodyElement.hidden, false);
    assert.equal(draftTitleInput.value, "Draft title survives collapse");
    assert.equal(
      findButtonByAriaLabel(documentRoot, "Collapse requirements list").getAttribute(
        "aria-expanded"
      ),
      "true"
    );
    assert.equal(
      dashboardScenario.fetchHarness.observedCallList.length,
      initialFetchCallCount
    );
  }, "requirements zone restored state");

  await clickButton(
    dashboardScenario.jsdomWindow,
    findButtonByAriaLabel(documentRoot, "Collapse requirements list")
  );
  await waitForAssertion(() => {
    assert.equal(requirementZoneBodyElement.hidden, true);
  }, "requirements zone collapsed before create rail restore");
  await clickButton(
    dashboardScenario.jsdomWindow,
    findButtonByAriaLabel(documentRoot, "Create requirement")
  );
  await waitForAssertion(() => {
    assert.equal(requirementZoneBodyElement.hidden, false);
    assert.equal(draftTitleInput.value, "Draft title survives collapse");
    assert.equal(
      dashboardScenario.fetchHarness.observedCallList.length,
      initialFetchCallCount
    );
  }, "collapsed create affordance restores without resetting draft");
} finally {
  await cleanupDashboardScenario(dashboardScenario.root);
  rmSync(temporaryDirectoryPath, { recursive: true, force: true });
}

console.log("requirement_zone_collapse.test.ts: PASS");
