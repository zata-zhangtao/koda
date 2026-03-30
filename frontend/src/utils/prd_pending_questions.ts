/** PRD 待确认问题工具
 *
 * 负责解析 PRD Markdown 中的结构化待确认问题块，并生成确定性的反馈文本。
 */

import type {
  PrdPendingQuestion,
  PrdPendingQuestionAnswerSelectionMap,
  PrdPendingQuestionAnswerSelectionMapByTaskId,
  PrdPendingQuestionOption,
  WorkflowStage,
} from "../types/index.ts";

interface StructuredPendingQuestionSectionMatch {
  headingText: string;
  sectionMarkdownText: string;
  sectionStartIndex: number;
  sectionEndIndex: number;
}

interface JsonCodeFenceMatch {
  jsonText: string;
}

interface RawPrdPendingQuestionOption {
  key?: unknown;
  label?: unknown;
}

interface RawPrdPendingQuestion {
  id?: unknown;
  title?: unknown;
  required?: unknown;
  recommended_option_key?: unknown;
  recommendation_reason?: unknown;
  options?: unknown;
}

interface RawPrdPendingQuestionPayload {
  pending_questions?: unknown;
}

export interface ParsedPrdPendingQuestionsResult {
  pendingQuestionList: PrdPendingQuestion[];
  renderableMarkdownText: string;
  parseErrorText: string | null;
  hasStructuredQuestionBlock: boolean;
}

export interface PrdPendingQuestionActionBlockReasonParams {
  selectedTaskStage: WorkflowStage | null;
  isSelectedTaskPrdFileInitialLoadPending: boolean;
  selectedTaskPrdPendingQuestionParseErrorText: string | null;
  selectedTaskPrdPendingQuestionList: PrdPendingQuestion[];
  selectedTaskUnansweredRequiredPrdPendingQuestionCount: number;
  hasSelectedTaskPrdPendingQuestionAnswerDraft: boolean;
}

