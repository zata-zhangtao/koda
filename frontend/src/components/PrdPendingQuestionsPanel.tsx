/** PRD 待确认问题面板
 *
 * 在 PRD 等待确认阶段渲染结构化问题的下拉选择、推荐信息和反馈预览。
 */

import type {
  PrdPendingQuestion,
  PrdPendingQuestionAnswerSelectionMap,
} from "../types";

interface PrdPendingQuestionsPanelProps {
  pendingQuestionList: PrdPendingQuestion[];
  selectedAnswerMap: PrdPendingQuestionAnswerSelectionMap;
  unansweredRequiredQuestionCount: number;
  feedbackPreviewText: string;
  isSubmitting: boolean;
  isSubmitDisabled: boolean;
  submitDisabledReasonText: string | null;
  onSelectAnswer: (questionId: string, optionKey: string) => void;
  onApplyAllRecommended: () => void;
  onSubmit: () => void;
}

function joinClassNames(...classNameList: Array<string | false | null | undefined>): string {
  return classNameList.filter(Boolean).join(" ");
}

export function PrdPendingQuestionsPanel({
  pendingQuestionList,
  selectedAnswerMap,
  unansweredRequiredQuestionCount,
  feedbackPreviewText,
  isSubmitting,
  isSubmitDisabled,
  submitDisabledReasonText,
  onSelectAnswer,
  onApplyAllRecommended,
  onSubmit,
}: PrdPendingQuestionsPanelProps) {
  return (
    <section className="devflow-card devflow-prd-pending-panel" aria-label="PRD 待确认问题">
      <div className="devflow-prd-pending-panel__header">
        <div className="devflow-prd-pending-panel__copy">
          <span className="devflow-prd-pending-panel__eyebrow">PRD Waiting Confirmation</span>
          <h4 className="devflow-prd-pending-panel__title">待确认问题</h4>
          <p className="devflow-prd-pending-panel__hint">
            {unansweredRequiredQuestionCount > 0
              ? `还有 ${unansweredRequiredQuestionCount} 个必答问题未完成，请先通过下拉选项确认。`
              : "全部必答题已完成，提交后会复用现有 DevLog + regenerate-prd 链路。"}
          </p>
        </div>

        <button
          type="button"
          className="devflow-button devflow-button--outline"
          onClick={onApplyAllRecommended}
          disabled={pendingQuestionList.length === 0 || isSubmitting}
        >
          一键采用推荐
        </button>
      </div>

      <div className="devflow-prd-pending-panel__question-list">
        {pendingQuestionList.map((pendingQuestionItem) => {
          const selectedOptionKeyText = selectedAnswerMap[pendingQuestionItem.id] ?? "";
          const selectedOption = pendingQuestionItem.options.find(
            (optionItem) => optionItem.key === selectedOptionKeyText
          );
          const recommendedOption = pendingQuestionItem.options.find(
            (optionItem) => optionItem.key === pendingQuestionItem.recommendedOptionKey
          );
          const isQuestionBlocked =
            pendingQuestionItem.required && selectedOptionKeyText.length === 0;

          return (
            <article
              key={pendingQuestionItem.id}
              className={joinClassNames(
                "devflow-prd-pending-panel__question",
                isQuestionBlocked && "devflow-prd-pending-panel__question--blocked"
              )}
            >
              <div className="devflow-prd-pending-panel__question-copy">
                <div className="devflow-prd-pending-panel__question-header">
                  <h5 className="devflow-prd-pending-panel__question-title">
                    {pendingQuestionItem.title}
                  </h5>
                  <span
                    className={joinClassNames(
                      "devflow-prd-pending-panel__question-tag",
                      pendingQuestionItem.required
                        ? "devflow-prd-pending-panel__question-tag--required"
                        : "devflow-prd-pending-panel__question-tag--optional"
                    )}
                  >
                    {pendingQuestionItem.required ? "必答" : "可选"}
                  </span>
                </div>

                <p className="devflow-prd-pending-panel__recommendation">
                  推荐答案：
                  <strong>
                    {recommendedOption
                      ? ` ${recommendedOption.key}. ${recommendedOption.label}`
                      : " 未提供"}
                  </strong>
                </p>
                <p className="devflow-prd-pending-panel__reason">
                  推荐理由：{pendingQuestionItem.recommendationReason}
                </p>
              </div>

              <label className="devflow-prd-pending-panel__select-label">
                <span className="devflow-prd-pending-panel__select-caption">选择答案</span>
                <select
                  className="devflow-input devflow-input--select devflow-prd-pending-panel__select"
                  value={selectedOptionKeyText}
                  onChange={(changeEvent) => {
                    onSelectAnswer(pendingQuestionItem.id, changeEvent.target.value);
                  }}
                  disabled={isSubmitting}
                >
                  <option value="">请选择一个选项</option>
                  {pendingQuestionItem.options.map((optionItem) => (
                    <option key={optionItem.key} value={optionItem.key}>
                      {`${optionItem.key}. ${optionItem.label}${
                        optionItem.key === pendingQuestionItem.recommendedOptionKey
                          ? "（推荐）"
                          : ""
                      }`}
                    </option>
                  ))}
                </select>
              </label>

              <p
                className={joinClassNames(
                  "devflow-prd-pending-panel__selection-status",
                  isQuestionBlocked &&
                    "devflow-prd-pending-panel__selection-status--warning"
                )}
              >
                {selectedOption
                  ? `当前选择：${selectedOption.key}. ${selectedOption.label}`
                  : pendingQuestionItem.required
                    ? "当前状态：尚未选择，完成后才能继续确认 PRD。"
                    : "当前状态：尚未选择。"}
              </p>
            </article>
          );
        })}
      </div>

      <div className="devflow-prd-pending-panel__footer">
        <div className="devflow-prd-pending-panel__preview-block">
          <span className="devflow-prd-pending-panel__preview-label">结构化反馈预览</span>
          <pre className="devflow-prd-pending-panel__preview">{feedbackPreviewText}</pre>
          <p className="devflow-prd-pending-panel__extra-hint">
            结构化选择之外的补充说明，仍可继续使用下方自由反馈输入框和附件上传。
          </p>
        </div>

        <div className="devflow-prd-pending-panel__actions">
          {submitDisabledReasonText ? (
            <p className="devflow-prd-pending-panel__action-hint">
              {submitDisabledReasonText}
            </p>
          ) : null}

          <button
            type="button"
            className="devflow-button devflow-button--secondary"
            onClick={onSubmit}
            disabled={isSubmitDisabled}
          >
            {isSubmitting ? <span className="devflow-spinner" aria-hidden="true" /> : null}
            <span>提交并重新生成 PRD</span>
          </button>
        </div>
      </div>
    </section>
  );
}
