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
  ABANDONED = "ABANDONED",
}

export const PROJECT_TIMELINE_DEFAULT_STATUS_FILTER_LIST: TaskLifecycleStatus[] = [
  TaskLifecycleStatus.OPEN,
  TaskLifecycleStatus.PENDING,
  TaskLifecycleStatus.CLOSED,
  TaskLifecycleStatus.DELETED,
  TaskLifecycleStatus.ABANDONED,
];

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

/** 任务调度动作类型 */
export enum TaskScheduleActionType {
  START_TASK = "start_task",
  RESUME_TASK = "resume_task",
  REVIEW_TASK = "review_task",
}

/** 任务调度触发类型 */
export enum TaskScheduleTriggerType {
  ONCE = "once",
  CRON = "cron",
}

/** 任务调度执行状态 */
export enum TaskScheduleRunStatus {
  SUCCEEDED = "succeeded",
  FAILED = "failed",
  SKIPPED = "skipped",
}

/** 任务卡片展示态 key */
export type TaskDisplayStageKey = WorkflowStage | "waiting_user" | "branch_missing";

/** AI 处理状态 */
export enum AIProcessingStatus {
  PENDING = "PENDING",
  PROCESSING = "PROCESSING",
  WAITING_REVIEW = "WAITING_REVIEW",
  CONFIRMED = "CONFIRMED",
}

/** 任务内独立问答消息角色 */
export enum TaskQaMessageRole {
  USER = "user",
  ASSISTANT = "assistant",
}

/** 任务内独立问答上下文作用域 */
export enum TaskQaContextScope {
  PRD_CONFIRMATION = "prd_confirmation",
  IMPLEMENTATION = "implementation",
}

/** 任务内独立问答生成状态 */
export enum TaskQaGenerationStatus {
  PENDING = "pending",
  COMPLETED = "completed",
  FAILED = "failed",
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

/** 前端运行时配置 */
export interface AppConfig {
  app_timezone: string;
  app_timezone_offset: string;
}

/** Project 类型 */
export interface Project {
  id: string;
  display_name: string;
  project_category: string | null;
  repo_path: string;
  repo_remote_url: string | null;
  repo_head_commit_hash: string | null;
  current_repo_remote_url: string | null;
  current_repo_head_commit_hash: string | null;
  description: string | null;
  is_repo_path_valid: boolean;
  is_repo_remote_consistent: boolean | null;
  is_repo_head_consistent: boolean | null;
  repo_consistency_note: string | null;
  created_at: string;
}

/** Task 类型 */
export interface TaskBranchHealth {
  expected_branch_name: string;
  branch_exists: boolean | null;
  worktree_exists: boolean;
  manual_completion_candidate: boolean;
  status_message: string | null;
}

/** Task 类型 */
export interface Task {
  id: string;
  run_account_id: string;
  project_id: string | null;
  task_title: string;
  lifecycle_status: TaskLifecycleStatus;
  workflow_stage: WorkflowStage;
  last_ai_activity_at: string | null;
  stage_updated_at: string;
  worktree_path: string | null;
  requirement_brief: string | null;
  auto_confirm_prd_and_execute: boolean;
  business_sync_original_workflow_stage: string | null;
  business_sync_original_lifecycle_status: string | null;
  business_sync_restored_at: string | null;
  business_sync_status_note: string | null;
  destroy_reason: string | null;
  destroyed_at: string | null;
  created_at: string;
  closed_at: string | null;
  log_count: number;
  is_codex_task_running: boolean;
  branch_health: TaskBranchHealth | null;
}

/** 可从 tasks/pending 中选择的 PRD 文件 */
export interface PendingPrdFile {
  file_name: string;
  relative_path: string;
  size_bytes: number;
  updated_at: string;
  title_preview?: string | null;
}

/** Pending PRD 文件列表响应 */
export interface PendingPrdFileList {
  files: PendingPrdFile[];
}

/** TaskSchedule 类型 */
export interface TaskSchedule {
  id: string;
  task_id: string;
  run_account_id: string;
  schedule_name: string;
  action_type: TaskScheduleActionType;
  trigger_type: TaskScheduleTriggerType;
  run_at: string | null;
  cron_expr: string | null;
  timezone_name: string;
  is_enabled: boolean;
  next_run_at: string | null;
  last_triggered_at: string | null;
  last_result_status: TaskScheduleRunStatus | null;
  created_at: string;
  updated_at: string;
}

/** 任务内独立问答消息 */
export interface TaskQaMessage {
  id: string;
  task_id: string;
  run_account_id: string;
  role: TaskQaMessageRole;
  context_scope: TaskQaContextScope;
  generation_status: TaskQaGenerationStatus;
  reply_to_message_id: string | null;
  model_name: string | null;
  content_markdown: string;
  error_text: string | null;
  created_at: string;
  updated_at: string;
}

/** TaskScheduleRun 类型 */
export interface TaskScheduleRun {
  id: string;
  schedule_id: string;
  task_id: string;
  planned_run_at: string;
  triggered_at: string;
  finished_at: string | null;
  run_status: TaskScheduleRunStatus;
  skip_reason: string | null;
  error_message: string | null;
  created_at: string;
}

/** 任务卡片与详情头部共用的展示元数据 */
export interface TaskCardMetadata {
  task_id: string;
  display_stage_key: TaskDisplayStageKey;
  display_stage_label: string;
  is_waiting_for_user: boolean;
  last_ai_activity_at: string | null;
  requirement_change_kind: "update" | "delete" | null;
  requirement_summary: string | null;
  business_sync_restored_at: string | null;
  business_sync_status_note: string | null;
  branch_health: TaskBranchHealth | null;
}

/** 提问接口返回值 */
export interface TaskQaCreateResponse {
  user_message: TaskQaMessage;
  assistant_message: TaskQaMessage;
}

/** 问答转反馈草稿返回值 */
export interface TaskQaFeedbackDraftResponse {
  source_message_id: string;
  draft_markdown: string;
}

/** PRD 待确认问题选项 */
export interface PrdPendingQuestionOption {
  key: string;
  label: string;
}

/** PRD 待确认问题 */
export interface PrdPendingQuestion {
  id: string;
  title: string;
  required: boolean;
  recommendedOptionKey: string;
  recommendationReason: string;
  options: PrdPendingQuestionOption[];
}

/** PRD 待确认问题答案映射 */
export type PrdPendingQuestionAnswerSelectionMap = Record<string, string>;

/** 按任务隔离的 PRD 待确认问题答案映射 */
export type PrdPendingQuestionAnswerSelectionMapByTaskId = Record<
  string,
  PrdPendingQuestionAnswerSelectionMap
>;

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
  automation_session_id?: string | null;
  automation_sequence_index?: number | null;
  automation_phase_label?: string | null;
  automation_runner_kind?: string | null;
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
  stalled_task_threshold_minutes: number;
  created_at: string;
  updated_at: string;
}

