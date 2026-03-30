import { toTimestampValue } from "./datetime.ts";
import type { DevLog } from "../types/index.ts";

export interface TaskTimelineRenderableLog extends DevLog {
  grouped_automation_transcript_chunk_count?: number | null;
  grouped_automation_transcript_started_at?: string | null;
  grouped_automation_transcript_ended_at?: string | null;
}

function compareDevLogsByCreatedAt(leftDevLog: DevLog, rightDevLog: DevLog): number {
  const createdAtDiff =
    toTimestampValue(leftDevLog.created_at) - toTimestampValue(rightDevLog.created_at);
  if (createdAtDiff !== 0) {
    return createdAtDiff;
  }

  return leftDevLog.id.localeCompare(rightDevLog.id);
}

function compareAutomationTranscriptChunks(leftDevLog: DevLog, rightDevLog: DevLog): number {
  const leftSequenceIndex = leftDevLog.automation_sequence_index ?? Number.MAX_SAFE_INTEGER;
  const rightSequenceIndex =
    rightDevLog.automation_sequence_index ?? Number.MAX_SAFE_INTEGER;
  if (leftSequenceIndex !== rightSequenceIndex) {
    return leftSequenceIndex - rightSequenceIndex;
  }

  return compareDevLogsByCreatedAt(leftDevLog, rightDevLog);
}

function buildGroupedAutomationTranscriptLog(
  transcriptChunkLogList: DevLog[]
): TaskTimelineRenderableLog {
  const chronologicalChunkLogList = [...transcriptChunkLogList].sort(
    compareDevLogsByCreatedAt
  );
  const orderedTranscriptChunkLogList = [...transcriptChunkLogList].sort(
    compareAutomationTranscriptChunks
  );
  const firstChunkLog = chronologicalChunkLogList[0];
  const lastChunkLog =
    chronologicalChunkLogList[chronologicalChunkLogList.length - 1];
  const mergedTextContent = orderedTranscriptChunkLogList
    .map((transcriptChunkLog) => transcriptChunkLog.text_content || "")
    .filter((transcriptChunkTextContent) => transcriptChunkTextContent.length > 0)
    .join("\n");
  const mergedPhaseLabel =
    orderedTranscriptChunkLogList.find(
      (transcriptChunkLog) => transcriptChunkLog.automation_phase_label
    )?.automation_phase_label ?? firstChunkLog?.automation_phase_label ?? null;
  const mergedRunnerKind =
    orderedTranscriptChunkLogList.find(
      (transcriptChunkLog) => transcriptChunkLog.automation_runner_kind
    )?.automation_runner_kind ?? firstChunkLog?.automation_runner_kind ?? null;

  return {
    ...firstChunkLog,
    text_content: mergedTextContent,
    automation_phase_label: mergedPhaseLabel,
    automation_runner_kind: mergedRunnerKind,
    grouped_automation_transcript_chunk_count: orderedTranscriptChunkLogList.length,
    grouped_automation_transcript_started_at: firstChunkLog?.created_at ?? null,
    grouped_automation_transcript_ended_at: lastChunkLog?.created_at ?? null,
  };
}

export function buildTaskTimelineRenderableLogList(
  devLogList: DevLog[]
): TaskTimelineRenderableLog[] {
  const renderableLogList: TaskTimelineRenderableLog[] = [];
  let pendingTranscriptChunkLogList: DevLog[] = [];
  let activeAutomationSessionId: string | null = null;

  function flushPendingTranscriptChunkLogList(): void {
    if (pendingTranscriptChunkLogList.length === 0) {
      return;
    }

    renderableLogList.push(
      buildGroupedAutomationTranscriptLog(pendingTranscriptChunkLogList)
    );
    pendingTranscriptChunkLogList = [];
    activeAutomationSessionId = null;
  }

  for (const devLogItem of devLogList) {
    const automationSessionId = devLogItem.automation_session_id ?? null;
    if (!automationSessionId) {
      flushPendingTranscriptChunkLogList();
      renderableLogList.push(devLogItem);
      continue;
    }

    if (
      activeAutomationSessionId !== null &&
      activeAutomationSessionId !== automationSessionId
    ) {
      flushPendingTranscriptChunkLogList();
    }

    activeAutomationSessionId = automationSessionId;
    pendingTranscriptChunkLogList.push(devLogItem);
  }

  flushPendingTranscriptChunkLogList();
  return renderableLogList;
}

export function isGroupedAutomationTranscriptLog(
  taskTimelineLog: TaskTimelineRenderableLog
): boolean {
  return (
    (taskTimelineLog.grouped_automation_transcript_chunk_count ?? 0) > 0 &&
    Boolean(taskTimelineLog.automation_session_id)
  );
}
