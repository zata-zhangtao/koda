import assert from "node:assert/strict";

import {
  buildPrdPendingQuestionsFeedbackText,
  derivePrdPendingQuestionActionBlockReason,
  getTaskScopedPrdPendingQuestionAnswerSelectionMap,
  parsePrdPendingQuestions,
  sanitizePrdPendingQuestionAnswerSelectionMap,
  setTaskScopedPrdPendingQuestionAnswerSelectionMap,
} from "../src/utils/prd_pending_questions.ts";

const emptyStructuredQuestionMarkdownText = [
  "# PRD",
  "",
  "## 0. 待确认问题（结构化）",
  "",
  "```json",
  JSON.stringify(
    {
      pending_questions: [],
    },
    null,
    2
  ),
  "```",
  "",
  "## 1. Scope",
  "Keep the rest of the markdown intact.",
].join("\n");

const emptyStructuredQuestionResult = parsePrdPendingQuestions(
  emptyStructuredQuestionMarkdownText
);
assert.equal(emptyStructuredQuestionResult.hasStructuredQuestionBlock, true);
assert.equal(emptyStructuredQuestionResult.pendingQuestionList.length, 0);
assert.match(
  emptyStructuredQuestionResult.parseErrorText ?? "",
  /must include at least one question/i
);
assert.equal(
  emptyStructuredQuestionResult.renderableMarkdownText,
  emptyStructuredQuestionMarkdownText
);

const validStructuredQuestionMarkdownText = [
  "# PRD",
  "",
  "## 0. 待确认问题（结构化）",
  "",
  "```json",
  JSON.stringify(
    {
      pending_questions: [
        {
          id: "storage_strategy",
          title: "待确认问题的数据源应该放在哪里？",
          required: true,
          recommended_option_key: "markdown_structured_block",
          recommendation_reason: "首期只需要复用现有 PRD 文件链路，不需要引入新存储层。",
          options: [
            {
              key: "markdown_structured_block",
              label: "写回 PRD 结构化区块",
            },
            {
              key: "database_field",
              label: "新增数据库字段",
            },
          ],
        },
      ],
    },
    null,
    2
  ),
  "```",
  "",
  "## 1. Scope",
  "Keep the rest of the markdown intact.",
].join("\n");

const validStructuredQuestionResult = parsePrdPendingQuestions(
  validStructuredQuestionMarkdownText
);
assert.equal(validStructuredQuestionResult.parseErrorText, null);
assert.equal(validStructuredQuestionResult.hasStructuredQuestionBlock, true);
assert.equal(validStructuredQuestionResult.pendingQuestionList.length, 1);
assert.equal(
  validStructuredQuestionResult.pendingQuestionList[0]?.recommendedOptionKey,
  "markdown_structured_block"
);
assert.ok(
  !validStructuredQuestionResult.renderableMarkdownText.includes(
    "待确认问题（结构化）"
  )
);
assert.ok(
  validStructuredQuestionResult.renderableMarkdownText.includes("## 1. Scope")
);

const structuredFeedbackText = buildPrdPendingQuestionsFeedbackText(
  validStructuredQuestionResult.pendingQuestionList,
  {
    storage_strategy: "markdown_structured_block",
  }
);
assert.match(structuredFeedbackText, /pending_question_answers/);
assert.match(structuredFeedbackText, /"selected_option_key": "markdown_structured_block"/);

const prdLoadingBlockReasonText = derivePrdPendingQuestionActionBlockReason({
  selectedTaskStage: "prd_waiting_confirmation",
  isSelectedTaskPrdFileInitialLoadPending: true,
  selectedTaskPrdPendingQuestionParseErrorText: null,
  selectedTaskPrdPendingQuestionList: [],
  selectedTaskUnansweredRequiredPrdPendingQuestionCount: 0,
  hasSelectedTaskPrdPendingQuestionAnswerDraft: false,
});
assert.match(prdLoadingBlockReasonText ?? "", /PRD 正在加载/i);

let taskScopedAnswerSelectionMapByTaskId = setTaskScopedPrdPendingQuestionAnswerSelectionMap(
  {},
  "task-a",
  {
    storage_strategy: "database_field",
  }
);
taskScopedAnswerSelectionMapByTaskId = setTaskScopedPrdPendingQuestionAnswerSelectionMap(
  taskScopedAnswerSelectionMapByTaskId,
  "task-b",
  {
    storage_strategy: "markdown_structured_block",
  }
);
assert.deepEqual(
  getTaskScopedPrdPendingQuestionAnswerSelectionMap(
    taskScopedAnswerSelectionMapByTaskId,
    "task-a"
  ),
  {
    storage_strategy: "database_field",
  }
);
assert.deepEqual(
  getTaskScopedPrdPendingQuestionAnswerSelectionMap(
    taskScopedAnswerSelectionMapByTaskId,
    "task-b"
  ),
  {
    storage_strategy: "markdown_structured_block",
  }
);
assert.deepEqual(
  sanitizePrdPendingQuestionAnswerSelectionMap(
    validStructuredQuestionResult.pendingQuestionList,
    getTaskScopedPrdPendingQuestionAnswerSelectionMap(
      taskScopedAnswerSelectionMapByTaskId,
      "task-b"
    )
  ),
  {
    storage_strategy: "markdown_structured_block",
  }
);
taskScopedAnswerSelectionMapByTaskId = setTaskScopedPrdPendingQuestionAnswerSelectionMap(
  taskScopedAnswerSelectionMapByTaskId,
  "task-b",
  {}
);
assert.deepEqual(
  getTaskScopedPrdPendingQuestionAnswerSelectionMap(
    taskScopedAnswerSelectionMapByTaskId,
    "task-b"
  ),
  {}
);
assert.deepEqual(
  getTaskScopedPrdPendingQuestionAnswerSelectionMap(
    taskScopedAnswerSelectionMapByTaskId,
    "task-a"
  ),
  {
    storage_strategy: "database_field",
  }
);

console.log("prd_pending_questions.test.ts: PASS");
