/** 主应用组件
 *
 * 将现有任务/日志数据映射为参考稿风格的 AI DEVFLOW 仪表盘。
 */

import type {
  ChangeEvent,
  ClipboardEvent,
  Dispatch,
  KeyboardEvent,
  ReactNode,
  SetStateAction,
  SVGProps,
} from "react";
import {
  Children as ReactChildren,
  isValidElement,
  memo,
  startTransition,
  useDeferredValue,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  appConfigApi,
  logApi,
  mediaApi,
  projectApi,
  runAccountApi,
  taskScheduleApi,
  taskApi,
} from "./api/client";
import { SettingsModal } from "./components/SettingsModal";
import {
  configureAppTimezone,
  formatDateTime,
  formatHourMinute,
  toTimestampValue,
} from "./utils/datetime";
import {
  AIProcessingStatus,
  DevLogStateTag,
  TaskScheduleActionType,
  TaskScheduleRunStatus,
  TaskScheduleTriggerType,
  type TaskCardMetadata,
  type TaskDisplayStageKey,
  TaskLifecycleStatus,
  WorkflowStage,
  type DevLog,
  type Project,
  type RunAccount,
  type Task,
  type TaskSchedule,
  type TaskScheduleRun,
} from "./types";

type RequirementStage = WorkflowStage;
type RequirementDisplayStage = TaskDisplayStageKey;

type TimelineKind = "ai_log" | "human_review" | "system_event";
type CompactTimelineCategory =
  | "general"
  | "prd"
  | "coding"
  | "review"
  | "test"
  | "delivery"
  | "system"
  | "changes";
type WorkspaceView = "active" | "completed" | "changes";
type AttachmentKind = "image" | "video" | "file";

interface RequirementViewModel {
  task: Task;
  description: string;
  displayStage: RequirementDisplayStage;
  displayStageLabel: string;
  cardMetaLabel: string;
  cardMetaTitle: string;
}

interface TimelineViewModel {
  log: DevLog;
  kind: TimelineKind;
  authorName: string;
  timeLabel: string;
}

interface CompactTimelineGroup {
  groupId: string;
  items: TimelineViewModel[];
  category: CompactTimelineCategory;
  label: string;
  tone: "default" | "error" | "success";
}

type TimelineRenderBlock =
  | {
      kind: "human";
      item: TimelineViewModel;
    }
  | {
      kind: "compact_group";
      group: CompactTimelineGroup;
    };

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
  | "open_editor"
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
const SELF_REVIEW_PASSED_LOG_MARKER_LIST = [
  "AI 自检闭环完成",
  "AI 自检完成，未发现阻塞性问题",
];
const SELF_REVIEW_STARTED_LOG_MARKER_LIST = [
  "开始第 1 轮代码评审",
  "开始执行代码评审",
];
const POST_REVIEW_LINT_PASSED_LOG_MARKER_LIST = [
  "post-review lint 闭环完成：pre-commit 已通过",
];
const POST_REVIEW_LINT_STARTED_LOG_MARKER_LIST = [
  "已进入自动化验证阶段，开始执行 post-review lint：",
  "post-review lint 未通过，开始第 ",
  "轮 AI lint 定向修复完成，开始重新执行 pre-commit lint。",
];
const RESUMABLE_AUTOMATION_STAGE_SET = new Set<WorkflowStage>([
  WorkflowStage.PRD_GENERATING,
  WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
  WorkflowStage.SELF_REVIEW_IN_PROGRESS,
  WorkflowStage.TEST_IN_PROGRESS,
  WorkflowStage.PR_PREPARING,
]);
const ACTIVE_DASHBOARD_POLL_INTERVAL_MS = 3000;
const TASK_CARD_METADATA_POLL_INTERVAL_MS = 60_000;
const SELECTED_TASK_LOG_POLL_INTERVAL_MS = 2000;
const SELECTED_TASK_LOG_INITIAL_LIMIT = 300;
const SELECTED_TASK_LOG_OLDER_BATCH_LIMIT = 300;
const SELECTED_TASK_LOG_INCREMENTAL_LIMIT = 200;
const SELECTED_TASK_SCHEDULE_POLL_INTERVAL_MS = 20_000;
const SELECTED_TASK_SCHEDULE_RUN_LIMIT = 20;
const INITIAL_VISIBLE_CONVERSATION_TURN_COUNT = 12;
const VISIBLE_CONVERSATION_TURN_INCREMENT = 20;
const COMPACT_TIMELINE_GROUP_VISIBLE_COUNT = 3;
const COMPACT_TIMELINE_GROUP_MAX_SIZE = 6;
const COMPACT_TIMELINE_ALERT_GROUP_VISIBLE_COUNT = 5;
const MARKDOWN_REMARK_PLUGIN_LIST = [remarkGfm];
const MARKDOWN_MERMAID_LANGUAGE_PATTERN = /\blanguage-mermaid\b/;
const IMAGE_FILE_NAME_PATTERN = /\.(avif|bmp|gif|heic|heif|jpe?g|png|svg|webp)$/i;
const VIDEO_FILE_NAME_PATTERN = /\.(avi|m4v|mkv|mov|mp4|ogg|ogv|webm)$/i;
const PRD_RELEVANT_STAGE_SET = new Set<WorkflowStage>([
  WorkflowStage.PRD_WAITING_CONFIRMATION,
  WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
  WorkflowStage.SELF_REVIEW_IN_PROGRESS,
  WorkflowStage.TEST_IN_PROGRESS,
  WorkflowStage.PR_PREPARING,
  WorkflowStage.ACCEPTANCE_IN_PROGRESS,
  WorkflowStage.CHANGES_REQUESTED,
]);
const WAITING_USER_METADATA_CANDIDATE_STAGE_SET = new Set<WorkflowStage>([
  WorkflowStage.SELF_REVIEW_IN_PROGRESS,
  WorkflowStage.TEST_IN_PROGRESS,
]);

let hasInitializedMermaidRenderer = false;

function _isContinueCommand(text: string): boolean {
  const trimmed = text.trim();
  return CONTINUE_COMMAND_PATTERNS.some((pattern) => pattern.test(trimmed));
}

function resolveBrowserTimezoneName(): string | null {
  const browserTimezoneName = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const normalizedTimezoneName = browserTimezoneName?.trim();
  if (!normalizedTimezoneName) {
    return null;
  }
  return normalizedTimezoneName;
}

function convertDatetimeLocalValueToUtcIso(rawDatetimeLocalValue: string): string | null {
  const normalizedDatetimeLocalValue = rawDatetimeLocalValue.trim();
  if (!normalizedDatetimeLocalValue) {
    return null;
  }
  const parsedLocalDatetime = new Date(normalizedDatetimeLocalValue);
  if (Number.isNaN(parsedLocalDatetime.getTime())) {
    return null;
  }
  return parsedLocalDatetime.toISOString();
}

function isLikelyImageFile(nextFile: File): boolean {
  const normalizedFileType = nextFile.type.trim().toLowerCase();
  const normalizedFileName = nextFile.name.trim().toLowerCase();
  return (
    normalizedFileType.startsWith("image/") ||
    IMAGE_FILE_NAME_PATTERN.test(normalizedFileName)
  );
}

function isLikelyVideoFile(nextFile: File): boolean {
  const normalizedFileType = nextFile.type.trim().toLowerCase();
  const normalizedFileName = nextFile.name.trim().toLowerCase();
  return (
    normalizedFileType.startsWith("video/") ||
    VIDEO_FILE_NAME_PATTERN.test(normalizedFileName)
  );
}

function guessMimeTypeFromFileName(fileName: string): string {
  const normalizedFileName = fileName.trim().toLowerCase();
  if (normalizedFileName.endsWith(".png")) {
    return "image/png";
  }
  if (normalizedFileName.endsWith(".jpg") || normalizedFileName.endsWith(".jpeg")) {
    return "image/jpeg";
  }
  if (normalizedFileName.endsWith(".gif")) {
    return "image/gif";
  }
  if (normalizedFileName.endsWith(".webp")) {
    return "image/webp";
  }
  if (normalizedFileName.endsWith(".bmp")) {
    return "image/bmp";
  }
  if (normalizedFileName.endsWith(".mp4") || normalizedFileName.endsWith(".m4v")) {
    return "video/mp4";
  }
  if (normalizedFileName.endsWith(".webm")) {
    return "video/webm";
  }
  if (normalizedFileName.endsWith(".mov")) {
    return "video/quicktime";
  }
  if (normalizedFileName.endsWith(".avi")) {
    return "video/x-msvideo";
  }
  if (normalizedFileName.endsWith(".mkv")) {
    return "video/x-matroska";
  }
  if (
    normalizedFileName.endsWith(".ogv") ||
    normalizedFileName.endsWith(".ogg")
  ) {
    return "video/ogg";
  }
  return "";
}

function normalizeClipboardFile(rawClipboardFile: File, fallbackType: string): File {
  const normalizedFileType =
    rawClipboardFile.type ||
    fallbackType ||
    guessMimeTypeFromFileName(rawClipboardFile.name) ||
    "application/octet-stream";
  const normalizedFileExtension = normalizedFileType.startsWith("image/")
    ? normalizedFileType.slice("image/".length).replace(/^x-/, "") || "png"
    : "bin";
  const normalizedFileName =
    rawClipboardFile.name ||
    (normalizedFileType.startsWith("image/")
      ? `clipboard-image.${normalizedFileExtension}`
      : `clipboard-file.${normalizedFileExtension}`);

  if (
    rawClipboardFile.type === normalizedFileType &&
    rawClipboardFile.name === normalizedFileName
  ) {
    return rawClipboardFile;
  }

  return new File([rawClipboardFile], normalizedFileName, {
    type: normalizedFileType,
    lastModified: rawClipboardFile.lastModified,
  });
}

function buildAttachmentDraftFromFile(nextFile: File): AttachmentDraft {
  const isImageFile = isLikelyImageFile(nextFile);
  const isVideoFile = !isImageFile && isLikelyVideoFile(nextFile);
  return {
    file: nextFile,
    kind: isImageFile ? "image" : isVideoFile ? "video" : "file",
    previewUrl: isImageFile || isVideoFile ? URL.createObjectURL(nextFile) : null,
  };
}

function getClipboardFile(
  clipboardEvent: ClipboardEvent<HTMLTextAreaElement>
): File | null {
  const clipboardItemList = Array.from(clipboardEvent.clipboardData.items);
  for (const clipboardItem of clipboardItemList) {
    if (clipboardItem.kind !== "file") {
      continue;
    }

    const rawClipboardFile = clipboardItem.getAsFile();
    if (!rawClipboardFile) {
      continue;
    }

    return normalizeClipboardFile(rawClipboardFile, clipboardItem.type);
  }

  const fallbackClipboardFile = clipboardEvent.clipboardData.files.item(0);
  if (!fallbackClipboardFile) {
    return null;
  }

  return normalizeClipboardFile(
    fallbackClipboardFile,
    guessMimeTypeFromFileName(fallbackClipboardFile.name)
  );
}

function buildRequirementBrief(
  rawRequirementDescription: string,
  attachmentDraft: AttachmentDraft | null,
  fallbackRequirementBrief: string | null = null
): string | null {
  const trimmedRequirementDescription = rawRequirementDescription.trim();
  if (trimmedRequirementDescription) {
    return trimmedRequirementDescription;
  }

  const trimmedFallbackRequirementBrief = fallbackRequirementBrief?.trim() ?? "";
  if (trimmedFallbackRequirementBrief) {
    return trimmedFallbackRequirementBrief;
  }

  if (!attachmentDraft) {
    return null;
  }

  const attachmentLabel =
    attachmentDraft.kind === "image"
      ? "Attached image"
      : attachmentDraft.kind === "video"
        ? "Attached video"
        : "Attached file";
  return `${attachmentLabel}: ${attachmentDraft.file.name || "clipboard-upload"}`;
}

function getAttachmentLabel(attachmentKind: AttachmentKind): string {
  if (attachmentKind === "image") {
    return "Image attachment";
  }
  if (attachmentKind === "video") {
    return "Video attachment";
  }
  return "File attachment";
}

function renderAttachmentPreview(attachmentDraft: AttachmentDraft): ReactNode {
  if (!attachmentDraft.previewUrl) {
    return (
      <span className="devflow-feedback__attachment-icon">
        <PaperclipIcon className="devflow-icon devflow-icon--small" />
      </span>
    );
  }

  if (attachmentDraft.kind === "video") {
    return (
      <video
        className="devflow-feedback__attachment-preview"
        src={attachmentDraft.previewUrl}
        muted
        playsInline
        preload="metadata"
      />
    );
  }

  return (
    <img
      className="devflow-feedback__attachment-preview"
      src={attachmentDraft.previewUrl}
      alt={attachmentDraft.file.name}
    />
  );
}