const STRUCTURED_PENDING_QUESTION_HEADING_TEXT = "待确认问题（结构化）";
const PRD_WAITING_CONFIRMATION_STAGE_VALUE = "prd_waiting_confirmation";
const MARKDOWN_HEADING_PATTERN = /^(#{1,6})\s+(.+)$/gm;
const JSON_CODE_FENCE_PATTERN = /```json\s*([\s\S]*?)```/gi;

function normalizeNonEmptyString(rawValue: unknown): string | null {
  if (typeof rawValue !== "string") {
    return null;
  }

  const trimmedValue = rawValue.trim();
  return trimmedValue.length > 0 ? trimmedValue : null;
}

function findStructuredPendingQuestionSection(
  prdMarkdownText: string
): StructuredPendingQuestionSectionMatch | null {
  const markdownHeadingMatchList = Array.from(
    prdMarkdownText.matchAll(MARKDOWN_HEADING_PATTERN)
  );

  for (let headingIndex = 0; headingIndex < markdownHeadingMatchList.length; headingIndex += 1) {
    const headingMatch = markdownHeadingMatchList[headingIndex];
    const headingText = headingMatch[2]?.trim() ?? "";
    if (!headingText.includes(STRUCTURED_PENDING_QUESTION_HEADING_TEXT)) {
      continue;
    }

    const headingStartIndex = headingMatch.index ?? 0;
    const headingLevel = headingMatch[1]?.length ?? 1;
    let sectionEndIndex = prdMarkdownText.length;

    for (
      let nextHeadingIndex = headingIndex + 1;
      nextHeadingIndex < markdownHeadingMatchList.length;
      nextHeadingIndex += 1
    ) {
      const nextHeadingMatch = markdownHeadingMatchList[nextHeadingIndex];
      const nextHeadingLevel = nextHeadingMatch[1]?.length ?? 1;
      if (nextHeadingLevel <= headingLevel) {
        sectionEndIndex = nextHeadingMatch.index ?? prdMarkdownText.length;
        break;
      }
    }

    return {
      headingText,
      sectionMarkdownText: prdMarkdownText.slice(headingStartIndex, sectionEndIndex),
      sectionStartIndex: headingStartIndex,
      sectionEndIndex,
    };
  }

  return null;
}

function findStructuredPendingQuestionJsonCodeFence(
  markdownText: string
): JsonCodeFenceMatch | null {
  const jsonCodeFenceMatchList = Array.from(
    markdownText.matchAll(JSON_CODE_FENCE_PATTERN)
  );

  for (const jsonCodeFenceMatch of jsonCodeFenceMatchList) {
    const jsonText = jsonCodeFenceMatch[1] ?? "";
    if (!jsonText.includes("\"pending_questions\"")) {
      continue;
    }

    return {
      jsonText,
    };
  }

  return null;
}

function normalizePendingQuestionOption(
  rawPendingQuestionOption: unknown
): PrdPendingQuestionOption | null {
  if (
    rawPendingQuestionOption === null ||
    typeof rawPendingQuestionOption !== "object"
  ) {
    return null;
  }

  const rawPendingQuestionOptionRecord =
    rawPendingQuestionOption as RawPrdPendingQuestionOption;
  const optionKeyText = normalizeNonEmptyString(rawPendingQuestionOptionRecord.key);
  const optionLabelText = normalizeNonEmptyString(rawPendingQuestionOptionRecord.label);
  if (!optionKeyText || !optionLabelText) {
    return null;
  }

  return {
    key: optionKeyText,
    label: optionLabelText,
  };
}

function normalizePendingQuestion(
  rawPendingQuestion: unknown
): PrdPendingQuestion | null {
  if (rawPendingQuestion === null || typeof rawPendingQuestion !== "object") {
    return null;
  }

  const rawPendingQuestionRecord = rawPendingQuestion as RawPrdPendingQuestion;
  const questionIdText = normalizeNonEmptyString(rawPendingQuestionRecord.id);
  const questionTitleText = normalizeNonEmptyString(rawPendingQuestionRecord.title);
  const recommendedOptionKeyText = normalizeNonEmptyString(
    rawPendingQuestionRecord.recommended_option_key
  );
  const recommendationReasonText = normalizeNonEmptyString(
    rawPendingQuestionRecord.recommendation_reason
  );
  if (
    !questionIdText ||
    !questionTitleText ||
    typeof rawPendingQuestionRecord.required !== "boolean" ||
    !recommendedOptionKeyText ||
    !recommendationReasonText ||
    !Array.isArray(rawPendingQuestionRecord.options)
  ) {
    return null;
  }

  const normalizedOptionList = rawPendingQuestionRecord.options
    .map((rawOption) => normalizePendingQuestionOption(rawOption))
    .filter(
      (normalizedOption): normalizedOption is PrdPendingQuestionOption =>
        normalizedOption !== null
    );
  if (normalizedOptionList.length !== rawPendingQuestionRecord.options.length) {
    return null;
  }

  const optionKeySet = new Set(normalizedOptionList.map((optionItem) => optionItem.key));
  if (optionKeySet.size !== normalizedOptionList.length) {
    return null;
  }
  if (!optionKeySet.has(recommendedOptionKeyText)) {
    return null;
  }

  return {
    id: questionIdText,
    title: questionTitleText,
    required: rawPendingQuestionRecord.required,
    recommendedOptionKey: recommendedOptionKeyText,
    recommendationReason: recommendationReasonText,
    options: normalizedOptionList,
  };
}

function stripStructuredPendingQuestionSection(
  prdMarkdownText: string,
  structuredSectionMatch: StructuredPendingQuestionSectionMatch
): string {
  const precedingMarkdownText = prdMarkdownText.slice(
    0,
    structuredSectionMatch.sectionStartIndex
  );
  const followingMarkdownText = prdMarkdownText.slice(
    structuredSectionMatch.sectionEndIndex
  );
  const stitchedMarkdownText = `${precedingMarkdownText}${followingMarkdownText}`;

  return stitchedMarkdownText.replace(/\n{3,}/g, "\n\n").trim();
}

export function parsePrdPendingQuestions(
  prdMarkdownText: string
): ParsedPrdPendingQuestionsResult {
  const structuredSectionMatch =
    findStructuredPendingQuestionSection(prdMarkdownText);
  if (!structuredSectionMatch) {
    return {
      pendingQuestionList: [],
      renderableMarkdownText: prdMarkdownText,
      parseErrorText: null,
      hasStructuredQuestionBlock: false,
    };
  }

  const jsonCodeFenceMatch = findStructuredPendingQuestionJsonCodeFence(
    structuredSectionMatch.sectionMarkdownText
  );
  if (!jsonCodeFenceMatch) {
    return {
      pendingQuestionList: [],
      renderableMarkdownText: prdMarkdownText,
      parseErrorText: `Structured section "${structuredSectionMatch.headingText}" is missing a JSON code fence.`,
      hasStructuredQuestionBlock: true,
    };
  }

  let rawPendingQuestionPayload: RawPrdPendingQuestionPayload;
  try {
    rawPendingQuestionPayload = JSON.parse(
      jsonCodeFenceMatch.jsonText
    ) as RawPrdPendingQuestionPayload;
  } catch (jsonParseError) {
    return {
      pendingQuestionList: [],
      renderableMarkdownText: prdMarkdownText,
      parseErrorText:
        jsonParseError instanceof Error
          ? jsonParseError.message
          : "Failed to parse structured pending-question JSON.",
      hasStructuredQuestionBlock: true,
    };
  }

  if (!Array.isArray(rawPendingQuestionPayload.pending_questions)) {
    return {
      pendingQuestionList: [],
      renderableMarkdownText: prdMarkdownText,
      parseErrorText: "Structured pending-question payload is missing pending_questions[].",
      hasStructuredQuestionBlock: true,
    };
  }

  const rawPendingQuestionList = rawPendingQuestionPayload.pending_questions;
  if (rawPendingQuestionList.length === 0) {
    return {
      pendingQuestionList: [],
      renderableMarkdownText: prdMarkdownText,
      parseErrorText:
        "Structured pending-question payload must include at least one question. Omit the entire structured section when there are no pending questions.",
      hasStructuredQuestionBlock: true,
    };
  }

  const normalizedPendingQuestionList = rawPendingQuestionList
    .map((rawPendingQuestionItem) => normalizePendingQuestion(rawPendingQuestionItem))
    .filter(
      (normalizedPendingQuestion): normalizedPendingQuestion is PrdPendingQuestion =>
        normalizedPendingQuestion !== null
    );
  if (
    normalizedPendingQuestionList.length !==
    rawPendingQuestionList.length
  ) {
    return {
      pendingQuestionList: [],
      renderableMarkdownText: prdMarkdownText,
      parseErrorText: "Structured pending-question payload does not match the required schema.",
      hasStructuredQuestionBlock: true,
    };
  }

  const pendingQuestionIdSet = new Set(
    normalizedPendingQuestionList.map((pendingQuestionItem) => pendingQuestionItem.id)
  );
  if (pendingQuestionIdSet.size !== normalizedPendingQuestionList.length) {
    return {
      pendingQuestionList: [],
      renderableMarkdownText: prdMarkdownText,
      parseErrorText: "Structured pending-question IDs must be unique.",
      hasStructuredQuestionBlock: true,
    };
  }

  return {
    pendingQuestionList: normalizedPendingQuestionList,
    renderableMarkdownText: stripStructuredPendingQuestionSection(
      prdMarkdownText,
      structuredSectionMatch
    ),
    parseErrorText: null,
    hasStructuredQuestionBlock: true,
  };
}

export function buildPrdPendingQuestionsFeedbackText(
  pendingQuestionList: PrdPendingQuestion[],
  selectedAnswerMap: PrdPendingQuestionAnswerSelectionMap
): string {
  const structuredAnswerPayload = {
    pending_question_answers: pendingQuestionList.map((pendingQuestionItem) => {
      const selectedOptionKeyText = selectedAnswerMap[pendingQuestionItem.id] ?? null;
      const selectedOption = pendingQuestionItem.options.find(
        (optionItem) => optionItem.key === selectedOptionKeyText
      );

      return {
        id: pendingQuestionItem.id,
        title: pendingQuestionItem.title,
        required: pendingQuestionItem.required,
        selected_option_key: selectedOptionKeyText,
        selected_option_label: selectedOption?.label ?? null,
        recommended_option_key: pendingQuestionItem.recommendedOptionKey,
      };
    }),
  };

  return [
    "PRD structured confirmation feedback",
    "",
    "```json",
    JSON.stringify(structuredAnswerPayload, null, 2),
    "```",
    "",
    "Please regenerate the PRD using these confirmed selections.",
  ].join("\n");
}

export function arePrdPendingQuestionSelectionMapsEqual(
  previousAnswerMap: PrdPendingQuestionAnswerSelectionMap,
  nextAnswerMap: PrdPendingQuestionAnswerSelectionMap
): boolean {
  const previousQuestionIdList = Object.keys(previousAnswerMap);
  const nextQuestionIdList = Object.keys(nextAnswerMap);
  if (previousQuestionIdList.length !== nextQuestionIdList.length) {
    return false;
  }

  return previousQuestionIdList.every(
    (questionIdText) =>
      previousAnswerMap[questionIdText] === nextAnswerMap[questionIdText]
  );
}

export function sanitizePrdPendingQuestionAnswerSelectionMap(
  pendingQuestionList: PrdPendingQuestion[],
  selectedAnswerMap: PrdPendingQuestionAnswerSelectionMap
): PrdPendingQuestionAnswerSelectionMap {
  const nextAnswerMap: PrdPendingQuestionAnswerSelectionMap = {};

  for (const pendingQuestionItem of pendingQuestionList) {
    const previousSelectedOptionKeyText = selectedAnswerMap[pendingQuestionItem.id];
    if (
      typeof previousSelectedOptionKeyText !== "string" ||
      previousSelectedOptionKeyText.length === 0
    ) {
      continue;
    }

    const hasMatchingOption = pendingQuestionItem.options.some(
      (optionItem) => optionItem.key === previousSelectedOptionKeyText
    );
    if (hasMatchingOption) {
      nextAnswerMap[pendingQuestionItem.id] = previousSelectedOptionKeyText;
    }
  }

  return nextAnswerMap;
}

export function getTaskScopedPrdPendingQuestionAnswerSelectionMap(
  answerSelectionMapByTaskId: PrdPendingQuestionAnswerSelectionMapByTaskId,
  taskId: string | null
): PrdPendingQuestionAnswerSelectionMap {
  if (!taskId) {
    return {};
  }

  return answerSelectionMapByTaskId[taskId] ?? {};
}

export function setTaskScopedPrdPendingQuestionAnswerSelectionMap(
  answerSelectionMapByTaskId: PrdPendingQuestionAnswerSelectionMapByTaskId,
  taskId: string,
  nextAnswerMap: PrdPendingQuestionAnswerSelectionMap
): PrdPendingQuestionAnswerSelectionMapByTaskId {
  const previousTaskAnswerMap = answerSelectionMapByTaskId[taskId] ?? {};
  if (arePrdPendingQuestionSelectionMapsEqual(previousTaskAnswerMap, nextAnswerMap)) {
    const hasExistingTaskEntry = Object.prototype.hasOwnProperty.call(
      answerSelectionMapByTaskId,
      taskId
    );
    if (hasExistingTaskEntry || Object.keys(nextAnswerMap).length > 0) {
      return answerSelectionMapByTaskId;
    }
  }

  if (Object.keys(nextAnswerMap).length === 0) {
    if (!Object.prototype.hasOwnProperty.call(answerSelectionMapByTaskId, taskId)) {
      return answerSelectionMapByTaskId;
    }

    const nextAnswerSelectionMapByTaskId = { ...answerSelectionMapByTaskId };
    delete nextAnswerSelectionMapByTaskId[taskId];
    return nextAnswerSelectionMapByTaskId;
  }

  return {
    ...answerSelectionMapByTaskId,
    [taskId]: nextAnswerMap,
  };
}

export function derivePrdPendingQuestionActionBlockReason({
  selectedTaskStage,
  isSelectedTaskPrdFileInitialLoadPending,
  selectedTaskPrdPendingQuestionParseErrorText,
  selectedTaskPrdPendingQuestionList,
  selectedTaskUnansweredRequiredPrdPendingQuestionCount,
  hasSelectedTaskPrdPendingQuestionAnswerDraft,
}: PrdPendingQuestionActionBlockReasonParams): string | null {
  if (selectedTaskStage !== PRD_WAITING_CONFIRMATION_STAGE_VALUE) {
    return null;
  }
  if (isSelectedTaskPrdFileInitialLoadPending) {
    return "当前任务 PRD 正在加载，请等待加载完成后再确认 PRD 或开始执行。";
  }
  if (selectedTaskPrdPendingQuestionParseErrorText !== null) {
    return [
      "当前 PRD 的“待确认问题（结构化）”区块格式无效。",
      "请先通过反馈让 AI 修复该 JSON 区块后，再继续确认 PRD 或开始执行。",
      `解析错误：${selectedTaskPrdPendingQuestionParseErrorText}`,
    ].join(" ");
  }
  if (selectedTaskPrdPendingQuestionList.length === 0) {
    return null;
  }
  if (selectedTaskUnansweredRequiredPrdPendingQuestionCount > 0) {
    return `还有 ${selectedTaskUnansweredRequiredPrdPendingQuestionCount} 个必答问题未完成，请先通过下拉列表完成确认。`;
  }
  if (hasSelectedTaskPrdPendingQuestionAnswerDraft) {
    return "请先提交当前下拉选择并重新生成 PRD，再继续确认或开始执行。";
  }
  return null;
}
