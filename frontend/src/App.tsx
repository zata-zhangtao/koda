/** 主应用组件
 *
 * 将现有任务/日志数据映射为参考稿风格的 AI DEVFLOW 仪表盘。
 */

import type {
  ChangeEvent,
  ClipboardEvent,
  KeyboardEvent,
  ReactNode,
  SVGProps,
} from "react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  appConfigApi,
  logApi,
  mediaApi,
  projectApi,
  runAccountApi,
  taskApi,
} from "./api/client";
import { SettingsModal } from "./components/SettingsModal";
import {
  configureAppTimezone,
  formatDateTime,
  formatHourMinute,
  formatMonthDay,
  toTimestampValue,
} from "./utils/datetime";
import {
  AIProcessingStatus,
  DevLogStateTag,
  TaskLifecycleStatus,
  WorkflowStage,
  type DevLog,
  type Project,
  type RunAccount,
  type Task,
} from "./types";

type RequirementStage = WorkflowStage;

type TimelineKind = "ai_log" | "human_review" | "system_event";
type ConversationTurnKind = "human" | "ai";

interface ConversationTurn {
  turnId: string;
  kind: ConversationTurnKind;
  authorName: string;
  timeLabel: string;
  items: TimelineViewModel[];
}
type WorkspaceView = "active" | "completed" | "changes";
type AttachmentKind = "image" | "file";

interface RequirementViewModel {
  task: Task;
  description: string;
  stage: RequirementStage;
  createdLabel: string;
}

interface TimelineViewModel {
  log: DevLog;
  kind: TimelineKind;
  authorName: string;
  timeLabel: string;
}

interface RequirementSnapshot {
  summary: string;
  title: string | null;
  changeKind: "update" | "delete" | null;
}

interface AttachmentDraft {
  file: File;
  kind: AttachmentKind;
  previewUrl: string | null;
}

type MutationName =
  | "create"
  | "start"
  | "confirm"
  | "execute"
  | "accept"
  | "request_changes"
  | "feedback"
  | "update"
  | "complete"
  | "delete"
  | "open_trae"
  | "open_terminal"
  | "cancel"
  | null;

const GUEST_USER_LABEL = "Guest User";
const REQUIREMENT_UPDATE_MARKER = "<!-- requirement-change:update -->";
const REQUIREMENT_DELETE_MARKER = "<!-- requirement-change:delete -->";

const CONTINUE_COMMAND_PATTERNS = [
  /^go\s+on$/i,
  /^continue$/i,
  /^继续$/,
  /^继续执行$/,
  /^retry$/i,
  /^重试$/,
  /^proceed$/i,
  /^go$/i,
  /^resume$/i,
];

function _isContinueCommand(text: string): boolean {
  const trimmed = text.trim();
  return CONTINUE_COMMAND_PATTERNS.some((pattern) => pattern.test(trimmed));
}

