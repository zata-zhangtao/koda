/** 日志流视图组件
 *
 * 显示时间线或任务视图中的日志列表
 */

import { LogCard } from "./LogCard";
import type { DevLog } from "../types";

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
  const groups = new Map<string, DevLog[]>();

  for (const log of logs) {
    const date = log.created_at.split("T")[0];
    if (!groups.has(date)) {
      groups.set(date, []);
    }
    groups.get(date)!.push(log);
  }

  return Array.from(groups.entries()).sort(
    (a, b) => new Date(b[0]).getTime() - new Date(a[0]).getTime()
  );
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  if (dateStr === today.toISOString().split("T")[0]) {
    return "Today";
  }
  if (dateStr === yesterday.toISOString().split("T")[0]) {
    return "Yesterday";
  }

  return date.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long",
  });
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
