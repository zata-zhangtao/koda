import type { DevLog } from "../types/index.ts";

export type CompactTimelineDerivedCategory =
  | "general"
  | "prd"
  | "coding"
  | "review"
  | "test"
  | "delivery"
  | "system"
  | "changes";

const EXPLICIT_PRD_PATTERN_LIST: RegExp[] = [
  /已收到 PRD 生成请求/u,
  /PRD 生成失败/u,
  /PRD 生成阶段/u,
  /用户手动中断了 PRD 生成/u,
  /PRD 已生成，请先由用户确认 PRD/u,
  /PRD 生成在启动阶段发生异常/u,
  /未能自动产出可确认的 PRD/u,
  /待确认的 PRD/u,
];

type CompactTimelineCategoryLog = Pick<DevLog, "text_content" | "automation_phase_label">;

export function deriveCompactTimelineCategoryFromPhaseLabel(
  rawAutomationPhaseLabel: string | null | undefined
): CompactTimelineDerivedCategory | null {
  const normalizedAutomationPhaseLabel =
    rawAutomationPhaseLabel?.trim().toLowerCase() ?? "";
  if (!normalizedAutomationPhaseLabel) {
    return null;
  }

  if (normalizedAutomationPhaseLabel.includes("lint")) {
    return "test";
  }

  if (normalizedAutomationPhaseLabel.includes("review")) {
    return "review";
  }

  if (
    normalizedAutomationPhaseLabel.includes("complete") ||
    normalizedAutomationPhaseLabel.includes("acceptance")
  ) {
    return "delivery";
  }

  if (normalizedAutomationPhaseLabel.includes("exec")) {
    return "coding";
  }

  if (normalizedAutomationPhaseLabel.includes("prd")) {
    return "prd";
  }

  return null;
}

export function logMatchesExplicitPrdCategory(
  timelineLog: CompactTimelineCategoryLog
): boolean {
  const timelineTextContent = timelineLog.text_content || "";
  return EXPLICIT_PRD_PATTERN_LIST.some((explicitPrdPattern) =>
    explicitPrdPattern.test(timelineTextContent)
  );
}
