import type { DevLog } from "../types/index.ts";

const COMPLETION_FAILURE_LOG_MARKER = "❌ Koda 未能完成分支收尾与合并：";

export function hasRetryableCompletionFailure(taskDevLogList: DevLog[]): boolean {
  for (let index = taskDevLogList.length - 1; index >= 0; index -= 1) {
    const taskDevLog = taskDevLogList[index];
    if (taskDevLog.state_tag !== "BUG") {
      continue;
    }

    return taskDevLog.text_content.includes(COMPLETION_FAILURE_LOG_MARKER);
  }

  return false;
}
