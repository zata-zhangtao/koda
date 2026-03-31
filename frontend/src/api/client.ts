/** API 客户端
 *
 * 封装与后端 API 的所有交互
 */

import type {
  AppConfig,
  CommandParseResult,
  DevLog,
  EmailSettings,
  EmailSettingsUpdate,
  ProjectTimelineEntry,
  ProjectTimelineSummary,
  ProjectTimelineTaskDetail,
  Project,
  RunAccount,
  Task,
  TaskCardMetadata,
  TaskQaContextScope,
  TaskQaCreateResponse,
  TaskQaFeedbackDraftResponse,
  TaskQaMessage,
  TaskChronicle,
  TaskSchedule,
  TaskScheduleRun,
  TaskReferenceCreateRequest,
  TaskReferenceCreateResponse,
  TimelineEntry,
  WebDAVSettings,
  WebDAVSettingsUpdate,
  WebDAVSyncResult,
} from "../types";
import { TaskLifecycleStatus, type WorkflowStage } from "../types";

const API_BASE = "/api";

type ApiErrorPayload = {
  detail?: string;
};

type LogListOptions = {
  createdAfter?: string | null;
  offset?: number;
};

type TaskListOptions = {
  projectId?: string | null;
  unlinkedOnly?: boolean;
};

function extractApiErrorMessage(
  responseText: string,
  statusCode: number
): string {
  if (!responseText) {
    return `HTTP ${statusCode}`;
  }

  try {
    const parsedErrorPayload = JSON.parse(responseText) as ApiErrorPayload;
    if (
      typeof parsedErrorPayload.detail === "string" &&
      parsedErrorPayload.detail.trim().length > 0
    ) {
      return parsedErrorPayload.detail;
    }
  } catch {
    // Ignore JSON parse errors and fall back to the raw response text.
  }

  return responseText;
}

/** 通用请求封装 */
async function fetchApi<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    headers: {
      "Content-Type": "application/json",
    },
    ...options,
  });

  if (!response.ok) {
    const responseText = await response.text();
    throw new Error(extractApiErrorMessage(responseText, response.status));
  }

  return response.json() as Promise<T>;
}

function buildTaskListQueryString(taskListOptions?: TaskListOptions): string {
  if (!taskListOptions) {
    return "";
  }

  const searchParams = new URLSearchParams();
  if (taskListOptions.projectId) {
    searchParams.set("project_id", taskListOptions.projectId);
  }
  if (taskListOptions.unlinkedOnly) {
    searchParams.set("unlinked_only", "true");
  }

  const serializedQueryString = searchParams.toString();
  return serializedQueryString ? `?${serializedQueryString}` : "";
}