function App() {
  const createRequirementAttachmentInputRef = useRef<HTMLInputElement | null>(null);
  const editRequirementAttachmentInputRef = useRef<HTMLInputElement | null>(null);
  const feedbackAttachmentInputRef = useRef<HTMLInputElement | null>(null);
  const latestTaskListRef = useRef<Task[]>([]);

  const [currentRunAccount, setCurrentRunAccount] = useState<RunAccount | null>(null);
  const [taskList, setTaskList] = useState<Task[]>([]);
  const [taskCardMetadataMap, setTaskCardMetadataMap] = useState<
    Record<string, TaskCardMetadata>
  >({});
  const [allDevLogList, setAllDevLogList] = useState<DevLog[]>([]);
  const [selectedTaskLogList, setSelectedTaskLogList] = useState<DevLog[]>([]);
  const [projectList, setProjectList] = useState<Project[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [workspaceView, setWorkspaceView] = useState<WorkspaceView>("active");
  const [isCreatePanelOpen, setIsCreatePanelOpen] = useState(false);
  const [isEditPanelOpen, setIsEditPanelOpen] = useState(false);
  const [newRequirementTitle, setNewRequirementTitle] = useState("");
  const [newRequirementDescription, setNewRequirementDescription] = useState("");
  const [createRequirementAttachmentDraft, setCreateRequirementAttachmentDraft] =
    useState<AttachmentDraft | null>(null);
  const [newRequirementProjectId, setNewRequirementProjectId] = useState<string | null>(null);
  const [
    isAutoConfirmPrdAndExecuteEnabled,
    setIsAutoConfirmPrdAndExecuteEnabled,
  ] = useState(false);
  const [editRequirementTitle, setEditRequirementTitle] = useState("");
  const [editRequirementDescription, setEditRequirementDescription] = useState("");
  const [editRequirementAttachmentDraft, setEditRequirementAttachmentDraft] =
    useState<AttachmentDraft | null>(null);
  const [feedbackInputText, setFeedbackInputText] = useState("");
  const [feedbackAttachmentDraft, setFeedbackAttachmentDraft] =
    useState<AttachmentDraft | null>(null);
  const [activeMutationName, setActiveMutationName] = useState<MutationName>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isDashboardLoading, setIsDashboardLoading] = useState(true);
  const [prdFileContent, setPrdFileContent] = useState<string | null>(null);
  const [isPrdFullscreenOpen, setIsPrdFullscreenOpen] = useState(false);
  const [isProjectPanelOpen, setIsProjectPanelOpen] = useState(false);
  const [visibleConversationTurnCount, setVisibleConversationTurnCount] = useState(
    INITIAL_VISIBLE_CONVERSATION_TURN_COUNT
  );
  const [expandedCompactTimelineGroupIdSet, setExpandedCompactTimelineGroupIdSet] =
    useState<Set<string>>(new Set());
  const [expandedCompactTimelineItemId, setExpandedCompactTimelineItemId] =
    useState<string | null>(null);
  const [isRequirementSummaryExpanded, setIsRequirementSummaryExpanded] =
    useState(false);
  const [isLoadingOlderTaskLogs, setIsLoadingOlderTaskLogs] = useState(false);
  const [, setAppTimezoneRevision] = useState(0);
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectPath, setNewProjectPath] = useState("");
  const [newProjectDescription, setNewProjectDescription] = useState("");
  const [editingProjectId, setEditingProjectId] = useState<string | null>(null);
  const [editingProjectName, setEditingProjectName] = useState("");
  const [editingProjectPath, setEditingProjectPath] = useState("");
  const [editingProjectDescription, setEditingProjectDescription] = useState("");
  const [isEmailSettingsOpen, setIsEmailSettingsOpen] = useState(false);
  const [selectedTaskScheduleList, setSelectedTaskScheduleList] = useState<TaskSchedule[]>(
    []
  );
  const [selectedTaskScheduleRunList, setSelectedTaskScheduleRunList] = useState<
    TaskScheduleRun[]
  >([]);
  const [isTaskSchedulePanelLoading, setIsTaskSchedulePanelLoading] = useState(false);
  const [isTaskScheduleCreating, setIsTaskScheduleCreating] = useState(false);
  const [activeTaskScheduleActionKey, setActiveTaskScheduleActionKey] = useState<
    string | null
  >(null);
  const [taskScheduleDraftName, setTaskScheduleDraftName] = useState("");
  const [taskScheduleDraftActionType, setTaskScheduleDraftActionType] =
    useState<TaskScheduleActionType>(TaskScheduleActionType.START_TASK);
  const [taskScheduleDraftTriggerType, setTaskScheduleDraftTriggerType] =
    useState<TaskScheduleTriggerType>(TaskScheduleTriggerType.ONCE);
  const [taskScheduleDraftRunAtText, setTaskScheduleDraftRunAtText] = useState("");
  const [taskScheduleDraftCronExprText, setTaskScheduleDraftCronExprText] = useState("");
  const [taskScheduleDraftIsEnabled, setTaskScheduleDraftIsEnabled] = useState(true);

  function resetCreateRequirementDraft(nextProjectId: string | null = null): void {
    setNewRequirementTitle("");
    setNewRequirementDescription("");
    setCreateRequirementAttachmentDraft((previousAttachmentDraft) => {
      if (previousAttachmentDraft?.previewUrl) {
        URL.revokeObjectURL(previousAttachmentDraft.previewUrl);
      }
      return null;
    });
    if (createRequirementAttachmentInputRef.current) {
      createRequirementAttachmentInputRef.current.value = "";
    }
    setNewRequirementProjectId(nextProjectId);
    setIsAutoConfirmPrdAndExecuteEnabled(false);
  }

  function openCreateRequirementPanel(): void {
    resetCreateRequirementDraft();
    setIsCreatePanelOpen(true);
    setErrorMessage(null);
    setSuccessMessage(null);
  }

  function resetEditRequirementDraft(): void {
    setEditRequirementTitle("");
    setEditRequirementDescription("");
    setEditRequirementAttachmentDraft((previousAttachmentDraft) => {
      if (previousAttachmentDraft?.previewUrl) {
        URL.revokeObjectURL(previousAttachmentDraft.previewUrl);
      }
      return null;
    });
    if (editRequirementAttachmentInputRef.current) {
      editRequirementAttachmentInputRef.current.value = "";
    }
  }

  function closeRequirementEditor(): void {
    setIsEditPanelOpen(false);
    resetEditRequirementDraft();
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
    if (!isProjectPanelOpen) {
      return;
    }
    void loadProjectList();
  }, [isProjectPanelOpen]);

  useEffect(() => {
    return () => {
      if (createRequirementAttachmentDraft?.previewUrl) {
        URL.revokeObjectURL(createRequirementAttachmentDraft.previewUrl);
      }
    };
  }, [createRequirementAttachmentDraft]);

  useEffect(() => {
    return () => {
      if (editRequirementAttachmentDraft?.previewUrl) {
        URL.revokeObjectURL(editRequirementAttachmentDraft.previewUrl);
      }
    };
  }, [editRequirementAttachmentDraft]);

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

  const devLogsByTaskId = useMemo(
    () => buildDevLogsByTaskId(allDevLogList),
    [allDevLogList]
  );
  const activeTaskList = useMemo(
    () =>
      taskList.filter(
        (taskItem) =>
          taskItem.lifecycle_status !== TaskLifecycleStatus.CLOSED &&
          taskItem.lifecycle_status !== TaskLifecycleStatus.DELETED &&
          !hasRequirementUpdateLog(devLogsByTaskId[taskItem.id] ?? [])
      ),
    [taskList, devLogsByTaskId]
  );
  const completedTaskList = useMemo(
    () =>
      taskList.filter(
        (taskItem) => taskItem.lifecycle_status === TaskLifecycleStatus.CLOSED
      ),
    [taskList]
  );
  const changedTaskList = useMemo(
    () =>
      taskList.filter((taskItem) => {
        const taskDevLogList = devLogsByTaskId[taskItem.id] ?? [];
        return (
          taskItem.lifecycle_status === TaskLifecycleStatus.DELETED ||
          (taskItem.lifecycle_status !== TaskLifecycleStatus.CLOSED &&
            hasRequirementUpdateLog(taskDevLogList))
        );
      }),
    [taskList, devLogsByTaskId]
  );
  const visibleTaskList = useMemo(() => {
    if (workspaceView === "completed") {
      return completedTaskList;
    }

    if (workspaceView === "changes") {
      return changedTaskList;
    }

    return activeTaskList;
  }, [activeTaskList, changedTaskList, completedTaskList, workspaceView]);
  const visibleTaskIds = useMemo(
    () => visibleTaskList.map((taskItem) => taskItem.id).join(","),
    [visibleTaskList]
  );
  const deferredSelectedTaskId = useDeferredValue(selectedTaskId);
  const detailTaskId = deferredSelectedTaskId;
  const isTaskSelectionPending =
    selectedTaskId !== null && selectedTaskId !== deferredSelectedTaskId;
  // Primary: find in current workspace view.
  // Fallback: find in full task list so the timeline never disappears when a task
  // transitions to a different workspace view (e.g. CLOSED → completed tab).
  const selectedTask = useMemo(
    () =>
      visibleTaskList.find((taskItem) => taskItem.id === detailTaskId) ??
      (detailTaskId
        ? taskList.find((taskItem) => taskItem.id === detailTaskId) ?? null
        : null),
    [detailTaskId, taskList, visibleTaskList]
  );
  const selectedTaskDevLogs = useMemo(() => {
    if (!selectedTask) {
      return [];
    }

    return selectedTaskLogList.length > 0
      ? selectedTaskLogList
      : devLogsByTaskId[selectedTask.id] ?? [];
  }, [devLogsByTaskId, selectedTask, selectedTaskLogList]);
  const selectedTaskCardMetadata = useMemo(
    () =>
      selectedTask
        ? resolveTaskCardMetadata(selectedTask, taskCardMetadataMap)
        : null,
    [selectedTask, taskCardMetadataMap]
  );
  const selectedTaskSnapshot = useMemo(
    () =>
      selectedTask
        ? deriveRequirementSnapshot(selectedTask, selectedTaskDevLogs)
        : null,
    [selectedTask, selectedTaskDevLogs]
  );
  const selectedTaskSummaryText =
    selectedTaskSnapshot?.summary || "No requirement brief captured yet.";
  const isSelectedTaskSummaryExpandable = useMemo(
    () => shouldAllowRequirementSummaryExpansion(selectedTaskSummaryText),
    [selectedTaskSummaryText]
  );
  const hasProjectConsistencyIssues = useMemo(
    () =>
      projectList.some(
        (projectItem) =>
          !isProjectSelectable(projectItem) ||
          projectItem.is_repo_head_consistent === false
      ),
    [projectList]
  );
  const requirementViewModelList = useMemo(
    () =>
      visibleTaskList.map((taskItem) =>
        buildRequirementViewModel(
          taskItem,
          devLogsByTaskId[taskItem.id] ?? [],
          resolveTaskCardMetadata(taskItem, taskCardMetadataMap)
        )
      ),
    [devLogsByTaskId, taskCardMetadataMap, visibleTaskList]
  );
  const selectedTimelineItemList = useMemo(
    () =>
      selectedTask
        ? selectedTaskDevLogs.map((devLogItem) =>
            buildTimelineViewModel(devLogItem, currentRunAccount))
        : [],
    [currentRunAccount, selectedTask, selectedTaskDevLogs]
  );
  const selectedTaskStage = useMemo(
    () =>
      selectedTask
        ? deriveRequirementStage(selectedTask, selectedTaskDevLogs)
        : null,
    [selectedTask, selectedTaskDevLogs]
  );
  const visibleTimelineItemList = useMemo(
    () =>
      visibleConversationTurnCount >= selectedTimelineItemList.length
        ? selectedTimelineItemList
        : selectedTimelineItemList.slice(-visibleConversationTurnCount),
    [selectedTimelineItemList, visibleConversationTurnCount]
  );
  const hiddenTimelineItemCount = Math.max(
    0,
    selectedTimelineItemList.length - visibleTimelineItemList.length
  );
  const timelineRenderBlockList = useMemo(
    () => buildTimelineRenderBlockList(visibleTimelineItemList),
    [visibleTimelineItemList]
  );
  const activeCompactTimelineCategory = useMemo(
    () => mapWorkflowStageToCompactTimelineCategory(selectedTaskStage),
    [selectedTaskStage]
  );
  const latestCompactTimelineGroupId = useMemo(
    () =>
      [...timelineRenderBlockList]
        .reverse()
        .find(
          (timelineRenderBlock): timelineRenderBlock is Extract<
            TimelineRenderBlock,
            { kind: "compact_group" }
          > => timelineRenderBlock.kind === "compact_group"
        )?.group.groupId ?? null,
    [timelineRenderBlockList]
  );
  const renderedCompactTimelineItemList = useMemo(
    () =>
      timelineRenderBlockList.flatMap((timelineRenderBlock) => {
        if (timelineRenderBlock.kind !== "compact_group") {
          return [];
        }

        return getVisibleCompactTimelineItemList(
          timelineRenderBlock.group,
          expandedCompactTimelineGroupIdSet.has(timelineRenderBlock.group.groupId)
        );
      }),
    [expandedCompactTimelineGroupIdSet, timelineRenderBlockList]
  );
  const selectedCompactTimelineItem = useMemo(
    () =>
      expandedCompactTimelineItemId
        ? selectedTimelineItemList.find(
            (timelineItem) => timelineItem.log.id === expandedCompactTimelineItemId
          ) ?? null
        : null,
    [expandedCompactTimelineItemId, selectedTimelineItemList]
  );
  const selectedCompactTimelineItemIndex = useMemo(
    () =>
      selectedCompactTimelineItem
        ? renderedCompactTimelineItemList.findIndex(
            (timelineItem) => timelineItem.log.id === selectedCompactTimelineItem.log.id
          )
        : -1,
    [renderedCompactTimelineItemList, selectedCompactTimelineItem]
  );
  const previousCompactTimelineItem =
    selectedCompactTimelineItemIndex > 0
      ? renderedCompactTimelineItemList[selectedCompactTimelineItemIndex - 1]
      : null;
  const nextCompactTimelineItem =
    selectedCompactTimelineItemIndex >= 0 &&
    selectedCompactTimelineItemIndex < renderedCompactTimelineItemList.length - 1
      ? renderedCompactTimelineItemList[selectedCompactTimelineItemIndex + 1]
      : null;
  const canLoadOlderTaskLogs =
    selectedTask !== null &&
    selectedTaskLogList.length > 0 &&
    selectedTaskLogList.length < selectedTask.log_count;
  const selectedTaskDocumentMarkdown = useMemo(
    () =>
      selectedTask
        ? buildTaskDocumentMarkdown(
            selectedTask,
            selectedTaskDevLogs,
            currentRunAccount
          )
        : "",
    [currentRunAccount, selectedTask, selectedTaskDevLogs]
  );
  const isSelectedTaskPrdGenerating =
    selectedTaskStage === WorkflowStage.PRD_GENERATING;
  const shouldRenderPersistedPrdFile =
    Boolean(prdFileContent) &&
    selectedTaskStage !== WorkflowStage.BACKLOG &&
    selectedTaskStage !== WorkflowStage.DONE &&
    !isSelectedTaskPrdGenerating;
  const selectedTaskPrdMarkdown = shouldRenderPersistedPrdFile
    ? prdFileContent ?? ""
    : selectedTaskDocumentMarkdown;
  const currentUserLabel =
    currentRunAccount?.account_display_name || GUEST_USER_LABEL;
  const canCreateRequirements = workspaceView === "active";
  const selectedTaskHasSettledSelfReview = useMemo(
    () =>
      selectedTask
        ? hasLatestSelfReviewCyclePassed(selectedTaskDevLogs)
        : false,
    [selectedTask, selectedTaskDevLogs]
  );
  const selectedTaskHasSettledPostReviewLint = useMemo(
    () =>
      selectedTask
        ? hasLatestPostReviewLintCyclePassed(selectedTaskDevLogs)
        : false,
    [selectedTask, selectedTaskDevLogs]
  );
  const selectedTaskStageLabel = useMemo(
    () => selectedTaskCardMetadata?.display_stage_label ?? null,
    [selectedTaskCardMetadata]
  );
  const selectedTaskDisplayStage = useMemo(
    () => selectedTaskCardMetadata?.display_stage_key ?? null,
    [selectedTaskCardMetadata]
  );
  const selectedTaskAiActivityLabel = useMemo(
    () =>
      formatTaskCardActivityLabel(selectedTaskCardMetadata?.last_ai_activity_at ?? null),
    [selectedTaskCardMetadata]
  );
  const selectedTaskAiActivityTitle = useMemo(
    () =>
      formatTaskCardActivityTitle(selectedTaskCardMetadata?.last_ai_activity_at ?? null),
    [selectedTaskCardMetadata]
  );
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

  const isSelectedTaskInActiveExecution =
    selectedTask?.is_codex_task_running ?? false;
  const hasAnyTaskInActiveExecution = useMemo(
    () => taskList.some((taskItem) => taskItem.is_codex_task_running),
    [taskList]
  );
  const canCompleteSelectedTask = selectedTask
    ? canCompleteTask(selectedTask, selectedTaskStage) &&
      !selectedTask.is_codex_task_running
    : false;
  const selectedTaskScheduleNameMap = useMemo(() => {
    return selectedTaskScheduleList.reduce<Record<string, string>>(
      (scheduleNameMap, taskScheduleItem) => {
        scheduleNameMap[taskScheduleItem.id] = taskScheduleItem.schedule_name;
        return scheduleNameMap;
      },
      {}
    );
  }, [selectedTaskScheduleList]);

  useEffect(() => {
    latestTaskListRef.current = taskList;
  }, [taskList]);

  useEffect(() => {
    if (!hasAnyTaskInActiveExecution) {
      return;
    }
    const pollingIntervalId = window.setInterval(() => {
      void loadDashboardData(true, {
        includeGlobalLogs: false,
        includeTaskCardMetadata: false,
      });
    }, ACTIVE_DASHBOARD_POLL_INTERVAL_MS);
    return () => {
      window.clearInterval(pollingIntervalId);
    };
  }, [hasAnyTaskInActiveExecution]);

  async function refreshTaskCardMetadata(options?: {
    fallbackTaskList?: Task[];
    errorLabel?: string;
  }): Promise<void> {
    const fallbackTaskList = options?.fallbackTaskList ?? latestTaskListRef.current;
    try {
      const taskCardMetadataList = await taskApi.listCardMetadata();
      setTaskCardMetadataMap(buildTaskCardMetadataMap(taskCardMetadataList));
    } catch (taskCardMetadataError) {
      console.error(
        options?.errorLabel ?? "Failed to load task card metadata:",
        taskCardMetadataError
      );
      setTaskCardMetadataMap((previousTaskCardMetadataMap) =>
        buildTaskCardMetadataFallbackMap(
          fallbackTaskList,
          previousTaskCardMetadataMap
        )
      );
    }
  }

  useEffect(() => {
    const pollTaskCardMetadata = () => {
      void refreshTaskCardMetadata();
    };

    pollTaskCardMetadata();
    const metadataPollIntervalId = window.setInterval(
      pollTaskCardMetadata,
      TASK_CARD_METADATA_POLL_INTERVAL_MS
    );
    return () => {
      window.clearInterval(metadataPollIntervalId);
    };
  }, []);

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
    setSelectedTaskLogList([]);
    setIsLoadingOlderTaskLogs(false);
    setIsRequirementSummaryExpanded(false);
    setIsPrdFullscreenOpen(false);
    setExpandedCompactTimelineGroupIdSet(new Set());
    setExpandedCompactTimelineItemId(null);
    setSelectedTaskScheduleList([]);
    setSelectedTaskScheduleRunList([]);
    setTaskScheduleDraftName("");
    setTaskScheduleDraftActionType(TaskScheduleActionType.START_TASK);
    setTaskScheduleDraftTriggerType(TaskScheduleTriggerType.ONCE);
    setTaskScheduleDraftRunAtText("");
    setTaskScheduleDraftCronExprText("");
    setTaskScheduleDraftIsEnabled(true);
  }, [workspaceView, detailTaskId]);

  useEffect(() => {
    setVisibleConversationTurnCount(INITIAL_VISIBLE_CONVERSATION_TURN_COUNT);
    setIsLoadingOlderTaskLogs(false);
    setIsRequirementSummaryExpanded(false);
    setExpandedCompactTimelineGroupIdSet(new Set());
    setExpandedCompactTimelineItemId(null);
  }, [detailTaskId]);

  useEffect(() => {
    if (!expandedCompactTimelineItemId) {
      return;
    }

    if (
      selectedTimelineItemList.some(
        (timelineItem) => timelineItem.log.id === expandedCompactTimelineItemId
      )
    ) {
      return;
    }

    setExpandedCompactTimelineItemId(null);
  }, [expandedCompactTimelineItemId, selectedTimelineItemList]);

  useEffect(() => {
    if (!isPrdFullscreenOpen) {
      return;
    }

    function handlePrdFullscreenKeydown(
      keyboardEvent: globalThis.KeyboardEvent
    ): void {
      if (keyboardEvent.key !== "Escape") {
        return;
      }

      keyboardEvent.preventDefault();
      setIsPrdFullscreenOpen(false);
    }

    window.addEventListener("keydown", handlePrdFullscreenKeydown);
    return () => {
      window.removeEventListener("keydown", handlePrdFullscreenKeydown);
    };
  }, [isPrdFullscreenOpen]);

  // 仅在切换任务时清空 PRD 内容，避免 taskList 每秒刷新触发闪烁
  useEffect(() => {
    setPrdFileContent(null);
  }, [detailTaskId]);

  // 按任务拉取完整日志列表，避免全局 100 条限制导致时间线空白
  useEffect(() => {
    if (!detailTaskId) {
      setSelectedTaskLogList([]);
      return;
    }

    let cancelled = false;
    let latestSelectedTaskLogCreatedAtText: string | null = null;
    let hasLoadedInitialLogBatch = false;

    const fetchInitialTaskLogBatch = async () => {
      try {
        const initialTaskLogList = await logApi.list(
          detailTaskId,
          SELECTED_TASK_LOG_INITIAL_LIMIT
        );
        if (cancelled) {
          return;
        }
        const sortedInitialTaskLogList = sortDevLogListByCreatedAt(initialTaskLogList);
        latestSelectedTaskLogCreatedAtText =
          sortedInitialTaskLogList[sortedInitialTaskLogList.length - 1]?.created_at ?? null;
        hasLoadedInitialLogBatch = true;
        setSelectedTaskLogList(sortedInitialTaskLogList);
      } catch {
        hasLoadedInitialLogBatch = true;
      }
    };

    const fetchIncrementalTaskLogBatch = async () => {
      if (!hasLoadedInitialLogBatch) {
        return;
      }

      try {
        const incrementalTaskLogList = await logApi.list(
          detailTaskId,
          latestSelectedTaskLogCreatedAtText
            ? SELECTED_TASK_LOG_INCREMENTAL_LIMIT
            : 1,
          latestSelectedTaskLogCreatedAtText
            ? { createdAfter: latestSelectedTaskLogCreatedAtText }
            : undefined
        );
        if (cancelled || incrementalTaskLogList.length === 0) {
          return;
        }

        const sortedIncrementalTaskLogList = sortDevLogListByCreatedAt(
          incrementalTaskLogList
        );
        latestSelectedTaskLogCreatedAtText =
          sortedIncrementalTaskLogList[sortedIncrementalTaskLogList.length - 1]?.created_at
          ?? latestSelectedTaskLogCreatedAtText;
        setSelectedTaskLogList((previousTaskLogList) =>
          latestSelectedTaskLogCreatedAtText === null
            ? sortedIncrementalTaskLogList
            : appendIncrementalDevLogList(
                previousTaskLogList,
                sortedIncrementalTaskLogList
              )
        );
      } catch {
        // Ignore transient polling failures and let the next interval retry.
      }
    };

    void fetchInitialTaskLogBatch();
    const pollId = window.setInterval(() => {
      void fetchIncrementalTaskLogBatch();
    }, SELECTED_TASK_LOG_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(pollId);
    };
  }, [detailTaskId]);

  useEffect(() => {
    if (!detailTaskId) {
      setSelectedTaskScheduleList([]);
      setSelectedTaskScheduleRunList([]);
      setIsTaskSchedulePanelLoading(false);
      return;
    }

    let cancelled = false;
    const fetchSelectedTaskScheduleData = async (silentBool: boolean) => {
      if (!silentBool) {
        setIsTaskSchedulePanelLoading(true);
      }
      const [taskScheduleListResult, taskScheduleRunListResult] =
        await Promise.allSettled([
          taskScheduleApi.list(detailTaskId),
          taskScheduleApi.listRuns(detailTaskId, SELECTED_TASK_SCHEDULE_RUN_LIMIT),
        ]);
      if (cancelled) {
        return;
      }

      if (taskScheduleListResult.status === "fulfilled") {
        setSelectedTaskScheduleList(taskScheduleListResult.value);
      } else {
        console.error("Failed to load task schedules:", taskScheduleListResult.reason);
      }

      if (taskScheduleRunListResult.status === "fulfilled") {
        setSelectedTaskScheduleRunList(taskScheduleRunListResult.value);
      } else {
        console.error(
          "Failed to load task schedule runs:",
          taskScheduleRunListResult.reason
        );
      }

      if (!silentBool) {
        if (
          taskScheduleListResult.status === "rejected" ||
          taskScheduleRunListResult.status === "rejected"
        ) {
          setErrorMessage((previousErrorMessage) =>
            previousErrorMessage ?? "Failed to load task schedules."
          );
        }
        setIsTaskSchedulePanelLoading(false);
      }
    };

    void fetchSelectedTaskScheduleData(false);
    const pollTaskScheduleId = window.setInterval(() => {
      void fetchSelectedTaskScheduleData(true);
    }, SELECTED_TASK_SCHEDULE_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(pollTaskScheduleId);
    };
  }, [detailTaskId]);

  // PRD 轮询：依赖稳定的派生值而非整个 taskList，防止每秒重置 interval
  const _prdPollTask = useMemo(
    () => taskList.find((taskItem) => taskItem.id === detailTaskId) ?? null,
    [detailTaskId, taskList]
  );
  const _prdWorktreePath = _prdPollTask?.worktree_path ?? null;
  const _prdPollStage = useMemo(
    () =>
      _prdPollTask
        ? deriveRequirementStage(_prdPollTask, devLogsByTaskId[_prdPollTask.id] ?? [])
        : null,
    [_prdPollTask, devLogsByTaskId]
  );
  const _prdPollActive =
    _prdWorktreePath !== null &&
    _prdPollStage !== null &&
    PRD_RELEVANT_STAGE_SET.has(_prdPollStage);

  useEffect(() => {
    if (!detailTaskId || !_prdPollActive) return;

    const loadPrd = () => {
      taskApi
        .getPrdFile(detailTaskId)
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
  }, [detailTaskId, _prdPollActive, _prdWorktreePath]);

  async function handleRevealOrLoadOlderConversationHistory(): Promise<void> {
    if (hiddenTimelineItemCount > 0) {
      startTransition(() => {
        setVisibleConversationTurnCount((previousCount) =>
          Math.min(
            selectedTimelineItemList.length,
            previousCount + VISIBLE_CONVERSATION_TURN_INCREMENT
          )
        );
      });
      return;
    }

    if (!selectedTask || !canLoadOlderTaskLogs || isLoadingOlderTaskLogs) {
      return;
    }

    setIsLoadingOlderTaskLogs(true);
    setErrorMessage(null);

    try {
      const olderTaskLogList = await logApi.list(
        selectedTask.id,
        SELECTED_TASK_LOG_OLDER_BATCH_LIMIT,
        { offset: selectedTaskLogList.length }
      );
      const sortedOlderTaskLogList = sortDevLogListByCreatedAt(olderTaskLogList);
      setSelectedTaskLogList((previousTaskLogList) =>
        prependOlderDevLogList(previousTaskLogList, sortedOlderTaskLogList)
      );
      startTransition(() => {
        setVisibleConversationTurnCount((previousCount) =>
          previousCount + VISIBLE_CONVERSATION_TURN_INCREMENT
        );
      });
    } catch (olderTaskLogError) {
      console.error(olderTaskLogError);
      setErrorMessage("Failed to load older timeline entries.");
    } finally {
      setIsLoadingOlderTaskLogs(false);
    }
  }

  async function loadDashboardData(
    silent = false,
    options?: {
      includeGlobalLogs?: boolean;
      includeTaskCardMetadata?: boolean;
    }
  ): Promise<void> {
    const shouldIncludeGlobalLogs = options?.includeGlobalLogs ?? true;
    const shouldIncludeTaskCardMetadata =
      options?.includeTaskCardMetadata ?? true;
    if (!silent) {
      setIsDashboardLoading(true);
    }

    const runAccountPromise = runAccountApi.getCurrent();
    const taskListPromise = taskApi.list();
    const devLogListPromise = shouldIncludeGlobalLogs
      ? logApi.list()
      : Promise.resolve<DevLog[] | null>(null);
    const taskCardMetadataPromise = shouldIncludeTaskCardMetadata
      ? taskApi.listCardMetadata()
      : Promise.resolve<TaskCardMetadata[] | null>(null);
    const [
      runAccountResult,
      taskListResult,
      devLogListResult,
      taskCardMetadataResult,
    ] = await Promise.allSettled([
      runAccountPromise,
      taskListPromise,
      devLogListPromise,
      taskCardMetadataPromise,
    ]);
    let nextTaskList: Task[] | null = null;
    let shouldRefreshWaitingUserMetadata = false;

    // On fetch failure, preserve previous state rather than wiping to empty.
    // This prevents the UI from going blank during transient server restarts
    // (e.g. hot-reload after a task branch merges changes into main).
    if (runAccountResult.status === "fulfilled") {
      setCurrentRunAccount(runAccountResult.value);
    }
    if (taskListResult.status === "fulfilled") {
      const previousTaskListSnapshot = latestTaskListRef.current;
      const sortedNextTaskList = sortTaskListByCreatedAt(taskListResult.value);
      nextTaskList = sortedNextTaskList;
      shouldRefreshWaitingUserMetadata =
        !shouldIncludeTaskCardMetadata &&
        shouldRefreshTaskCardMetadataAfterTaskListUpdate(
          previousTaskListSnapshot,
          sortedNextTaskList
        );
      latestTaskListRef.current = sortedNextTaskList;
      setTaskList(sortedNextTaskList);
      setSelectedTaskId((previousSelectedTaskId) => {
        if (!previousSelectedTaskId) return previousSelectedTaskId;
        const hasMatchingTask = sortedNextTaskList.some(
          (taskItem) => taskItem.id === previousSelectedTaskId
        );
        return hasMatchingTask ? previousSelectedTaskId : null;
      });
    }
    if (devLogListResult.status === "fulfilled") {
      if (devLogListResult.value !== null) {
        setAllDevLogList(sortDevLogListByCreatedAt(devLogListResult.value));
      }
    }
    const fallbackTaskListForMetadata = nextTaskList ?? latestTaskListRef.current;
    if (taskCardMetadataResult.status === "fulfilled") {
      if (taskCardMetadataResult.value !== null) {
        setTaskCardMetadataMap(
          buildTaskCardMetadataMap(taskCardMetadataResult.value)
        );
      }
    } else if (shouldIncludeTaskCardMetadata) {
      setTaskCardMetadataMap((previousTaskCardMetadataMap) =>
        buildTaskCardMetadataFallbackMap(
          fallbackTaskListForMetadata,
          previousTaskCardMetadataMap
        )
      );
    }

    if (shouldRefreshWaitingUserMetadata && nextTaskList !== null) {
      void refreshTaskCardMetadata({
        fallbackTaskList: nextTaskList,
        errorLabel: "Failed to refresh waiting-user metadata:",
      });
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
    if (shouldIncludeGlobalLogs && devLogListResult.status === "rejected") {
      dashboardErrors.push("Failed to load timeline entries.");
      console.error(devLogListResult.reason);
    }
    if (
      shouldIncludeTaskCardMetadata &&
      taskCardMetadataResult.status === "rejected"
    ) {
      dashboardErrors.push("Failed to load task card metadata.");
      console.error(taskCardMetadataResult.reason);
    }

    setErrorMessage(dashboardErrors.length > 0 ? dashboardErrors.join(" ") : null);
    setIsDashboardLoading(false);
  }

  async function initializeDashboard(): Promise<void> {
    await loadAppConfig();
    await Promise.all([
      loadDashboardData(false, {
        includeTaskCardMetadata: false,
      }),
      loadProjectList(),
    ]);
  }

  async function loadProjectList(): Promise<void> {
    try {
      const nextProjectList = await projectApi.list();
      setProjectList(nextProjectList);
    } catch (projectListError) {
      console.error("Failed to load projects:", projectListError);
      setErrorMessage((previousErrorMessage) =>
        previousErrorMessage ?? "Failed to load projects."
      );
    }
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

  async function reloadSelectedTaskSchedulePanel(taskId: string): Promise<void> {
    const [taskScheduleList, taskScheduleRunList] = await Promise.all([
      taskScheduleApi.list(taskId),
      taskScheduleApi.listRuns(taskId, SELECTED_TASK_SCHEDULE_RUN_LIMIT),
    ]);
    setSelectedTaskScheduleList(taskScheduleList);
    setSelectedTaskScheduleRunList(taskScheduleRunList);
  }

  async function handleCreateTaskSchedule(): Promise<void> {
    if (!selectedTask) {
      return;
    }

    const isOnceTriggerType =
      taskScheduleDraftTriggerType === TaskScheduleTriggerType.ONCE;
    const normalizedScheduleNameText = taskScheduleDraftName.trim();
    const normalizedRunAtText = taskScheduleDraftRunAtText.trim();
    const normalizedCronExprText = taskScheduleDraftCronExprText.trim();
    const normalizedRunAtUtcIsoText = isOnceTriggerType
      ? convertDatetimeLocalValueToUtcIso(normalizedRunAtText)
      : null;
    const browserTimezoneNameText = isOnceTriggerType
      ? resolveBrowserTimezoneName()
      : null;
    if (!normalizedScheduleNameText) {
      setErrorMessage("Schedule name is required.");
      setSuccessMessage(null);
      return;
    }

    if (isOnceTriggerType && !normalizedRunAtText) {
      setErrorMessage("run_at is required when trigger type is once.");
      setSuccessMessage(null);
      return;
    }
    if (isOnceTriggerType && !normalizedRunAtUtcIsoText) {
      setErrorMessage("run_at is invalid.");
      setSuccessMessage(null);
      return;
    }
    if (
      taskScheduleDraftTriggerType === TaskScheduleTriggerType.CRON &&
      !normalizedCronExprText
    ) {
      setErrorMessage("cron_expr is required when trigger type is cron.");
      setSuccessMessage(null);
      return;
    }

    setIsTaskScheduleCreating(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      await taskScheduleApi.create(selectedTask.id, {
        schedule_name: normalizedScheduleNameText,
        action_type: taskScheduleDraftActionType as "start_task" | "resume_task",
        trigger_type: taskScheduleDraftTriggerType as "once" | "cron",
        run_at: isOnceTriggerType ? normalizedRunAtUtcIsoText : null,
        cron_expr:
          taskScheduleDraftTriggerType === TaskScheduleTriggerType.CRON
            ? normalizedCronExprText
            : null,
        timezone_name: browserTimezoneNameText ?? undefined,
        is_enabled: taskScheduleDraftIsEnabled,
      });
      await reloadSelectedTaskSchedulePanel(selectedTask.id);
      setTaskScheduleDraftName("");
      if (taskScheduleDraftTriggerType === TaskScheduleTriggerType.ONCE) {
        setTaskScheduleDraftRunAtText("");
      } else {
        setTaskScheduleDraftCronExprText("");
      }
      setSuccessMessage("Task schedule created.");
    } catch (taskScheduleCreateError) {
      console.error(taskScheduleCreateError);
      setErrorMessage(
        taskScheduleCreateError instanceof Error
          ? taskScheduleCreateError.message
          : "Failed to create task schedule."
      );
    } finally {
      setIsTaskScheduleCreating(false);
    }
  }

  async function handleToggleTaskSchedule(taskScheduleItem: TaskSchedule): Promise<void> {
    if (!selectedTask) {
      return;
    }

    const actionKey = `toggle:${taskScheduleItem.id}`;
    setActiveTaskScheduleActionKey(actionKey);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      await taskScheduleApi.update(selectedTask.id, taskScheduleItem.id, {
        is_enabled: !taskScheduleItem.is_enabled,
      });
      await reloadSelectedTaskSchedulePanel(selectedTask.id);
      setSuccessMessage(
        taskScheduleItem.is_enabled ? "Task schedule disabled." : "Task schedule enabled."
      );
    } catch (taskScheduleUpdateError) {
      console.error(taskScheduleUpdateError);
      setErrorMessage(
        taskScheduleUpdateError instanceof Error
          ? taskScheduleUpdateError.message
          : "Failed to update task schedule."
      );
    } finally {
      setActiveTaskScheduleActionKey(null);
    }
  }

  async function handleRunTaskScheduleNow(taskScheduleItem: TaskSchedule): Promise<void> {
    if (!selectedTask) {
      return;
    }

    const actionKey = `run-now:${taskScheduleItem.id}`;
    setActiveTaskScheduleActionKey(actionKey);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      await taskScheduleApi.runNow(selectedTask.id, taskScheduleItem.id);
      await reloadSelectedTaskSchedulePanel(selectedTask.id);
      setSuccessMessage("Task schedule run-now dispatched.");
    } catch (taskScheduleRunNowError) {
      console.error(taskScheduleRunNowError);
      setErrorMessage(
        taskScheduleRunNowError instanceof Error
          ? taskScheduleRunNowError.message
          : "Failed to run task schedule now."
      );
    } finally {
      setActiveTaskScheduleActionKey(null);
    }
  }

  async function handleDeleteTaskSchedule(taskScheduleItem: TaskSchedule): Promise<void> {
    if (!selectedTask) {
      return;
    }

    const shouldDeleteScheduleBool = window.confirm(
      `Delete schedule "${taskScheduleItem.schedule_name}"?`
    );
    if (!shouldDeleteScheduleBool) {
      return;
    }

    const actionKey = `delete:${taskScheduleItem.id}`;
    setActiveTaskScheduleActionKey(actionKey);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      await taskScheduleApi.delete(selectedTask.id, taskScheduleItem.id);
      await reloadSelectedTaskSchedulePanel(selectedTask.id);
      setSuccessMessage("Task schedule deleted.");
    } catch (taskScheduleDeleteError) {
      console.error(taskScheduleDeleteError);
      setErrorMessage(
        taskScheduleDeleteError instanceof Error
          ? taskScheduleDeleteError.message
          : "Failed to delete task schedule."
      );
    } finally {
      setActiveTaskScheduleActionKey(null);
    }
  }

  async function handleCreateRequirement(): Promise<void> {
    const nextRequirementTitle = newRequirementTitle.trim();
    const nextRequirementDescription = newRequirementDescription.trim();
    const nextRequirementBrief = buildRequirementBrief(
      nextRequirementDescription,
      createRequirementAttachmentDraft
    );

    if (!nextRequirementTitle || !nextRequirementBrief) {
      setErrorMessage("Title and description or image/video are required.");
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
        requirement_brief: nextRequirementBrief,
        auto_confirm_prd_and_execute: isAutoConfirmPrdAndExecuteEnabled,
      });

      if (createRequirementAttachmentDraft) {
        if (createRequirementAttachmentDraft.kind === "image") {
          await mediaApi.uploadImage(
            createRequirementAttachmentDraft.file,
            nextRequirementDescription,
            createdTask.id
          );
        } else {
          await mediaApi.uploadAttachment(
            createRequirementAttachmentDraft.file,
            nextRequirementDescription,
            createdTask.id
          );
        }
      } else {
        await logApi.create({
          task_id: createdTask.id,
          text_content: nextRequirementDescription,
          state_tag: DevLogStateTag.NONE,
        });
      }

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

  async function handleOpenInEditor(taskItem: Task): Promise<void> {
    setActiveMutationName("open_editor");
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const result = await taskApi.openInEditor(taskItem.id);
      setSuccessMessage(`已在编辑器中打开：${result.opened}`);
    } catch (openError) {
      console.error(openError);
      setErrorMessage(
        openError instanceof Error
          ? openError.message
          : "无法打开编辑器，请确认 worktree 目录已创建。"
      );
    } finally {
      setActiveMutationName(null);
    }
  }

  async function handleOpenProjectInEditor(projectId: string): Promise<void> {
    setActiveMutationName("open_editor");
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const result = await projectApi.openInEditor(projectId);
      setSuccessMessage(`已在编辑器中打开：${result.opened}`);
    } catch (openError) {
      console.error(openError);
      setErrorMessage(
        openError instanceof Error ? openError.message : "无法打开编辑器。"
      );
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

    resetEditRequirementDraft();
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
    const nextRequirementBrief = buildRequirementBrief(
      nextRequirementDescription,
      editRequirementAttachmentDraft,
      selectedTaskSnapshot.summary
    );

    if (!nextRequirementTitle || !nextRequirementBrief) {
      setErrorMessage("Requirement title and summary or image/video are required.");
      setSuccessMessage(null);
      return;
    }

    const titleChanged = nextRequirementTitle !== selectedTask.task_title;
    const summaryChanged = nextRequirementBrief !== selectedTaskSnapshot.summary;
    const attachmentChanged = editRequirementAttachmentDraft !== null;

    if (!titleChanged && !summaryChanged && !attachmentChanged) {
      closeRequirementEditor();
      return;
    }

    setActiveMutationName("update");
    setErrorMessage(null);
    setSuccessMessage(null);

    const shouldAttemptPrdRegeneration =
      selectedTask.workflow_stage !== WorkflowStage.BACKLOG &&
      !selectedTask.is_codex_task_running;
    let didPersistRequirementChange = false;

    try {
      await taskApi.update(selectedTask.id, {
        task_title: nextRequirementTitle,
        requirement_brief: nextRequirementBrief,
      });

      const requirementUpdateLogText = buildRequirementUpdateLog(
        selectedTask.task_title,
        nextRequirementTitle,
        nextRequirementBrief
      );
      if (editRequirementAttachmentDraft) {
        if (editRequirementAttachmentDraft.kind === "image") {
          await mediaApi.uploadImage(
            editRequirementAttachmentDraft.file,
            requirementUpdateLogText,
            selectedTask.id
          );
        } else {
          await mediaApi.uploadAttachment(
            editRequirementAttachmentDraft.file,
            requirementUpdateLogText,
            selectedTask.id
          );
        }
      } else {
        await logApi.create({
          task_id: selectedTask.id,
          text_content: requirementUpdateLogText,
          state_tag: DevLogStateTag.NONE,
        });
      }
      didPersistRequirementChange = true;

      let nextSuccessMessage = "Requirement changes were appended to history.";
      if (shouldAttemptPrdRegeneration) {
        const regeneratedTask = await taskApi.regeneratePrd(selectedTask.id);
        setTaskList((prev) =>
          prev.map((taskItem) =>
            taskItem.id === regeneratedTask.id ? regeneratedTask : taskItem
          )
        );
        nextSuccessMessage =
          "Requirement changes were saved. Koda is regenerating the PRD.";
      } else if (selectedTask.workflow_stage !== WorkflowStage.BACKLOG) {
        nextSuccessMessage =
          "Requirement changes were saved. Cancel the running automation if you want to regenerate the PRD now.";
      }

      setWorkspaceView("changes");
      closeRequirementEditor();
      setSuccessMessage(nextSuccessMessage);
      await loadDashboardData(true);
    } catch (updateError) {
      console.error(updateError);
      setErrorMessage(
        didPersistRequirementChange && shouldAttemptPrdRegeneration
          ? "Requirement changes were saved, but PRD regeneration failed."
          : "Failed to update requirement."
      );
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
        const isManualSelfReviewOverride =
          taskItem.workflow_stage === WorkflowStage.SELF_REVIEW_IN_PROGRESS &&
          !hasLatestSelfReviewCyclePassed(devLogsByTaskId[taskItem.id] ?? []);
        await taskApi.complete(taskItem.id);
        setSuccessMessage(
          isManualSelfReviewOverride
            ? "已记录人工接管，Koda 正在执行 Git 收尾：git add .、基于任务摘要提交、rebase main、必要时自动修复冲突、合并到 main，并清理 worktree。"
            : "Koda is finalizing the branch: git add ., commit from the task summary, rebase main, auto-fix rebase conflicts with Codex if needed, merge into main, and clean up the worktree."
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

    const shouldRegeneratePrdAfterFeedback =
      selectedTask.workflow_stage === WorkflowStage.PRD_WAITING_CONFIRMATION &&
      !selectedTask.is_codex_task_running;
    let didPersistFeedback = false;

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
      didPersistFeedback = true;

      setFeedbackInputText("");
      setFeedbackAttachmentDraft(null);
      if (feedbackAttachmentInputRef.current) {
        feedbackAttachmentInputRef.current.value = "";
      }

      if (shouldRegeneratePrdAfterFeedback) {
        const regeneratedTask = await taskApi.regeneratePrd(selectedTask.id);
        setTaskList((prev) =>
          prev.map((taskItem) =>
            taskItem.id === regeneratedTask.id ? regeneratedTask : taskItem
          )
        );
        setSuccessMessage("Feedback saved. Koda is regenerating the PRD.");
      }

      // 若用户输入了继续指令，根据当前阶段自动恢复执行
      const isContinueCommand = _isContinueCommand(nextFeedbackInputText);
      if (
        isContinueCommand &&
        !feedbackAttachmentDraft &&
        !shouldRegeneratePrdAfterFeedback
      ) {
        const stage = selectedTask.workflow_stage;
        if (stage === WorkflowStage.CHANGES_REQUESTED) {
          // 正常重试：直接触发执行
          const resumedTask = await taskApi.execute(selectedTask.id);
          setTaskList((prev) =>
            prev.map((t) => (t.id === resumedTask.id ? resumedTask : t))
          );
        } else if (
          RESUMABLE_AUTOMATION_STAGE_SET.has(stage) &&
          !selectedTask.is_codex_task_running
        ) {
          if (
            stage === WorkflowStage.SELF_REVIEW_IN_PROGRESS &&
            selectedTaskHasSettledSelfReview
          ) {
            setSuccessMessage("AI 自检已通过，点击 Complete 进入 Git 收尾。");
          } else if (
            stage === WorkflowStage.TEST_IN_PROGRESS &&
            selectedTaskHasSettledPostReviewLint
          ) {
            setSuccessMessage("自动化验证已通过，点击 Complete 进入 Git 收尾。");
          } else {
            const resumedTask = await taskApi.resume(selectedTask.id);
            setTaskList((prev) =>
              prev.map((t) => (t.id === resumedTask.id ? resumedTask : t))
            );
          }
        } else if (stage === WorkflowStage.SELF_REVIEW_IN_PROGRESS) {
          if (selectedTask.is_codex_task_running) {
            setSuccessMessage("AI 自检仍在执行中，请等待当前评审结束，或先手动中断。");
          } else if (selectedTaskHasSettledSelfReview) {
            setSuccessMessage("AI 自检已通过，点击 Complete 进入 Git 收尾。");
          } else {
            setSuccessMessage("AI 自检已停止但尚未形成通过结论，可继续恢复或直接点击 Complete 进行人工接管。");
          }
        } else if (stage === WorkflowStage.TEST_IN_PROGRESS) {
          if (selectedTask.is_codex_task_running) {
            setSuccessMessage("自动化验证仍在执行中，请等待当前阶段结束，或先手动中断。");
          } else if (selectedTaskHasSettledPostReviewLint) {
            setSuccessMessage("自动化验证已通过，点击 Complete 进入 Git 收尾。");
          } else {
            setSuccessMessage("自动化验证已停止但尚未通过，可继续恢复当前 lint 闭环。");
          }
        } else if (stage === WorkflowStage.PRD_WAITING_CONFIRMATION) {
          setSuccessMessage("PRD 已生成，先确认 PRD，再开始执行。");
        } else {
          setSuccessMessage("当前阶段不支持继续恢复。");
        }
      }

      await loadDashboardData(true);
    } catch (feedbackError) {
      console.error(feedbackError);
      setErrorMessage(
        didPersistFeedback && shouldRegeneratePrdAfterFeedback
          ? "Feedback was saved, but PRD regeneration failed."
          : "Failed to process feedback."
      );
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
    const pastedFile = getClipboardFile(clipboardEvent);

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

  function handleCreateRequirementPaste(
    clipboardEvent: ClipboardEvent<HTMLTextAreaElement>
  ): void {
    const pastedFile = getClipboardFile(clipboardEvent);

    if (!pastedFile) {
      return;
    }

    clipboardEvent.preventDefault();
    setCreateRequirementAttachmentDraftFromFile(pastedFile);
  }

  function handleEditRequirementPaste(
    clipboardEvent: ClipboardEvent<HTMLTextAreaElement>
  ): void {
    const pastedFile = getClipboardFile(clipboardEvent);

    if (!pastedFile) {
      return;
    }

    clipboardEvent.preventDefault();
    setEditRequirementAttachmentDraftFromFile(pastedFile);
  }

  function handleCreateRequirementAttachmentInputChange(
    changeEvent: ChangeEvent<HTMLInputElement>
  ): void {
    const nextFile = changeEvent.target.files?.[0];
    if (!nextFile) {
      return;
    }

    setCreateRequirementAttachmentDraftFromFile(nextFile);
  }

  function handleEditRequirementAttachmentInputChange(
    changeEvent: ChangeEvent<HTMLInputElement>
  ): void {
    const nextFile = changeEvent.target.files?.[0];
    if (!nextFile) {
      return;
    }

    setEditRequirementAttachmentDraftFromFile(nextFile);
  }

  function setCreateRequirementAttachmentDraftFromFile(nextFile: File): void {
    setCreateRequirementAttachmentDraft((previousAttachmentDraft) => {
      if (previousAttachmentDraft?.previewUrl) {
        URL.revokeObjectURL(previousAttachmentDraft.previewUrl);
      }

      return buildAttachmentDraftFromFile(nextFile);
    });
    setSuccessMessage(null);
    setErrorMessage(null);
  }

  function setEditRequirementAttachmentDraftFromFile(nextFile: File): void {
    setEditRequirementAttachmentDraft((previousAttachmentDraft) => {
      if (previousAttachmentDraft?.previewUrl) {
        URL.revokeObjectURL(previousAttachmentDraft.previewUrl);
      }

      return buildAttachmentDraftFromFile(nextFile);
    });
    setSuccessMessage(null);
    setErrorMessage(null);
  }

  function setAttachmentDraftFromFile(nextFile: File): void {
    setFeedbackAttachmentDraft((previousAttachmentDraft) => {
      if (previousAttachmentDraft?.previewUrl) {
        URL.revokeObjectURL(previousAttachmentDraft.previewUrl);
      }

      return buildAttachmentDraftFromFile(nextFile);
    });
    setSuccessMessage(null);
    setErrorMessage(null);
  }

  function clearCreateRequirementAttachmentDraft(): void {
    setCreateRequirementAttachmentDraft((previousAttachmentDraft) => {
      if (previousAttachmentDraft?.previewUrl) {
        URL.revokeObjectURL(previousAttachmentDraft.previewUrl);
      }
      return null;
    });
    if (createRequirementAttachmentInputRef.current) {
      createRequirementAttachmentInputRef.current.value = "";
    }
  }

  function clearEditRequirementAttachmentDraft(): void {
    setEditRequirementAttachmentDraft((previousAttachmentDraft) => {
      if (previousAttachmentDraft?.previewUrl) {
        URL.revokeObjectURL(previousAttachmentDraft.previewUrl);
      }
      return null;
    });
    if (editRequirementAttachmentInputRef.current) {
      editRequirementAttachmentInputRef.current.value = "";
    }
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
      await loadProjectList();
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
      await loadProjectList();
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
      await loadProjectList();
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
    if (feedbackAttachmentInputRef.current) {
      feedbackAttachmentInputRef.current.value = "";
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
                  onClick={() => {
                    startTransition(() => {
                      setWorkspaceView(viewName);
                    });
                  }}
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

                <div className="devflow-create-panel__composer">
                  <button
                    type="button"
                    className="devflow-create-panel__attach"
                    onClick={() => createRequirementAttachmentInputRef.current?.click()}
                    disabled={activeMutationName === "create"}
                    aria-label="Attach image or video to requirement"
                  >
                    <PaperclipIcon className="devflow-icon devflow-icon--small" />
                  </button>

                  <textarea
                    className="devflow-input devflow-input--textarea devflow-input--textarea-with-attachment"
                    placeholder="Describe what you want to build..."
                    value={newRequirementDescription}
                    onChange={(changeEvent) =>
                      setNewRequirementDescription(changeEvent.target.value)
                    }
                    onPaste={handleCreateRequirementPaste}
                  />

                  <input
                    ref={createRequirementAttachmentInputRef}
                    className="devflow-feedback__file-input"
                    type="file"
                    accept="image/*,video/*"
                    onChange={handleCreateRequirementAttachmentInputChange}
                  />
                </div>

                {createRequirementAttachmentDraft ? (
                  <div className="devflow-feedback__attachment">
                    {renderAttachmentPreview(createRequirementAttachmentDraft)}

                    <div className="devflow-feedback__attachment-copy">
                      <span className="devflow-feedback__attachment-name">
                        {createRequirementAttachmentDraft.file.name}
                      </span>
                      <span className="devflow-feedback__attachment-meta">
                        {getAttachmentLabel(createRequirementAttachmentDraft.kind)}
                        {" · "}
                        {formatFileSize(createRequirementAttachmentDraft.file.size)}
                      </span>
                    </div>

                    <button
                      type="button"
                      className="devflow-feedback__attachment-remove"
                      onClick={clearCreateRequirementAttachmentDraft}
                    >
                      <XIcon className="devflow-icon devflow-icon--small" />
                    </button>
                  </div>
                ) : (
                  <p className="devflow-create-panel__hint">
                    Tip: Paste an image/video into the description box or attach one
                    from disk.
                  </p>
                )}

                <select
                  className="devflow-input devflow-input--select"
                  value={newRequirementProjectId ?? ""}
                  onChange={(changeEvent) =>
                    setNewRequirementProjectId(changeEvent.target.value || null)
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

                <label className="devflow-create-panel__auto-execute">
                  <input
                    type="checkbox"
                    checked={isAutoConfirmPrdAndExecuteEnabled}
                    disabled={activeMutationName === "create"}
                    onChange={(changeEvent) =>
                      setIsAutoConfirmPrdAndExecuteEnabled(
                        changeEvent.target.checked
                      )
                    }
                  />
                  <span>PRD 生成后自动确认并直接开始执行</span>
                </label>

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
                <RequirementCardButton
                  key={requirementViewModel.task.id}
                  isSelected={selectedTaskId === requirementViewModel.task.id}
                  onSelectTaskId={setSelectedTaskId}
                  requirementViewModel={requirementViewModel}
                />
              ))}
            </div>
          </section>

          <section className="devflow-column devflow-column--detail">
            {isTaskSelectionPending ? (
              <div className="devflow-empty-detail">
                <div className="devflow-empty-detail__icon">
                  <ChevronRightIcon className="devflow-icon devflow-icon--large" />
                </div>
                <p className="devflow-empty-detail__text">
                  正在切换需求详情...
                </p>
              </div>
            ) : selectedTask ? (
              <div className="devflow-detail">
                <div className="devflow-detail__body">
                  <div className="devflow-detail__header">
                    <div className="devflow-detail__copy">
                      <div className="devflow-detail__title-row">
                        <h2 className="devflow-detail__title">
                          {selectedTask.task_title}
                        </h2>
                        {selectedTaskDisplayStage ? (
                          <StatusBadge
                            status={selectedTaskDisplayStage}
                            label={selectedTaskStageLabel ?? undefined}
                          />
                        ) : null}
                      </div>
                      <div className="devflow-detail__meta-row">
                        <span className="devflow-detail__meta-pill">
                          <span className="devflow-detail__meta-label">
                            真实阶段
                          </span>
                          <span className="devflow-detail__meta-value">
                            {formatStageLabel(selectedTask.workflow_stage)}
                          </span>
                        </span>
                        <span
                          className="devflow-detail__meta-pill"
                          title={selectedTaskAiActivityTitle}
                        >
                          <span className="devflow-detail__meta-label">
                            最近 AI
                          </span>
                          <span className="devflow-detail__meta-value">
                            {selectedTaskAiActivityLabel}
                          </span>
                        </span>
                      </div>
                      <div className="devflow-detail__description-block">
                        <div
                          className={
                            isSelectedTaskSummaryExpandable &&
                            !isRequirementSummaryExpanded
                              ? "devflow-detail__description-shell devflow-detail__description-shell--collapsed"
                              : "devflow-detail__description-shell"
                          }
                        >
                          <p className="devflow-detail__description">
                            {selectedTaskSummaryText}
                          </p>
                        </div>
                        {isSelectedTaskSummaryExpandable ? (
                          <button
                            type="button"
                            className="devflow-detail__description-toggle"
                            aria-expanded={isRequirementSummaryExpanded}
                            onClick={() =>
                              setIsRequirementSummaryExpanded(
                                (previousExpandedState) =>
                                  !previousExpandedState
                              )
                            }
                          >
                            {isRequirementSummaryExpanded
                              ? "收起完整需求"
                              : "展开完整需求"}
                          </button>
                        ) : null}
                      </div>
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
                          busy={activeMutationName === "open_editor"}
                          onClick={() => {
                            void handleOpenProjectInEditor(selectedTask.project_id!);
                          }}
                        >
                          <CodeIcon className="devflow-icon devflow-icon--small" />
                          <span>打开项目目录</span>
                        </ActionButton>
                      ) : null}

                      {/* ── 打开 Worktree（执行后才显示） ── */}
                      {selectedTask.worktree_path &&
                      selectedTask.lifecycle_status !== TaskLifecycleStatus.DELETED ? (
                        <ActionButton
                          variant="outline"
                          busy={activeMutationName === "open_editor"}
                          onClick={() => {
                            void handleOpenInEditor(selectedTask);
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
                          {canCompleteSelectedTask ? (
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
                          ) : null}
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

                      <div className="devflow-create-panel__composer">
                        <textarea
                          className="devflow-input devflow-input--textarea devflow-input--textarea-with-attachment"
                          placeholder="Updated requirement summary"
                          value={editRequirementDescription}
                          onChange={(changeEvent) =>
                            setEditRequirementDescription(changeEvent.target.value)
                          }
                          onPaste={handleEditRequirementPaste}
                        />

                        <button
                          type="button"
                          className="devflow-create-panel__attach"
                          onClick={() => editRequirementAttachmentInputRef.current?.click()}
                          disabled={activeMutationName === "update"}
                          aria-label="Attach image or video to requirement revision"
                        >
                          <PaperclipIcon className="devflow-icon devflow-icon--small" />
                        </button>

                        <input
                          ref={editRequirementAttachmentInputRef}
                          className="devflow-feedback__file-input"
                          type="file"
                          accept="image/*,video/*"
                          onChange={handleEditRequirementAttachmentInputChange}
                        />
                      </div>

                      {editRequirementAttachmentDraft ? (
                        <div className="devflow-feedback__attachment">
                          {renderAttachmentPreview(editRequirementAttachmentDraft)}

                          <div className="devflow-feedback__attachment-copy">
                            <span className="devflow-feedback__attachment-name">
                              {editRequirementAttachmentDraft.file.name}
                            </span>
                            <span className="devflow-feedback__attachment-meta">
                              {getAttachmentLabel(editRequirementAttachmentDraft.kind)}
                              {" · "}
                              {formatFileSize(editRequirementAttachmentDraft.file.size)}
                            </span>
                          </div>

                          <button
                            type="button"
                            className="devflow-feedback__attachment-remove"
                            onClick={clearEditRequirementAttachmentDraft}
                          >
                            <XIcon className="devflow-icon devflow-icon--small" />
                          </button>
                        </div>
                      ) : (
                        <p className="devflow-create-panel__hint">
                          Tip: Paste an image/video into the summary box or attach one
                          from disk.
                        </p>
                      )}

                      <div className="devflow-create-panel__actions">
                        <ActionButton
                          variant="ghost"
                          onClick={closeRequirementEditor}
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

                  <div className="devflow-detail-section devflow-task-schedule-panel">
                    <div className="devflow-detail-section__header">
                      <h3 className="devflow-detail-section__title">
                        <HistoryIcon className="devflow-icon devflow-icon--small" />
                        <span>Task Schedules</span>
                      </h3>
                      <span className="devflow-task-schedule-panel__summary">
                        {isTaskSchedulePanelLoading
                          ? "Loading..."
                          : `${selectedTaskScheduleList.length} configured`}
                      </span>
                    </div>

                    <CardSurface className="devflow-task-schedule-panel__create-card">
                      <div className="devflow-task-schedule-panel__create-grid">
                        <input
                          className="devflow-input"
                          placeholder="Schedule name"
                          value={taskScheduleDraftName}
                          onChange={(changeEvent) =>
                            setTaskScheduleDraftName(changeEvent.target.value)
                          }
                        />
                        <select
                          className="devflow-input devflow-input--select"
                          value={taskScheduleDraftActionType}
                          onChange={(changeEvent) =>
                            setTaskScheduleDraftActionType(
                              changeEvent.target.value as TaskScheduleActionType
                            )
                          }
                        >
                          <option value={TaskScheduleActionType.START_TASK}>start_task</option>
                          <option value={TaskScheduleActionType.RESUME_TASK}>resume_task</option>
                        </select>
                        <select
                          className="devflow-input devflow-input--select"
                          value={taskScheduleDraftTriggerType}
                          onChange={(changeEvent) =>
                            setTaskScheduleDraftTriggerType(
                              changeEvent.target.value as TaskScheduleTriggerType
                            )
                          }
                        >
                          <option value={TaskScheduleTriggerType.ONCE}>once</option>
                          <option value={TaskScheduleTriggerType.CRON}>cron</option>
                        </select>
                        {taskScheduleDraftTriggerType === TaskScheduleTriggerType.ONCE ? (
                          <input
                            className="devflow-input"
                            type="datetime-local"
                            value={taskScheduleDraftRunAtText}
                            onChange={(changeEvent) =>
                              setTaskScheduleDraftRunAtText(changeEvent.target.value)
                            }
                          />
                        ) : (
                          <input
                            className="devflow-input"
                            placeholder="Cron expression, e.g. 0 2 * * *"
                            value={taskScheduleDraftCronExprText}
                            onChange={(changeEvent) =>
                              setTaskScheduleDraftCronExprText(changeEvent.target.value)
                            }
                          />
                        )}
                        <label className="devflow-task-schedule-panel__enabled-field">
                          <input
                            type="checkbox"
                            checked={taskScheduleDraftIsEnabled}
                            onChange={(changeEvent) =>
                              setTaskScheduleDraftIsEnabled(changeEvent.target.checked)
                            }
                          />
                          <span>Enabled</span>
                        </label>
                        <ActionButton
                          variant="primary"
                          busy={isTaskScheduleCreating}
                          onClick={() => {
                            void handleCreateTaskSchedule();
                          }}
                        >
                          {isTaskScheduleCreating ? "Creating..." : "Save Schedule"}
                        </ActionButton>
                      </div>
                    </CardSurface>

                    {selectedTaskScheduleList.length === 0 ? (
                      <div className="devflow-empty-card devflow-empty-card--detail">
                        <p className="devflow-empty-card__text">
                          No task schedule configured.
                        </p>
                      </div>
                    ) : (
                      <div className="devflow-task-schedule-panel__list">
                        {selectedTaskScheduleList.map((taskScheduleItem) => {
                          const toggleActionKey = `toggle:${taskScheduleItem.id}`;
                          const runNowActionKey = `run-now:${taskScheduleItem.id}`;
                          const deleteActionKey = `delete:${taskScheduleItem.id}`;
                          const isToggleBusy =
                            activeTaskScheduleActionKey === toggleActionKey;
                          const isRunNowBusy =
                            activeTaskScheduleActionKey === runNowActionKey;
                          const isDeleteBusy =
                            activeTaskScheduleActionKey === deleteActionKey;
                          return (
                            <CardSurface
                              key={taskScheduleItem.id}
                              className="devflow-task-schedule-panel__item"
                            >
                              <div className="devflow-task-schedule-panel__item-header">
                                <h4 className="devflow-task-schedule-panel__item-title">
                                  {taskScheduleItem.schedule_name}
                                </h4>
                                <span
                                  className={
                                    taskScheduleItem.is_enabled
                                      ? "devflow-task-schedule-panel__item-status devflow-task-schedule-panel__item-status--enabled"
                                      : "devflow-task-schedule-panel__item-status devflow-task-schedule-panel__item-status--disabled"
                                  }
                                >
                                  {taskScheduleItem.is_enabled ? "Enabled" : "Disabled"}
                                </span>
                              </div>
                              <p className="devflow-task-schedule-panel__item-meta">
                                {formatTaskScheduleActionLabel(taskScheduleItem.action_type)}
                                {" · "}
                                {formatTaskScheduleTriggerLabel(taskScheduleItem.trigger_type)}
                                {" · "}
                                TZ {taskScheduleItem.timezone_name}
                              </p>
                              <p className="devflow-task-schedule-panel__item-meta">
                                Next:{" "}
                                {taskScheduleItem.next_run_at
                                  ? formatDateTime(taskScheduleItem.next_run_at)
                                  : "-"}
                              </p>
                              <p className="devflow-task-schedule-panel__item-meta">
                                Last:{" "}
                                <span
                                  className={formatTaskScheduleRunStatusClassName(
                                    taskScheduleItem.last_result_status
                                  )}
                                >
                                  {formatTaskScheduleRunStatusLabel(
                                    taskScheduleItem.last_result_status
                                  )}
                                </span>
                              </p>
                              <div className="devflow-task-schedule-panel__item-actions">
                                <button
                                  type="button"
                                  className="devflow-detail-section__action"
                                  disabled={isToggleBusy}
                                  onClick={() => {
                                    void handleToggleTaskSchedule(taskScheduleItem);
                                  }}
                                >
                                  {isToggleBusy
                                    ? "Saving..."
                                    : taskScheduleItem.is_enabled
                                      ? "Disable"
                                      : "Enable"}
                                </button>
                                <button
                                  type="button"
                                  className="devflow-detail-section__action"
                                  disabled={isRunNowBusy}
                                  onClick={() => {
                                    void handleRunTaskScheduleNow(taskScheduleItem);
                                  }}
                                >
                                  {isRunNowBusy ? "Dispatching..." : "Run Now"}
                                </button>
                                <button
                                  type="button"
                                  className="devflow-detail-section__action"
                                  disabled={isDeleteBusy}
                                  onClick={() => {
                                    void handleDeleteTaskSchedule(taskScheduleItem);
                                  }}
                                >
                                  {isDeleteBusy ? "Deleting..." : "Delete"}
                                </button>
                              </div>
                            </CardSurface>
                          );
                        })}
                      </div>
                    )}

                    <CardSurface className="devflow-task-schedule-panel__runs">
                      <div className="devflow-task-schedule-panel__runs-header">
                        <h4 className="devflow-task-schedule-panel__runs-title">
                          Recent Schedule Runs
                        </h4>
                      </div>
                      {selectedTaskScheduleRunList.length === 0 ? (
                        <p className="devflow-task-schedule-panel__runs-empty">
                          No schedule run history yet.
                        </p>
                      ) : (
                        <div className="devflow-task-schedule-panel__run-list">
                          {selectedTaskScheduleRunList.map((taskScheduleRunItem) => (
                            <div
                              key={taskScheduleRunItem.id}
                              className="devflow-task-schedule-panel__run-item"
                            >
                              <div className="devflow-task-schedule-panel__run-primary">
                                <span className="devflow-task-schedule-panel__run-schedule">
                                  {selectedTaskScheduleNameMap[taskScheduleRunItem.schedule_id] ??
                                    taskScheduleRunItem.schedule_id.slice(0, 8)}
                                </span>
                                <span
                                  className={formatTaskScheduleRunStatusClassName(
                                    taskScheduleRunItem.run_status
                                  )}
                                >
                                  {formatTaskScheduleRunStatusLabel(
                                    taskScheduleRunItem.run_status
                                  )}
                                </span>
                              </div>
                              <div className="devflow-task-schedule-panel__run-meta">
                                Planned {formatDateTime(taskScheduleRunItem.planned_run_at)}
                              </div>
                              {taskScheduleRunItem.skip_reason ||
                              taskScheduleRunItem.error_message ? (
                                <div className="devflow-task-schedule-panel__run-note">
                                  {taskScheduleRunItem.skip_reason ??
                                    taskScheduleRunItem.error_message}
                                </div>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      )}
                    </CardSurface>
                  </div>

                  <div className="devflow-detail-grid">
                    <div className="devflow-detail-section">
                      <h3 className="devflow-detail-section__title">
                        <HistoryIcon className="devflow-icon devflow-icon--small" />
                        <span>Timeline</span>
                      </h3>

                      <div className="devflow-conversation">
                        <p className="devflow-conversation__legend">
                          用户消息保留正文。Agent / System 日志只显示摘要、状态和涉及文件，
                          避免大段输出把时间线撑满。
                        </p>

                        {isSelectedTaskInActiveExecution ? (
                          <div className="devflow-execution-banner">
                            <span className="devflow-footer__pulse" />
                            <span>
                              {selectedTaskStage === WorkflowStage.PRD_GENERATING
                                ? "AI 正在生成 PRD，请稍候..."
                                : selectedTaskStage === WorkflowStage.SELF_REVIEW_IN_PROGRESS
                                  ? "AI 正在执行自检与代码评审，输出实时显示在下方..."
                                  : selectedTaskStage === WorkflowStage.PR_PREPARING
                                    ? "Koda 正在整理分支并执行合并收尾..."
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

                        {selectedTimelineItemList.length === 0 ? (
                          <div className="devflow-empty-card devflow-empty-card--detail">
                            <p className="devflow-empty-card__text">
                              Timeline will appear here after task activity begins.
                            </p>
                          </div>
                        ) : null}

                        {hiddenTimelineItemCount > 0 || canLoadOlderTaskLogs ? (
                          <div className="devflow-conversation__history-gate">
                            <span className="devflow-conversation__history-copy">
                              {hiddenTimelineItemCount > 0
                                ? `已折叠较早的 ${hiddenTimelineItemCount} 条时间线记录，先显示最近内容以提升切换速度。`
                                : `当前仅加载了最近 ${selectedTaskLogList.length} 条日志，较早历史按需继续加载。`}
                            </span>
                            <button
                              type="button"
                              className="devflow-conversation__history-btn"
                              disabled={isLoadingOlderTaskLogs}
                              onClick={() => {
                                void handleRevealOrLoadOlderConversationHistory();
                              }}
                            >
                              {hiddenTimelineItemCount > 0
                                ? "显示更早记录"
                                : isLoadingOlderTaskLogs
                                  ? "加载中..."
                                  : "加载更早日志"}
                            </button>
                          </div>
                        ) : null}

                        {timelineRenderBlockList.map((timelineRenderBlock) => {
                          if (timelineRenderBlock.kind === "human") {
                            const timelineItem = timelineRenderBlock.item;
                            const imgUrl =
                              mapMediaPathToPublicUrl(
                                timelineItem.log.media_original_image_path
                              ) ||
                              mapMediaPathToPublicUrl(
                                timelineItem.log.media_thumbnail_path
                              );
                            return (
                              <div
                                key={timelineItem.log.id}
                                className="devflow-turn-card devflow-turn-card--human"
                              >
                                <div className="devflow-turn-card__human-header">
                                  <UserIcon className="devflow-icon devflow-icon--tiny devflow-icon--human" />
                                  <span className="devflow-turn-card__author">
                                    {timelineItem.authorName}
                                  </span>
                                  <span className="devflow-turn-card__time">
                                    {timelineItem.timeLabel}
                                  </span>
                                </div>
                                <div className="devflow-turn-card__human-body">
                                  <MarkdownBlock
                                    className="devflow-markdown"
                                    markdownText={timelineItem.log.text_content || ""}
                                  />
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
                              </div>
                            );
                          }

                          return (
                            <CompactTimelineGroupCard
                              key={timelineRenderBlock.group.groupId}
                              group={timelineRenderBlock.group}
                              isExpanded={expandedCompactTimelineGroupIdSet.has(
                                timelineRenderBlock.group.groupId
                              )}
                              isLatest={
                                timelineRenderBlock.group.groupId === latestCompactTimelineGroupId
                              }
                              isStageMatched={
                                activeCompactTimelineCategory !== null &&
                                timelineRenderBlock.group.category ===
                                  activeCompactTimelineCategory
                              }
                              expandedCompactTimelineItemId={
                                expandedCompactTimelineItemId
                              }
                              onToggleItemDetail={(timelineItemId) => {
                                startTransition(() => {
                                  setExpandedCompactTimelineItemId((previousItemId) =>
                                    previousItemId === timelineItemId ? null : timelineItemId
                                  );
                                });
                              }}
                              onToggle={() => {
                                startTransition(() => {
                                  setExpandedCompactTimelineGroupIdSet((previousGroupIdSet) => {
                                    const nextGroupIdSet = new Set(previousGroupIdSet);
                                    if (nextGroupIdSet.has(timelineRenderBlock.group.groupId)) {
                                      nextGroupIdSet.delete(timelineRenderBlock.group.groupId);
                                    } else {
                                      nextGroupIdSet.add(timelineRenderBlock.group.groupId);
                                    }
                                    return nextGroupIdSet;
                                  });
                                });
                              }}
                            />
                          );
                        })}
                      </div>

                      {selectedCompactTimelineItem ? (
                        <CompactTimelineDetailDrawer
                          timelineItem={selectedCompactTimelineItem}
                          previousTimelineItem={previousCompactTimelineItem}
                          nextTimelineItem={nextCompactTimelineItem}
                          onSelectTimelineItem={(timelineItemId) => {
                            startTransition(() => {
                              setExpandedCompactTimelineItemId(timelineItemId);
                            });
                          }}
                          onClose={() => {
                            startTransition(() => {
                              setExpandedCompactTimelineItemId(null);
                            });
                          }}
                        />
                      ) : null}
                    </div>

                    <div className="devflow-detail-section">
                      <div className="devflow-detail-section__header">
                        <h3 className="devflow-detail-section__title">
                          <FileTextIcon className="devflow-icon devflow-icon--small" />
                          <span>PRD Document</span>
                        </h3>
                        <button
                          type="button"
                          className="devflow-detail-section__action"
                          onClick={() => setIsPrdFullscreenOpen(true)}
                        >
                          <ExpandIcon className="devflow-icon devflow-icon--tiny" />
                          <span>全屏查看</span>
                        </button>
                      </div>

                      <CardSurface className="devflow-document-card">
                        {isSelectedTaskPrdGenerating ? (
                          <div className="devflow-execution-banner">
                            <span className="devflow-footer__pulse" />
                            <span>AI 正在生成 PRD 文件，完成后将显示在这里...</span>
                          </div>
                        ) : (
                          <MarkdownBlock
                            className="devflow-markdown devflow-markdown--document"
                            markdownText={selectedTaskPrdMarkdown}
                            enableMermaid
                          />
                        )}
                      </CardSurface>

                      {isPrdFullscreenOpen ? (
                        <PrdFullscreenModal
                          taskTitle={selectedTask.task_title}
                          markdownText={selectedTaskPrdMarkdown}
                          isGenerating={isSelectedTaskPrdGenerating}
                          onClose={() => setIsPrdFullscreenOpen(false)}
                        />
                      ) : null}
                    </div>
                  </div>
                </div>

                {canSendFeedback ? (
                  <div className="devflow-feedback">
                    {feedbackAttachmentDraft ? (
                      <div className="devflow-feedback__attachment">
                        {renderAttachmentPreview(feedbackAttachmentDraft)}

                        <div className="devflow-feedback__attachment-copy">
                          <span className="devflow-feedback__attachment-name">
                            {feedbackAttachmentDraft.file.name}
                          </span>
                          <span className="devflow-feedback__attachment-meta">
                            {getAttachmentLabel(feedbackAttachmentDraft.kind)}
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
                        onClick={() => feedbackAttachmentInputRef.current?.click()}
                        disabled={activeMutationName === "feedback"}
                      >
                        <PaperclipIcon className="devflow-icon devflow-icon--small" />
                      </button>

                      <textarea
                        className="devflow-feedback__textarea"
                        placeholder="Ask AI to refine the PRD, or paste an image/video/file directly..."
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
                        ref={feedbackAttachmentInputRef}
                        className="devflow-feedback__file-input"
                        type="file"
                        onChange={handleAttachmentInputChange}
                      />
                    </div>
                    <p className="devflow-feedback__hint">
                      Tip: Press Enter to send, Shift + Enter for new line, or paste an
                      image/video/file directly into the composer.
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

interface MarkdownBlockProps {
  markdownText: string;
  className?: string;
  enableMermaid?: boolean;
}

interface MermaidDiagramBlockProps {
  chartDefinition: string;
}

const MARKDOWN_COMPONENT_MAP_WITH_MERMAID: Components = {
  pre({ children, node, ...restProps }) {
    const childNodeList = ReactChildren.toArray(children);
    const firstChildNode = childNodeList[0];

    if (
      childNodeList.length === 1 &&
      isValidElement(firstChildNode) &&
      firstChildNode.type === MermaidDiagramBlock
    ) {
      return <>{firstChildNode}</>;
    }

    return <pre {...restProps}>{children}</pre>;
  },
  code({ children, className, node, ...restProps }) {
    const codeText = String(children).replace(/\n$/, "");

    if (MARKDOWN_MERMAID_LANGUAGE_PATTERN.test(className ?? "")) {
      return <MermaidDiagramBlock chartDefinition={codeText} />;
    }

    return (
      <code {...restProps} className={className}>
        {children}
      </code>
    );
  },
};

const MarkdownBlock = memo(function MarkdownBlock({
  markdownText,
  className,
  enableMermaid = false,
}: MarkdownBlockProps) {
  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={MARKDOWN_REMARK_PLUGIN_LIST}
        components={enableMermaid ? MARKDOWN_COMPONENT_MAP_WITH_MERMAID : undefined}
      >
        {markdownText}
      </ReactMarkdown>
    </div>
  );
});

function MermaidDiagramBlock({ chartDefinition }: MermaidDiagramBlockProps) {
  const mermaidDiagramId = useId().replace(/:/g, "-");
  const [renderedSvgMarkup, setRenderedSvgMarkup] = useState<string | null>(null);
  const [renderErrorText, setRenderErrorText] = useState<string | null>(null);

  useEffect(() => {
    let isCancelled = false;

    setRenderedSvgMarkup(null);
    setRenderErrorText(null);

    async function renderMermaidDiagram(): Promise<void> {
      try {
        const mermaidModule = await import("mermaid");
        const mermaidApi = mermaidModule.default;

        if (!hasInitializedMermaidRenderer) {
          mermaidApi.initialize({
            startOnLoad: false,
            theme: "neutral",
            fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
          });
          hasInitializedMermaidRenderer = true;
        }

        const { svg } = await mermaidApi.render(
          `devflow-mermaid-${mermaidDiagramId}`,
          chartDefinition
        );
        if (isCancelled) {
          return;
        }

        setRenderedSvgMarkup(svg);
      } catch (error) {
        if (isCancelled) {
          return;
        }

        setRenderErrorText(
          error instanceof Error ? error.message : "Unknown Mermaid render error."
        );
      }
    }

    void renderMermaidDiagram();
    return () => {
      isCancelled = true;
    };
  }, [chartDefinition, mermaidDiagramId]);

  if (renderErrorText) {
    return (
      <div className="devflow-mermaid devflow-mermaid--error">
        <div className="devflow-mermaid__status">
          Mermaid 渲染失败，已回退为源码预览。
        </div>
        <pre className="devflow-mermaid__fallback">{chartDefinition}</pre>
        <p className="devflow-mermaid__error">{renderErrorText}</p>
      </div>
    );
  }

  if (!renderedSvgMarkup) {
    return (
      <div className="devflow-mermaid devflow-mermaid--loading">
        <div className="devflow-mermaid__status">Rendering Mermaid diagram...</div>
      </div>
    );
  }

  return (
    <div
      className="devflow-mermaid"
      dangerouslySetInnerHTML={{ __html: renderedSvgMarkup }}
    />
  );
}

interface PrdFullscreenModalProps {
  taskTitle: string;
  markdownText: string;
  isGenerating: boolean;
  onClose: () => void;
}

function PrdFullscreenModal({
  taskTitle,
  markdownText,
  isGenerating,
  onClose,
}: PrdFullscreenModalProps) {
  return (
    <div
      className="devflow-prd-modal"
      role="dialog"
      aria-modal="true"
      aria-label={`${taskTitle} PRD document`}
      onClick={onClose}
    >
      <div
        className="devflow-prd-modal__panel"
        onClick={(clickEvent) => {
          clickEvent.stopPropagation();
        }}
      >
        <div className="devflow-prd-modal__header">
          <div className="devflow-prd-modal__copy">
            <span className="devflow-prd-modal__eyebrow">PRD Fullscreen</span>
            <h4 className="devflow-prd-modal__title">{taskTitle}</h4>
            <p className="devflow-prd-modal__hint">
              按 Esc 或点击右上角关闭，滚动查看完整 PRD。
            </p>
          </div>

          <button
            type="button"
            className="devflow-prd-modal__close"
            onClick={onClose}
          >
            <XIcon className="devflow-icon devflow-icon--small" />
            <span>关闭</span>
          </button>
        </div>

        <div className="devflow-prd-modal__body">
          {isGenerating ? (
            <div className="devflow-execution-banner">
              <span className="devflow-footer__pulse" />
              <span>AI 正在生成 PRD 文件，完成后将显示在这里...</span>
            </div>
          ) : (
            <MarkdownBlock
              className="devflow-markdown devflow-markdown--document"
              markdownText={markdownText}
              enableMermaid
            />
          )}
        </div>
      </div>
    </div>
  );
}

interface CompactTimelineGroupCardProps {
  group: CompactTimelineGroup;
  isExpanded: boolean;
  isLatest: boolean;
  isStageMatched: boolean;
  expandedCompactTimelineItemId: string | null;
  onToggleItemDetail: (timelineItemId: string) => void;
  onToggle: () => void;
}

function CompactTimelineGroupCard({
  group,
  isExpanded,
  isLatest,
  isStageMatched,
  expandedCompactTimelineItemId,
  onToggleItemDetail,
  onToggle,
}: CompactTimelineGroupCardProps) {
  const visibleTimelineItemList = getVisibleCompactTimelineItemList(group, isExpanded);
  const hiddenTimelineItemCount =
    group.items.length - visibleTimelineItemList.length;
  const groupStartTimeLabel = group.items[0]?.timeLabel ?? "";
  const groupEndTimeLabel = group.items[group.items.length - 1]?.timeLabel ?? "";
  const groupTimeLabel =
    group.items.length > 1 && groupStartTimeLabel !== groupEndTimeLabel
      ? `${groupStartTimeLabel} - ${groupEndTimeLabel}`
      : groupStartTimeLabel;
  const groupLabel = group.label;
  const groupSourceLabel = buildCompactTimelineGroupSourceLabel(group);
  const groupSummaryText = buildCompactTimelineGroupSummaryText(group);
  const groupStatusLabel =
    group.tone === "error"
      ? "需处理"
      : group.tone === "success"
        ? "已完成"
        : null;

  return (
    <div
      className={joinClassNames(
        "devflow-timeline-group",
        `devflow-timeline-group--${group.tone}`,
        isLatest && "devflow-timeline-group--latest",
        isStageMatched && "devflow-timeline-group--current"
      )}
    >
      <div className="devflow-timeline-group__header">
        <div className="devflow-timeline-group__heading">
          <span
            className={joinClassNames(
              "devflow-timeline-group__icon-wrap",
              `devflow-timeline-group__icon-wrap--${group.tone}`
            )}
          >
            {renderCompactTimelineGroupIcon(group)}
          </span>

          <div className="devflow-timeline-group__heading-copy">
            <span className="devflow-timeline-group__eyebrow">{groupSourceLabel}</span>
            <span className="devflow-timeline-group__label">{groupLabel}</span>
            <span className="devflow-timeline-group__summary">{groupSummaryText}</span>
            {isLatest || isStageMatched ? (
              <div className="devflow-timeline-group__signals">
                {isStageMatched ? (
                  <span className="devflow-timeline-group__signal devflow-timeline-group__signal--current">
                    当前阶段
                  </span>
                ) : null}
                {isLatest ? (
                  <span className="devflow-timeline-group__signal devflow-timeline-group__signal--latest">
                    最近更新
                  </span>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>

        <div className="devflow-timeline-group__meta-row">
          <div
            className={joinClassNames(
              "devflow-timeline-group__meta-segment",
              "devflow-timeline-group__meta-segment--status-slot",
              groupStatusLabel
                ? "devflow-timeline-group__meta-segment--status"
                : "devflow-timeline-group__meta-segment--placeholder",
              groupStatusLabel && `devflow-timeline-group__meta-segment--${group.tone}`
            )}
            aria-hidden={!groupStatusLabel}
          >
            <span className="devflow-timeline-group__meta-label">状态</span>
            <span
              className={joinClassNames(
                "devflow-timeline-group__meta-value",
                "devflow-timeline-group__meta-value--status",
                !groupStatusLabel && "devflow-timeline-group__meta-value--placeholder",
                groupStatusLabel && `devflow-timeline-group__meta-value--${group.tone}`
              )}
            >
              {groupStatusLabel ? (
                <span className="devflow-timeline-group__meta-status-dot" />
              ) : null}
              {groupStatusLabel ?? "\u00a0"}
            </span>
          </div>

          <div className="devflow-timeline-group__meta-segment devflow-timeline-group__meta-segment--count">
            <span className="devflow-timeline-group__meta-label">日志</span>
            <span className="devflow-timeline-group__meta-value devflow-timeline-group__meta-value--count">
              {group.items.length}
              <span className="devflow-timeline-group__meta-unit">条</span>
            </span>
          </div>

          <div className="devflow-timeline-group__meta-segment devflow-timeline-group__meta-segment--time">
            <span className="devflow-timeline-group__meta-label">时间</span>
            <span className="devflow-timeline-group__meta-value devflow-timeline-group__meta-value--time">
              {groupTimeLabel}
            </span>
          </div>
        </div>
      </div>

      <div className="devflow-timeline-group__rows">
        {visibleTimelineItemList.map((timelineItem) => (
          <LightweightTimelineItem
            key={timelineItem.log.id}
            timelineItem={timelineItem}
            previewText={buildCompactTimelinePreviewText(timelineItem)}
            tone={deriveCompactTimelineItemTone(timelineItem)}
            isDetailOpen={expandedCompactTimelineItemId === timelineItem.log.id}
            onToggleDetail={() => onToggleItemDetail(timelineItem.log.id)}
          />
        ))}
      </div>

      {group.items.length > COMPACT_TIMELINE_GROUP_VISIBLE_COUNT ? (
        <button
          type="button"
          className="devflow-timeline-group__toggle"
          onClick={onToggle}
        >
          {isExpanded
            ? "收起这组日志"
            : `展开更早的 ${hiddenTimelineItemCount} 条日志`}
        </button>
      ) : null}
    </div>
  );
}

interface LightweightTimelineItemProps {
  timelineItem: TimelineViewModel;
  previewText: string;
  tone: "default" | "error" | "success";
  isDetailOpen: boolean;
  onToggleDetail: () => void;
}

const LightweightTimelineItem = memo(function LightweightTimelineItem({
  timelineItem,
  previewText,
  tone,
  isDetailOpen,
  onToggleDetail,
}: LightweightTimelineItemProps) {
  const isAiTimelineItem = timelineItem.kind === "ai_log";
  const sourceLabel = isAiTimelineItem ? "Agent" : "System";
  const metadataTagList = buildCompactTimelineMetadataTagList(timelineItem);
  const statusLabel =
    tone === "error" ? "错误" : tone === "success" ? "完成" : null;

  return (
    <div
      className={joinClassNames(
        "devflow-turn-card__compact-row",
        `devflow-turn-card__compact-row--${tone}`,
        isDetailOpen && "devflow-turn-card__compact-row--selected"
      )}
    >
      <div className="devflow-turn-card__compact-rail">
        <span className="devflow-turn-card__compact-time">{timelineItem.timeLabel}</span>
        <span
          className={joinClassNames(
            "devflow-turn-card__compact-source",
            isAiTimelineItem
              ? "devflow-turn-card__compact-source--ai"
              : "devflow-turn-card__compact-source--system"
          )}
        >
          {isAiTimelineItem ? (
            <RobotIcon className="devflow-icon devflow-icon--tiny devflow-icon--ai" />
          ) : (
            <CodeIcon className="devflow-icon devflow-icon--tiny" />
          )}
          <span>{sourceLabel}</span>
        </span>
      </div>

      <div className="devflow-turn-card__compact-main">
        <div className="devflow-turn-card__compact-copy">
          <p className="devflow-turn-card__lite-preview">{previewText}</p>
          {statusLabel ? (
            <span
              className={joinClassNames(
                "devflow-turn-card__compact-status",
                `devflow-turn-card__compact-status--${tone}`
              )}
            >
              {statusLabel}
            </span>
          ) : null}
        </div>

        <div className="devflow-turn-card__compact-meta">
          {metadataTagList.length > 0 ? (
            <div className="devflow-turn-card__compact-tags">
              {metadataTagList.map((metadataTag) => (
                <span
                  key={`${timelineItem.log.id}:${metadataTag}`}
                  className="devflow-turn-card__compact-tag"
                >
                  {metadataTag}
                </span>
              ))}
            </div>
          ) : null}

          <button
            type="button"
            className="devflow-turn-card__compact-detail-toggle"
            onClick={onToggleDetail}
          >
            {isDetailOpen ? "关闭详情" : "查看详情"}
          </button>
        </div>
      </div>
    </div>
  );
});

interface CompactTimelineDetailDrawerProps {
  timelineItem: TimelineViewModel;
  previousTimelineItem: TimelineViewModel | null;
  nextTimelineItem: TimelineViewModel | null;
  onSelectTimelineItem: (timelineItemId: string) => void;
  onClose: () => void;
}

function CompactTimelineDetailDrawer({
  timelineItem,
  previousTimelineItem,
  nextTimelineItem,
  onSelectTimelineItem,
  onClose,
}: CompactTimelineDetailDrawerProps) {
  const copyResetTimerRef = useRef<number | null>(null);
  const [copyButtonLabel, setCopyButtonLabel] = useState("复制原文");
  const metadataTagList = buildCompactTimelineMetadataTagList(timelineItem);
  const detailTone = deriveCompactTimelineItemTone(timelineItem);
  const detailAttachmentUrl =
    mapMediaPathToPublicUrl(timelineItem.log.media_original_image_path) ||
    mapMediaPathToPublicUrl(timelineItem.log.media_thumbnail_path);
  const detailSourceLabel =
    timelineItem.kind === "ai_log" ? "Agent" : "System";

  useEffect(() => {
    if (copyResetTimerRef.current) {
      window.clearTimeout(copyResetTimerRef.current);
      copyResetTimerRef.current = null;
    }
    setCopyButtonLabel("复制原文");
  }, [timelineItem.log.id]);

  useEffect(() => {
    return () => {
      if (copyResetTimerRef.current) {
        window.clearTimeout(copyResetTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    function handleDrawerKeydown(keyboardEvent: globalThis.KeyboardEvent): void {
      if (
        keyboardEvent.metaKey ||
        keyboardEvent.ctrlKey ||
        keyboardEvent.altKey ||
        keyboardEvent.shiftKey ||
        isEditableKeyboardEventTarget(keyboardEvent.target)
      ) {
        return;
      }

      if (keyboardEvent.key === "Escape") {
        keyboardEvent.preventDefault();
        onClose();
        return;
      }

      if (
        (keyboardEvent.key === "ArrowLeft" || keyboardEvent.key === "ArrowUp") &&
        previousTimelineItem
      ) {
        keyboardEvent.preventDefault();
        onSelectTimelineItem(previousTimelineItem.log.id);
        return;
      }

      if (
        (keyboardEvent.key === "ArrowRight" || keyboardEvent.key === "ArrowDown") &&
        nextTimelineItem
      ) {
        keyboardEvent.preventDefault();
        onSelectTimelineItem(nextTimelineItem.log.id);
      }
    }

    window.addEventListener("keydown", handleDrawerKeydown);
    return () => {
      window.removeEventListener("keydown", handleDrawerKeydown);
    };
  }, [nextTimelineItem, onClose, onSelectTimelineItem, previousTimelineItem]);

  function scheduleCopyButtonReset(): void {
    if (copyResetTimerRef.current) {
      window.clearTimeout(copyResetTimerRef.current);
    }
    copyResetTimerRef.current = window.setTimeout(() => {
      setCopyButtonLabel("复制原文");
      copyResetTimerRef.current = null;
    }, 1600);
  }

  async function handleCopyRawText(): Promise<void> {
    const rawTimelineText = timelineItem.log.text_content || "";

    if (!navigator.clipboard?.writeText) {
      setCopyButtonLabel("无法复制");
      scheduleCopyButtonReset();
      return;
    }

    try {
      await navigator.clipboard.writeText(rawTimelineText);
      setCopyButtonLabel("已复制");
    } catch {
      setCopyButtonLabel("复制失败");
    }

    scheduleCopyButtonReset();
  }

  return (
    <aside
      className={joinClassNames(
        "devflow-timeline-detail-drawer",
        `devflow-timeline-detail-drawer--${detailTone}`
      )}
    >
      <div className="devflow-timeline-detail-drawer__header">
        <div className="devflow-timeline-detail-drawer__copy">
          <span className="devflow-timeline-detail-drawer__eyebrow">
            {detailSourceLabel} Detail
          </span>
          <h4 className="devflow-timeline-detail-drawer__title">
            {buildCompactTimelinePreviewText(timelineItem)}
          </h4>
          <p className="devflow-timeline-detail-drawer__meta">
            {formatDateTime(timelineItem.log.created_at)}
          </p>
        </div>

        <button
          type="button"
          className="devflow-timeline-detail-drawer__close"
          onClick={onClose}
        >
          <XIcon className="devflow-icon devflow-icon--small" />
        </button>
      </div>

      {metadataTagList.length > 0 ? (
        <div className="devflow-timeline-detail-drawer__tags">
          {metadataTagList.map((metadataTag) => (
            <span
              key={`${timelineItem.log.id}:${metadataTag}`}
              className="devflow-timeline-detail-drawer__tag"
            >
              {metadataTag}
            </span>
          ))}
        </div>
      ) : null}

      <pre className="devflow-timeline-detail-drawer__body">
        {timelineItem.log.text_content || "无正文内容。"}
      </pre>

      <div className="devflow-timeline-detail-drawer__footer">
        <div className="devflow-timeline-detail-drawer__toolbar">
          <div className="devflow-timeline-detail-drawer__nav">
            <button
              type="button"
              className="devflow-timeline-detail-drawer__nav-btn"
              title="ArrowLeft / ArrowUp"
              disabled={!previousTimelineItem}
              onClick={() => {
                if (previousTimelineItem) {
                  onSelectTimelineItem(previousTimelineItem.log.id);
                }
              }}
            >
              <span className="devflow-timeline-detail-drawer__nav-arrow">←</span>
              <span>上一条</span>
            </button>
            <button
              type="button"
              className="devflow-timeline-detail-drawer__nav-btn"
              title="ArrowRight / ArrowDown"
              disabled={!nextTimelineItem}
              onClick={() => {
                if (nextTimelineItem) {
                  onSelectTimelineItem(nextTimelineItem.log.id);
                }
              }}
            >
              <span>下一条</span>
              <span className="devflow-timeline-detail-drawer__nav-arrow">→</span>
            </button>
          </div>

          <div className="devflow-timeline-detail-drawer__actions">
            <button
              type="button"
              className="devflow-timeline-detail-drawer__copy-btn"
              onClick={() => {
                void handleCopyRawText();
              }}
            >
              {copyButtonLabel}
            </button>

            {detailAttachmentUrl ? (
              <a
                className="devflow-timeline-detail-drawer__link"
                href={detailAttachmentUrl}
                target="_blank"
                rel="noreferrer"
              >
                查看附件
              </a>
            ) : null}
          </div>
        </div>

        <div className="devflow-timeline-detail-drawer__hint">
          <span className="devflow-timeline-detail-drawer__hint-label">快捷键</span>
          <span className="devflow-timeline-detail-drawer__kbd">Esc</span>
          <span className="devflow-timeline-detail-drawer__hint-copy">关闭</span>
          <span className="devflow-timeline-detail-drawer__kbd">← / ↑</span>
          <span className="devflow-timeline-detail-drawer__hint-copy">上一条</span>
          <span className="devflow-timeline-detail-drawer__kbd">→ / ↓</span>
          <span className="devflow-timeline-detail-drawer__hint-copy">下一条</span>
        </div>
      </div>
    </aside>
  );
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
  status: RequirementDisplayStage;
  label?: string;
}

function StatusBadge({ status, label }: StatusBadgeProps) {
  return (
    <span
      className={joinClassNames(
        "devflow-badge",
        `devflow-badge--${status}`
      )}
    >
      {label ?? formatTaskDisplayStageLabel(status)}
    </span>
  );
}

interface RequirementCardButtonProps {
  requirementViewModel: RequirementViewModel;
  isSelected: boolean;
  onSelectTaskId: Dispatch<SetStateAction<string | null>>;
}

const RequirementCardButton = memo(function RequirementCardButton({
  requirementViewModel,
  isSelected,
  onSelectTaskId,
}: RequirementCardButtonProps) {
  return (
    <button
      className={joinClassNames(
        "devflow-requirement-card-button",
        isSelected && "devflow-requirement-card-button--selected"
      )}
      onClick={() => {
        startTransition(() => {
          onSelectTaskId(requirementViewModel.task.id);
        });
      }}
    >
      <CardSurface
        className={joinClassNames(
          "devflow-requirement-card",
          isSelected && "devflow-requirement-card--selected"
        )}
      >
        <div className="devflow-requirement-card__meta">
          <StatusBadge
            status={requirementViewModel.displayStage}
            label={requirementViewModel.displayStageLabel}
          />
          <span
            className="devflow-requirement-card__date"
            title={requirementViewModel.cardMetaTitle}
          >
            {requirementViewModel.cardMetaLabel}
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
  );
});

function buildRequirementViewModel(
  taskItem: Task,
  taskDevLogList: DevLog[],
  taskCardMetadata: TaskCardMetadata
): RequirementViewModel {
  return {
    task: taskItem,
    description: buildRequirementDescription(taskItem, taskDevLogList),
    displayStage: taskCardMetadata.display_stage_key,
    displayStageLabel: taskCardMetadata.display_stage_label,
    cardMetaLabel: formatTaskCardActivityLabel(taskCardMetadata.last_ai_activity_at),
    cardMetaTitle: formatTaskCardActivityTitle(taskCardMetadata.last_ai_activity_at),
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

function buildTimelineRenderBlockList(
  timelineItemList: TimelineViewModel[]
): TimelineRenderBlock[] {
  const timelineRenderBlockList: TimelineRenderBlock[] = [];
  let compactTimelineItemList: TimelineViewModel[] = [];

  const flushCompactTimelineGroup = () => {
    if (compactTimelineItemList.length === 0) {
      return;
    }

    timelineRenderBlockList.push({
      kind: "compact_group",
      group: buildCompactTimelineGroup(compactTimelineItemList),
    });
    compactTimelineItemList = [];
  };

  for (const timelineItem of timelineItemList) {
    if (isHumanTimelineItem(timelineItem)) {
      flushCompactTimelineGroup();
      timelineRenderBlockList.push({
        kind: "human",
        item: timelineItem,
      });
      continue;
    }

    if (
      compactTimelineItemList.length > 0 &&
      shouldStartNewCompactTimelineGroup(compactTimelineItemList, timelineItem)
    ) {
      flushCompactTimelineGroup();
    }

    compactTimelineItemList.push(timelineItem);
  }

  flushCompactTimelineGroup();
  return timelineRenderBlockList;
}

function buildCompactTimelineGroup(
  timelineItemList: TimelineViewModel[]
): CompactTimelineGroup {
  const firstTimelineItem = timelineItemList[0];
  const lastTimelineItem = timelineItemList[timelineItemList.length - 1];
  const groupCategory = deriveCompactTimelineGroupCategory(timelineItemList);

  return {
    groupId: `${firstTimelineItem?.log.id ?? "group"}:${lastTimelineItem?.log.id ?? "group"}`,
    items: timelineItemList,
    category: groupCategory,
    label: deriveCompactTimelineGroupLabel(timelineItemList),
    tone: deriveCompactTimelineGroupTone(timelineItemList),
  };
}

function shouldStartNewCompactTimelineGroup(
  compactTimelineItemList: TimelineViewModel[],
  nextTimelineItem: TimelineViewModel
): boolean {
  if (compactTimelineItemList.length === 0) {
    return false;
  }

  const lastTimelineItem = compactTimelineItemList[compactTimelineItemList.length - 1];
  const lastTimelineCategory = deriveCompactTimelineItemCategory(lastTimelineItem);
  const nextTimelineCategory = deriveCompactTimelineItemCategory(nextTimelineItem);

  return (
    compactTimelineItemList.length >= COMPACT_TIMELINE_GROUP_MAX_SIZE ||
    lastTimelineItem.kind !== nextTimelineItem.kind ||
    lastTimelineCategory !== nextTimelineCategory
  );
}

function deriveCompactTimelineGroupCategory(
  timelineItemList: TimelineViewModel[]
): CompactTimelineCategory {
  const compactTimelineCategoryCountMap = new Map<CompactTimelineCategory, number>();

  for (const timelineItem of timelineItemList) {
    const nextCategory = deriveCompactTimelineItemCategory(timelineItem);
    compactTimelineCategoryCountMap.set(
      nextCategory,
      (compactTimelineCategoryCountMap.get(nextCategory) ?? 0) + 1
    );
  }

  let dominantCategory: CompactTimelineCategory = "general";
  let dominantCount = -1;
  for (const [category, count] of compactTimelineCategoryCountMap.entries()) {
    if (count > dominantCount) {
      dominantCategory = category;
      dominantCount = count;
    }
  }

  return dominantCategory;
}

function deriveCompactTimelineGroupLabel(
  timelineItemList: TimelineViewModel[]
): string {
  const firstTimelineItem = timelineItemList[0];
  const groupCategory = deriveCompactTimelineGroupCategory(timelineItemList);

  if (!firstTimelineItem) {
    return "运行日志";
  }

  if (groupCategory === "general") {
    return firstTimelineItem.kind === "system_event" ? "系统事件" : "Agent 运行";
  }

  return getCompactTimelineCategoryLabel(groupCategory);
}

function deriveCompactTimelineGroupTone(
  timelineItemList: TimelineViewModel[]
): "default" | "error" | "success" {
  if (timelineItemList.some((timelineItem) => deriveCompactTimelineItemTone(timelineItem) === "error")) {
    return "error";
  }

  if (
    timelineItemList.every(
      (timelineItem) => deriveCompactTimelineItemTone(timelineItem) === "success"
    )
  ) {
    return "success";
  }

  return "default";
}

function deriveCompactTimelineItemTone(
  timelineItem: TimelineViewModel
): "default" | "error" | "success" {
  const normalizedTimelineText = timelineItem.log.text_content.toLowerCase();
  if (
    timelineItem.log.state_tag === DevLogStateTag.BUG ||
    normalizedTimelineText.includes("error") ||
    normalizedTimelineText.includes("failed") ||
    normalizedTimelineText.includes("failure") ||
    normalizedTimelineText.includes("exception") ||
    normalizedTimelineText.includes("429") ||
    normalizedTimelineText.includes("exit 1") ||
    normalizedTimelineText.includes("失败")
  ) {
    return "error";
  }

  if (
    timelineItem.log.state_tag === DevLogStateTag.FIXED ||
    normalizedTimelineText.includes("success") ||
    normalizedTimelineText.includes("completed") ||
    normalizedTimelineText.includes("完成") ||
    normalizedTimelineText.includes("已完成")
  ) {
    return "success";
  }

  return "default";
}

function deriveCompactTimelineItemCategory(
  timelineItem: TimelineViewModel
): CompactTimelineCategory {
  const normalizedTimelineText = timelineItem.log.text_content.toLowerCase();

  if (
    deriveCompactTimelineItemTone(timelineItem) === "error" ||
    normalizedTimelineText.includes("changes requested") ||
    normalizedTimelineText.includes("rollback") ||
    normalizedTimelineText.includes("回退") ||
    normalizedTimelineText.includes("待修改")
  ) {
    return "changes";
  }

  if (normalizedTimelineText.includes("prd")) {
    return "prd";
  }

  if (
    normalizedTimelineText.includes("review") ||
    normalizedTimelineText.includes("self review") ||
    normalizedTimelineText.includes("自检") ||
    normalizedTimelineText.includes("评审")
  ) {
    return "review";
  }

  if (
    normalizedTimelineText.includes("test") ||
    normalizedTimelineText.includes("pytest") ||
    normalizedTimelineText.includes("playwright") ||
    normalizedTimelineText.includes("pre-commit") ||
    normalizedTimelineText.includes("lint") ||
    normalizedTimelineText.includes("测试")
  ) {
    return "test";
  }

  if (
    normalizedTimelineText.includes("pull request") ||
    normalizedTimelineText.includes("pr ") ||
    normalizedTimelineText.includes("pr:") ||
    normalizedTimelineText.includes("acceptance") ||
    normalizedTimelineText.includes("验收") ||
    normalizedTimelineText.includes("complete") ||
    normalizedTimelineText.includes("merge")
  ) {
    return "delivery";
  }

  if (timelineItem.kind === "system_event") {
    return "system";
  }

  if (
    normalizedTimelineText.includes("codex") ||
    normalizedTimelineText.includes("worktree") ||
    normalizedTimelineText.includes("implement") ||
    normalizedTimelineText.includes("coding") ||
    normalizedTimelineText.includes("修改文件") ||
    normalizedTimelineText.includes("涉及文件")
  ) {
    return "coding";
  }

  return "general";
}

function isHumanTimelineItem(timelineItem: TimelineViewModel): boolean {
  return (
    timelineItem.kind === "human_review" &&
    timelineItem.log.state_tag === DevLogStateTag.NONE
  );
}

function buildCompactTimelinePreviewText(timelineItem: TimelineViewModel): string {
  const rawTimelineText = timelineItem.log.text_content || "";
  const cleanedTimelinePreviewText = cleanMarkdownPreview(rawTimelineText);
  const filePathMatchList = extractCompactTimelineFilePathList(cleanedTimelinePreviewText);

  if (
    rawTimelineText.toLowerCase().includes("codex exec") &&
    (rawTimelineText.includes("失败") || rawTimelineText.toLowerCase().includes("failed"))
  ) {
    return "Codex 执行失败，任务已回退到待修改。";
  }

  if (
    rawTimelineText.includes("429 Too Many Requests") ||
    rawTimelineText.toLowerCase().includes("retry limit")
  ) {
    return "请求被限流：429 Too Many Requests。";
  }

  if (
    rawTimelineText.toLowerCase().includes("changes requested") ||
    rawTimelineText.includes("待修改")
  ) {
    return "任务进入待修改阶段，等待人工或下一轮处理。";
  }

  if (rawTimelineText.toLowerCase().includes("openai codex")) {
    return "启动 Codex 执行环境。";
  }

  if (deriveCompactTimelineItemTone(timelineItem) === "error") {
    const errorPreviewText = buildCompactTimelineErrorPreviewText(
      timelineItem,
      cleanedTimelinePreviewText,
      filePathMatchList
    );
    if (errorPreviewText) {
      return errorPreviewText;
    }
  }

  if (
    filePathMatchList.length > 0 &&
    /\bM\s+[\w./-]+\.[a-zA-Z0-9]+\b/.test(rawTimelineText)
  ) {
    return `修改文件：${filePathMatchList.join("、")}`;
  }

  if (
    filePathMatchList.length > 0 &&
    !rawTimelineText.toLowerCase().includes("error") &&
    !rawTimelineText.includes("失败")
  ) {
    return `涉及文件：${filePathMatchList.join("、")}`;
  }

  if (cleanedTimelinePreviewText.length > 0) {
    return truncateText(cleanedTimelinePreviewText, 140);
  }

  const hasTimelineAttachment =
    Boolean(timelineItem.log.media_original_image_path) ||
    Boolean(timelineItem.log.media_thumbnail_path);
  if (hasTimelineAttachment) {
    return timelineItem.kind === "ai_log"
      ? "AI 输出包含附件，正文未渲染。"
      : "系统日志包含附件，正文未渲染。";
  }

  return timelineItem.kind === "ai_log"
    ? "AI 输出正文未渲染。"
    : "系统日志正文未渲染。";
}

function buildCompactTimelineErrorPreviewText(
  timelineItem: TimelineViewModel,
  cleanedTimelinePreviewText: string,
  filePathMatchList: string[]
): string | null {
  const rawTimelineLineList = timelineItem.log.text_content
    .split("\n")
    .map((rawTimelineLine) => cleanMarkdownPreview(rawTimelineLine))
    .filter((rawTimelineLine) => rawTimelineLine.length > 0);
  const errorLinePattern =
    /(失败|failed|failure|exception|error|traceback|exit\s*1|429|denied|timeout|timed out|invalid)/i;
  const matchedErrorLine = rawTimelineLineList.find((rawTimelineLine) =>
    errorLinePattern.test(rawTimelineLine)
  );

  if (matchedErrorLine) {
    return `异常原因：${truncateText(matchedErrorLine, 116)}`;
  }

  const exceptionNameMatch = cleanedTimelinePreviewText.match(
    /\b([A-Za-z_][\w.]*(?:Exception|Error))\b/
  );
  if (exceptionNameMatch) {
    return `异常原因：${exceptionNameMatch[1]}`;
  }

  if (timelineItem.log.state_tag === DevLogStateTag.BUG) {
    if (filePathMatchList.length > 0) {
      return `处理异常，涉及文件：${filePathMatchList.join("、")}`;
    }
    if (cleanedTimelinePreviewText.length > 0) {
      return `处理异常：${truncateText(cleanedTimelinePreviewText, 118)}`;
    }
    return "处理异常，详细正文未渲染。";
  }

  return null;
}

function buildCompactTimelineGroupSummaryText(group: CompactTimelineGroup): string {
  const aiTimelineItemCount = group.items.filter(
    (timelineItem) => timelineItem.kind === "ai_log"
  ).length;
  const systemTimelineItemCount = group.items.length - aiTimelineItemCount;
  const summaryPartList: string[] = [];

  if (aiTimelineItemCount > 0) {
    summaryPartList.push(`Agent ${aiTimelineItemCount} 条`);
  }

  if (systemTimelineItemCount > 0) {
    summaryPartList.push(`System ${systemTimelineItemCount} 条`);
  }

  return summaryPartList.join(" · ");
}

function buildCompactTimelineGroupSourceLabel(group: CompactTimelineGroup): string {
  const aiTimelineItemCount = group.items.filter(
    (timelineItem) => timelineItem.kind === "ai_log"
  ).length;
  const systemTimelineItemCount = group.items.length - aiTimelineItemCount;

  if (aiTimelineItemCount > 0 && systemTimelineItemCount > 0) {
    return "Agent + System";
  }

  if (aiTimelineItemCount > 0) {
    return "Agent";
  }

  return "System";
}

function getCompactTimelineGroupCollapsedVisibleCount(
  group: CompactTimelineGroup
): number {
  if (group.tone === "error" || group.category === "changes") {
    return COMPACT_TIMELINE_ALERT_GROUP_VISIBLE_COUNT;
  }

  return COMPACT_TIMELINE_GROUP_VISIBLE_COUNT;
}

function getVisibleCompactTimelineItemList(
  group: CompactTimelineGroup,
  isExpanded: boolean
): TimelineViewModel[] {
  const collapsedVisibleCount = getCompactTimelineGroupCollapsedVisibleCount(group);

  if (isExpanded || group.items.length <= collapsedVisibleCount) {
    return group.items;
  }

  return group.items.slice(-collapsedVisibleCount);
}

function renderCompactTimelineGroupIcon(group: CompactTimelineGroup): ReactNode {
  const iconClassName = "devflow-icon devflow-icon--small";

  if (group.tone === "error" || group.category === "changes") {
    return <AlertTriangleIcon className={iconClassName} />;
  }

  switch (group.category) {
    case "prd":
      return <FileTextIcon className={iconClassName} />;
    case "coding":
      return <CodeIcon className={iconClassName} />;
    case "review":
      return <CheckCircleIcon className={iconClassName} />;
    case "test":
      return <TerminalIcon className={iconClassName} />;
    case "delivery":
      return <RocketIcon className={iconClassName} />;
    case "system":
      return <HistoryIcon className={iconClassName} />;
    case "general":
      return group.items[0]?.kind === "system_event"
        ? <HistoryIcon className={iconClassName} />
        : <RobotIcon className={iconClassName} />;
    default:
      return <HistoryIcon className={iconClassName} />;
  }
}

function buildCompactTimelineMetadataTagList(
  timelineItem: TimelineViewModel
): string[] {
  const metadataTagList: string[] = [];

  if (timelineItem.log.state_tag === DevLogStateTag.BUG) {
    metadataTagList.push("BUG");
  } else if (timelineItem.log.state_tag === DevLogStateTag.FIXED) {
    metadataTagList.push("FIXED");
  } else if (timelineItem.log.state_tag === DevLogStateTag.OPTIMIZATION) {
    metadataTagList.push("OPT");
  } else if (timelineItem.log.state_tag === DevLogStateTag.TRANSFERRED) {
    metadataTagList.push("SYNC");
  }

  metadataTagList.push(
    ...extractCompactTimelineFilePathList(
      cleanMarkdownPreview(timelineItem.log.text_content || "")
    ).slice(0, 2)
  );

  if (
    timelineItem.log.media_original_image_path ||
    timelineItem.log.media_thumbnail_path
  ) {
    metadataTagList.push("附件");
  }

  return Array.from(new Set(metadataTagList)).slice(0, 3);
}

function extractCompactTimelineFilePathList(rawTimelineText: string): string[] {
  return Array.from(
    new Set(rawTimelineText.match(/\b[\w./-]+\.[a-zA-Z0-9]+\b/g) ?? [])
  ).slice(0, 3);
}

function getCompactTimelineCategoryLabel(
  category: CompactTimelineCategory
): string {
  const compactTimelineCategoryLabelMap: Record<CompactTimelineCategory, string> = {
    general: "运行日志",
    prd: "PRD 生成",
    coding: "编码执行",
    review: "自检评审",
    test: "测试验证",
    delivery: "交付收尾",
    system: "系统事件",
    changes: "异常处理",
  };

  return compactTimelineCategoryLabelMap[category];
}

function mapWorkflowStageToCompactTimelineCategory(
  workflowStage: WorkflowStage | null
): CompactTimelineCategory | null {
  if (!workflowStage) {
    return null;
  }

  switch (workflowStage) {
    case WorkflowStage.PRD_GENERATING:
    case WorkflowStage.PRD_WAITING_CONFIRMATION:
      return "prd";
    case WorkflowStage.IMPLEMENTATION_IN_PROGRESS:
      return "coding";
    case WorkflowStage.SELF_REVIEW_IN_PROGRESS:
      return "review";
    case WorkflowStage.TEST_IN_PROGRESS:
      return "test";
    case WorkflowStage.PR_PREPARING:
    case WorkflowStage.ACCEPTANCE_IN_PROGRESS:
    case WorkflowStage.DONE:
      return "delivery";
    case WorkflowStage.CHANGES_REQUESTED:
      return "changes";
    default:
      return null;
  }
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

function buildTaskCardMetadataMap(
  taskCardMetadataList: TaskCardMetadata[]
): Record<string, TaskCardMetadata> {
  return Object.fromEntries(
    taskCardMetadataList.map((taskCardMetadata) => [
      taskCardMetadata.task_id,
      taskCardMetadata,
    ])
  );
}

function buildTaskCardMetadataFallbackMap(
  taskList: Task[],
  previousTaskCardMetadataMap: Record<string, TaskCardMetadata>
): Record<string, TaskCardMetadata> {
  return Object.fromEntries(
    taskList.map((taskItem) => [
      taskItem.id,
      resolveTaskCardMetadataFromSnapshot(
        taskItem,
        previousTaskCardMetadataMap[taskItem.id]
      ),
    ])
  );
}

function buildFallbackTaskCardMetadata(taskItem: Task): TaskCardMetadata {
  return {
    task_id: taskItem.id,
    display_stage_key: taskItem.workflow_stage,
    display_stage_label: formatStageLabel(taskItem.workflow_stage),
    is_waiting_for_user: false,
    last_ai_activity_at: taskItem.last_ai_activity_at,
  };
}

function didTaskEnterWaitingUserMetadataRefreshWindow(
  previousTaskSnapshot: Task | undefined,
  nextTaskSnapshot: Task
): boolean {
  if (!previousTaskSnapshot) {
    return false;
  }

  return (
    previousTaskSnapshot.is_codex_task_running &&
    !nextTaskSnapshot.is_codex_task_running &&
    WAITING_USER_METADATA_CANDIDATE_STAGE_SET.has(nextTaskSnapshot.workflow_stage)
  );
}

function shouldRefreshTaskCardMetadataAfterTaskListUpdate(
  previousTaskList: Task[],
  nextTaskList: Task[]
): boolean {
  const previousTaskSnapshotMap = new Map(
    previousTaskList.map((taskItem) => [taskItem.id, taskItem])
  );
  return nextTaskList.some((nextTaskItem) =>
    didTaskEnterWaitingUserMetadataRefreshWindow(
      previousTaskSnapshotMap.get(nextTaskItem.id),
      nextTaskItem
    )
  );
}

function resolveTaskCardMetadata(
  taskItem: Task,
  taskCardMetadataMap: Record<string, TaskCardMetadata>
): TaskCardMetadata {
  return resolveTaskCardMetadataFromSnapshot(
    taskItem,
    taskCardMetadataMap[taskItem.id]
  );
}

function resolveTaskCardMetadataFromSnapshot(
  taskItem: Task,
  cachedTaskCardMetadata: TaskCardMetadata | undefined
): TaskCardMetadata {
  const fallbackTaskCardMetadata = buildFallbackTaskCardMetadata(taskItem);
  if (!cachedTaskCardMetadata) {
    return fallbackTaskCardMetadata;
  }

  if (!isTaskCardMetadataCompatibleWithTaskSnapshot(taskItem, cachedTaskCardMetadata)) {
    return fallbackTaskCardMetadata;
  }

  return {
    ...cachedTaskCardMetadata,
    last_ai_activity_at: selectNewestTaskCardActivityAt(
      taskItem.last_ai_activity_at,
      cachedTaskCardMetadata.last_ai_activity_at
    ),
  };
}

function isTaskCardMetadataCompatibleWithTaskSnapshot(
  taskItem: Task,
  taskCardMetadata: TaskCardMetadata
): boolean {
  if (taskCardMetadata.task_id !== taskItem.id) {
    return false;
  }

  if (taskCardMetadata.display_stage_key === "waiting_user") {
    return (
      !taskItem.is_codex_task_running &&
      WAITING_USER_METADATA_CANDIDATE_STAGE_SET.has(taskItem.workflow_stage)
    );
  }

  return taskCardMetadata.display_stage_key === taskItem.workflow_stage;
}

function selectNewestTaskCardActivityAt(
  taskLastAiActivityAt: string | null,
  metadataLastAiActivityAt: string | null
): string | null {
  if (!taskLastAiActivityAt) {
    return metadataLastAiActivityAt;
  }
  if (!metadataLastAiActivityAt) {
    return taskLastAiActivityAt;
  }

  return toTimestampValue(taskLastAiActivityAt) >=
    toTimestampValue(metadataLastAiActivityAt)
    ? taskLastAiActivityAt
    : metadataLastAiActivityAt;
}

function formatTaskDisplayStageLabel(
  displayStage: RequirementDisplayStage
): string {
  if (displayStage === "waiting_user") {
    return "等待用户";
  }

  return formatStageLabel(displayStage);
}

function formatTaskCardActivityLabel(lastAiActivityAt: string | null): string {
  if (!lastAiActivityAt) {
    return "AI --";
  }

  return `AI ${formatHourMinute(lastAiActivityAt)}`;
}

function formatTaskCardActivityTitle(lastAiActivityAt: string | null): string {
  if (!lastAiActivityAt) {
    return "最近 AI：暂无自动化输出";
  }

  return `最近 AI：${formatDateTime(lastAiActivityAt)}`;
}

function canCompleteTask(
  taskItem: Task,
  taskStage: RequirementStage | null
): boolean {
  if (
    taskItem.lifecycle_status === TaskLifecycleStatus.CLOSED ||
    taskItem.lifecycle_status === TaskLifecycleStatus.DELETED
  ) {
    return false;
  }

  if (!taskItem.worktree_path) {
    return true;
  }

  if (taskStage === WorkflowStage.SELF_REVIEW_IN_PROGRESS) {
    return true;
  }

  return (
    taskStage === WorkflowStage.TEST_IN_PROGRESS ||
    taskStage === WorkflowStage.PR_PREPARING ||
    taskStage === WorkflowStage.ACCEPTANCE_IN_PROGRESS
  );
}

function hasLatestSelfReviewCyclePassed(taskDevLogList: DevLog[]): boolean {
  for (let index = taskDevLogList.length - 1; index >= 0; index -= 1) {
    const logText = taskDevLogList[index].text_content;
    if (
      SELF_REVIEW_PASSED_LOG_MARKER_LIST.some((markerText) =>
        logText.includes(markerText)
      )
    ) {
      return true;
    }
    if (
      SELF_REVIEW_STARTED_LOG_MARKER_LIST.some((markerText) =>
        logText.includes(markerText)
      )
    ) {
      return false;
    }
  }

  return false;
}

function hasLatestPostReviewLintCyclePassed(taskDevLogList: DevLog[]): boolean {
  for (let index = taskDevLogList.length - 1; index >= 0; index -= 1) {
    const logText = taskDevLogList[index].text_content;
    if (
      POST_REVIEW_LINT_PASSED_LOG_MARKER_LIST.some((markerText) =>
        logText.includes(markerText)
      )
    ) {
      return true;
    }
    if (
      POST_REVIEW_LINT_STARTED_LOG_MARKER_LIST.some((markerText) =>
        logText.includes(markerText)
      )
    ) {
      return false;
    }
  }

  return false;
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

function shouldAllowRequirementSummaryExpansion(
  requirementSummaryText: string
): boolean {
  const normalizedRequirementSummaryText = requirementSummaryText.trim();
  const summaryLineCount = normalizedRequirementSummaryText.split(/\r?\n/).length;

  return (
    normalizedRequirementSummaryText.length > 280 ||
    summaryLineCount > 4
  );
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

function formatTaskScheduleActionLabel(actionType: TaskScheduleActionType): string {
  const actionTypeLabelMap: Record<TaskScheduleActionType, string> = {
    [TaskScheduleActionType.START_TASK]: "start_task",
    [TaskScheduleActionType.RESUME_TASK]: "resume_task",
  };
  return actionTypeLabelMap[actionType];
}

function formatTaskScheduleTriggerLabel(triggerType: TaskScheduleTriggerType): string {
  const triggerTypeLabelMap: Record<TaskScheduleTriggerType, string> = {
    [TaskScheduleTriggerType.ONCE]: "once",
    [TaskScheduleTriggerType.CRON]: "cron",
  };
  return triggerTypeLabelMap[triggerType];
}

function formatTaskScheduleRunStatusLabel(
  runStatus: TaskScheduleRunStatus | null
): string {
  if (runStatus === null) {
    return "never";
  }

  const runStatusLabelMap: Record<TaskScheduleRunStatus, string> = {
    [TaskScheduleRunStatus.SUCCEEDED]: "succeeded",
    [TaskScheduleRunStatus.FAILED]: "failed",
    [TaskScheduleRunStatus.SKIPPED]: "skipped",
  };
  return runStatusLabelMap[runStatus];
}

function formatTaskScheduleRunStatusClassName(
  runStatus: TaskScheduleRunStatus | null
): string {
  if (runStatus === TaskScheduleRunStatus.SUCCEEDED) {
    return "devflow-task-schedule-panel__status devflow-task-schedule-panel__status--succeeded";
  }
  if (runStatus === TaskScheduleRunStatus.FAILED) {
    return "devflow-task-schedule-panel__status devflow-task-schedule-panel__status--failed";
  }
  if (runStatus === TaskScheduleRunStatus.SKIPPED) {
    return "devflow-task-schedule-panel__status devflow-task-schedule-panel__status--skipped";
  }
  return "devflow-task-schedule-panel__status";
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

function appendIncrementalDevLogList(
  previousDevLogList: DevLog[],
  incrementalDevLogList: DevLog[]
): DevLog[] {
  if (incrementalDevLogList.length === 0) {
    return previousDevLogList;
  }

  const existingDevLogIdSet = new Set(
    previousDevLogList.map((devLogItem) => devLogItem.id)
  );
  const appendedDevLogList = [...previousDevLogList];

  for (const incrementalDevLogItem of incrementalDevLogList) {
    if (existingDevLogIdSet.has(incrementalDevLogItem.id)) {
      continue;
    }
    appendedDevLogList.push(incrementalDevLogItem);
  }

  return appendedDevLogList;
}

function prependOlderDevLogList(
  previousDevLogList: DevLog[],
  olderDevLogList: DevLog[]
): DevLog[] {
  if (olderDevLogList.length === 0) {
    return previousDevLogList;
  }

  const existingDevLogIdSet = new Set(
    olderDevLogList.map((devLogItem) => devLogItem.id)
  );
  const prependedDevLogList = [...olderDevLogList];

  for (const previousDevLogItem of previousDevLogList) {
    if (!existingDevLogIdSet.has(previousDevLogItem.id)) {
      prependedDevLogList.push(previousDevLogItem);
    }
  }

  return prependedDevLogList;
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

function isEditableKeyboardEventTarget(eventTarget: EventTarget | null): boolean {
  if (!(eventTarget instanceof HTMLElement)) {
    return false;
  }

  const tagName = eventTarget.tagName;
  return (
    tagName === "INPUT" ||
    tagName === "TEXTAREA" ||
    tagName === "SELECT" ||
    eventTarget.isContentEditable
  );
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

function ExpandIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path
        d="M8 3H3v5M16 3h5v5M3 16v5h5M21 16v5h-5"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M9 9L3 3M15 9l6-6M9 15l-6 6M15 15l6 6"
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

function AlertTriangleIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path
        d="M12 3l9 16H3l9-16z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M12 9v4"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M12 16h.01"
        stroke="currentColor"
        strokeWidth="2.2"
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
