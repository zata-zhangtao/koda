import type { DevLog, TaskCardMetadata } from "../types";

const REQUIREMENT_UPDATE_MARKER = "<!-- requirement-change:update -->";
const REQUIREMENT_DELETE_MARKER = "<!-- requirement-change:delete -->";

type RequirementChangeFallbackMetadata = Pick<
  TaskCardMetadata,
  "requirement_change_kind" | "requirement_summary"
>;

export function deriveFallbackRequirementChangeMetadata(
  taskDevLogList: DevLog[],
  cachedTaskCardMetadata?: TaskCardMetadata
): RequirementChangeFallbackMetadata {
  if (cachedTaskCardMetadata?.requirement_change_kind) {
    return {
      requirement_change_kind: cachedTaskCardMetadata.requirement_change_kind,
      requirement_summary: cachedTaskCardMetadata.requirement_summary,
    };
  }

  for (
    let taskDevLogIndex = taskDevLogList.length - 1;
    taskDevLogIndex >= 0;
    taskDevLogIndex -= 1
  ) {
    const parsedRequirementChangeMetadata = parseRequirementChangeMetadata(
      taskDevLogList[taskDevLogIndex].text_content
    );
    if (parsedRequirementChangeMetadata) {
      return parsedRequirementChangeMetadata;
    }
  }

  return {
    requirement_change_kind: null,
    requirement_summary: null,
  };
}

function parseRequirementChangeMetadata(
  rawMarkdownText: string
): RequirementChangeFallbackMetadata | null {
  const hasRequirementUpdateMarker = rawMarkdownText.includes(
    REQUIREMENT_UPDATE_MARKER
  );
  const hasRequirementDeleteMarker = rawMarkdownText.includes(
    REQUIREMENT_DELETE_MARKER
  );
  if (!hasRequirementUpdateMarker && !hasRequirementDeleteMarker) {
    return null;
  }

  const requirementChangeKind = hasRequirementUpdateMarker ? "update" : "delete";
  const summarySectionLabel =
    requirementChangeKind === "update" ? "Summary:" : "Final Summary:";
  const rawSummaryText = extractMarkerBody(rawMarkdownText, summarySectionLabel) ?? "";
  const normalizedSummaryText = cleanMarkdownPreview(rawSummaryText) || null;

  return {
    requirement_change_kind: requirementChangeKind,
    requirement_summary: normalizedSummaryText,
  };
}

function extractMarkerBody(
  rawMarkdownText: string,
  sectionLabel: string
): string | null {
  const sectionPattern = new RegExp(`${escapeRegExp(sectionLabel)}\\n([\\s\\S]*)$`);
  const sectionMatch = rawMarkdownText.match(sectionPattern);
  return sectionMatch?.[1]?.trim() || null;
}

function cleanMarkdownPreview(rawMarkdownText: string): string {
  return rawMarkdownText
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/^\/[a-z-]+\s+/gi, "")
    .replace(/```[\s\S]*?```/g, " code block ")
    .replace(/`/g, "")
    .replace(/[#!>*_[\]()\-+]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function escapeRegExp(rawText: string): string {
  return rawText.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
