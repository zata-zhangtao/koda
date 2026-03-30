import assert from "node:assert/strict";

import type { DevLog } from "../src/types/index.ts";
import {
  buildTaskTimelineRenderableLogList,
  isGroupedAutomationTranscriptLog,
} from "../src/utils/task_timeline_continuity.ts";

function buildDevLog(overrides: Partial<DevLog>): DevLog {
  return {
    id: overrides.id ?? "log-id",
    task_id: overrides.task_id ?? "task-1",
    run_account_id: overrides.run_account_id ?? "run-1",
    created_at: overrides.created_at ?? "2026-03-30T16:00:00+08:00",
    text_content: overrides.text_content ?? "",
    state_tag: overrides.state_tag ?? "OPTIMIZATION",
    media_original_image_path: overrides.media_original_image_path ?? null,
    media_thumbnail_path: overrides.media_thumbnail_path ?? null,
    task_title: overrides.task_title ?? "Task",
    automation_session_id: overrides.automation_session_id ?? null,
    automation_sequence_index: overrides.automation_sequence_index ?? null,
    automation_phase_label: overrides.automation_phase_label ?? null,
    automation_runner_kind: overrides.automation_runner_kind ?? null,
  };
}

const groupedTimelineLogList = buildTaskTimelineRenderableLogList([
  buildDevLog({
    id: "chunk-1",
    created_at: "2026-03-30T16:00:00+08:00",
    text_content: "line one",
    automation_session_id: "session-a",
    automation_sequence_index: 1,
    automation_phase_label: "codex-exec",
    automation_runner_kind: "codex",
  }),
  buildDevLog({
    id: "chunk-2",
    created_at: "2026-03-30T16:00:05+08:00",
    text_content: "line two",
    automation_session_id: "session-a",
    automation_sequence_index: 2,
    automation_phase_label: "codex-exec",
    automation_runner_kind: "codex",
  }),
  buildDevLog({
    id: "manual-log",
    created_at: "2026-03-30T16:01:00+08:00",
    text_content: "manual note",
    state_tag: "NONE",
  }),
  buildDevLog({
    id: "chunk-3",
    created_at: "2026-03-30T16:01:05+08:00",
    text_content: "line three",
    automation_session_id: "session-a",
    automation_sequence_index: 3,
    automation_phase_label: "codex-exec",
    automation_runner_kind: "codex",
  }),
]);

assert.equal(groupedTimelineLogList.length, 3);
assert.equal(groupedTimelineLogList[0]?.text_content, "line one\nline two");
assert.equal(
  groupedTimelineLogList[0]?.grouped_automation_transcript_chunk_count,
  2
);
assert.equal(
  groupedTimelineLogList[0]?.grouped_automation_transcript_started_at,
  "2026-03-30T16:00:00+08:00"
);
assert.equal(
  groupedTimelineLogList[0]?.grouped_automation_transcript_ended_at,
  "2026-03-30T16:00:05+08:00"
);
assert.equal(groupedTimelineLogList[1]?.id, "manual-log");
assert.equal(groupedTimelineLogList[2]?.text_content, "line three");
assert.equal(
  groupedTimelineLogList[2]?.grouped_automation_transcript_chunk_count,
  1
);
assert.equal(isGroupedAutomationTranscriptLog(groupedTimelineLogList[0]!), true);
assert.equal(isGroupedAutomationTranscriptLog(groupedTimelineLogList[1]!), false);

const legacyTimelineLogList = buildTaskTimelineRenderableLogList([
  buildDevLog({
    id: "legacy-1",
    created_at: "2026-03-30T16:10:00+08:00",
    text_content: "legacy one",
    state_tag: "NONE",
  }),
  buildDevLog({
    id: "legacy-2",
    created_at: "2026-03-30T16:10:05+08:00",
    text_content: "legacy two",
    state_tag: "FIXED",
  }),
]);

assert.equal(legacyTimelineLogList.length, 2);
assert.equal(legacyTimelineLogList[0]?.id, "legacy-1");
assert.equal(legacyTimelineLogList[1]?.id, "legacy-2");

console.log("task_timeline_continuity.test.ts: PASS");
