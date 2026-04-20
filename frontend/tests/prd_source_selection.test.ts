import assert from "node:assert/strict";

import {
  canSubmitPrdSourceAction,
  getPrdSourceActionLabel,
  isMarkdownPrdImportFile,
} from "../src/utils/prd_source_selection.ts";

assert.equal(canSubmitPrdSourceAction("ai_generate", null, null, "upload", ""), true);
assert.equal(canSubmitPrdSourceAction("pending", null, null, "upload", ""), false);
assert.equal(
  canSubmitPrdSourceAction(
    "pending",
    "tasks/pending/example.md",
    null,
    "upload",
    ""
  ),
  true
);
assert.equal(
  canSubmitPrdSourceAction("manual_import", null, null, "upload", ""),
  false
);
assert.equal(
  canSubmitPrdSourceAction(
    "manual_import",
    null,
    new File(["# PRD"], "manual.md", { type: "text/markdown" }),
    "upload",
    ""
  ),
  true
);
assert.equal(
  canSubmitPrdSourceAction("manual_import", null, null, "paste", "# PRD\n"),
  true
);
assert.equal(
  canSubmitPrdSourceAction("manual_import", null, null, "paste", "  \n  "),
  false
);
assert.equal(
  isMarkdownPrdImportFile(
    new File(["# PRD"], "clipboard.md", { type: "text/plain" })
  ),
  true
);
assert.equal(
  isMarkdownPrdImportFile(
    new File(["# PRD"], "clipboard", { type: "text/markdown" })
  ),
  true
);
assert.equal(
  isMarkdownPrdImportFile(
    new File(["not markdown"], "clipboard.txt", { type: "text/plain" })
  ),
  false
);
assert.equal(getPrdSourceActionLabel("ai_generate"), "开始任务");
assert.equal(getPrdSourceActionLabel("pending"), "使用选中的 PRD");
assert.equal(getPrdSourceActionLabel("manual_import"), "导入 PRD");

console.log("prd_source_selection.test.ts: PASS");
