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
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { logApi, mediaApi, runAccountApi, taskApi } from "./api/client";
import {
  AIProcessingStatus,
  DevLogStateTag,
  TaskLifecycleStatus,
  type DevLog,
  type RunAccount,
  type Task,
} from "./types";

type RequirementStage =
  | "pending"
  | "prd_generating"
  | "prd_ready"
  | "coding"
  | "reviewing"
  | "testing"
  | "completed"
  | "changed"
  | "deleted";

type TimelineKind = "ai_log" | "human_review" | "system_event";
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
  | "feedback"
  | "update"
  | "complete"
  | "delete"
  | null;

const GUEST_USER_LABEL = "Guest User";
const REQUIREMENT_UPDATE_MARKER = "<!-- requirement-change:update -->";
const REQUIREMENT_DELETE_MARKER = "<!-- requirement-change:delete -->";

function App() {
  const attachmentInputRef = useRef<HTMLInputElement | null>(null);

  const [currentRunAccount, setCurrentRunAccount] = useState<RunAccount | null>(null);
  const [taskList, setTaskList] = useState<Task[]>([]);
  const [allDevLogList, setAllDevLogList] = useState<DevLog[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [workspaceView, setWorkspaceView] = useState<WorkspaceView>("active");
  const [isCreatePanelOpen, setIsCreatePanelOpen] = useState(false);
  const [isEditPanelOpen, setIsEditPanelOpen] = useState(false);
  const [newRequirementTitle, setNewRequirementTitle] = useState("");
  const [newRequirementDescription, setNewRequirementDescription] = useState("");
  const [editRequirementTitle, setEditRequirementTitle] = useState("");
  const [editRequirementDescription, setEditRequirementDescription] = useState("");
  const [feedbackInputText, setFeedbackInputText] = useState("");
  const [feedbackAttachmentDraft, setFeedbackAttachmentDraft] =
    useState<AttachmentDraft | null>(null);
  const [activeMutationName, setActiveMutationName] = useState<MutationName>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isDashboardLoading, setIsDashboardLoading] = useState(true);

  useEffect(() => {
    void loadDashboardData();
  }, []);

  useEffect(() => {
    return () => {
      if (feedbackAttachmentDraft?.previewUrl) {
        URL.revokeObjectURL(feedbackAttachmentDraft.previewUrl);
      }
    };
  }, [feedbackAttachmentDraft]);

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
  const selectedTask =
    visibleTaskList.find((taskItem) => taskItem.id === selectedTaskId) ?? null;
  const selectedTaskDevLogs = selectedTask
    ? devLogsByTaskId[selectedTask.id] ?? []
    : [];
  const selectedTaskSnapshot = selectedTask
    ? deriveRequirementSnapshot(selectedTask, selectedTaskDevLogs)
    : null;
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

  useEffect(() => {
    setIsCreatePanelOpen(false);
    setIsEditPanelOpen(false);
    setFeedbackInputText("");
    setFeedbackAttachmentDraft(null);
    setSuccessMessage(null);
    setErrorMessage(null);
  }, [workspaceView, selectedTaskId]);

  async function loadDashboardData(): Promise<void> {
    setIsDashboardLoading(true);

    const [
      runAccountResult,
      taskListResult,
      devLogListResult,
    ] = await Promise.allSettled([
      runAccountApi.getCurrent(),
      taskApi.list(),
      logApi.list(),
    ]);

    const nextRunAccount =
      runAccountResult.status === "fulfilled" ? runAccountResult.value : null;
    const nextTaskList =
      taskListResult.status === "fulfilled"
        ? sortTaskListByCreatedAt(taskListResult.value)
        : [];
    const nextAllDevLogList =
      devLogListResult.status === "fulfilled"
        ? sortDevLogListByCreatedAt(devLogListResult.value)
        : [];

    setCurrentRunAccount(nextRunAccount);
    setTaskList(nextTaskList);
    setAllDevLogList(nextAllDevLogList);
    setSelectedTaskId((previousSelectedTaskId) => {
      if (!previousSelectedTaskId) {
        return previousSelectedTaskId;
      }

      const hasMatchingTask = nextTaskList.some(
        (taskItem) => taskItem.id === previousSelectedTaskId
      );
      return hasMatchingTask ? previousSelectedTaskId : null;
    });

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
      });

      await logApi.create({
        task_id: createdTask.id,
        text_content: nextRequirementDescription,
        state_tag: DevLogStateTag.NONE,
      });

      setWorkspaceView("active");
      setSelectedTaskId(createdTask.id);
      setNewRequirementTitle("");
      setNewRequirementDescription("");
      setSuccessMessage("Requirement created successfully.");
      await loadDashboardData();

      window.setTimeout(() => {
        setIsCreatePanelOpen(false);
        setSuccessMessage(null);
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
      await taskApi.updateStatus(taskItem.id, TaskLifecycleStatus.OPEN);
      await logApi.create({
        task_id: taskItem.id,
        text_content:
          "Autonomous workflow started. Preparing PRD outline and implementation track.",
        state_tag: DevLogStateTag.OPTIMIZATION,
      });
      await loadDashboardData();
    } catch (startError) {
      console.error(startError);
      setErrorMessage("Failed to start task.");
    } finally {
      setActiveMutationName(null);
    }
  }

  async function handleConfirmPrd(taskItem: Task): Promise<void> {
    setActiveMutationName("confirm");
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      if (taskItem.lifecycle_status === TaskLifecycleStatus.PENDING) {
        await taskApi.updateStatus(taskItem.id, TaskLifecycleStatus.OPEN);
      }

      await logApi.create({
        task_id: taskItem.id,
        text_content:
          "PRD confirmed. Continue implementation, review, and validation based on the approved scope.",
        state_tag: DevLogStateTag.FIXED,
      });
      await loadDashboardData();
    } catch (confirmError) {
      console.error(confirmError);
      setErrorMessage("Failed to confirm PRD.");
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
      if (titleChanged) {
        await taskApi.update(selectedTask.id, {
          task_title: nextRequirementTitle,
        });
      }

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
      await loadDashboardData();
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
      await taskApi.updateStatus(taskItem.id, TaskLifecycleStatus.CLOSED);
      await logApi.create({
        task_id: taskItem.id,
        text_content:
          "Requirement completed and moved into the completed archive.",
        state_tag: DevLogStateTag.FIXED,
      });
      setWorkspaceView("completed");
      setSuccessMessage("Requirement moved to completed.");
      await loadDashboardData();
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
      await loadDashboardData();
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
      await loadDashboardData();
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

            <div className="devflow-user-chip">
              <span className="devflow-user-chip__avatar">
                <UserIcon className="devflow-icon devflow-icon--tiny" />
              </span>
              <span className="devflow-user-chip__label">{currentUserLabel}</span>
            </div>
          </div>
        </div>
      </header>

      <main className="devflow-shell devflow-main">
        {errorMessage ? (
          <div className="devflow-alert devflow-alert--error">
            <RobotIcon className="devflow-icon devflow-icon--tiny" />
            <span>{errorMessage}</span>
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
                  onClick={() => {
                    setIsCreatePanelOpen(true);
                    setErrorMessage(null);
                    setSuccessMessage(null);
                  }}
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
                    onClick={() => {
                      setIsCreatePanelOpen(false);
                      setErrorMessage(null);
                      setSuccessMessage(null);
                    }}
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
                      onClick={() => setIsCreatePanelOpen(true)}
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
                      {selectedTask.lifecycle_status !== TaskLifecycleStatus.CLOSED &&
                      selectedTask.lifecycle_status !== TaskLifecycleStatus.OPEN &&
                      selectedTask.lifecycle_status !== TaskLifecycleStatus.DELETED ? (
                        <ActionButton
                          variant="primary"
                          busy={activeMutationName === "start"}
                          onClick={() => {
                            void handleStartTask(selectedTask);
                          }}
                        >
                          <PlayIcon className="devflow-icon devflow-icon--small" />
                          <span>Start Task</span>
                        </ActionButton>
                      ) : null}

                      {selectedTaskStage === "prd_ready" &&
                      selectedTask.lifecycle_status !== TaskLifecycleStatus.DELETED ? (
                        <ActionButton
                          variant="secondary"
                          busy={activeMutationName === "confirm"}
                          onClick={() => {
                            void handleConfirmPrd(selectedTask);
                          }}
                        >
                          <CheckCircleIcon className="devflow-icon devflow-icon--small" />
                          <span>Confirm PRD</span>
                        </ActionButton>
                      ) : null}

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

                      <div className="devflow-timeline">
                        {selectedTimelineItemList.length === 0 ? (
                          <div className="devflow-empty-card devflow-empty-card--detail">
                            <p className="devflow-empty-card__text">
                              Timeline will appear here after task activity begins.
                            </p>
                          </div>
                        ) : null}

                        {selectedTimelineItemList.map((timelineViewModel) => {
                          const timelineImageUrl =
                            mapMediaPathToPublicUrl(
                              timelineViewModel.log.media_original_image_path
                            ) ||
                            mapMediaPathToPublicUrl(
                              timelineViewModel.log.media_thumbnail_path
                            );

                          return (
                            <article
                              key={timelineViewModel.log.id}
                              className="devflow-timeline-item"
                            >
                              <div
                                className={joinClassNames(
                                  "devflow-timeline-item__dot",
                                  `devflow-timeline-item__dot--${timelineViewModel.kind}`
                                )}
                              />

                              <div className="devflow-timeline-item__content">
                                <div className="devflow-timeline-item__meta">
                                  {timelineViewModel.kind === "ai_log" ? (
                                    <RobotIcon className="devflow-icon devflow-icon--tiny devflow-icon--ai" />
                                  ) : (
                                    <UserIcon className="devflow-icon devflow-icon--tiny devflow-icon--human" />
                                  )}
                                  <span className="devflow-timeline-item__author">
                                    {timelineViewModel.authorName}
                                  </span>
                                  <span className="devflow-timeline-item__time">
                                    {timelineViewModel.timeLabel}
                                  </span>
                                </div>

                                <div className="devflow-markdown devflow-timeline-item__markdown">
                                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                    {timelineViewModel.log.text_content ||
                                      "No message content provided."}
                                  </ReactMarkdown>
                                </div>

                                {timelineImageUrl ? (
                                  <a
                                    className="devflow-timeline-item__image-link"
                                    href={timelineImageUrl}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    <img
                                      className="devflow-timeline-item__image"
                                      src={timelineImageUrl}
                                      alt="Timeline attachment"
                                    />
                                  </a>
                                ) : null}
                              </div>
                            </article>
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
                        <div className="devflow-markdown devflow-markdown--document">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {selectedTaskDocumentMarkdown}
                          </ReactMarkdown>
                        </div>
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
  variant?: "primary" | "secondary" | "outline" | "ghost";
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

  const firstTextLog = taskDevLogList.find((devLogItem) =>
    Boolean(cleanMarkdownPreview(devLogItem.text_content))
  );

  if (!firstTextLog) {
    return {
      summary: "No requirement brief captured yet.",
      title: taskItem.task_title,
      changeKind: null,
    };
  }

  return {
    summary: cleanMarkdownPreview(firstTextLog.text_content),
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
    "- [ ] Verify responsive behavior on narrow screens",
    "- [ ] Keep current backend task and log flows operational",
  ].join("\n");
}

function deriveRequirementStage(
  taskItem: Task,
  taskDevLogList: DevLog[]
): RequirementStage {
  if (taskItem.lifecycle_status === TaskLifecycleStatus.DELETED) {
    return "deleted";
  }

  if (hasRequirementUpdateLog(taskDevLogList)) {
    return "changed";
  }

  if (taskItem.lifecycle_status === TaskLifecycleStatus.CLOSED) {
    return "completed";
  }

  if (
    taskDevLogList.some(
      (devLogItem) =>
        devLogItem.ai_processing_status === AIProcessingStatus.CONFIRMED ||
        Boolean(devLogItem.ai_generated_title) ||
        Boolean(devLogItem.ai_analysis_text) ||
        Boolean(devLogItem.ai_extracted_code)
    )
  ) {
    return "prd_ready";
  }

  if (taskItem.lifecycle_status === TaskLifecycleStatus.PENDING) {
    return "pending";
  }

  if (taskDevLogList.length === 0) {
    return "prd_generating";
  }

  if (taskDevLogList.length <= 2) {
    return "prd_ready";
  }

  if (taskDevLogList.length <= 5) {
    return "coding";
  }

  if (taskDevLogList.length <= 8) {
    return "reviewing";
  }

  return "testing";
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
    .replace(/[#!>*_[\]()\-]+/g, " ")
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
  if (stage === "prd_ready") {
    return "prd ready";
  }

  if (stage === "prd_generating") {
    return "drafting";
  }

  return stage.replace(/_/g, " ");
}

function formatMonthDay(rawDateText: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  }).format(new Date(rawDateText));
}

function formatHourMinute(rawDateText: string): string {
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(rawDateText));
}

function formatDateTime(rawDateText: string): string {
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(rawDateText));
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

function toTimestampValue(rawDateText: string): number {
  const parsedTimestamp = Date.parse(rawDateText);
  return Number.isNaN(parsedTimestamp) ? 0 : parsedTimestamp;
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

export default App;