function App() {
  const attachmentInputRef = useRef<HTMLInputElement | null>(null);
  const aiTurnBodyElementByTurnIdRef = useRef<Record<string, HTMLDivElement | null>>({});
  const previousExpandedTurnIdSetRef = useRef<Set<string>>(new Set());

  const [currentRunAccount, setCurrentRunAccount] = useState<RunAccount | null>(null);
  const [taskList, setTaskList] = useState<Task[]>([]);
  const [allDevLogList, setAllDevLogList] = useState<DevLog[]>([]);
  const [selectedTaskLogList, setSelectedTaskLogList] = useState<DevLog[]>([]);
  const [projectList, setProjectList] = useState<Project[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [workspaceView, setWorkspaceView] = useState<WorkspaceView>("active");
  const [isCreatePanelOpen, setIsCreatePanelOpen] = useState(false);
  const [isEditPanelOpen, setIsEditPanelOpen] = useState(false);
  const [newRequirementTitle, setNewRequirementTitle] = useState("");
  const [newRequirementDescription, setNewRequirementDescription] = useState("");
  const [newRequirementProjectId, setNewRequirementProjectId] = useState<string | null>(null);
  const [editRequirementTitle, setEditRequirementTitle] = useState("");
  const [editRequirementDescription, setEditRequirementDescription] = useState("");
  const [feedbackInputText, setFeedbackInputText] = useState("");
  const [feedbackAttachmentDraft, setFeedbackAttachmentDraft] =
    useState<AttachmentDraft | null>(null);
  const [activeMutationName, setActiveMutationName] = useState<MutationName>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isDashboardLoading, setIsDashboardLoading] = useState(true);
  const [prdFileContent, setPrdFileContent] = useState<string | null>(null);
  const [isProjectPanelOpen, setIsProjectPanelOpen] = useState(false);
  const [expandedTurnIdSet, setExpandedTurnIdSet] = useState<Set<string>>(new Set());
  const [, setAppTimezoneRevision] = useState(0);
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectPath, setNewProjectPath] = useState("");
  const [newProjectDescription, setNewProjectDescription] = useState("");
  const [editingProjectId, setEditingProjectId] = useState<string | null>(null);
  const [editingProjectName, setEditingProjectName] = useState("");
  const [editingProjectPath, setEditingProjectPath] = useState("");
  const [editingProjectDescription, setEditingProjectDescription] = useState("");
  const [isEmailSettingsOpen, setIsEmailSettingsOpen] = useState(false);

  function resetCreateRequirementDraft(nextProjectId: string | null = null): void {
    setNewRequirementTitle("");
    setNewRequirementDescription("");
    setNewRequirementProjectId(nextProjectId);
  }

  function openCreateRequirementPanel(): void {
    resetCreateRequirementDraft();
    setIsCreatePanelOpen(true);
    setErrorMessage(null);
    setSuccessMessage(null);
  }

  function closeCreateRequirementPanel(): void {
    setIsCreatePanelOpen(false);
    resetCreateRequirementDraft();
    setErrorMessage(null);
    setSuccessMessage(null);
  }

  useEffect(() => {
    void initializeDashboard();
  }, []);

  useEffect(() => {
    return () => {
      if (feedbackAttachmentDraft?.previewUrl) {
        URL.revokeObjectURL(feedbackAttachmentDraft.previewUrl);
      }
    };
  }, [feedbackAttachmentDraft]);

  useEffect(() => {
    if (
      newRequirementProjectId &&
      !projectList.some(
        (projectItem) =>
          projectItem.id === newRequirementProjectId &&
          isProjectSelectable(projectItem)
      )
    ) {
      setNewRequirementProjectId(null);
    }
  }, [newRequirementProjectId, projectList]);

  useEffect(() => {
    if (
      editingProjectId &&
      !projectList.some((projectItem) => projectItem.id === editingProjectId)
    ) {
      resetProjectEditDraft();
    }
  }, [editingProjectId, projectList]);

  const devLogsByTaskId = buildDevLogsByTaskId(allDevLogList);
  const activeTaskList = taskList.filter(
    (taskItem) =>
      taskItem.lifecycle_status !== TaskLifecycleStatus.CLOSED &&
      taskItem.lifecycle_status !== TaskLifecycleStatus.DELETED &&
      !hasRequirementUpdateLog(devLogsByTaskId[taskItem.id] ?? [])
  );
  const completedTaskList = taskList.filter(
    (taskItem) => taskItem.lifecycle_status === TaskLifecycleStatus.CLOSED
  );
  const changedTaskList = taskList.filter((taskItem) => {
    const taskDevLogList = devLogsByTaskId[taskItem.id] ?? [];
    return (
      taskItem.lifecycle_status === TaskLifecycleStatus.DELETED ||
      (taskItem.lifecycle_status !== TaskLifecycleStatus.CLOSED &&
        hasRequirementUpdateLog(taskDevLogList))
    );
  });
  const visibleTaskList =
    workspaceView === "active"
      ? activeTaskList
      : workspaceView === "completed"
        ? completedTaskList
        : changedTaskList;
  const visibleTaskIds = visibleTaskList.map((taskItem) => taskItem.id).join(",");
  // Primary: find in current workspace view.
  // Fallback: find in full task list so the timeline never disappears when a task
  // transitions to a different workspace view (e.g. CLOSED → completed tab).
  const selectedTask =
    visibleTaskList.find((taskItem) => taskItem.id === selectedTaskId) ??
    (selectedTaskId
      ? taskList.find((taskItem) => taskItem.id === selectedTaskId) ?? null
      : null);
  const selectedTaskDevLogs = selectedTask
    ? (selectedTaskLogList.length > 0
        ? selectedTaskLogList
        : devLogsByTaskId[selectedTask.id] ?? [])
    : [];
  const selectedTaskSnapshot = selectedTask
    ? deriveRequirementSnapshot(selectedTask, selectedTaskDevLogs)
    : null;
  const hasProjectConsistencyIssues = projectList.some(
    (projectItem) =>
      !isProjectSelectable(projectItem) ||
      projectItem.is_repo_head_consistent === false
  );
  const requirementViewModelList = visibleTaskList.map((taskItem) =>
    buildRequirementViewModel(taskItem, devLogsByTaskId[taskItem.id] ?? [])
  );
  const selectedTimelineItemList = selectedTask
    ? selectedTaskDevLogs.map((devLogItem) =>
        buildTimelineViewModel(devLogItem, currentRunAccount)
      )
    : [];
  const selectedTaskStage = selectedTask
    ? deriveRequirementStage(selectedTask, selectedTaskDevLogs)
    : null;
  const conversationTurnList = groupTimelineIntoConversationTurns(selectedTimelineItemList);
  const latestAiConversationTurn =
    [...conversationTurnList].reverse().find((turnItem) => turnItem.kind === "ai") ?? null;
  const lastAiTurnId = latestAiConversationTurn?.turnId ?? null;
  const latestAiTurnLastItemId =
    latestAiConversationTurn && latestAiConversationTurn.items.length > 0
      ? latestAiConversationTurn.items[latestAiConversationTurn.items.length - 1].log.id
      : null;
  const selectedTaskDocumentMarkdown = selectedTask
    ? buildTaskDocumentMarkdown(
        selectedTask,
        selectedTaskDevLogs,
        currentRunAccount
      )
    : "";
  const currentUserLabel =
    currentRunAccount?.account_display_name || GUEST_USER_LABEL;
  const canCreateRequirements = workspaceView === "active";
  const canEditSelectedTask = selectedTask
    ? selectedTask.lifecycle_status !== TaskLifecycleStatus.CLOSED &&
      selectedTask.lifecycle_status !== TaskLifecycleStatus.DELETED
    : false;
  const canSendFeedback = selectedTask
    ? selectedTask.lifecycle_status !== TaskLifecycleStatus.CLOSED &&
      selectedTask.lifecycle_status !== TaskLifecycleStatus.DELETED
    : false;
  const hasFeedbackPayload =
    Boolean(feedbackInputText.trim()) || feedbackAttachmentDraft !== null;

  // 自动轮询：codex 实际运行的阶段（PRD 生成 + 编码执行等）
  const activeExecutionStageSet = new Set<WorkflowStage>([
    WorkflowStage.PRD_GENERATING,
    WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
    WorkflowStage.SELF_REVIEW_IN_PROGRESS,
    WorkflowStage.TEST_IN_PROGRESS,
    WorkflowStage.PR_PREPARING,
  ]);
  const isSelectedTaskInActiveExecution =
    selectedTaskStage !== null && activeExecutionStageSet.has(selectedTaskStage);

  useEffect(() => {
    if (!isSelectedTaskInActiveExecution) {
      return;
    }
    const pollingIntervalId = window.setInterval(() => {
      void loadDashboardData(true);
    }, 1000);
    return () => {
      window.clearInterval(pollingIntervalId);
    };
  }, [isSelectedTaskInActiveExecution]);

  useEffect(() => {
    if (visibleTaskList.length === 0) {
      setSelectedTaskId(null);
      return;
    }

    setSelectedTaskId((previousSelectedTaskId) => {
      if (
        previousSelectedTaskId &&
        visibleTaskList.some((taskItem) => taskItem.id === previousSelectedTaskId)
      ) {
        return previousSelectedTaskId;
      }

      return visibleTaskList[0].id;
    });
  }, [workspaceView, visibleTaskIds, visibleTaskList]);

  // Auto-switch workspace view when the selected task moves out of the current view
  // (e.g. task completes its git ops and lifecycle_status becomes CLOSED while the
  // user is still on the "active" tab).
  useEffect(() => {
    if (!selectedTaskId) return;
    if (visibleTaskIds.includes(selectedTaskId)) return;

    const missingTask = taskList.find((t) => t.id === selectedTaskId);
    if (!missingTask) return;

    if (missingTask.lifecycle_status === TaskLifecycleStatus.CLOSED) {
      setWorkspaceView("completed");
    } else if (missingTask.lifecycle_status === TaskLifecycleStatus.DELETED) {
      setWorkspaceView("changes");
    }
  }, [selectedTaskId, visibleTaskIds, taskList]);

  useEffect(() => {
    setIsCreatePanelOpen(false);
    resetCreateRequirementDraft();
    setIsEditPanelOpen(false);
    setFeedbackInputText("");
    setFeedbackAttachmentDraft(null);
    setSuccessMessage(null);
    setErrorMessage(null);
    setPrdFileContent(null);
    setExpandedTurnIdSet(new Set());
    setSelectedTaskLogList([]);
  }, [workspaceView, selectedTaskId]);

  // 自动展开最新 AI 消息卡片
  useEffect(() => {
    if (!lastAiTurnId) return;
    setExpandedTurnIdSet((prev) => {
      if (prev.has(lastAiTurnId)) return prev;
      const next = new Set(prev);
      next.add(lastAiTurnId);
      return next;
    });
  }, [lastAiTurnId]);

  useLayoutEffect(() => {
    const previousExpandedTurnIdSet = previousExpandedTurnIdSetRef.current;

    expandedTurnIdSet.forEach((expandedTurnId) => {
      if (previousExpandedTurnIdSet.has(expandedTurnId)) {
        return;
      }

      const expandedAiTurnBodyElement =
        aiTurnBodyElementByTurnIdRef.current[expandedTurnId];
      if (!expandedAiTurnBodyElement) {
        return;
      }

      expandedAiTurnBodyElement.scrollTop = expandedAiTurnBodyElement.scrollHeight;
    });

    previousExpandedTurnIdSetRef.current = new Set(expandedTurnIdSet);
  }, [expandedTurnIdSet]);

  useLayoutEffect(() => {
    if (!lastAiTurnId || !latestAiTurnLastItemId || !expandedTurnIdSet.has(lastAiTurnId)) {
      return;
    }

    const latestAiTurnBodyElement = aiTurnBodyElementByTurnIdRef.current[lastAiTurnId];
    if (!latestAiTurnBodyElement) {
      return;
    }

    latestAiTurnBodyElement.scrollTop = latestAiTurnBodyElement.scrollHeight;
  }, [expandedTurnIdSet, lastAiTurnId, latestAiTurnLastItemId]);

  // 当选中任务有 worktree 且处于 PRD 相关阶段时，轮询 PRD 文件内容
  const prdRelevantStageSet = new Set<WorkflowStage>([
    // PRD_GENERATING 不在这里：生成中阶段强制显示 banner，不读旧文件
    WorkflowStage.PRD_WAITING_CONFIRMATION,
    WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
    WorkflowStage.SELF_REVIEW_IN_PROGRESS,
    WorkflowStage.TEST_IN_PROGRESS,
    WorkflowStage.PR_PREPARING,
    WorkflowStage.ACCEPTANCE_IN_PROGRESS,
    WorkflowStage.CHANGES_REQUESTED,
  ]);

  // 仅在切换任务时清空 PRD 内容，避免 taskList 每秒刷新触发闪烁
  useEffect(() => {
    setPrdFileContent(null);
  }, [selectedTaskId]);

  // 按任务拉取完整日志列表，避免全局 100 条限制导致时间线空白
  useEffect(() => {
    if (!selectedTaskId) {
      setSelectedTaskLogList([]);
      return;
    }
    let cancelled = false;
    const fetch = () => {
      logApi.list(selectedTaskId, 2000).then((logs) => {
        if (!cancelled) setSelectedTaskLogList(sortDevLogListByCreatedAt(logs));
      }).catch(() => {});
    };
    fetch();
    const pollId = window.setInterval(fetch, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(pollId);
    };
  }, [selectedTaskId]);

  // PRD 轮询：依赖稳定的派生值而非整个 taskList，防止每秒重置 interval
  const _prdPollTask = taskList.find((t) => t.id === selectedTaskId);
  const _prdWorktreePath = _prdPollTask?.worktree_path ?? null;
  const _prdPollStage = _prdPollTask
    ? deriveRequirementStage(_prdPollTask, devLogsByTaskId[_prdPollTask.id] ?? [])
    : null;
  const _prdPollActive =
    _prdWorktreePath !== null &&
    _prdPollStage !== null &&
    prdRelevantStageSet.has(_prdPollStage);

  useEffect(() => {
    if (!selectedTaskId || !_prdPollActive) return;

    const loadPrd = () => {
      taskApi
        .getPrdFile(selectedTaskId)
        .then((result) => {
          const nextContent = result.content ?? null;
          setPrdFileContent((prev) => (prev === nextContent ? prev : nextContent));
        })
        .catch(() => {});
    };

    loadPrd();
    const prdPollId = window.setInterval(loadPrd, 2000);
    return () => window.clearInterval(prdPollId);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTaskId, _prdPollActive, _prdWorktreePath]);

  async function loadDashboardData(silent = false): Promise<void> {
    if (!silent) {
      setIsDashboardLoading(true);
    }

    const [
      runAccountResult,
      taskListResult,
      devLogListResult,
      projectListResult,
    ] = await Promise.allSettled([
      runAccountApi.getCurrent(),
      taskApi.list(),
      logApi.list(),
      projectApi.list(),
    ]);

    // On fetch failure, preserve previous state rather than wiping to empty.
    // This prevents the UI from going blank during transient server restarts
    // (e.g. hot-reload after a task branch merges changes into main).
    if (runAccountResult.status === "fulfilled") {
      setCurrentRunAccount(runAccountResult.value);
    }
    if (taskListResult.status === "fulfilled") {
      const nextTaskList = sortTaskListByCreatedAt(taskListResult.value);
      setTaskList(nextTaskList);
      setSelectedTaskId((previousSelectedTaskId) => {
        if (!previousSelectedTaskId) return previousSelectedTaskId;
        const hasMatchingTask = nextTaskList.some(
          (taskItem) => taskItem.id === previousSelectedTaskId
        );
        return hasMatchingTask ? previousSelectedTaskId : null;
      });
    }
    if (devLogListResult.status === "fulfilled") {
      setAllDevLogList(sortDevLogListByCreatedAt(devLogListResult.value));
    }
    if (projectListResult.status === "fulfilled") {
      setProjectList(projectListResult.value);
    }

    const dashboardErrors: string[] = [];
    if (runAccountResult.status === "rejected") {
      dashboardErrors.push("Failed to load run account.");
      console.error(runAccountResult.reason);
    }
    if (taskListResult.status === "rejected") {
      dashboardErrors.push("Failed to load requirements.");
      console.error(taskListResult.reason);
    }
    if (devLogListResult.status === "rejected") {
      dashboardErrors.push("Failed to load timeline entries.");
      console.error(devLogListResult.reason);
    }

    setErrorMessage(dashboardErrors.length > 0 ? dashboardErrors.join(" ") : null);
    setIsDashboardLoading(false);
  }

  async function initializeDashboard(): Promise<void> {
    await loadAppConfig();
    await loadDashboardData();
  }

  async function loadAppConfig(): Promise<void> {
    try {
      const appConfig = await appConfigApi.get();
      configureAppTimezone(appConfig.app_timezone);
      setAppTimezoneRevision((previousRevision) => previousRevision + 1);
    } catch (appConfigError) {
      console.error("Failed to load app config:", appConfigError);
    }
  }

  async function handleCreateRequirement(): Promise<void> {
    const nextRequirementTitle = newRequirementTitle.trim();
    const nextRequirementDescription = newRequirementDescription.trim();

    if (!nextRequirementTitle || !nextRequirementDescription) {
      setErrorMessage("Title and description are required.");
      setSuccessMessage(null);
      return;
    }

    setActiveMutationName("create");
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const createdTask = await taskApi.create({
        task_title: nextRequirementTitle,
        project_id: newRequirementProjectId,
        requirement_brief: nextRequirementDescription,
      });

      await logApi.create({
        task_id: createdTask.id,
        text_content: nextRequirementDescription,
        state_tag: DevLogStateTag.NONE,
      });

      setWorkspaceView("active");
      setSelectedTaskId(createdTask.id);
      resetCreateRequirementDraft();
      setSuccessMessage("Requirement created successfully.");
      await loadDashboardData(true);

      window.setTimeout(() => {
        closeCreateRequirementPanel();
      }, 1200);
    } catch (creationError) {
      console.error(creationError);
      setErrorMessage("Failed to create requirement.");
    } finally {
      setActiveMutationName(null);
    }
  }

  async function handleStartTask(taskItem: Task): Promise<void> {
    setActiveMutationName("start");
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const startedTask = await taskApi.start(taskItem.id);
      const worktreeMsg = startedTask.worktree_path
        ? `Worktree 已创建：\`${startedTask.worktree_path}\`\n\nAI 正在生成 PRD，请稍候...`
        : "AI 正在生成 PRD，请稍候...";
      await logApi.create({
        task_id: taskItem.id,
        text_content: worktreeMsg,
        state_tag: DevLogStateTag.OPTIMIZATION,
      });
      await loadDashboardData(true);
    } catch (startError) {
      console.error(startError);
      setErrorMessage(
        startError instanceof Error ? startError.message : "Failed to start task."
      );
      // 刷新数据，让界面与数据库实际状态同步
      await loadDashboardData(true);
    } finally {
      setActiveMutationName(null);
    }
  }

  async function handleConfirmPrd(taskItem: Task): Promise<void> {
    setActiveMutationName("confirm");
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      await taskApi.updateStage(taskItem.id, WorkflowStage.PRD_WAITING_CONFIRMATION);
      await logApi.create({
        task_id: taskItem.id,
        text_content:
          "PRD 已确认。可点击「开始执行」触发 AI 进入编码阶段。",
        state_tag: DevLogStateTag.FIXED,
      });
      await loadDashboardData(true);
    } catch (confirmError) {
      console.error(confirmError);
      setErrorMessage("Failed to confirm PRD.");
    } finally {
      setActiveMutationName(null);
    }
  }

  async function handleStartExecution(taskItem: Task): Promise<void> {
    setActiveMutationName("execute");
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      await taskApi.execute(taskItem.id);
      await logApi.create({
        task_id: taskItem.id,
        text_content:
          "执行已启动，AI 进入无打扰编码阶段，正在基于 PRD 生成代码。",
        state_tag: DevLogStateTag.OPTIMIZATION,
      });
      await loadDashboardData(true);
    } catch (executeError) {
      console.error(executeError);
      setErrorMessage("Failed to start execution.");
    } finally {
      setActiveMutationName(null);
    }
  }

  async function handleAcceptTask(taskItem: Task): Promise<void> {
    setActiveMutationName("accept");
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      await taskApi.updateStage(taskItem.id, WorkflowStage.DONE);
      await logApi.create({
        task_id: taskItem.id,
        text_content:
          "需求验收通过，已标记为完成。",
        state_tag: DevLogStateTag.FIXED,
      });
      setWorkspaceView("completed");
      await loadDashboardData(true);
    } catch (acceptError) {
      console.error(acceptError);
      setErrorMessage("Failed to accept task.");
    } finally {
      setActiveMutationName(null);
    }
  }

  async function handleRequestChanges(taskItem: Task): Promise<void> {
    setActiveMutationName("request_changes");
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      await taskApi.updateStage(taskItem.id, WorkflowStage.CHANGES_REQUESTED);
      await logApi.create({
        task_id: taskItem.id,
        text_content:
          "验收不通过，已提出修改请求。请在反馈框中补充具体问题，AI 将重新进入实现阶段。",
        state_tag: DevLogStateTag.BUG,
      });
      await loadDashboardData(true);
    } catch (requestError) {
      console.error(requestError);
      setErrorMessage("Failed to request changes.");
    } finally {
      setActiveMutationName(null);
    }
  }

  async function handleOpenInTrae(taskItem: Task): Promise<void> {
    setActiveMutationName("open_trae");
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const result = await taskApi.openInTrae(taskItem.id);
      setSuccessMessage(`已在 Trae 中打开：${result.opened}`);
    } catch (openError) {
      console.error(openError);
      setErrorMessage("无法打开 Trae，请确认 worktree 目录已创建。");
    } finally {
      setActiveMutationName(null);
    }
  }

  async function handleOpenProjectInTrae(projectId: string): Promise<void> {
    setActiveMutationName("open_trae");
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const result = await projectApi.openInTrae(projectId);
      setSuccessMessage(`已在 Trae 中打开：${result.opened}`);
    } catch (openError) {
      console.error(openError);
      setErrorMessage("无法打开 Trae。");
    } finally {
      setActiveMutationName(null);
    }
  }

  async function handleOpenTerminal(taskItem: Task): Promise<void> {
    setActiveMutationName("open_terminal");
    setErrorMessage(null);
    try {
      await taskApi.openTerminal(taskItem.id);
    } catch (err) {
      console.error(err);
      setErrorMessage(
        err instanceof Error ? err.message : "无法打开终端，请确认任务已启动。"
      );
    } finally {
      setActiveMutationName(null);
    }
  }

  async function handleCancelTask(taskItem: Task): Promise<void> {
    setActiveMutationName("cancel");
    setErrorMessage(null);
    try {
      const updatedTask = await taskApi.cancel(taskItem.id);
      setTaskList((prev) =>
        prev.map((t) => (t.id === updatedTask.id ? updatedTask : t))
      );
    } catch (err) {
      console.error(err);
      setErrorMessage(
        err instanceof Error ? err.message : "中断失败，请手动刷新页面。"
      );
    } finally {
      setActiveMutationName(null);
    }
  }

  function handleOpenRequirementEditor(): void {
    if (!selectedTask || !selectedTaskSnapshot) {
      return;
    }

    setEditRequirementTitle(selectedTask.task_title);
    setEditRequirementDescription(selectedTaskSnapshot.summary);
    setIsEditPanelOpen(true);
    setErrorMessage(null);
    setSuccessMessage(null);
  }

  async function handleSaveRequirementChanges(): Promise<void> {
    if (!selectedTask || !selectedTaskSnapshot) {
      return;
    }

    const nextRequirementTitle = editRequirementTitle.trim();
    const nextRequirementDescription = editRequirementDescription.trim();

    if (!nextRequirementTitle || !nextRequirementDescription) {
      setErrorMessage("Requirement title and summary are required.");
      setSuccessMessage(null);
      return;
    }

    const titleChanged = nextRequirementTitle !== selectedTask.task_title;
    const summaryChanged =
      nextRequirementDescription !== selectedTaskSnapshot.summary;

    if (!titleChanged && !summaryChanged) {
      setIsEditPanelOpen(false);
      return;
    }

    setActiveMutationName("update");
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      await taskApi.update(selectedTask.id, {
        task_title: nextRequirementTitle,
        requirement_brief: nextRequirementDescription,
      });

      await logApi.create({
        task_id: selectedTask.id,
        text_content: buildRequirementUpdateLog(
          selectedTask.task_title,
          nextRequirementTitle,
          nextRequirementDescription
        ),
        state_tag: DevLogStateTag.NONE,
      });

      setWorkspaceView("changes");
      setIsEditPanelOpen(false);
      setSuccessMessage("Requirement changes were appended to history.");
      await loadDashboardData(true);
    } catch (updateError) {
      console.error(updateError);
      setErrorMessage("Failed to update requirement.");
    } finally {
      setActiveMutationName(null);
    }
  }

  async function handleCompleteRequirement(taskItem: Task): Promise<void> {
    setActiveMutationName("complete");
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      if (taskItem.worktree_path) {
        await taskApi.complete(taskItem.id);
        setSuccessMessage(
          "Koda is finalizing the branch: git add ., commit from the task summary, rebase main, auto-fix rebase conflicts with Codex if needed, merge into main, and clean up the worktree."
        );
        await loadDashboardData(true);
        return;
      }

      await taskApi.updateStatus(taskItem.id, TaskLifecycleStatus.CLOSED);
      await logApi.create({
        task_id: taskItem.id,
        text_content:
          "Requirement completed and moved into the completed archive.",
        state_tag: DevLogStateTag.FIXED,
      });
      setWorkspaceView("completed");
      setSuccessMessage("Requirement moved to completed.");
      await loadDashboardData(true);
    } catch (completionError) {
      console.error(completionError);
      setErrorMessage("Failed to complete requirement.");
    } finally {
      setActiveMutationName(null);
    }
  }

  async function handleDeleteRequirement(taskItem: Task): Promise<void> {
    const taskSnapshot = deriveRequirementSnapshot(
      taskItem,
      devLogsByTaskId[taskItem.id] ?? []
    );

    const isDeletionConfirmed = window.confirm(
      "Move this requirement into deleted history?"
    );
    if (!isDeletionConfirmed) {
      return;
    }

    setActiveMutationName("delete");
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      await taskApi.updateStatus(taskItem.id, TaskLifecycleStatus.DELETED);
      await logApi.create({
        task_id: taskItem.id,
        text_content: buildRequirementDeleteLog(
          taskItem.task_title,
          taskSnapshot.summary
        ),
        state_tag: DevLogStateTag.NONE,
      });
      setWorkspaceView("changes");
      setSuccessMessage("Requirement moved to deleted history.");
      await loadDashboardData(true);
    } catch (deleteError) {
      console.error(deleteError);
      setErrorMessage("Failed to delete requirement.");
    } finally {
      setActiveMutationName(null);
    }
  }

  async function handleFeedbackSubmit(): Promise<void> {
    if (!selectedTask) {
      return;
    }

    const nextFeedbackInputText = feedbackInputText.trim();
    if (!nextFeedbackInputText && !feedbackAttachmentDraft) {
      return;
    }

    setActiveMutationName("feedback");
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      if (feedbackAttachmentDraft) {
        if (feedbackAttachmentDraft.kind === "image") {
          await mediaApi.uploadImage(
            feedbackAttachmentDraft.file,
            nextFeedbackInputText,
            selectedTask.id
          );
        } else {
          await mediaApi.uploadAttachment(
            feedbackAttachmentDraft.file,
            nextFeedbackInputText,
            selectedTask.id
          );
        }
      } else {
        await logApi.create({
          task_id: selectedTask.id,
          text_content: nextFeedbackInputText,
          state_tag: DevLogStateTag.NONE,
        });
      }

      setFeedbackInputText("");
      setFeedbackAttachmentDraft(null);
      if (attachmentInputRef.current) {
        attachmentInputRef.current.value = "";
      }

      // 若用户输入了继续指令，根据当前阶段自动恢复执行
      const isContinueCommand = _isContinueCommand(nextFeedbackInputText);
      if (isContinueCommand && !feedbackAttachmentDraft) {
        const stage = selectedTask.workflow_stage;
        if (stage === WorkflowStage.CHANGES_REQUESTED) {
          // 正常重试：直接触发执行
          const resumedTask = await taskApi.execute(selectedTask.id);
          setTaskList((prev) =>
            prev.map((t) => (t.id === resumedTask.id ? resumedTask : t))
          );
        } else if (
          stage === WorkflowStage.IMPLEMENTATION_IN_PROGRESS ||
          stage === WorkflowStage.SELF_REVIEW_IN_PROGRESS
        ) {
          // 进程已死但阶段未更新：先取消（强制回到 changes_requested），再重新执行
          const cancelledTask = await taskApi.cancel(selectedTask.id);
          setTaskList((prev) =>
            prev.map((t) => (t.id === cancelledTask.id ? cancelledTask : t))
          );
          const resumedTask = await taskApi.execute(selectedTask.id);
          setTaskList((prev) =>
            prev.map((t) => (t.id === resumedTask.id ? resumedTask : t))
          );
        }
      }

      await loadDashboardData(true);
    } catch (feedbackError) {
      console.error(feedbackError);
      setErrorMessage("Failed to process feedback.");
    } finally {
      setActiveMutationName(null);
    }
  }

  function handleFeedbackKeyDown(
    keyboardEvent: KeyboardEvent<HTMLTextAreaElement>
  ): void {
    if (keyboardEvent.key === "Enter" && !keyboardEvent.shiftKey) {
      keyboardEvent.preventDefault();
      void handleFeedbackSubmit();
    }
  }

  function handleFeedbackPaste(
    clipboardEvent: ClipboardEvent<HTMLTextAreaElement>
  ): void {
    const clipboardItemList = Array.from(clipboardEvent.clipboardData.items);
    const pastedFile = clipboardItemList.find(
      (clipboardItem) => clipboardItem.kind === "file"
    )?.getAsFile();

    if (!pastedFile) {
      return;
    }

    clipboardEvent.preventDefault();
    setAttachmentDraftFromFile(pastedFile);
  }

  function handleAttachmentInputChange(
    changeEvent: ChangeEvent<HTMLInputElement>
  ): void {
    const nextFile = changeEvent.target.files?.[0];
    if (!nextFile) {
      return;
    }

    setAttachmentDraftFromFile(nextFile);
  }

  function setAttachmentDraftFromFile(nextFile: File): void {
    setFeedbackAttachmentDraft((previousAttachmentDraft) => {
      if (previousAttachmentDraft?.previewUrl) {
        URL.revokeObjectURL(previousAttachmentDraft.previewUrl);
      }

      return {
        file: nextFile,
        kind: nextFile.type.startsWith("image/") ? "image" : "file",
        previewUrl: nextFile.type.startsWith("image/")
          ? URL.createObjectURL(nextFile)
          : null,
      };
    });
    setSuccessMessage(null);
    setErrorMessage(null);
  }

  async function handleCreateProject(): Promise<void> {
    const trimmedName = newProjectName.trim();
    const trimmedPath = newProjectPath.trim();
    if (!trimmedName || !trimmedPath) {
      setErrorMessage("项目名称和仓库路径不能为空。");
      return;
    }
    setActiveMutationName("create");
    setErrorMessage(null);
    try {
      const createdProject = await projectApi.create({
        display_name: trimmedName,
        repo_path: trimmedPath,
        description: newProjectDescription.trim() || null,
      });
      setNewProjectName("");
      setNewProjectPath("");
      setNewProjectDescription("");
      setSuccessMessage(`项目「${trimmedName}」已创建。`);
      await loadDashboardData(true);
      if (isCreatePanelOpen) {
        setNewRequirementProjectId(createdProject.id);
      }
      window.setTimeout(() => {
        setIsProjectPanelOpen(false);
        setSuccessMessage(null);
      }, 1200);
    } catch (err) {
      console.error(err);
      setErrorMessage(
        err instanceof Error
          ? err.message
          : "创建项目失败，请确认路径是有效的 Git 仓库。"
      );
    } finally {
      setActiveMutationName(null);
    }
  }

  function resetProjectEditDraft(): void {
    setEditingProjectId(null);
    setEditingProjectName("");
    setEditingProjectPath("");
    setEditingProjectDescription("");
  }

  function openProjectEdit(projectItem: Project): void {
    setEditingProjectId(projectItem.id);
    setEditingProjectName(projectItem.display_name);
    setEditingProjectPath(projectItem.repo_path);
    setEditingProjectDescription(projectItem.description ?? "");
    setErrorMessage(null);
    setSuccessMessage(null);
  }

  async function handleUpdateProject(): Promise<void> {
    if (!editingProjectId) {
      return;
    }

    const trimmedName = editingProjectName.trim();
    const trimmedPath = editingProjectPath.trim();
    if (!trimmedName || !trimmedPath) {
      setErrorMessage("项目名称和仓库路径不能为空。");
      setSuccessMessage(null);
      return;
    }

    setActiveMutationName("update");
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const updatedProject = await projectApi.update(editingProjectId, {
        display_name: trimmedName,
        repo_path: trimmedPath,
        description: editingProjectDescription.trim() || null,
      });
      await loadDashboardData(true);
      resetProjectEditDraft();
      setSuccessMessage(
        updatedProject.is_repo_head_consistent === false
          ? `项目「${updatedProject.display_name}」已更新，但当前 HEAD 与已同步指纹不同。`
          : `项目「${updatedProject.display_name}」已更新。`
      );
    } catch (err) {
      console.error(err);
      setErrorMessage(
        err instanceof Error ? err.message : "更新项目失败，请确认路径是有效的 Git 仓库。"
      );
    } finally {
      setActiveMutationName(null);
    }
  }

  async function handleDeleteProject(projectItem: Project): Promise<void> {
    if (!window.confirm(`删除项目「${projectItem.display_name}」？`)) return;
    try {
      await projectApi.delete(projectItem.id);
      if (editingProjectId === projectItem.id) {
        resetProjectEditDraft();
      }
      await loadDashboardData(true);
    } catch (err) {
      console.error(err);
      setErrorMessage(err instanceof Error ? err.message : "删除项目失败。");
    }
  }

  function clearAttachmentDraft(): void {
    setFeedbackAttachmentDraft((previousAttachmentDraft) => {
      if (previousAttachmentDraft?.previewUrl) {
        URL.revokeObjectURL(previousAttachmentDraft.previewUrl);
      }
      return null;
    });
    if (attachmentInputRef.current) {
      attachmentInputRef.current.value = "";
    }
  }

  return (
    <div className="devflow-app">
      <header className="devflow-header">
        <div className="devflow-shell devflow-header__content">
          <div className="devflow-header__branding">
            <h1 className="devflow-header__title">AI DEVFLOW</h1>
            <div className="devflow-header__divider" />
            <span className="devflow-header__subtitle">Dashboard</span>
          </div>

          <div className="devflow-header__controls">
            <div className="devflow-view-switch" role="tablist" aria-label="Workspace view">
              {(
                [
                  ["active", `Active ${activeTaskList.length}`],
                  ["completed", `Completed ${completedTaskList.length}`],
                  ["changes", `Changes ${changedTaskList.length}`],
                ] as const
              ).map(([viewName, viewLabel]) => (
                <button
                  key={viewName}
                  type="button"
                  role="tab"
                  aria-selected={workspaceView === viewName}
                  className={joinClassNames(
                    "devflow-view-switch__button",
                    workspaceView === viewName &&
                      "devflow-view-switch__button--selected"
                  )}
                  onClick={() => setWorkspaceView(viewName)}
                >
                  {viewLabel}
                </button>
              ))}
            </div>

            <button
              type="button"
              className={joinClassNames(
                "devflow-projects-btn",
                isProjectPanelOpen && "devflow-projects-btn--active"
              )}
              onClick={() => {
                setIsProjectPanelOpen((prev) => !prev);
                setErrorMessage(null);
                setSuccessMessage(null);
              }}
            >
              <CodeIcon className="devflow-icon devflow-icon--tiny" />
              <span>项目 {projectList.length > 0 ? `(${projectList.length})` : ""}</span>
            </button>

            <div className="devflow-user-chip">
              <span className="devflow-user-chip__avatar">
                <UserIcon className="devflow-icon devflow-icon--tiny" />
              </span>
              <span className="devflow-user-chip__label">{currentUserLabel}</span>
            </div>

            <button
              type="button"
              className="devflow-projects-btn"
              onClick={() => setIsEmailSettingsOpen(true)}
              title="Email notification settings"
            >
              <span>📧</span>
            </button>
          </div>
        </div>
      </header>

      {isEmailSettingsOpen && (
        <SettingsModal onClose={() => setIsEmailSettingsOpen(false)} />
      )}

      <main className="devflow-shell devflow-main">
        {errorMessage ? (
          <div className="devflow-alert devflow-alert--error">
            <RobotIcon className="devflow-icon devflow-icon--tiny" />
            <span>{errorMessage}</span>
          </div>
        ) : null}

        {isProjectPanelOpen ? (
          <div className="devflow-project-panel">
            <div className="devflow-project-panel__header">
              <h3 className="devflow-project-panel__title">
                <CodeIcon className="devflow-icon devflow-icon--small" />
                <span>项目管理</span>
              </h3>
              <button
                type="button"
                className="devflow-project-panel__close"
                onClick={() => setIsProjectPanelOpen(false)}
              >
                <XIcon className="devflow-icon devflow-icon--small" />
              </button>
            </div>

            <div className="devflow-project-panel__list">
              {hasProjectConsistencyIssues ? (
                <div className="devflow-inline-message devflow-inline-message--error">
                  <RobotIcon className="devflow-icon devflow-icon--tiny" />
                  <span>检测到项目一致性问题。请按列表中的状态修复路径、仓库或提交基线。</span>
                </div>
              ) : null}

              {projectList.length === 0 ? (
                <p className="devflow-project-panel__empty">暂无项目，请在下方添加。</p>
              ) : (
                projectList.map((projectItem) => {
                  const projectHealthState = getProjectHealthState(projectItem);
                  return (
                    <div
                      key={projectItem.id}
                      className={joinClassNames(
                        "devflow-project-item",
                        projectHealthState.containerClassName
                      )}
                    >
                      {editingProjectId === projectItem.id ? (
                        <>
                          <div className="devflow-project-item__form">
                            <input
                              className="devflow-input devflow-input--title"
                              placeholder="项目名称"
                              value={editingProjectName}
                              onChange={(changeEvent) =>
                                setEditingProjectName(changeEvent.target.value)
                              }
                            />
                            <input
                              className="devflow-input devflow-input--title"
                              placeholder="当前机器上的本地 Git 仓库绝对路径"
                              value={editingProjectPath}
                              onChange={(changeEvent) =>
                                setEditingProjectPath(changeEvent.target.value)
                              }
                            />
                            <input
                              className="devflow-input devflow-input--title"
                              placeholder="描述（可选）"
                              value={editingProjectDescription}
                              onChange={(changeEvent) =>
                                setEditingProjectDescription(changeEvent.target.value)
                              }
                            />
                          </div>

                          <div className="devflow-project-item__actions">
                            <button
                              type="button"
                              className="devflow-project-item__action"
                              onClick={resetProjectEditDraft}
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              className="devflow-project-item__action devflow-project-item__action--primary"
                              onClick={() => {
                                void handleUpdateProject();
                              }}
                            >
                              {activeMutationName === "update" ? "Saving..." : "Save"}
                            </button>
                          </div>
                        </>
                      ) : (
                        <>
                          <div className="devflow-project-item__info">
                            <div className="devflow-project-item__title-row">
                              <span className="devflow-project-item__name">
                                {projectItem.display_name}
                              </span>
                              <span
                                className={joinClassNames(
                                  "devflow-project-item__status",
                                  projectHealthState.statusClassName
                                )}
                              >
                                {projectHealthState.statusLabel}
                              </span>
                            </div>
                            <span className="devflow-project-item__path">{projectItem.repo_path}</span>
                            {projectItem.description ? (
                              <span className="devflow-project-item__description">
                                {projectItem.description}
                              </span>
                            ) : null}
                            {projectHealthState.note ? (
                              <span className="devflow-project-item__hint">
                                {projectHealthState.note}
                              </span>
                            ) : null}
                            {projectHealthState.fingerprint ? (
                              <span className="devflow-project-item__fingerprint">
                                {projectHealthState.fingerprint}
                              </span>
                            ) : null}
                          </div>

                          <div className="devflow-project-item__actions">
                            <button
                              type="button"
                              className="devflow-project-item__action"
                              onClick={() => openProjectEdit(projectItem)}
                            >
                              {projectHealthState.actionLabel}
                            </button>
                            <button
                              type="button"
                              className="devflow-project-item__delete"
                              onClick={() => {
                                void handleDeleteProject(projectItem);
                              }}
                            >
                              <TrashIcon className="devflow-icon devflow-icon--tiny" />
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  );
                })
              )}
            </div>

            <div className="devflow-project-panel__form">
              <input
                className="devflow-input devflow-input--title"
                placeholder="项目名称"
                value={newProjectName}
                onChange={(e) => setNewProjectName(e.target.value)}
              />
              <input
                className="devflow-input devflow-input--title"
                placeholder="本地 Git 仓库绝对路径，如 /Users/me/myrepo"
                value={newProjectPath}
                onChange={(e) => setNewProjectPath(e.target.value)}
              />
              <input
                className="devflow-input devflow-input--title"
                placeholder="描述（可选）"
                value={newProjectDescription}
                onChange={(e) => setNewProjectDescription(e.target.value)}
              />
              {errorMessage ? (
                <div className="devflow-inline-message devflow-inline-message--error">
                  <RobotIcon className="devflow-icon devflow-icon--tiny" />
                  <span>{errorMessage}</span>
                </div>
              ) : null}
              {successMessage ? (
                <div className="devflow-inline-message devflow-inline-message--success">
                  <CheckCircleIcon className="devflow-icon devflow-icon--tiny" />
                  <span>{successMessage}</span>
                </div>
              ) : null}
              <ActionButton
                variant="primary"
                busy={activeMutationName === "create"}
                onClick={() => { void handleCreateProject(); }}
              >
                {activeMutationName === "create" ? "添加中..." : "添加项目"}
              </ActionButton>
            </div>
          </div>
        ) : null}

        <div className="devflow-layout">
          <section className="devflow-column devflow-column--requirements">
            <div className="devflow-section-heading">
              <h2 className="devflow-section-heading__title">
                {getWorkspaceHeading(workspaceView)}
              </h2>
              {canCreateRequirements ? (
                <ActionButton
                  variant="outline"
                  className="devflow-icon-button"
                  onClick={openCreateRequirementPanel}
                >
                  <PlusIcon className="devflow-icon devflow-icon--small" />
                </ActionButton>
              ) : null}
            </div>

            {isCreatePanelOpen && canCreateRequirements ? (
              <CardSurface className="devflow-create-panel">
                <input
                  className="devflow-input devflow-input--title"
                  placeholder="Requirement Title"
                  value={newRequirementTitle}
                  onChange={(changeEvent) =>
                    setNewRequirementTitle(changeEvent.target.value)
                  }
                />

                <textarea
                  className="devflow-input devflow-input--textarea"
                  placeholder="Describe what you want to build..."
                  value={newRequirementDescription}
                  onChange={(changeEvent) =>
                    setNewRequirementDescription(changeEvent.target.value)
                  }
                />

                <select
                  className="devflow-input devflow-input--select"
                  value={newRequirementProjectId ?? ""}
                  onChange={(changeEvent) =>
                    setNewRequirementProjectId(
                      changeEvent.target.value || null
                    )
                  }
                >
                  <option value="">-- 不关联项目 --</option>
                  {projectList.map((projectItem) => (
                    <option
                      key={projectItem.id}
                      value={projectItem.id}
                      disabled={!isProjectSelectable(projectItem)}
                    >
                      {isProjectSelectable(projectItem)
                        ? projectItem.display_name
                        : `${projectItem.display_name} (${getProjectHealthState(projectItem).statusLabel.toLowerCase()})`}
                    </option>
                  ))}
                </select>

                {errorMessage ? (
                  <div className="devflow-inline-message devflow-inline-message--error">
                    <RobotIcon className="devflow-icon devflow-icon--tiny" />
                    <span>{errorMessage}</span>
                  </div>
                ) : null}

                {successMessage ? (
                  <div className="devflow-inline-message devflow-inline-message--success">
                    <CheckCircleIcon className="devflow-icon devflow-icon--tiny" />
                    <span>{successMessage}</span>
                  </div>
                ) : null}

                <div className="devflow-create-panel__actions">
                  <ActionButton
                    variant="ghost"
                    onClick={closeCreateRequirementPanel}
                  >
                    Cancel
                  </ActionButton>
                  <ActionButton
                    variant="primary"
                    busy={activeMutationName === "create"}
                    onClick={() => {
                      void handleCreateRequirement();
                    }}
                  >
                    {activeMutationName === "create" ? "Creating..." : "Create"}
                  </ActionButton>
                </div>
              </CardSurface>
            ) : null}

            <div className="devflow-requirement-list">
              {isDashboardLoading ? (
                <CardSurface className="devflow-loading-card">
                  <span>Loading requirements...</span>
                </CardSurface>
              ) : null}

              {!isDashboardLoading && requirementViewModelList.length === 0 ? (
                <div className="devflow-empty-card">
                  <p className="devflow-empty-card__text">
                    {getWorkspaceEmptyState(workspaceView)}
                  </p>
                  {canCreateRequirements ? (
                    <ActionButton
                      variant="ghost"
                      className="devflow-empty-card__action"
                      onClick={openCreateRequirementPanel}
                    >
                      Create First Task
                    </ActionButton>
                  ) : null}
                </div>
              ) : null}

              {requirementViewModelList.map((requirementViewModel) => (
                <button
                  key={requirementViewModel.task.id}
                  className={joinClassNames(
                    "devflow-requirement-card-button",
                    selectedTask?.id === requirementViewModel.task.id &&
                      "devflow-requirement-card-button--selected"
                  )}
                  onClick={() => setSelectedTaskId(requirementViewModel.task.id)}
                >
                  <CardSurface
                    className={joinClassNames(
                      "devflow-requirement-card",
                      selectedTask?.id === requirementViewModel.task.id &&
                        "devflow-requirement-card--selected"
                    )}
                  >
                    <div className="devflow-requirement-card__meta">
                      <StatusBadge status={requirementViewModel.stage} />
                      <span className="devflow-requirement-card__date">
                        {requirementViewModel.createdLabel}
                      </span>
                    </div>
                    <h3 className="devflow-requirement-card__title">
                      {requirementViewModel.task.task_title}
                    </h3>
                    <p className="devflow-requirement-card__description">
                      {requirementViewModel.description}
                    </p>
                  </CardSurface>
                </button>
              ))}
            </div>
          </section>

          <section className="devflow-column devflow-column--detail">
            {selectedTask ? (
              <div className="devflow-detail">
                <div className="devflow-detail__body">
                  <div className="devflow-detail__header">
                    <div className="devflow-detail__copy">
                      <div className="devflow-detail__title-row">
                        <h2 className="devflow-detail__title">
                          {selectedTask.task_title}
                        </h2>
                        {selectedTaskStage ? (
                          <StatusBadge status={selectedTaskStage} />
                        ) : null}
                      </div>
                      <p className="devflow-detail__description">
                        {selectedTaskSnapshot?.summary ||
                          "No requirement brief captured yet."}
                      </p>
                    </div>

                    <div className="devflow-detail__actions">
                      {/* ── Backlog: 开始任务 ── */}
                      {selectedTaskStage === WorkflowStage.BACKLOG &&
                      selectedTask.lifecycle_status !== TaskLifecycleStatus.DELETED ? (
                        <ActionButton
                          variant="primary"
                          busy={activeMutationName === "start"}
                          onClick={() => {
                            void handleStartTask(selectedTask);
                          }}
                        >
                          <PlayIcon className="devflow-icon devflow-icon--small" />
                          <span>开始任务</span>
                        </ActionButton>
                      ) : null}

                      {/* ── PRD 撰写中: 重新生成 + 确认 PRD ── */}
                      {selectedTaskStage === WorkflowStage.PRD_GENERATING &&
                      selectedTask.lifecycle_status !== TaskLifecycleStatus.DELETED ? (
                        <>
                          <ActionButton
                            variant="primary"
                            busy={activeMutationName === "start"}
                            onClick={() => {
                              void handleStartTask(selectedTask);
                            }}
                          >
                            <PlayIcon className="devflow-icon devflow-icon--small" />
                            <span>重新生成</span>
                          </ActionButton>
                          <ActionButton
                            variant="secondary"
                            busy={activeMutationName === "confirm"}
                            onClick={() => {
                              void handleConfirmPrd(selectedTask);
                            }}
                          >
                            <CheckCircleIcon className="devflow-icon devflow-icon--small" />
                            <span>确认 PRD</span>
                          </ActionButton>
                        </>
                      ) : null}

                      {/* ── PRD 待确认: 确认 PRD + 开始执行 ── */}
                      {selectedTaskStage === WorkflowStage.PRD_WAITING_CONFIRMATION &&
                      selectedTask.lifecycle_status !== TaskLifecycleStatus.DELETED ? (
                        <>
                          <ActionButton
                            variant="secondary"
                            busy={activeMutationName === "confirm"}
                            onClick={() => {
                              void handleConfirmPrd(selectedTask);
                            }}
                          >
                            <CheckCircleIcon className="devflow-icon devflow-icon--small" />
                            <span>确认 PRD</span>
                          </ActionButton>
                          <ActionButton
                            variant="execute"
                            busy={activeMutationName === "execute"}
                            onClick={() => {
                              void handleStartExecution(selectedTask);
                            }}
                          >
                            <RocketIcon className="devflow-icon devflow-icon--small" />
                            <span>开始执行</span>
                          </ActionButton>
                        </>
                      ) : null}

                      {/* ── Changes Requested: 重新执行 ── */}
                      {selectedTaskStage === WorkflowStage.CHANGES_REQUESTED &&
                      selectedTask.lifecycle_status !== TaskLifecycleStatus.DELETED ? (
                        <ActionButton
                          variant="execute"
                          busy={activeMutationName === "execute"}
                          onClick={() => {
                            void handleStartExecution(selectedTask);
                          }}
                        >
                          <RocketIcon className="devflow-icon devflow-icon--small" />
                          <span>重新执行</span>
                        </ActionButton>
                      ) : null}

                      {/* ── 验收阶段: 验收通过 + 请求修改 ── */}
                      {selectedTaskStage === WorkflowStage.ACCEPTANCE_IN_PROGRESS &&
                      selectedTask.lifecycle_status !== TaskLifecycleStatus.DELETED ? (
                        <>
                          <ActionButton
                            variant="secondary"
                            busy={activeMutationName === "accept"}
                            onClick={() => {
                              void handleAcceptTask(selectedTask);
                            }}
                          >
                            <CheckCircleIcon className="devflow-icon devflow-icon--small" />
                            <span>验收通过</span>
                          </ActionButton>
                          <ActionButton
                            variant="outline"
                            busy={activeMutationName === "request_changes"}
                            onClick={() => {
                              void handleRequestChanges(selectedTask);
                            }}
                          >
                            <EditIcon className="devflow-icon devflow-icon--small" />
                            <span>请求修改</span>
                          </ActionButton>
                        </>
                      ) : null}

                      {/* ── 打开项目根目录（有关联项目时始终显示） ── */}
                      {selectedTask.project_id &&
                      selectedTask.lifecycle_status !== TaskLifecycleStatus.DELETED ? (
                        <ActionButton
                          variant="outline"
                          busy={activeMutationName === "open_trae"}
                          onClick={() => {
                            void handleOpenProjectInTrae(selectedTask.project_id!);
                          }}
                        >
                          <CodeIcon className="devflow-icon devflow-icon--small" />
                          <span>打开项目</span>
                        </ActionButton>
                      ) : null}

                      {/* ── 打开 Worktree（执行后才显示） ── */}
                      {selectedTask.worktree_path &&
                      selectedTask.lifecycle_status !== TaskLifecycleStatus.DELETED ? (
                        <ActionButton
                          variant="outline"
                          busy={activeMutationName === "open_trae"}
                          onClick={() => {
                            void handleOpenInTrae(selectedTask);
                          }}
                        >
                          <CodeIcon className="devflow-icon devflow-icon--small" />
                          <span>打开 Worktree</span>
                        </ActionButton>
                      ) : null}

                      {/* ── 通用操作 ── */}
                      {canEditSelectedTask ? (
                        <>
                          <ActionButton
                            variant="outline"
                            onClick={handleOpenRequirementEditor}
                          >
                            <EditIcon className="devflow-icon devflow-icon--small" />
                            <span>Edit Requirement</span>
                          </ActionButton>
                          <ActionButton
                            variant="outline"
                            busy={activeMutationName === "complete"}
                            onClick={() => {
                              void handleCompleteRequirement(selectedTask);
                            }}
                          >
                            <ArchiveIcon className="devflow-icon devflow-icon--small" />
                            <span>Complete</span>
                          </ActionButton>
                          <ActionButton
                            variant="ghost"
                            busy={activeMutationName === "delete"}
                            onClick={() => {
                              void handleDeleteRequirement(selectedTask);
                            }}
                          >
                            <TrashIcon className="devflow-icon devflow-icon--small" />
                            <span>Delete</span>
                          </ActionButton>
                        </>
                      ) : null}
                    </div>
                  </div>

                  {isEditPanelOpen && canEditSelectedTask ? (
                    <CardSurface className="devflow-edit-panel">
                      <div className="devflow-edit-panel__header">
                        <h3 className="devflow-detail-section__title">
                          <EditIcon className="devflow-icon devflow-icon--small" />
                          <span>Requirement Revision</span>
                        </h3>
                        <p className="devflow-edit-panel__hint">
                          Saving appends the new scope to history instead of replacing
                          previous execution context.
                        </p>
                      </div>

                      <input
                        className="devflow-input devflow-input--title"
                        placeholder="Requirement Title"
                        value={editRequirementTitle}
                        onChange={(changeEvent) =>
                          setEditRequirementTitle(changeEvent.target.value)
                        }
                      />

                      <textarea
                        className="devflow-input devflow-input--textarea"
                        placeholder="Updated requirement summary"
                        value={editRequirementDescription}
                        onChange={(changeEvent) =>
                          setEditRequirementDescription(changeEvent.target.value)
                        }
                      />

                      <div className="devflow-create-panel__actions">
                        <ActionButton
                          variant="ghost"
                          onClick={() => setIsEditPanelOpen(false)}
                        >
                          Cancel
                        </ActionButton>
                        <ActionButton
                          variant="primary"
                          busy={activeMutationName === "update"}
                          onClick={() => {
                            void handleSaveRequirementChanges();
                          }}
                        >
                          {activeMutationName === "update" ? "Saving..." : "Append Change"}
                        </ActionButton>
                      </div>
                    </CardSurface>
                  ) : null}

                  <div className="devflow-detail-grid">
                    <div className="devflow-detail-section">
                      <h3 className="devflow-detail-section__title">
                        <HistoryIcon className="devflow-icon devflow-icon--small" />
                        <span>Timeline</span>
                      </h3>

                      <div className="devflow-conversation">
                        {isSelectedTaskInActiveExecution ? (
                          <div className="devflow-execution-banner">
                            <span className="devflow-footer__pulse" />
                            <span>
                              {selectedTaskStage === WorkflowStage.PRD_GENERATING
                                ? "AI 正在生成 PRD，请稍候..."
                                : "AI 正在执行编码，输出实时显示在下方..."}
                            </span>
                            <button
                              type="button"
                              className="devflow-execution-banner__terminal-btn"
                              title="在终端中实时查看 codex 输出"
                              disabled={activeMutationName === "open_terminal"}
                              onClick={() => { void handleOpenTerminal(selectedTask); }}
                            >
                              <TerminalIcon className="devflow-icon devflow-icon--tiny" />
                              <span>打开终端</span>
                            </button>
                            <button
                              type="button"
                              className="devflow-execution-banner__cancel-btn"
                              title="中断 codex 并回退至修改请求阶段"
                              disabled={activeMutationName === "cancel"}
                              onClick={() => { void handleCancelTask(selectedTask); }}
                            >
                              <span>⏹ 中断</span>
                            </button>
                          </div>
                        ) : null}

                        {conversationTurnList.length === 0 ? (
                          <div className="devflow-empty-card devflow-empty-card--detail">
                            <p className="devflow-empty-card__text">
                              Timeline will appear here after task activity begins.
                            </p>
                          </div>
                        ) : null}

                        {conversationTurnList.map((turn) => {
                          if (turn.kind === "human") {
                            return (
                              <div key={turn.turnId} className="devflow-turn-card devflow-turn-card--human">
                                <div className="devflow-turn-card__human-header">
                                  <UserIcon className="devflow-icon devflow-icon--tiny devflow-icon--human" />
                                  <span className="devflow-turn-card__author">{turn.authorName}</span>
                                  <span className="devflow-turn-card__time">{turn.timeLabel}</span>
                                </div>
                                {turn.items.map((item) => {
                                  const imgUrl =
                                    mapMediaPathToPublicUrl(item.log.media_original_image_path) ||
                                    mapMediaPathToPublicUrl(item.log.media_thumbnail_path);
                                  return (
                                    <div key={item.log.id} className="devflow-turn-card__human-body">
                                      <div className="devflow-markdown">
                                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                          {item.log.text_content || ""}
                                        </ReactMarkdown>
                                      </div>
                                      {imgUrl ? (
                                        <a
                                          className="devflow-timeline-item__image-link"
                                          href={imgUrl}
                                          target="_blank"
                                          rel="noreferrer"
                                        >
                                          <img
                                            className="devflow-timeline-item__image"
                                            src={imgUrl}
                                            alt="Attachment"
                                          />
                                        </a>
                                      ) : null}
                                    </div>
                                  );
                                })}
                              </div>
                            );
                          }

                          // AI turn card
                          const isExpanded = expandedTurnIdSet.has(turn.turnId);
                          return (
                            <div
                              key={turn.turnId}
                              className={joinClassNames(
                                "devflow-turn-card devflow-turn-card--ai",
                                isExpanded && "devflow-turn-card--expanded"
                              )}
                            >
                              <button
                                type="button"
                                className="devflow-turn-card__ai-header"
                                onClick={() => {
                                  setExpandedTurnIdSet((prev) => {
                                    const next = new Set(prev);
                                    if (next.has(turn.turnId)) {
                                      next.delete(turn.turnId);
                                    } else {
                                      next.add(turn.turnId);
                                    }
                                    return next;
                                  });
                                }}
                              >
                                <RobotIcon className="devflow-icon devflow-icon--tiny devflow-icon--ai" />
                                <span className="devflow-turn-card__author">{turn.authorName}</span>
                                <span className="devflow-turn-card__time">{turn.timeLabel}</span>
                                <span className="devflow-turn-card__count">{turn.items.length} 条输出</span>
                                <ChevronRightIcon
                                  className={joinClassNames(
                                    "devflow-icon devflow-icon--tiny devflow-turn-card__chevron",
                                    isExpanded && "devflow-turn-card__chevron--open"
                                  )}
                                />
                              </button>

                              {isExpanded ? (
                                <div
                                  className="devflow-turn-card__ai-body"
                                  ref={(aiTurnBodyElement) => {
                                    aiTurnBodyElementByTurnIdRef.current[turn.turnId] =
                                      aiTurnBodyElement;
                                  }}
                                >
                                  {turn.items.map((item) => {
                                    const imgUrl =
                                      mapMediaPathToPublicUrl(item.log.media_original_image_path) ||
                                      mapMediaPathToPublicUrl(item.log.media_thumbnail_path);
                                    return (
                                      <div key={item.log.id} className="devflow-turn-card__ai-entry">
                                        <span className="devflow-turn-card__entry-time">{item.timeLabel}</span>
                                        <div className="devflow-markdown devflow-turn-card__entry-content">
                                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                            {item.log.text_content || ""}
                                          </ReactMarkdown>
                                        </div>
                                        {imgUrl ? (
                                          <a
                                            className="devflow-timeline-item__image-link"
                                            href={imgUrl}
                                            target="_blank"
                                            rel="noreferrer"
                                          >
                                            <img
                                              className="devflow-timeline-item__image"
                                              src={imgUrl}
                                              alt="Attachment"
                                            />
                                          </a>
                                        ) : null}
                                      </div>
                                    );
                                  })}
                                </div>
                              ) : null}
                            </div>
                          );
                        })}
                      </div>
                    </div>

                    <div className="devflow-detail-section">
                      <h3 className="devflow-detail-section__title">
                        <FileTextIcon className="devflow-icon devflow-icon--small" />
                        <span>PRD Document</span>
                      </h3>

                      <CardSurface className="devflow-document-card">
                        {prdFileContent &&
                        selectedTaskStage !== WorkflowStage.BACKLOG &&
                        selectedTaskStage !== WorkflowStage.DONE &&
                        selectedTaskStage !== WorkflowStage.PRD_GENERATING ? (
                          <div className="devflow-markdown devflow-markdown--document">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {prdFileContent}
                            </ReactMarkdown>
                          </div>
                        ) : selectedTaskStage === WorkflowStage.PRD_GENERATING ? (
                          <div className="devflow-execution-banner">
                            <span className="devflow-footer__pulse" />
                            <span>AI 正在生成 PRD 文件，完成后将显示在这里...</span>
                          </div>
                        ) : (
                          <div className="devflow-markdown devflow-markdown--document">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {selectedTaskDocumentMarkdown}
                            </ReactMarkdown>
                          </div>
                        )}
                      </CardSurface>
                    </div>
                  </div>
                </div>

                {canSendFeedback ? (
                  <div className="devflow-feedback">
                    {feedbackAttachmentDraft ? (
                      <div className="devflow-feedback__attachment">
                        {feedbackAttachmentDraft.previewUrl ? (
                          <img
                            className="devflow-feedback__attachment-preview"
                            src={feedbackAttachmentDraft.previewUrl}
                            alt={feedbackAttachmentDraft.file.name}
                          />
                        ) : (
                          <span className="devflow-feedback__attachment-icon">
                            <PaperclipIcon className="devflow-icon devflow-icon--small" />
                          </span>
                        )}

                        <div className="devflow-feedback__attachment-copy">
                          <span className="devflow-feedback__attachment-name">
                            {feedbackAttachmentDraft.file.name}
                          </span>
                          <span className="devflow-feedback__attachment-meta">
                            {feedbackAttachmentDraft.kind === "image"
                              ? "Image attachment"
                              : "File attachment"}
                            {" · "}
                            {formatFileSize(feedbackAttachmentDraft.file.size)}
                          </span>
                        </div>

                        <button
                          type="button"
                          className="devflow-feedback__attachment-remove"
                          onClick={clearAttachmentDraft}
                        >
                          <XIcon className="devflow-icon devflow-icon--small" />
                        </button>
                      </div>
                    ) : null}

                    <div className="devflow-feedback__composer">
                      <button
                        type="button"
                        className="devflow-feedback__attach"
                        onClick={() => attachmentInputRef.current?.click()}
                        disabled={activeMutationName === "feedback"}
                      >
                        <PaperclipIcon className="devflow-icon devflow-icon--small" />
                      </button>

                      <textarea
                        className="devflow-feedback__textarea"
                        placeholder="Ask AI to refine the PRD, or paste an image/file directly..."
                        value={feedbackInputText}
                        onChange={(changeEvent) =>
                          setFeedbackInputText(changeEvent.target.value)
                        }
                        onKeyDown={handleFeedbackKeyDown}
                        onPaste={handleFeedbackPaste}
                      />

                      <button
                        type="button"
                        className="devflow-feedback__send"
                        onClick={() => {
                          void handleFeedbackSubmit();
                        }}
                        disabled={
                          activeMutationName === "feedback" || !hasFeedbackPayload
                        }
                      >
                        <SendIcon className="devflow-icon devflow-icon--small" />
                      </button>

                      <input
                        ref={attachmentInputRef}
                        className="devflow-feedback__file-input"
                        type="file"
                        onChange={handleAttachmentInputChange}
                      />
                    </div>
                    <p className="devflow-feedback__hint">
                      Tip: Press Enter to send, Shift + Enter for new line, or paste an
                      image/file directly into the composer.
                    </p>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="devflow-empty-detail">
                <div className="devflow-empty-detail__icon">
                  <ChevronRightIcon className="devflow-icon devflow-icon--large" />
                </div>
                <p className="devflow-empty-detail__text">
                  {getWorkspaceDetailEmptyState(workspaceView)}
                </p>
              </div>
            )}
          </section>
        </div>
      </main>

      <footer className="devflow-footer">
        <div className="devflow-shell devflow-footer__content">
          <div className="devflow-footer__left">
            <div className="devflow-footer__agent">
              <span className="devflow-footer__pulse" />
              <span className="devflow-footer__label">AI Agent Active</span>
            </div>
            <div className="devflow-footer__version">
              <CodeIcon className="devflow-icon devflow-icon--tiny" />
              <span>v1.0.4-autonomous</span>
            </div>
          </div>

          <div className="devflow-footer__right">
            <span className="devflow-footer__status">
              {selectedTask
                ? `Tracking ${selectedTask.task_title}`
                : `Browsing ${getWorkspaceHeading(workspaceView).toLowerCase()}`}
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}

interface CardSurfaceProps {
  children: ReactNode;
  className?: string;
}

function CardSurface({ children, className }: CardSurfaceProps) {
  return (
    <div className={joinClassNames("devflow-card", className)}>{children}</div>
  );
}

interface ActionButtonProps {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "execute" | "outline" | "ghost";
  className?: string;
  busy?: boolean;
  disabled?: boolean;
}

function ActionButton({
  children,
  onClick,
  variant = "primary",
  className,
  busy = false,
  disabled = false,
}: ActionButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || busy}
      className={joinClassNames(
        "devflow-button",
        `devflow-button--${variant}`,
        className
      )}
    >
      {busy ? <span className="devflow-spinner" aria-hidden="true" /> : null}
      {children}
    </button>
  );
}

interface StatusBadgeProps {
  status: RequirementStage;
}

function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <span
      className={joinClassNames(
        "devflow-badge",
        `devflow-badge--${status}`
      )}
    >
      {formatStageLabel(status)}
    </span>
  );
}

