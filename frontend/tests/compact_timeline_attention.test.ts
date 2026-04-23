import assert from "node:assert/strict";

import type { DevLog } from "../src/types/index.ts";
import {
  groupRequiresAttention,
  logIndicatesSuccess,
  logRequiresAttention,
} from "../src/utils/compact_timeline_attention.ts";

function buildDevLog(overrides: Partial<DevLog>): DevLog {
  return {
    id: overrides.id ?? "log-id",
    task_id: overrides.task_id ?? "task-1",
    run_account_id: overrides.run_account_id ?? "run-1",
    created_at: overrides.created_at ?? "2026-04-22T16:00:00+08:00",
    text_content: overrides.text_content ?? "",
    state_tag: overrides.state_tag ?? "NONE",
    media_original_image_path: overrides.media_original_image_path ?? null,
    media_thumbnail_path: overrides.media_thumbnail_path ?? null,
    task_title: overrides.task_title ?? "Task",
    automation_session_id: overrides.automation_session_id ?? null,
    automation_sequence_index: overrides.automation_sequence_index ?? null,
    automation_phase_label: overrides.automation_phase_label ?? null,
    automation_runner_kind: overrides.automation_runner_kind ?? null,
  };
}

assert.equal(
  logRequiresAttention(
    buildDevLog({
      text_content: "Still missing the rollback guard in the last error path.",
    })
  ),
  false
);

assert.equal(
  logRequiresAttention(
    buildDevLog({
      state_tag: "BUG",
      text_content:
        "🛠️ post-review lint 未通过，开始第 1/2 轮 AI lint 定向修复。",
    })
  ),
  false
);

assert.equal(
  logRequiresAttention(
    buildDevLog({
      state_tag: "BUG",
      text_content:
        "❌ AI 自检闭环未完成：第 1 轮评审执行失败。\n任务已进入：待修改（changes_requested），需要人工介入。",
    })
  ),
  true
);

assert.equal(
  logRequiresAttention(
    buildDevLog({
      state_tag: "BUG",
      text_content:
        "📝 独立代码评审完成：发现需要处理的阻塞性问题。本次运行只记录 review 结论，不会自动回改，也不会修改任务阶段。",
    })
  ),
  true
);

assert.equal(
  logRequiresAttention(
    buildDevLog({
      state_tag: "BUG",
      text_content:
        "⚠️ Koda 已把任务分支合并到 `main`，但自动清理没有完全成功：cleanup warning。\n任务仍会标记为完成，请按日志提示手动处理残留 worktree/branch。",
    })
  ),
  true
);

assert.equal(
  logIndicatesSuccess(
    buildDevLog({
      state_tag: "FIXED",
      text_content:
        "✅ AI 自检闭环完成：第 1 轮评审通过，未发现阻塞性问题。",
    })
  ),
  true
);

assert.equal(
  logIndicatesSuccess(
    buildDevLog({
      state_tag: "FIXED",
      text_content: "✅ 第 1 轮自动回改完成，开始重新执行 AI 自检（2/3）。",
    })
  ),
  false
);

assert.equal(
  logIndicatesSuccess(
    buildDevLog({
      state_tag: "FIXED",
      text_content:
        "🛠️ 第 1 轮 AI lint 定向修复完成，开始重新执行 pre-commit lint。",
    })
  ),
  false
);

assert.equal(
  logIndicatesSuccess(
    buildDevLog({
      state_tag: "FIXED",
      text_content: "This implementation completed a local sub-step and moved on.",
    })
  ),
  false
);

assert.equal(
  groupRequiresAttention([
    buildDevLog({
      text_content: "Implementation summary mentions an error path, but nothing failed.",
    }),
    buildDevLog({
      text_content:
        "❌ AI 自检闭环未完成：第 1 轮评审执行失败。\n任务已进入：待修改（changes_requested），需要人工介入。",
      state_tag: "BUG",
    }),
  ]),
  true
);

console.log("compact_timeline_attention.test.ts: PASS");
