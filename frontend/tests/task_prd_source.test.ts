import assert from "node:assert/strict";

import {
  buildArchivedTaskPrdNoticeText,
  isArchivedTaskPrdFilePath,
} from "../src/utils/task_prd_source.ts";

assert.equal(
  isArchivedTaskPrdFilePath(
    "/Users/zata/code/task/demo/tasks/archive/prd-ac99f28d-example.md"
  ),
  true
);

assert.equal(
  isArchivedTaskPrdFilePath(
    "C:\\Users\\zata\\code\\task\\demo\\tasks\\archive\\prd-ac99f28d-example.md"
  ),
  true
);

assert.equal(
  isArchivedTaskPrdFilePath(
    "/Users/zata/code/task/demo/tasks/prd-ac99f28d-example.md"
  ),
  false
);

assert.equal(isArchivedTaskPrdFilePath(null), false);

assert.equal(
  buildArchivedTaskPrdNoticeText(
    "/Users/zata/code/task/demo/tasks/archive/prd-ac99f28d-example.md"
  ),
  "当前展示的是 tasks/archive/ 中的已归档 PRD。它仍然对应当前任务的同一份 PRD 文档，但 live tasks 根目录里已经没有可读的活动 PRD 文件。"
);

assert.equal(
  buildArchivedTaskPrdNoticeText(
    "/Users/zata/code/task/demo/tasks/prd-ac99f28d-example.md"
  ),
  null
);

console.log("task_prd_source.test.ts: PASS");
