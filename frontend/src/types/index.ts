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

/** 任务生命周期状态 */
export enum TaskLifecycleStatus {
  OPEN = "OPEN",
  CLOSED = "CLOSED",
  PENDING = "PENDING",
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

/** Task 类型 */
export interface Task {
  id: string;
  run_account_id: string;
  task_title: string;
  lifecycle_status: TaskLifecycleStatus;
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
