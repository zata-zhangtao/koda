/** 侧边栏组件
 *
 * 显示 RunAccount 信息、任务列表和待校正队列
 */

import type { RunAccount, Task } from "../types";

interface SidebarProps {
  runAccount: RunAccount | null;
  tasks: Task[];
  activeTask: Task | null;
  onTaskSelect: (taskId: string) => void;
  onCreateTask: (title: string) => void;
  onTaskStatusChange: (taskId: string, status: string) => void;
  reviewQueueCount: number;
  onOpenEmailSettings: () => void;
}

export function Sidebar({
  runAccount,
  tasks,
  activeTask,
  onTaskSelect,
  onCreateTask,
  onTaskStatusChange,
  reviewQueueCount,
  onOpenEmailSettings,
}: SidebarProps) {
  const handleCreateTask = () => {
    const title = prompt("Enter task title:");
    if (title?.trim()) {
      onCreateTask(title.trim());
    }
  };

  const openTasks = tasks.filter((t) => t.lifecycle_status === "OPEN");
  const closedTasks = tasks.filter((t) => t.lifecycle_status === "CLOSED");

  return (
    <aside style={styles.container}>
      {/* RunAccount 信息 */}
      <div style={styles.accountSection}>
        <h3 style={styles.sectionTitle}>Run Account</h3>
        {runAccount ? (
          <div style={styles.accountCard}>
            <div style={styles.accountName}>{runAccount.account_display_name}</div>
            <div style={styles.accountMeta}>
              {runAccount.user_name} • {runAccount.environment_os}
            </div>
            {runAccount.git_branch_name && (
              <div style={styles.branchTag}>🌿 {runAccount.git_branch_name}</div>
            )}
          </div>
        ) : (
          <div style={styles.loadingText}>Loading...</div>
        )}
      </div>

      {/* 任务列表 */}
      <div style={styles.tasksSection}>
        <div style={styles.tasksHeader}>
          <h3 style={styles.sectionTitle}>Tasks</h3>
          <button style={styles.addButton} onClick={handleCreateTask}>
            +
          </button>
        </div>

        {/* 活跃任务 */}
        <div style={styles.taskGroup}>
          <span style={styles.taskGroupLabel}>Open</span>
          {openTasks.length === 0 ? (
            <div style={styles.emptyTasks}>No open tasks</div>
          ) : (
            openTasks.map((task) => (
              <TaskItem
                key={task.id}
                task={task}
                isActive={activeTask?.id === task.id}
                onClick={() => onTaskSelect(task.id)}
                onClose={() => onTaskStatusChange(task.id, "CLOSED")}
              />
            ))
          )}
        </div>

        {/* 已关闭任务 */}
        {closedTasks.length > 0 && (
          <div style={styles.taskGroup}>
            <span style={styles.taskGroupLabel}>Closed</span>
            {closedTasks.slice(0, 5).map((task) => (
              <TaskItem
                key={task.id}
                task={task}
                isActive={activeTask?.id === task.id}
                onClick={() => onTaskSelect(task.id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* 待校正队列 (Phase 2) */}
      <div style={styles.reviewSection}>
        <div style={styles.reviewHeader}>
          <h3 style={styles.sectionTitle}>Review Queue</h3>
          {reviewQueueCount > 0 && (
            <span style={styles.reviewBadge}>{reviewQueueCount}</span>
          )}
        </div>
        {reviewQueueCount === 0 && (
          <div style={styles.emptyReview}>No pending reviews</div>
        )}
      </div>

      {/* 底部设置按钮 */}
      <div style={styles.settingsSection}>
        <button style={styles.settingsButton} onClick={onOpenEmailSettings} title="Email notification settings">
          📧 Email Notifications
        </button>
      </div>
    </aside>
  );
}

interface TaskItemProps {
  task: Task;
  isActive: boolean;
  onClick: () => void;
  onClose?: () => void;
}

function TaskItem({ task, isActive, onClick, onClose }: TaskItemProps) {
  return (
    <div
      style={{
        ...styles.taskItem,
        ...(isActive ? styles.taskItemActive : {}),
      }}
      onClick={onClick}
    >
      <div style={styles.taskTitle}>{task.task_title}</div>
      <div style={styles.taskMeta}>
        <span>{task.log_count} logs</span>
        {onClose && (
          <button
            style={styles.closeTaskBtn}
            onClick={(e) => {
              e.stopPropagation();
              if (confirm("Close this task?")) {
                onClose();
              }
            }}
            title="Close task"
          >
            ✓
          </button>
        )}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    width: "280px",
    minWidth: "280px",
    backgroundColor: "#16213e",
    borderRight: "1px solid #2d3748",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  },
  accountSection: {
    padding: "16px",
    borderBottom: "1px solid #2d3748",
  },
  sectionTitle: {
    fontSize: "12px",
    textTransform: "uppercase",
    letterSpacing: "0.5px",
    color: "#a0a0a0",
    marginBottom: "12px",
  },
  accountCard: {
    backgroundColor: "#1a1a2e",
    padding: "12px",
    borderRadius: "8px",
    border: "1px solid #2d3748",
  },
  accountName: {
    fontWeight: 600,
    fontSize: "14px",
    marginBottom: "4px",
  },
  accountMeta: {
    fontSize: "12px",
    color: "#a0a0a0",
  },
  branchTag: {
    fontSize: "11px",
    color: "#48bb78",
    marginTop: "4px",
  },
  loadingText: {
    fontSize: "14px",
    color: "#a0a0a0",
  },
  tasksSection: {
    flex: 1,
    padding: "16px",
    overflow: "auto",
  },
  tasksHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "12px",
  },
  addButton: {
    width: "24px",
    height: "24px",
    borderRadius: "4px",
    border: "none",
    backgroundColor: "#e94560",
    color: "white",
    fontSize: "18px",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  taskGroup: {
    marginBottom: "16px",
  },
  taskGroupLabel: {
    fontSize: "11px",
    color: "#a0a0a0",
    textTransform: "uppercase",
    letterSpacing: "0.5px",
    marginBottom: "8px",
    display: "block",
  },
  emptyTasks: {
    fontSize: "13px",
    color: "#666",
    padding: "8px 0",
  },
  taskItem: {
    padding: "10px 12px",
    backgroundColor: "#1a1a2e",
    borderRadius: "6px",
    marginBottom: "6px",
    cursor: "pointer",
    border: "1px solid transparent",
    transition: "all 0.2s",
  },
  taskItemActive: {
    borderColor: "#e94560",
    backgroundColor: "#2d1f2f",
  },
  taskTitle: {
    fontSize: "13px",
    fontWeight: 500,
    marginBottom: "4px",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  taskMeta: {
    fontSize: "11px",
    color: "#a0a0a0",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  closeTaskBtn: {
    background: "none",
    border: "none",
    color: "#48bb78",
    cursor: "pointer",
    fontSize: "14px",
    padding: "0 4px",
  },
  reviewSection: {
    padding: "16px",
    borderTop: "1px solid #2d3748",
  },
  reviewHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  reviewBadge: {
    backgroundColor: "#e94560",
    color: "white",
    fontSize: "11px",
    padding: "2px 8px",
    borderRadius: "10px",
    fontWeight: 600,
  },
  emptyReview: {
    fontSize: "13px",
    color: "#666",
    padding: "8px 0",
  },
  settingsSection: {
    padding: "12px 16px",
    borderTop: "1px solid #2d3748",
  },
  settingsButton: {
    width: "100%",
    padding: "8px 12px",
    backgroundColor: "transparent",
    border: "1px solid #2d3748",
    borderRadius: "6px",
    color: "#a0a0a0",
    fontSize: "12px",
    cursor: "pointer",
    textAlign: "left" as const,
  },
};
