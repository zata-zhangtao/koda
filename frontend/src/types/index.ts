/** TypeScript 类型定义
 *
 * 定义 DSL 前端使用的所有数据类型
 */

/** 日志状态标记 */
export enum DevLogStateTag {
  NONE = "NONE",
  BUG = "BUG",
  OPTIMIZATION = "OPTIMIZATION",
  FIXED = "FIXED",
  TRANSFERRED = "TRANSFERRED",
}

/** 任务生命周期状态（向后兼容） */
export enum TaskLifecycleStatus {
  OPEN = "OPEN",
  CLOSED = "CLOSED",
  PENDING = "PENDING",
  DELETED = "DELETED",
}

/** 需求卡片工作流阶段（UI 阶段展示的唯一数据源） */
export enum WorkflowStage {
  BACKLOG = "backlog",
  PRD_GENERATING = "prd_generating",
  PRD_WAITING_CONFIRMATION = "prd_waiting_confirmation",
  IMPLEMENTATION_IN_PROGRESS = "implementation_in_progress",
  SELF_REVIEW_IN_PROGRESS = "self_review_in_progress",
  TEST_IN_PROGRESS = "test_in_progress",
  PR_PREPARING = "pr_preparing",
  ACCEPTANCE_IN_PROGRESS = "acceptance_in_progress",
  CHANGES_REQUESTED = "changes_requested",
  DONE = "done",
}

/** AI 处理状态 */
export enum AIProcessingStatus {
  PENDING = "PENDING",
  PROCESSING = "PROCESSING",
  WAITING_REVIEW = "WAITING_REVIEW",
  CONFIRMED = "CONFIRMED",
}

/** RunAccount 类型 */
export interface RunAccount {
  id: string;
  account_display_name: string;
  user_name: string;
  environment_os: string;
  git_branch_name: string | null;
  created_at: string;
  is_active: boolean;
}

/** Project 类型 */
export interface Project {
  id: string;
  display_name: string;
  repo_path: string;
  description: string | null;
  created_at: string;
}

/** Task 类型 */
export interface Task {
  id: string;
  run_account_id: string;
  project_id: string | null;
  task_title: string;
  lifecycle_status: TaskLifecycleStatus;
  workflow_stage: WorkflowStage;
  worktree_path: string | null;
  requirement_brief: string | null;
  created_at: string;
  closed_at: string | null;
  log_count: number;
}

/** DevLog 类型 */
export interface DevLog {
  id: string;
  task_id: string;
  run_account_id: string;
  created_at: string;
  text_content: string;
  state_tag: DevLogStateTag;
  media_original_image_path: string | null;
  media_thumbnail_path: string | null;
  task_title: string;
  // AI fields (Phase 2)
  ai_processing_status?: AIProcessingStatus | null;
  ai_generated_title?: string | null;
  ai_analysis_text?: string | null;
  ai_extracted_code?: string | null;
  ai_confidence_score?: number | null;
}

/** 命令解析结果 */
export interface CommandParseResult {
  is_command: boolean;
  command_type: string | null;
  state_tag: DevLogStateTag;
  content: string;
  task_title: string | null;
}

/** 时间线条目 */
export interface TimelineEntry extends DevLog {
  state_icon: string;
  has_media: boolean;
}

/** 邮件通知设置 */
export interface EmailSettings {
  id: number;
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password_masked: string;
  smtp_use_ssl: boolean;
  receiver_email: string;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

/** 邮件设置保存请求体 */
export interface EmailSettingsUpdate {
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password: string;
  smtp_use_ssl: boolean;
  receiver_email: string;
  is_enabled: boolean;
}

/** 任务编年史 */
export interface TaskChronicle {
  task: {
    id: string;
    title: string;
    status: string;
    created_at: string;
    closed_at: string | null;
  };
  logs: TimelineEntry[];
  stats: {
    total_logs: number;
    bug_count: number;
    fix_count: number;
  };
}
