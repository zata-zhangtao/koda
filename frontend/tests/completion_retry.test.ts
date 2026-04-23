import assert from "node:assert/strict";

import type { DevLog } from "../src/types.ts";
import { hasRetryableCompletionFailure } from "../src/utils/completion_retry.ts";

const baseDevLog: Omit<DevLog, "id" | "text_content" | "created_at"> = {
  task_id: "task-1",
  run_account_id: "run-account-1",
  state_tag: "NONE" as DevLog["state_tag"],
  media_original_image_path: null,
  media_thumbnail_path: null,
  task_title: "Task title",
};

const completionFailureDevLog: DevLog = {
  ...baseDevLog,
  id: "log-complete-failure",
  created_at: "2026-04-23T14:00:00+08:00",
  state_tag: "BUG" as DevLog["state_tag"],
  text_content: [
    "❌ Koda 未能完成分支收尾与合并：承载 `main` 分支的工作区不是干净状态，无法自动执行 merge。",
    "任务已进入：待修改（changes_requested），需要人工介入。",
  ].join("\n"),
};

const implementationFailureDevLog: DevLog = {
  ...baseDevLog,
  id: "log-implementation-failure",
  created_at: "2026-04-23T15:00:00+08:00",
  state_tag: "BUG" as DevLog["state_tag"],
  text_content: [
    "❌ codex exec 执行失败，任务实现阶段未能完成。",
    "任务已进入：待修改（changes_requested），需要人工介入。",
  ].join("\n"),
};

const laterHumanNoteDevLog: DevLog = {
  ...baseDevLog,
  id: "log-human-note",
  created_at: "2026-04-23T16:00:00+08:00",
  text_content: "用户已在仓库外手动清理主工作区，准备重试 Complete。",
};

assert.equal(hasRetryableCompletionFailure([completionFailureDevLog]), true);

assert.equal(
  hasRetryableCompletionFailure([
    completionFailureDevLog,
    laterHumanNoteDevLog,
  ]),
  true
);

assert.equal(
  hasRetryableCompletionFailure([
    completionFailureDevLog,
    implementationFailureDevLog,
  ]),
  false
);

assert.equal(hasRetryableCompletionFailure([]), false);

console.log("completion_retry.test.ts: PASS");