function buildRequirementViewModel(
  taskItem: Task,
  taskDevLogList: DevLog[]
): RequirementViewModel {
  return {
    task: taskItem,
    description: buildRequirementDescription(taskItem, taskDevLogList),
    stage: deriveRequirementStage(taskItem, taskDevLogList),
    createdLabel: formatMonthDay(taskItem.created_at),
  };
}

function buildTimelineViewModel(
  devLogItem: DevLog,
  currentRunAccount: RunAccount | null
): TimelineViewModel {
  const timelineKind = deriveTimelineKind(devLogItem);
  return {
    log: devLogItem,
    kind: timelineKind,
    authorName: deriveTimelineAuthorName(timelineKind, currentRunAccount),
    timeLabel: formatHourMinute(devLogItem.created_at),
  };
}

function groupTimelineIntoConversationTurns(
  timelineItems: TimelineViewModel[]
): ConversationTurn[] {
  const turns: ConversationTurn[] = [];

  for (const item of timelineItems) {
    // 只有 state_tag === NONE 的 human_review 才是真正的用户输入
    // 系统自动写入的状态消息（state_tag = FIXED/OPTIMIZATION/BUG 等）归入 AI 侧
    const turnKind: ConversationTurnKind =
      item.kind === "human_review" && item.log.state_tag === DevLogStateTag.NONE
        ? "human"
        : "ai";
    const lastTurn = turns[turns.length - 1];

    // Consecutive AI logs are merged into a single AI turn
    if (lastTurn && lastTurn.kind === "ai" && turnKind === "ai") {
      lastTurn.items.push(item);
    } else {
      turns.push({
        turnId: item.log.id,
        kind: turnKind,
        authorName: item.authorName,
        timeLabel: item.timeLabel,
        items: [item],
      });
    }
  }

  return turns;
}

