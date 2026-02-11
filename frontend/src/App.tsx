/** 主应用组件
 *
 * 3 栏布局：Sidebar | Stream | Input
 */

import { useCallback, useEffect, useState } from "react";
import { InputBox } from "./components/InputBox";
import { LogCard } from "./components/LogCard";
import { Sidebar } from "./components/Sidebar";
import { logApi, mediaApi, runAccountApi, taskApi } from "./api/client";
import type { DevLog, RunAccount, Task } from "./types";

function App() {
  const [runAccount, setRunAccount] = useState<RunAccount | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [logs, setLogs] = useState<DevLog[]>([]);
  const [activeTask, setActiveTask] = useState<Task | null>(null);
  const [view, setView] = useState<"timeline" | "task">("timeline");

  // 加载数据
  const loadData = useCallback(async () => {
    try {
      const account = await runAccountApi.getCurrent();

      const [taskListResult, logListResult] = await Promise.allSettled([
        taskApi.list(),
        logApi.list(),
      ]);

      const taskList = taskListResult.status === "fulfilled" ? taskListResult.value : [];
      const logList = logListResult.status === "fulfilled" ? logListResult.value : [];

      if (taskListResult.status === "rejected") {
        console.error("Failed to load tasks:", taskListResult.reason);
      }

      if (logListResult.status === "rejected") {
        console.error("Failed to load logs:", logListResult.reason);
      }

      setRunAccount(account);
      setTasks(taskList);
      setLogs(logList);

      // 设置活跃任务
      const openTask = taskList.find((t) => t.lifecycle_status === "OPEN");
      setActiveTask(openTask || null);
    } catch (error) {
      console.error("Failed to load data:", error);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // 处理日志提交
  const handleLogSubmit = async (text: string) => {
    try {
      await logApi.createWithCommand(text);
      await loadData();
    } catch (error) {
      console.error("Failed to submit log:", error);
    }
  };

  // 处理图片上传
  const handleImageUpload = async (file: File, text: string) => {
    try {
      await mediaApi.uploadImage(file, text);
      await loadData();
    } catch (error) {
      console.error("Failed to upload image:", error);
    }
  };

  // 处理任务切换
  const handleTaskSelect = async (taskId: string) => {
    const task = tasks.find((t) => t.id === taskId);
    if (task) {
      setActiveTask(task);
      setView("task");
      try {
        const taskLogs = await logApi.list(taskId);
        setLogs(taskLogs);
      } catch (error) {
        console.error("Failed to load task logs:", error);
      }
    }
  };

  // 处理创建任务
  const handleCreateTask = async (title: string) => {
    try {
      await taskApi.create({ task_title: title });
      await loadData();
    } catch (error) {
      console.error("Failed to create task:", error);
    }
  };

  // 处理任务状态更新
  const handleTaskStatusChange = async (taskId: string, status: string) => {
    try {
      await taskApi.updateStatus(taskId, status);
      await loadData();
    } catch (error) {
      console.error("Failed to update task status:", error);
    }
  };

  return (
    <div style={styles.container}>
      {/* 左侧边栏 */}
      <Sidebar
        runAccount={runAccount}
        tasks={tasks}
        activeTask={activeTask}
        onTaskSelect={handleTaskSelect}
        onCreateTask={handleCreateTask}
        onTaskStatusChange={handleTaskStatusChange}
        reviewQueueCount={0} // Phase 2: 从 API 获取
      />

      {/* 中间主区域 */}
      <div style={styles.main}>
        {/* 顶部工具栏 */}
        <div style={styles.toolbar}>
          <div style={styles.viewToggle}>
            <button
              style={{
                ...styles.viewButton,
                ...(view === "timeline" ? styles.viewButtonActive : {}),
              }}
              onClick={() => {
                setView("timeline");
                loadData();
              }}
            >
              Timeline
            </button>
            <button
              style={{
                ...styles.viewButton,
                ...(view === "task" ? styles.viewButtonActive : {}),
              }}
              onClick={() => setView("task")}
              disabled={!activeTask}
            >
              Task View
            </button>
          </div>
          {activeTask && (
            <div style={styles.activeTaskInfo}>
              <span style={styles.taskLabel}>当前任务:</span>
              <span style={styles.taskName}>{activeTask.task_title}</span>
              <span
                style={{
                  ...styles.taskStatus,
                  ...getStatusStyle(activeTask.lifecycle_status),
                }}
              >
                {activeTask.lifecycle_status}
              </span>
            </div>
          )}
        </div>

        {/* 日志流 */}
        <div style={styles.stream}>
          {logs.length === 0 ? (
            <div style={styles.emptyState}>
              <p>还没有日志记录</p>
              <p style={styles.emptyHint}>在下方输入框开始记录你的开发流程...</p>
            </div>
          ) : (
            logs.map((log) => <LogCard key={log.id} log={log} />)
          )}
        </div>

        {/* 底部输入框 */}
        <InputBox
          onSubmit={handleLogSubmit}
          onImageUpload={handleImageUpload}
          activeTask={activeTask}
        />
      </div>
    </div>
  );
}

function getStatusStyle(status: string): React.CSSProperties {
  switch (status) {
    case "OPEN":
      return { backgroundColor: "#48bb78", color: "white" };
    case "CLOSED":
      return { backgroundColor: "#a0a0a0", color: "white" };
    case "PENDING":
      return { backgroundColor: "#ed8936", color: "white" };
    default:
      return {};
  }
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: "flex",
    height: "100vh",
    overflow: "hidden",
  },
  main: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  },
  toolbar: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "12px 20px",
    borderBottom: "1px solid #2d3748",
    backgroundColor: "#16213e",
  },
  viewToggle: {
    display: "flex",
    gap: "8px",
  },
  viewButton: {
    padding: "6px 16px",
    borderRadius: "6px",
    border: "1px solid #2d3748",
    backgroundColor: "#1a1a2e",
    color: "#eaeaea",
    cursor: "pointer",
    fontSize: "14px",
  },
  viewButtonActive: {
    backgroundColor: "#e94560",
    borderColor: "#e94560",
  },
  activeTaskInfo: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    fontSize: "14px",
  },
  taskLabel: {
    color: "#a0a0a0",
  },
  taskName: {
    color: "#eaeaea",
    fontWeight: 500,
  },
  taskStatus: {
    padding: "2px 8px",
    borderRadius: "4px",
    fontSize: "12px",
    textTransform: "uppercase",
  },
  stream: {
    flex: 1,
    overflow: "auto",
    padding: "20px",
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
  emptyHint: {
    marginTop: "8px",
    fontSize: "14px",
  },
};

export default App;
