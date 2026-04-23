import assert from "node:assert/strict";

import {
  deriveCompactTimelineCategoryFromPhaseLabel,
  logMatchesExplicitPrdCategory,
} from "../src/utils/compact_timeline_category.ts";

assert.equal(deriveCompactTimelineCategoryFromPhaseLabel("codex-prd"), "prd");
assert.equal(deriveCompactTimelineCategoryFromPhaseLabel("codex-exec"), "coding");
assert.equal(
  deriveCompactTimelineCategoryFromPhaseLabel("codex-review-round-2"),
  "review"
);
assert.equal(
  deriveCompactTimelineCategoryFromPhaseLabel("post-review-lint"),
  "test"
);
assert.equal(
  deriveCompactTimelineCategoryFromPhaseLabel("git-complete"),
  "delivery"
);

assert.equal(
  logMatchesExplicitPrdCategory({
    automation_phase_label: null,
    text_content: "已收到 PRD 生成请求，等待后台执行器开始写入详细日志。",
  }),
  true
);

assert.equal(
  logMatchesExplicitPrdCategory({
    automation_phase_label: "codex-exec",
    text_content: "Execution started and will implement code based on the confirmed PRD.",
  }),
  false
);

console.log("compact_timeline_category.test.ts: PASS");
