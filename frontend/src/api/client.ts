/** API 客户端
 *
 * 封装与后端 API 的所有交互
 */

import type {
  CommandParseResult,
  DevLog,
  Project,
  RunAccount,
  Task,
  TaskChronicle,
  TimelineEntry,
} from "../types";
import { type WorkflowStage } from "../types";

const API_BASE = "/api";

type ApiErrorPayload = {
  detail?: string;
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

/** Task API */
export const taskApi = {
  /** 列出任务 */
  list: () => fetchApi<Task[]>("/tasks"),

  /** 创建任务 */
  create: (data: { task_title: string; project_id?: string | null; requirement_brief?: string | null }) =>
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

  /** 触发任务进入执行阶段（「开始执行」按钮） */
  execute: (id: string) =>
    fetchApi<Task>(`/tasks/${id}/execute`, {
      method: "POST",
    }),

  /** 更新任务内容 */
  update: (id: string, data: { task_title: string; requirement_brief?: string | null }) =>
    fetchApi<Task>(`/tasks/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),

  /** 获取任务详情 */
  get: (id: string) => fetchApi<Task>(`/tasks/${id}`),

  /** 读取 worktree 中的 PRD 文件内容 */
  getPrdFile: (id: string) =>
    fetchApi<{ content: string | null; path: string | null }>(`/tasks/${id}/prd-file`),

  /** 使用 trae-cn 打开 worktree 目录 */
  openInTrae: (id: string) =>
    fetchApi<{ opened: string }>(`/tasks/${id}/open-in-trae`, {
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
};

/** Project API */
export const projectApi = {
  /** 列出所有项目 */
  list: () => fetchApi<Project[]>("/projects"),

  /** 创建项目 */
  create: (data: {
    display_name: string;
    repo_path: string;
    description?: string | null;
  }) =>
    fetchApi<Project>("/projects", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  /** 获取项目详情 */
  get: (id: string) => fetchApi<Project>(`/projects/${id}`),

  /** 删除项目 */
  delete: (id: string) =>
    fetch(`${"/api"}/projects/${id}`, { method: "DELETE" }),

  /** 使用 trae-cn 打开项目根目录 */
  openInTrae: (id: string) =>
    fetchApi<{ opened: string }>(`/projects/${id}/open-in-trae`, {
      method: "POST",
    }),
};

/** DevLog API */
export const logApi = {
  /** 列出日志 */
  list: (taskId?: string, limit = 100) =>
    fetchApi<DevLog[]>(
      `/logs?${taskId ? `task_id=${taskId}&` : ""}limit=${limit}`
    ),

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
};
