/** API 客户端
 *
 * 封装与后端 API 的所有交互
 */

import type {
  CommandParseResult,
  DevLog,
  RunAccount,
  Task,
  TaskChronicle,
  TimelineEntry,
} from "../types";

const API_BASE = "/api";

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
    const error = await response.text();
    throw new Error(error || `HTTP ${response.status}`);
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
  create: (data: { task_title: string }) =>
    fetchApi<Task>("/tasks", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  /** 更新任务状态 */
  updateStatus: (id: string, status: string) =>
    fetchApi<Task>(`/tasks/${id}/status`, {
      method: "PUT",
      body: JSON.stringify({ lifecycle_status: status }),
    }),

  /** 获取任务详情 */
  get: (id: string) => fetchApi<Task>(`/tasks/${id}`),
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
  uploadImage: async (file: File, textContent = ""): Promise<DevLog> => {
    const formData = new FormData();
    formData.append("uploaded_image_file", file);
    formData.append("text_content", textContent);

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