/** WebDAV 存储设置 */
export interface WebDAVSettings {
  id: number;
  server_url: string;
  username: string;
  password_masked: string;
  remote_path: string;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

/** WebDAV 存储设置保存请求体 */
export interface WebDAVSettingsUpdate {
  server_url: string;
  username: string;
  password: string;
  remote_path: string;
  is_enabled: boolean;
}

/** WebDAV 备份/同步操作结果 */
export interface WebDAVSyncResult {
  success: boolean;
  message: string;
  remote_url?: string | null;
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
  stalled_task_threshold_minutes: number;
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

/** 任务工件快照 */
export interface TaskArtifactSnapshot {
  artifact_type: "PRD" | "PLANNING_WITH_FILES";
  source_path: string | null;
  content_markdown: string;
  file_manifest: string[];
  captured_at: string;
}

/** 项目时间线条目 */
export interface ProjectTimelineEntry {
  task_id: string;
  project_id: string;
  project_display_name: string | null;
  project_category: string | null;
  task_title: string;
  lifecycle_status: TaskLifecycleStatus;
  workflow_stage: WorkflowStage;
  created_at: string;
  closed_at: string | null;
  last_activity_at: string;
  total_logs: number;
  bug_count: number;
  fix_count: number;
  has_prd_artifact: boolean;
  has_planning_artifact: boolean;
}

/** 项目时间线任务详情 */
export interface ProjectTimelineTaskDetail {
  task: {
    id: string;
    project_id: string | null;
    project_display_name: string | null;
    project_category: string | null;
    title: string;
    lifecycle_status: TaskLifecycleStatus;
    workflow_stage: WorkflowStage;
    created_at: string;
    closed_at: string | null;
  };
  requirement_snapshot: string | null;
  prd_snapshot: TaskArtifactSnapshot | null;
  planning_snapshot: TaskArtifactSnapshot | null;
  logs: TimelineEntry[];
  stats: {
    total_logs: number;
    bug_count: number;
    fix_count: number;
  };
}

/** 项目时间线总结 */
export interface ProjectTimelineSummary {
  summary_text: string;
  milestones: string[];
  risks: string[];
  next_actions: string[];
  source_task_ids: string[];
}

/** 历史需求引用请求体 */
export interface TaskReferenceCreateRequest {
  source_task_id: string;
  append_to_requirement_brief: boolean;
  reference_note?: string | null;
}

/** 历史需求引用结果 */
export interface TaskReferenceCreateResponse {
  target_task_id: string;
  source_task_id: string;
  reference_log_id: string;
  requirement_brief_appended: boolean;
}
