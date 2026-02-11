/** 编年史视图组件
 *
 * 显示任务编年史的完整生命周期
 */

import { useEffect, useState } from "react";
import { chronicleApi } from "../api/client";
import { LogCard } from "./LogCard";
import type { TaskChronicle } from "../types";

interface ChronicleViewProps {
  taskId: string;
}

export function ChronicleView({ taskId }: ChronicleViewProps) {
  const [chronicle, setChronicle] = useState<TaskChronicle | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadChronicle();
  }, [taskId]);

  const loadChronicle = async () => {
    try {
      setLoading(true);
      const data = await chronicleApi.getTaskChronicle(taskId);
      setChronicle(data);
    } catch (error) {
      console.error("Failed to load chronicle:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleExport = async () => {
    try {
      const response = await chronicleApi.exportMarkdown({ task_id: taskId });
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `chronicle-${taskId.slice(0, 8)}.md`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (error) {
      console.error("Failed to export:", error);
    }
  };

  if (loading) {
    return (
      <div style={styles.loading}>
        <p>Loading chronicle...</p>
      </div>
    );
  }

  if (!chronicle) {
    return (
      <div style={styles.error}>
        <p>Failed to load chronicle</p>
      </div>
    );
  }

  const { task, logs, stats } = chronicle;
  const duration = calculateDuration(task.created_at, task.closed_at);

  return (
    <div style={styles.container}>
      {/* 任务头部 */}
      <div style={styles.header}>
        <h2 style={styles.title}>{task.title}</h2>
        <div style={styles.meta}>
          <span style={styles.status}>{task.status}</span>
          <span style={styles.duration}>{duration}</span>
        </div>
        <div style={styles.stats}>
          <span>📊 {stats.total_logs} logs</span>
          <span>🐛 {stats.bug_count} bugs</span>
          <span>✅ {stats.fix_count} fixes</span>
        </div>
        <button style={styles.exportBtn} onClick={handleExport}>
          Export Markdown
        </button>
      </div>

      {/* 日志流 */}
      <div style={styles.logs}>
        {logs.length === 0 ? (
          <p style={styles.empty}>No logs in this task yet</p>
        ) : (
          logs.map((log) => <LogCard key={log.id} log={log} />)
        )}
      </div>
    </div>
  );
}

function calculateDuration(start: string, end: string | null): string {
  const startDate = new Date(start);
  const endDate = end ? new Date(end) : new Date();
  const diff = endDate.getTime() - startDate.getTime();

  const days = Math.floor(diff / (1000 * 60 * 60 * 24));
  const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
  const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));

  if (days > 0) {
    return `${days}d ${hours}h`;
  }
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  return `${minutes}m`;
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
  },
  loading: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    height: "100%",
    color: "#a0a0a0",
  },
  error: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    height: "100%",
    color: "#f56565",
  },
  header: {
    padding: "20px",
    backgroundColor: "#16213e",
    borderBottom: "1px solid #2d3748",
  },
  title: {
    margin: "0 0 12px 0",
    fontSize: "20px",
    fontWeight: 600,
  },
  meta: {
    display: "flex",
    gap: "12px",
    marginBottom: "12px",
  },
  status: {
    padding: "4px 12px",
    backgroundColor: "#0f3460",
    borderRadius: "4px",
    fontSize: "12px",
    textTransform: "uppercase",
  },
  duration: {
    padding: "4px 12px",
    backgroundColor: "#533483",
    borderRadius: "4px",
    fontSize: "12px",
  },
  stats: {
    display: "flex",
    gap: "16px",
    fontSize: "13px",
    color: "#a0a0a0",
    marginBottom: "16px",
  },
  exportBtn: {
    padding: "8px 16px",
    backgroundColor: "#e94560",
    color: "white",
    border: "none",
    borderRadius: "6px",
    cursor: "pointer",
    fontSize: "13px",
  },
  logs: {
    flex: 1,
    overflow: "auto",
    padding: "20px",
    display: "flex",
    flexDirection: "column",
    gap: "12px",
  },
  empty: {
    textAlign: "center",
    color: "#a0a0a0",
    padding: "40px",
  },
};