function buildDevLogsByTaskId(devLogList: DevLog[]): Record<string, DevLog[]> {
  return devLogList.reduce<Record<string, DevLog[]>>((groupedDevLogs, devLogItem) => {
    const nextTaskId = devLogItem.task_id;
    if (!groupedDevLogs[nextTaskId]) {
      groupedDevLogs[nextTaskId] = [];
    }
    groupedDevLogs[nextTaskId].push(devLogItem);
    return groupedDevLogs;
  }, {});
}

function buildRequirementDescription(taskItem: Task, taskDevLogList: DevLog[]): string {
  return truncateText(
    deriveRequirementSnapshot(taskItem, taskDevLogList).summary,
    120
  );
}

function deriveRequirementSnapshot(
  taskItem: Task,
  taskDevLogList: DevLog[]
): RequirementSnapshot {
  // Check devlogs first for manual revisions (most recent wins)
  for (let index = taskDevLogList.length - 1; index >= 0; index -= 1) {
    const parsedRequirementChange = parseRequirementChangeLog(
      taskDevLogList[index].text_content
    );
    if (parsedRequirementChange) {
      return {
        summary:
          parsedRequirementChange.summary || "No requirement brief captured yet.",
        title: parsedRequirementChange.title || taskItem.task_title,
        changeKind: parsedRequirementChange.kind,
      };
    }
  }

  // Use requirement_brief stored directly on the task (immune to log pagination)
  if (taskItem.requirement_brief) {
    return {
      summary: taskItem.requirement_brief,
      title: taskItem.task_title,
      changeKind: null,
    };
  }

  return {
    summary: "No requirement brief captured yet.",
    title: taskItem.task_title,
    changeKind: null,
  };
}

