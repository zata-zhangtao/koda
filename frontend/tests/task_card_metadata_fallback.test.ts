import assert from "node:assert/strict";

import type { DevLog, TaskCardMetadata } from "../src/types.ts";
import { deriveFallbackRequirementChangeMetadata } from "../src/utils/task_card_metadata_fallback.ts";

const baseDevLog: Omit<DevLog, "id" | "text_content" | "created_at"> = {
  task_id: "task-1",
  run_account_id: "run-account-1",
  state_tag: "NONE" as DevLog["state_tag"],
  media_original_image_path: null,
  media_thumbnail_path: null,
  task_title: "Task title",
};

const updateRequirementDevLog: DevLog = {
  ...baseDevLog,
  id: "log-update",
  created_at: "2026-03-30T14:00:00+08:00",
  text_content: [
    "<!-- requirement-change:update -->",
    "## Requirement Updated",
    "",
    "Summary:",
    "Updated summary from logs",
  ].join("\n"),
};

const deleteRequirementDevLog: DevLog = {
  ...baseDevLog,
  id: "log-delete",
  created_at: "2026-03-30T15:00:00+08:00",
  text_content: [
    "<!-- requirement-change:delete -->",
    "## Requirement Deleted",
    "",
    "Final Summary:",
    "Deleted summary from logs",
  ].join("\n"),
};

const cachedRequirementChangeMetadata: TaskCardMetadata = {
  task_id: "task-1",
  display_stage_key: "waiting_user",
  display_stage_label: "等待用户",
  is_waiting_for_user: true,
  last_ai_activity_at: "2026-03-30T16:00:00+08:00",
  requirement_change_kind: "update",
  requirement_summary: "Cached summary",
  branch_health: null,
};

assert.deepEqual(
  deriveFallbackRequirementChangeMetadata([], cachedRequirementChangeMetadata),
  {
    requirement_change_kind: "update",
    requirement_summary: "Cached summary",
  }
);

assert.deepEqual(
  deriveFallbackRequirementChangeMetadata([updateRequirementDevLog]),
  {
    requirement_change_kind: "update",
    requirement_summary: "Updated summary from logs",
  }
);

assert.deepEqual(
  deriveFallbackRequirementChangeMetadata([
    updateRequirementDevLog,
    deleteRequirementDevLog,
  ]),
  {
    requirement_change_kind: "delete",
    requirement_summary: "Deleted summary from logs",
  }
);

assert.deepEqual(deriveFallbackRequirementChangeMetadata([]), {
  requirement_change_kind: null,
  requirement_summary: null,
});

console.log("task_card_metadata_fallback.test.ts: PASS");
