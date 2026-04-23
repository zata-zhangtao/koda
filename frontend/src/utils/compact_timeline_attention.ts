import type { DevLog } from "../types/index.ts";
import { parseApiDate } from "./datetime.ts";

const ATTENTION_REQUIRED_PATTERN_LIST: RegExp[] = [
  /任务已进入：待修改（changes_requested）/i,
  /需要人工介入/u,
  /需要处理的阻塞性问题/u,
  /请人工阅读 transcript/i,
  /需要手动处理/u,
  /手动处理残留 worktree\/branch/i,
  /manual intervention/i,
  /needs attention/i,
];
const STALE_TIMELINE_UPDATE_THRESHOLD_MS = 5 * 60 * 1000;
const SUCCESS_REQUIRED_PATTERN_LIST: RegExp[] = [
  /AI 自检闭环完成/u,
  /AI 自检完成，未发现阻塞性问题/u,
  /post-review lint 闭环完成：pre-commit 已通过/i,
  /独立代码评审完成：未发现阻塞性问题/u,
  /Koda 已完成分支收尾并合并到 `main`/u,
  /需求验收通过，已标记为完成/u,
  /Requirement completed and moved into the completed archive\./i,
  /已记录人工确认完成/u,
];

type CompactTimelineAttentionLog = Pick<
  DevLog,
  "created_at" | "text_content" | "state_tag"
>;

function isTimelineLogStale(
  timelineLog: CompactTimelineAttentionLog,
  currentTimestampMs: number
): boolean {
  const parsedTimelineLogDate = parseApiDate(timelineLog.created_at);
  if (!parsedTimelineLogDate) {
    return false;
  }

  return currentTimestampMs - parsedTimelineLogDate.getTime() >= STALE_TIMELINE_UPDATE_THRESHOLD_MS;
}

export function logRequiresAttention(
  timelineLog: CompactTimelineAttentionLog
): boolean {
  const timelineTextContent = timelineLog.text_content || "";
  return ATTENTION_REQUIRED_PATTERN_LIST.some((attentionPattern) =>
    attentionPattern.test(timelineTextContent)
  );
}

export function groupRequiresAttention(
  timelineLogList: CompactTimelineAttentionLog[],
  currentTimestampMs: number = Date.now()
): boolean {
  if (timelineLogList.length === 0) {
    return false;
  }

  if (timelineLogList.some((timelineLog) => logRequiresAttention(timelineLog))) {
    return true;
  }

  let latestTimelineLog = timelineLogList[0];
  let latestTimelineLogTimestamp =
    parseApiDate(latestTimelineLog.created_at)?.getTime() ?? -Infinity;
  for (const candidateLog of timelineLogList.slice(1)) {
    const candidateLogTimestamp =
      parseApiDate(candidateLog.created_at)?.getTime() ?? -Infinity;
    if (candidateLogTimestamp > latestTimelineLogTimestamp) {
      latestTimelineLog = candidateLog;
      latestTimelineLogTimestamp = candidateLogTimestamp;
    }
  }

  return isTimelineLogStale(latestTimelineLog, currentTimestampMs);
}

export function logIndicatesSuccess(
  timelineLog: CompactTimelineAttentionLog
): boolean {
  const timelineTextContent = timelineLog.text_content || "";
  return SUCCESS_REQUIRED_PATTERN_LIST.some((successPattern) =>
    successPattern.test(timelineTextContent)
  );
}