function buildTaskDocumentMarkdown(
  selectedTask: Task,
  selectedTaskDevLogs: DevLog[],
  currentRunAccount: RunAccount | null
): string {
  const selectedTaskStage = deriveRequirementStage(selectedTask, selectedTaskDevLogs);
  const requirementSnapshot = deriveRequirementSnapshot(
    selectedTask,
    selectedTaskDevLogs
  );
  const highlightedLogList = selectedTaskDevLogs
    .slice(-5)
    .map((devLogItem) => cleanMarkdownPreview(devLogItem.text_content))
    .filter(Boolean)
    .map((previewText) => `- ${truncateText(previewText, 140)}`);
  const stateTagSummaryList = selectedTaskDevLogs
    .filter((devLogItem) => devLogItem.state_tag !== DevLogStateTag.NONE)
    .slice(-5)
    .map(
      (devLogItem) =>
        `- ${devLogItem.state_tag.toLowerCase()}: ${truncateText(
          cleanMarkdownPreview(devLogItem.text_content),
          120
        )}`
    );
  const revisionSummaryList = selectedTaskDevLogs
    .map((devLogItem) => parseRequirementChangeLog(devLogItem.text_content))
    .filter(
      (
        requirementChange
      ): requirementChange is { kind: "update" | "delete"; title: string | null; summary: string } =>
        Boolean(requirementChange)
    )
    .slice(-3)
    .map(
      (requirementChange) =>
        `- ${requirementChange.kind}: ${truncateText(
          requirementChange.summary,
          140
        )}`
    );

  return [
    `# ${selectedTask.task_title}`,
    "",
    "## Overview",
    requirementSnapshot.summary,
    "",
    "## Current Flow",
    `- Workflow stage: ${formatStageLabel(selectedTaskStage)}`,
    `- Repository task status: ${selectedTask.lifecycle_status.toLowerCase()}`,
    `- Timeline entries: ${selectedTaskDevLogs.length}`,
    `- Run account: ${currentRunAccount?.account_display_name || GUEST_USER_LABEL}`,
    `- Created: ${formatDateTime(selectedTask.created_at)}`,
    "",
    "## Requirement History",
    ...(revisionSummaryList.length > 0
      ? revisionSummaryList
      : ["- No requirement revisions captured yet."]),
    "",
    "## Implementation Notes",
    ...(stateTagSummaryList.length > 0
      ? stateTagSummaryList
      : ["- No structured implementation notes yet."]),
    "",
    "## Recent Timeline",
    ...(highlightedLogList.length > 0
      ? highlightedLogList
      : ["- Waiting for the first timeline entry."]),
    "",
    "## Validation Checklist",
    "- [ ] Match the reference layout and spacing system",
    "- [ ] Validate the requirement list, timeline, and PRD panels",
    "- [ ] Confirm PRD metadata includes `原始需求标题` and `需求名称（AI 归纳）`",
    "- [ ] Verify responsive behavior on narrow screens",
    "- [ ] Keep current backend task and log flows operational",
  ].join("\n");
}

