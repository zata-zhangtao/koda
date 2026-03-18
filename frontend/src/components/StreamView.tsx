/** 日志流视图组件
 *
 * 显示时间线或任务视图中的日志列表
 */

import { LogCard } from "./LogCard";
import type { DevLog } from "../types";
import { formatDateGroupLabel, groupItemsByAppDate } from "../utils/datetime";

interface StreamViewProps {
  logs: DevLog[];
  view: "timeline" | "task";
}

export function StreamView({ logs, view }: StreamViewProps) {
  if (logs.length === 0) {
    return (
      <div style={styles.emptyState}>
        <p>No logs yet</p>
        <p style={styles.hint}>Start logging your development flow...</p>
      </div>
    );
  }

  // 时间线视图按日期分组
  if (view === "timeline") {
    const groupedLogs = groupLogsByDate(logs);
    return (
      <div style={styles.container}>
        {groupedLogs.map(([date, dateLogs]) => (
          <div key={date} style={styles.dateGroup}>
            <div style={styles.dateHeader}>{formatDate(date)}</div>
            <div style={styles.logsContainer}>
              {dateLogs.map((log) => (
                <LogCard key={log.id} log={log} />
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  // 任务视图直接显示
  return (
    <div style={styles.container}>
      {logs.map((log) => (
        <LogCard key={log.id} log={log} />
      ))}
    </div>
  );
}

function groupLogsByDate(logs: DevLog[]): [string, DevLog[]][] {
  return groupItemsByAppDate(logs, (log) => log.created_at);
}

function formatDate(dateStr: string): string {
  return formatDateGroupLabel(dateStr);
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: "flex",
    flexDirection: "column",
    gap: "12px",
  },
  emptyState: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    height: "100%",
    color: "#a0a0a0",
  },
  hint: {
    marginTop: "8px",
    fontSize: "14px",
  },
  dateGroup: {
    marginBottom: "20px",
  },
  dateHeader: {
    fontSize: "14px",
    fontWeight: 600,
    color: "#a0a0a0",
    padding: "8px 0",
    borderBottom: "1px solid #2d3748",
    marginBottom: "12px",
  },
  logsContainer: {
    display: "flex",
    flexDirection: "column",
    gap: "12px",
  },
};