/** RunAccount API */
export const runAccountApi = {
  /** 获取当前活跃账户 */
  getCurrent: () => fetchApi<RunAccount>("/run-accounts/current"),

  /** 列出所有账户 */
  list: () => fetchApi<RunAccount[]>("/run-accounts"),

  /** 创建账户 */
  create: (data: {
    user_name: string;
    environment_os: string;
    git_branch_name?: string;
    account_display_name?: string;
  }) =>
    fetchApi<RunAccount>("/run-accounts", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  /** 激活账户 */
  activate: (id: string) =>
    fetchApi<RunAccount>(`/run-accounts/${id}/activate`, {
      method: "PUT",
    }),
};

/** App Config API */
export const appConfigApi = {
  /** 获取前端运行时配置 */
  get: () => fetchApi<AppConfig>("/app-config"),
};

/** Task API */
export const taskApi = {
  /** 列出任务 */
  list: (taskListOptions?: TaskListOptions) =>
    fetchApi<Task[]>(`/tasks${buildTaskListQueryString(taskListOptions)}`),

  /** 列出任务卡片展示元数据 */
  listCardMetadata: (taskListOptions?: TaskListOptions) =>
    fetchApi<TaskCardMetadata[]>(
      `/tasks/card-metadata${buildTaskListQueryString(taskListOptions)}`
    ),

  /** 创建任务 */
  create: (data: {
    task_title: string;
    project_id?: string | null;
    requirement_brief?: string | null;
    auto_confirm_prd_and_execute?: boolean;
  }) =>
    fetchApi<Task>("/tasks", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  /** 更新任务生命周期状态 */
  updateStatus: (id: string, status: string) =>
    fetchApi<Task>(`/tasks/${id}/status`, {
      method: "PUT",
      body: JSON.stringify({ lifecycle_status: status }),
    }),

  /** 更新任务工作流阶段（通用阶段跳转） */
  updateStage: (id: string, workflowStage: WorkflowStage) =>
    fetchApi<Task>(`/tasks/${id}/stage`, {
      method: "PUT",
      body: JSON.stringify({ workflow_stage: workflowStage }),
    }),

  /** 启动任务：创建 worktree 并进入 PRD_GENERATING（「开始任务」按钮） */
  start: (id: string) =>
    fetchApi<Task>(`/tasks/${id}/start`, {
      method: "POST",
    }),

  /** 基于当前需求内容、反馈与附件重新生成 PRD */
  regeneratePrd: (id: string) =>
    fetchApi<Task>(`/tasks/${id}/regenerate-prd`, {
      method: "POST",
    }),

  /** 触发任务进入执行阶段（「开始执行」按钮） */
  execute: (id: string) =>
    fetchApi<Task>(`/tasks/${id}/execute`, {
      method: "POST",
    }),

  /** 从当前持久化工作流阶段恢复被中断的后台自动化 */
  resume: (id: string) =>
    fetchApi<Task>(`/tasks/${id}/resume`, {
      method: "POST",
    }),

  /** 触发任务进入完成收尾阶段（AI-summary-first commit + rebase + Codex conflict fix + merge + cleanup） */
  complete: (id: string) =>
    fetchApi<Task>(`/tasks/${id}/complete`, {
      method: "POST",
    }),

  /** 在检测到任务分支缺失后人工确认完成 */
  manualComplete: (id: string) =>
    fetchApi<Task>(`/tasks/${id}/manual-complete`, {
      method: "POST",
    }),

  /** 更新任务内容 */
  update: (
    id: string,
    data: {
      task_title: string;
      requirement_brief?: string | null;
      project_id?: string | null;
    }
  ) =>
    fetchApi<Task>(`/tasks/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),

  /** 销毁已启动任务，并要求记录销毁原因 */
  destroy: (id: string, data: { destroy_reason: string }) =>
    fetchApi<Task>(`/tasks/${id}/destroy`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  /** 获取任务详情 */
  get: (id: string) => fetchApi<Task>(`/tasks/${id}`),

  /** 读取 worktree 中的 PRD 文件内容 */
  getPrdFile: (id: string) =>
    fetchApi<{ content: string | null; path: string | null }>(`/tasks/${id}/prd-file`),

  /** 使用配置的编辑器命令打开 worktree 目录 */
  openInEditor: (id: string) =>
    fetchApi<{ opened: string }>(`/tasks/${id}/open-in-editor`, {
      method: "POST",
    }),

  /** 打开终端实时查看 codex 输出 */
  openTerminal: (id: string) =>
    fetchApi<{ log_file: string }>(`/tasks/${id}/open-terminal`, {
      method: "POST",
    }),

  /** 中断正在运行的 codex 进程并将任务回退至 changes_requested */
  cancel: (id: string) =>
    fetchApi<Task>(`/tasks/${id}/cancel`, {
      method: "POST",
    }),

  /** 把历史需求引用到目标任务卡片 */
  createReference: (targetTaskId: string, data: TaskReferenceCreateRequest) =>
    fetchApi<TaskReferenceCreateResponse>(`/tasks/${targetTaskId}/references`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
};

/** Task Schedule API */
export const taskScheduleApi = {
  /** 列出任务调度规则 */
  list: (taskId: string) =>
    fetchApi<TaskSchedule[]>(`/tasks/${taskId}/schedules`),

  /** 创建任务调度规则 */
  create: (
    taskId: string,
    data: {
      schedule_name: string;
      action_type: "start_task" | "resume_task";
      trigger_type: "once" | "cron";
      run_at?: string | null;
      cron_expr?: string | null;
      timezone_name?: string;
      is_enabled?: boolean;
    }
  ) =>
    fetchApi<TaskSchedule>(`/tasks/${taskId}/schedules`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  /** 更新任务调度规则 */
  update: (
    taskId: string,
    scheduleId: string,
    data: {
      schedule_name?: string;
      action_type?: "start_task" | "resume_task";
      trigger_type?: "once" | "cron";
      run_at?: string | null;
      cron_expr?: string | null;
      timezone_name?: string;
      is_enabled?: boolean;
    }
  ) =>
    fetchApi<TaskSchedule>(`/tasks/${taskId}/schedules/${scheduleId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),

  /** 删除任务调度规则 */
  delete: async (taskId: string, scheduleId: string) => {
    const response = await fetch(`${API_BASE}/tasks/${taskId}/schedules/${scheduleId}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      const responseText = await response.text();
      throw new Error(extractApiErrorMessage(responseText, response.status));
    }
  },

  /** 手动立即触发一次调度规则 */
  runNow: (taskId: string, scheduleId: string) =>
    fetchApi<TaskScheduleRun>(`/tasks/${taskId}/schedules/${scheduleId}/run-now`, {
      method: "POST",
    }),

  /** 查询任务调度执行历史 */
  listRuns: (taskId: string, limit = 50) =>
    fetchApi<TaskScheduleRun[]>(
      `/tasks/${taskId}/schedules/runs?limit=${encodeURIComponent(String(limit))}`
    ),
};

/** Task sidecar Q&A API */
export const taskQaApi = {
  /** 获取任务独立问答消息列表 */
  list: (taskId: string) =>
    fetchApi<TaskQaMessage[]>(`/tasks/${taskId}/qa/messages`),

  /** 发送任务独立问答 */
  create: (
    taskId: string,
    data: {
      question_markdown: string;
      context_scope: TaskQaContextScope;
    }
  ) =>
    fetchApi<TaskQaCreateResponse>(`/tasks/${taskId}/qa/messages`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  /** 将独立问答结论整理成反馈草稿 */
  convertToFeedbackDraft: (taskId: string, messageId: string) =>
    fetchApi<TaskQaFeedbackDraftResponse>(
      `/tasks/${taskId}/qa/messages/${messageId}/feedback-draft`,
      {
        method: "POST",
      }
    ),
};

/** Project API */
export const projectApi = {
  /** 列出所有项目 */
  list: () => fetchApi<Project[]>("/projects"),

  /** 创建项目 */
  create: (data: {
    display_name: string;
    project_category?: string | null;
    repo_path: string;
    description?: string | null;
  }) =>
    fetchApi<Project>("/projects", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  /** 更新项目，主要用于在新机器上重绑本地仓库路径 */
  update: (
    id: string,
    data: {
      display_name: string;
      project_category?: string | null;
      repo_path: string;
      description?: string | null;
    }
  ) =>
    fetchApi<Project>(`/projects/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  /** 获取项目详情 */
  get: (id: string) => fetchApi<Project>(`/projects/${id}`),

  /** 删除项目 */
  delete: async (id: string) => {
    const response = await fetch(`${API_BASE}/projects/${id}`, { method: "DELETE" });
    if (!response.ok) {
      const responseText = await response.text();
      throw new Error(extractApiErrorMessage(responseText, response.status));
    }
  },

  /** 使用配置的编辑器命令打开项目根目录 */
  openInEditor: (id: string) =>
    fetchApi<{ opened: string }>(`/projects/${id}/open-in-editor`, {
      method: "POST",
    }),
};

/** DevLog API */
export const logApi = {
  /** 列出日志 */
  list: (taskId?: string, limit = 100, options?: LogListOptions) => {
    const searchParams = new URLSearchParams();
    if (taskId) {
      searchParams.set("task_id", taskId);
    }
    searchParams.set("limit", String(limit));
    if (typeof options?.offset === "number") {
      searchParams.set("offset", String(options.offset));
    }
    if (options?.createdAfter) {
      searchParams.set("created_after", options.createdAfter);
    }
    return fetchApi<DevLog[]>(`/logs?${searchParams.toString()}`);
  },

  /** 创建日志 */
  create: (data: {
    text_content: string;
    state_tag?: string;
    task_id?: string;
    media_original_image_path?: string;
    media_thumbnail_path?: string;
  }) =>
    fetchApi<DevLog>("/logs", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  /** 解析命令 */
  parseCommand: (text: string) =>
    fetchApi<CommandParseResult>(`/logs/parse-command?text=${encodeURIComponent(text)}`),

  /** 创建日志（带命令解析） */
  createWithCommand: (text: string) =>
    fetchApi<DevLog>(`/logs/create-with-command?text=${encodeURIComponent(text)}`, {
      method: "POST",
    }),

  /** 获取待校正队列 */
  getReviewQueue: () => fetchApi<DevLog[]>("/logs/review-queue"),
};

/** Media API */
export const mediaApi = {
  /** 上传图片 */
  uploadImage: async (
    file: File,
    textContent = "",
    taskId?: string
  ): Promise<DevLog> => {
    const formData = new FormData();
    formData.append("uploaded_image_file", file);
    formData.append("text_content", textContent);
    if (taskId) {
      formData.append("task_id", taskId);
    }

    const response = await fetch(`${API_BASE}/media/upload`, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(error || `HTTP ${response.status}`);
    }

    return response.json();
  },

  /** 上传附件 */
  uploadAttachment: async (
    file: File,
    textContent = "",
    taskId?: string
  ): Promise<DevLog> => {
    const formData = new FormData();
    formData.append("uploaded_file", file);
    formData.append("text_content", textContent);
    if (taskId) {
      formData.append("task_id", taskId);
    }

    const response = await fetch(`${API_BASE}/media/upload-attachment`, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(error || `HTTP ${response.status}`);
    }

    return response.json();
  },

  /** 获取图片 URL */
  getImageUrl: (filename: string, isThumbnail = false) =>
    `/media/${filename}${isThumbnail ? "?thumbnail=true" : ""}`,
};

/** Email Settings API */
export const emailSettingsApi = {
  /** 获取邮件设置 */
  get: () => fetchApi<EmailSettings>("/email-settings"),

  /** 保存邮件设置（upsert） */
  save: (data: EmailSettingsUpdate) =>
    fetchApi<EmailSettings>("/email-settings", {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  /** 发送测试邮件 */
  test: (subject?: string, body?: string) =>
    fetchApi<{ success: boolean; message: string }>("/email-settings/test", {
      method: "POST",
      body: JSON.stringify({ subject, body }),
    }),
};

/** WebDAV Settings API */
export const webdavSettingsApi = {
  /** 获取 WebDAV 设置 */
  get: () => fetchApi<WebDAVSettings>("/webdav-settings"),

  /** 保存 WebDAV 设置（upsert） */
  save: (data: WebDAVSettingsUpdate) =>
    fetchApi<WebDAVSettings>("/webdav-settings", {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  /** 测试 WebDAV 连接 */
  test: () => fetchApi<WebDAVSyncResult>("/webdav-settings/test", { method: "POST" }),

  /** 上传数据库到 WebDAV */
  upload: () => fetchApi<WebDAVSyncResult>("/webdav-settings/sync/upload", { method: "POST" }),

  /** 从 WebDAV 下载数据库（覆盖本地） */
  download: () => fetchApi<WebDAVSyncResult>("/webdav-settings/sync/download", { method: "POST" }),

  /** 上传业务状态快照到 WebDAV */
  uploadBusinessSnapshot: () =>
    fetchApi<WebDAVSyncResult>("/webdav-settings/sync/business/upload", {
      method: "POST",
    }),

  /** 从 WebDAV 下载业务状态快照并导入当前工作区 */
  downloadBusinessSnapshot: () =>
    fetchApi<WebDAVSyncResult>("/webdav-settings/sync/business/download", {
      method: "POST",
    }),
};

/** Chronicle API */
export const chronicleApi = {
  /** 获取时间线 */
  getTimeline: () => fetchApi<TimelineEntry[]>("/chronicle/timeline"),

  /** 获取任务编年史 */
  getTaskChronicle: (taskId: string) =>
    fetchApi<TaskChronicle>(`/chronicle/task/${taskId}`),

  /** 导出 Markdown */
  exportMarkdown: (params?: { task_id?: string }) =>
    fetch(`/api/chronicle/export?format=markdown${params?.task_id ? `&task_id=${params.task_id}` : ""}`),

  /** 获取项目维度时间线 */
  getProjectTimeline: (params: {
    project_id?: string | null;
    project_category?: string | null;
    lifecycle_status?: TaskLifecycleStatus[];
    start_date?: string | null;
    end_date?: string | null;
    limit?: number;
    offset?: number;
  }) => {
    const searchParams = new URLSearchParams();
    if (params.project_id) {
      searchParams.set("project_id", params.project_id);
    }
    if (params.project_category) {
      searchParams.set("project_category", params.project_category);
    }
    for (const lifecycleStatus of params.lifecycle_status ?? []) {
      searchParams.append("lifecycle_status", lifecycleStatus);
    }
    if (params.start_date) {
      searchParams.set("start_date", params.start_date);
    }
    if (params.end_date) {
      searchParams.set("end_date", params.end_date);
    }
    searchParams.set("limit", String(params.limit ?? 100));
    searchParams.set("offset", String(params.offset ?? 0));
    return fetchApi<ProjectTimelineEntry[]>(
      `/chronicle/project-timeline?${searchParams.toString()}`
    );
  },

  /** 获取项目时间线中的任务详情 */
  getProjectTimelineTaskDetail: (taskId: string) =>
    fetchApi<ProjectTimelineTaskDetail>(`/chronicle/project-timeline/${taskId}`),

  /** 生成项目时间线摘要 */
  summarizeProjectTimeline: (data: {
    project_id?: string | null;
    project_category?: string | null;
    lifecycle_status_list?: TaskLifecycleStatus[] | null;
    start_date?: string | null;
    end_date?: string | null;
    summary_focus?: "progress" | "risk" | "decision";
  }) =>
    fetchApi<ProjectTimelineSummary>("/chronicle/project-timeline/summary", {
      method: "POST",
      body: JSON.stringify(data),
    }),
};