function deriveRequirementStage(
  taskItem: Task,
  _taskDevLogList: DevLog[]
): RequirementStage {
  // workflow_stage is the single source of truth — no log-count heuristics
  return taskItem.workflow_stage;
}

function hasRequirementUpdateLog(taskDevLogList: DevLog[]): boolean {
  return taskDevLogList.some((devLogItem) => {
    const parsedRequirementChange = parseRequirementChangeLog(devLogItem.text_content);
    return parsedRequirementChange?.kind === "update";
  });
}

function parseRequirementChangeLog(
  rawMarkdownText: string
): { kind: "update" | "delete"; title: string | null; summary: string } | null {
  const updateMatch = rawMarkdownText.includes(REQUIREMENT_UPDATE_MARKER);
  const deleteMatch = rawMarkdownText.includes(REQUIREMENT_DELETE_MARKER);

  if (!updateMatch && !deleteMatch) {
    return null;
  }

  const changeKind: "update" | "delete" = updateMatch ? "update" : "delete";
  const titleLabel = changeKind === "update" ? "Current Title:" : "Title:";
  const summaryLabel = changeKind === "update" ? "Summary:" : "Final Summary:";
  const title = extractMarkerField(rawMarkdownText, titleLabel);
  const summary = cleanMarkdownPreview(
    extractMarkerBody(rawMarkdownText, summaryLabel) || ""
  );

  return {
    kind: changeKind,
    title,
    summary,
  };
}

function extractMarkerField(
  rawMarkdownText: string,
  fieldLabel: string
): string | null {
  const fieldPattern = new RegExp(
    `${escapeRegExp(fieldLabel)}\\s*(.+)$`,
    "m"
  );
  const fieldMatch = rawMarkdownText.match(fieldPattern);
  return fieldMatch?.[1]?.trim() || null;
}

function extractMarkerBody(
  rawMarkdownText: string,
  sectionLabel: string
): string | null {
  const sectionPattern = new RegExp(
    `${escapeRegExp(sectionLabel)}\\n([\\s\\S]*)$`
  );
  const sectionMatch = rawMarkdownText.match(sectionPattern);
  return sectionMatch?.[1]?.trim() || null;
}

function buildRequirementUpdateLog(
  previousTitle: string,
  nextTitle: string,
  nextSummary: string
): string {
  return [
    REQUIREMENT_UPDATE_MARKER,
    "## Requirement Updated",
    "",
    `Previous Title: ${previousTitle}`,
    `Current Title: ${nextTitle}`,
    "",
    "Summary:",
    nextSummary,
  ].join("\n");
}

function buildRequirementDeleteLog(
  taskTitle: string,
  finalSummary: string
): string {
  return [
    REQUIREMENT_DELETE_MARKER,
    "## Requirement Deleted",
    "",
    `Title: ${taskTitle}`,
    "",
    "Final Summary:",
    finalSummary || "No requirement summary was captured before deletion.",
  ].join("\n");
}

function deriveTimelineKind(devLogItem: DevLog): TimelineKind {
  if (
    devLogItem.ai_processing_status &&
    devLogItem.ai_processing_status !== AIProcessingStatus.CONFIRMED
  ) {
    return "ai_log";
  }

  if (
    Boolean(devLogItem.ai_generated_title) ||
    Boolean(devLogItem.ai_analysis_text) ||
    Boolean(devLogItem.ai_extracted_code)
  ) {
    return "ai_log";
  }

  if (
    devLogItem.state_tag === DevLogStateTag.TRANSFERRED ||
    devLogItem.text_content.includes(REQUIREMENT_DELETE_MARKER)
  ) {
    return "system_event";
  }

  return "human_review";
}

function deriveTimelineAuthorName(
  timelineKind: TimelineKind,
  currentRunAccount: RunAccount | null
): string {
  if (timelineKind === "ai_log") {
    return "AI Agent";
  }

  if (timelineKind === "system_event") {
    return "System";
  }

  return currentRunAccount?.account_display_name || GUEST_USER_LABEL;
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

function truncateText(rawText: string, maxLength: number): string {
  if (rawText.length <= maxLength) {
    return rawText;
  }

  return `${rawText.slice(0, maxLength - 1).trimEnd()}…`;
}

function formatStageLabel(stage: RequirementStage): string {
  const stageLabelMap: Record<WorkflowStage, string> = {
    [WorkflowStage.BACKLOG]: "Backlog",
    [WorkflowStage.PRD_GENERATING]: "Drafting PRD",
    [WorkflowStage.PRD_WAITING_CONFIRMATION]: "PRD Ready",
    [WorkflowStage.IMPLEMENTATION_IN_PROGRESS]: "Coding",
    [WorkflowStage.SELF_REVIEW_IN_PROGRESS]: "Self Review",
    [WorkflowStage.TEST_IN_PROGRESS]: "Testing",
    [WorkflowStage.PR_PREPARING]: "PR Prep",
    [WorkflowStage.ACCEPTANCE_IN_PROGRESS]: "Acceptance",
    [WorkflowStage.CHANGES_REQUESTED]: "Changes Requested",
    [WorkflowStage.DONE]: "Done",
  };
  return stageLabelMap[stage] ?? stage.replace(/_/g, " ");
}

function formatFileSize(fileSizeBytes: number): string {
  if (fileSizeBytes < 1024) {
    return `${fileSizeBytes} B`;
  }

  if (fileSizeBytes < 1024 * 1024) {
    return `${(fileSizeBytes / 1024).toFixed(1)} KB`;
  }

  return `${(fileSizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

function sortTaskListByCreatedAt(taskList: Task[]): Task[] {
  return [...taskList].sort(
    (leftTask, rightTask) =>
      toTimestampValue(rightTask.created_at) - toTimestampValue(leftTask.created_at)
  );
}

function sortDevLogListByCreatedAt(devLogList: DevLog[]): DevLog[] {
  return [...devLogList].sort(
    (leftDevLog, rightDevLog) =>
      toTimestampValue(leftDevLog.created_at) - toTimestampValue(rightDevLog.created_at)
  );
}

function mapMediaPathToPublicUrl(rawMediaPath: string | null): string | null {
  if (!rawMediaPath) {
    return null;
  }

  const normalizedMediaPath = rawMediaPath.replace(/\\/g, "/").replace(/^\/+/, "");
  if (normalizedMediaPath.startsWith("data/media/")) {
    return `/${normalizedMediaPath.slice("data".length).replace(/^\/+/, "")}`;
  }

  if (normalizedMediaPath.startsWith("media/")) {
    return `/${normalizedMediaPath}`;
  }

  return `/${normalizedMediaPath}`;
}

function getWorkspaceHeading(workspaceView: WorkspaceView): string {
  if (workspaceView === "completed") {
    return "Completed Tasks";
  }

  if (workspaceView === "changes") {
    return "Changed Requirements";
  }

  return "Requirements";
}

function getWorkspaceEmptyState(workspaceView: WorkspaceView): string {
  if (workspaceView === "completed") {
    return "No completed requirements yet.";
  }

  if (workspaceView === "changes") {
    return "No modified or deleted requirements yet.";
  }

  return "No requirements yet.";
}

function getWorkspaceDetailEmptyState(workspaceView: WorkspaceView): string {
  if (workspaceView === "completed") {
    return "Select a completed requirement to inspect its archived history.";
  }

  if (workspaceView === "changes") {
    return "Select a modified or deleted requirement to inspect the appended change history.";
  }

  return "Select a requirement to view details and start the pipeline.";
}

function escapeRegExp(rawText: string): string {
  return rawText.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function joinClassNames(
  ...classNameList: Array<string | false | null | undefined>
): string {
  return classNameList.filter(Boolean).join(" ");
}

function isProjectSelectable(projectItem: Project): boolean {
  return (
    projectItem.is_repo_path_valid &&
    projectItem.is_repo_remote_consistent !== false
  );
}

function shortenCommitHash(rawCommitHash: string | null): string | null {
  if (!rawCommitHash) {
    return null;
  }

  return rawCommitHash.slice(0, 8);
}

function getProjectHealthState(projectItem: Project): {
  statusLabel: string;
  statusClassName: string;
  containerClassName: string | null;
  actionLabel: string;
  note: string | null;
  fingerprint: string | null;
} {
  if (!projectItem.is_repo_path_valid) {
    return {
      statusLabel: "Need relink",
      statusClassName: "devflow-project-item__status--invalid",
      containerClassName: "devflow-project-item--invalid",
      actionLabel: "Relink",
      note:
        projectItem.repo_consistency_note ??
        "This repo path is not valid on the current machine.",
      fingerprint: null,
    };
  }

  if (projectItem.is_repo_remote_consistent === false) {
    return {
      statusLabel: "Wrong repo",
      statusClassName: "devflow-project-item__status--invalid",
      containerClassName: "devflow-project-item--invalid",
      actionLabel: "Relink",
      note:
        projectItem.repo_consistency_note ??
        "Current repo origin does not match the stored synced fingerprint.",
      fingerprint: projectItem.repo_remote_url
        ? `Expected remote: ${projectItem.repo_remote_url}`
        : null,
    };
  }

  if (projectItem.is_repo_head_consistent === false) {
    const expectedCommitHash = shortenCommitHash(projectItem.repo_head_commit_hash);
    const currentCommitHash = shortenCommitHash(
      projectItem.current_repo_head_commit_hash
    );
    return {
      statusLabel: "Commit drift",
      statusClassName: "devflow-project-item__status--warning",
      containerClassName: "devflow-project-item--warning",
      actionLabel: "Edit",
      note:
        projectItem.repo_consistency_note ??
        "Current repo HEAD differs from the stored synced fingerprint.",
      fingerprint:
        expectedCommitHash && currentCommitHash
          ? `Expected ${expectedCommitHash} · Current ${currentCommitHash}`
          : null,
    };
  }

  if (projectItem.repo_consistency_note) {
    return {
      statusLabel: "Pending sync",
      statusClassName: "devflow-project-item__status--warning",
      containerClassName: "devflow-project-item--warning",
      actionLabel: "Edit",
      note: projectItem.repo_consistency_note,
      fingerprint: null,
    };
  }

  return {
    statusLabel: "Ready",
    statusClassName: "devflow-project-item__status--valid",
    containerClassName: null,
    actionLabel: "Edit",
    note: null,
    fingerprint: shortenCommitHash(projectItem.repo_head_commit_hash)
      ? `HEAD ${shortenCommitHash(projectItem.repo_head_commit_hash)}`
      : null,
  };
}

function PlusIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path
        d="M12 5v14M5 12h14"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ChevronRightIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path
        d="M9 6l6 6-6 6"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function HistoryIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path
        d="M3 12a9 9 0 109-9 8.96 8.96 0 00-6.36 2.64L3 8"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M3 3v5h5M12 7v5l3 2"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function FileTextIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path
        d="M14 2H7a2 2 0 00-2 2v16a2 2 0 002 2h10a2 2 0 002-2V7l-5-5z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M14 2v5h5M9 13h6M9 17h6M9 9h2"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CodeIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path
        d="M16 18l6-6-6-6M8 6l-6 6 6 6M14 4l-4 16"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function PlayIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path
        d="M8 5l11 7-11 7V5z"
        fill="currentColor"
        stroke="currentColor"
        strokeWidth="1.1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CheckCircleIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeWidth="1.8"
      />
      <path
        d="M8 12.5l2.5 2.5L16 9.5"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function EditIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path
        d="M12 20h9"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M16.5 3.5a2.12 2.12 0 113 3L7 19l-4 1 1-4 12.5-12.5z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ArchiveIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <rect
        x="3"
        y="4"
        width="18"
        height="5"
        rx="1.5"
        stroke="currentColor"
        strokeWidth="1.8"
      />
      <path
        d="M5 9h14v10a2 2 0 01-2 2H7a2 2 0 01-2-2V9zm5 4h4"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function TrashIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path
        d="M3 6h18M8 6V4h8v2m-9 0l1 14h8l1-14"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function PaperclipIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path
        d="M21.44 11.05l-8.49 8.49a6 6 0 11-8.49-8.49l9.19-9.19a4 4 0 115.66 5.66L10.12 17.7a2 2 0 11-2.83-2.83l8.48-8.49"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function XIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path
        d="M18 6L6 18M6 6l12 12"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function UserIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path
        d="M20 21a8 8 0 10-16 0"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx="12"
        cy="7"
        r="4"
        stroke="currentColor"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function RobotIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <rect
        x="5"
        y="8"
        width="14"
        height="10"
        rx="3"
        stroke="currentColor"
        strokeWidth="1.8"
      />
      <path
        d="M12 4v4M8.5 12h.01M15.5 12h.01M9 16h6"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function SendIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path
        d="M22 2L11 13"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M22 2l-7 20-4-9-9-4 20-7z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function RocketIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path
        d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 00-2.91-.09z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M12 15l-3-3a22 22 0 012-3.95A12.88 12.88 0 0122 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 01-4 2z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function TerminalIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <polyline
        points="4 17 10 11 4 5"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <line
        x1="12"
        y1="19"
        x2="20"
        y2="19"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

export default App;
