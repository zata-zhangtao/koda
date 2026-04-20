# API 参考

本页通过 `mkdocstrings` 直接引用 Python 对象文档，避免手写重复说明。

## 应用入口

::: main.main
    handler: python

::: backend.dsl.app.create_application
    handler: python

## 配置与基础设施

::: utils.settings.Config
    handler: python

::: utils.database
    handler: python
    options:
      members:
        - create_database_engine
        - create_tables
        - get_db
        - init_database

::: utils.logger.Logger
    handler: python

## 路由层

::: backend.dsl.api.run_accounts
    handler: python
    options:
      members:
        - list_run_accounts
        - create_run_account
        - activate_run_account
        - get_current_run_account

::: backend.dsl.api.projects
    handler: python
    options:
      members:
        - list_projects
        - create_project
        - get_project
        - open_project_in_editor
        - open_project_in_trae
        - delete_project

::: backend.dsl.api.email_settings
    handler: python
    options:
      members:
        - get_email_settings
        - upsert_email_settings
        - test_email_settings

::: backend.dsl.api.tasks
    handler: python
    options:
      members:
        - list_tasks
        - list_task_card_metadata
        - create_task
        - update_task_status
        - update_task_stage
        - start_task
        - regenerate_task_prd
        - execute_task
        - review_task
        - resume_task
        - cancel_task
        - destroy_task
        - get_task_prd_file
        - open_task_in_editor
        - open_task_in_trae
        - open_task_terminal
        - update_task
        - create_task_reference
        - get_task

::: backend.dsl.api.task_schedules
    handler: python
    options:
      members:
        - list_task_schedules
        - create_task_schedule
        - list_task_schedule_runs
        - run_task_schedule_now
        - update_task_schedule
        - delete_task_schedule
::: backend.dsl.api.task_qa
    handler: python
    options:
      members:
        - list_task_qa_messages
        - create_task_qa_message
        - convert_task_qa_message_to_feedback_draft

::: backend.dsl.schemas.task_schema.TaskDestroySchema
    handler: python

::: backend.dsl.schemas.task_schema.TaskReferenceCreateSchema
    handler: python

::: backend.dsl.schemas.task_schema.TaskReferenceResponseSchema
    handler: python

::: backend.dsl.schemas.chronicle_schema.ProjectTimelineEntrySchema
    handler: python

::: backend.dsl.schemas.chronicle_schema.ProjectTimelineTaskDetailSchema
    handler: python

::: backend.dsl.schemas.chronicle_schema.ProjectTimelineSummaryRequestSchema
    handler: python

::: backend.dsl.schemas.chronicle_schema.ProjectTimelineSummaryResponseSchema
    handler: python

::: backend.dsl.api.logs
    handler: python
    options:
      members:
        - list_logs
        - create_log
        - parse_command
        - create_log_with_command
        - get_review_queue
        - update_ai_review

::: backend.dsl.api.media
    handler: python
    options:
      members:
        - upload_image
        - upload_attachment
        - get_image

::: backend.dsl.api.chronicle
    handler: python
    options:
      members:
        - get_timeline
        - get_task_chronicle
        - get_project_timeline
        - get_project_timeline_task_detail
        - summarize_project_timeline
        - export_chronicle

## 连续 Transcript 合同

- `/api/logs` 返回的 `DevLog` 现在会携带可选字段 `automation_session_id`、`automation_sequence_index`、`automation_phase_label`、`automation_runner_kind`；旧日志和人工日志这些字段保持 `null`
- `ChronicleService.get_task_chronicle(...)` 继续保留原始 `logs` 列表，同时额外提供按相邻同 session 聚合后的 `transcript_blocks`
- `ChronicleService.export_markdown(..., task_id=...)` 会消费这些 `transcript_blocks`，把连续自动化输出合并成单个 Markdown transcript block；全局 timeline 导出仍保持逐条日志

## 响应 Schema

::: backend.dsl.schemas.task_schema.TaskCreateSchema
    handler: python

::: backend.dsl.schemas.task_schema.TaskResponseSchema
    handler: python

::: backend.dsl.schemas.task_schema.TaskCardMetadataSchema
    handler: python

::: backend.dsl.schemas.task_schedule_schema.TaskScheduleResponseSchema
    handler: python

::: backend.dsl.schemas.task_schedule_schema.TaskScheduleRunResponseSchema
    handler: python

::: backend.dsl.schemas.task_qa_schema.TaskQaMessageResponseSchema
    handler: python

::: backend.dsl.schemas.task_qa_schema.TaskQaCreateResponseSchema
    handler: python

::: backend.dsl.schemas.task_qa_schema.TaskQaFeedbackDraftResponseSchema
    handler: python

## 数据模型

::: backend.dsl.models.run_account.RunAccount
    handler: python

::: backend.dsl.models.project.Project
    handler: python

::: backend.dsl.models.task.Task
    handler: python

::: backend.dsl.models.dev_log.DevLog
    handler: python

::: backend.dsl.models.task_qa_message.TaskQaMessage
    handler: python

::: backend.dsl.models.email_settings.EmailSettings
    handler: python

::: backend.dsl.models.task_notification.TaskNotification
    handler: python

::: backend.dsl.models.task_schedule.TaskSchedule
    handler: python

::: backend.dsl.models.task_schedule_run.TaskScheduleRun
::: backend.dsl.models.task_artifact.TaskArtifact
    handler: python

::: backend.dsl.models.task_reference_link.TaskReferenceLink
    handler: python

::: backend.dsl.models.enums
    handler: python
    options:
      members:
        - DevLogStateTag
        - TaskLifecycleStatus
        - TaskArtifactType
        - WorkflowStage
        - AIProcessingStatus
        - TaskQaMessageRole
        - TaskQaContextScope
        - TaskQaGenerationStatus
        - TaskNotificationEventType
        - TaskScheduleActionType
        - TaskScheduleTriggerType
        - TaskScheduleRunStatus

## 服务层

::: backend.dsl.services.project_service.ProjectService
    handler: python
    options:
      members:
        - create_project
        - list_projects
        - get_project_by_id
        - delete_project

::: backend.dsl.services.task_service.TaskService
    handler: python
    options:
      members:
        - create_task
        - get_tasks
        - get_task_by_id
        - update_task_status
        - update_workflow_stage
        - start_task
        - execute_task
        - update_task
        - destroy_task
        - get_active_task

::: backend.dsl.services.task_notification_service.TaskNotificationService
    handler: python
    options:
      members:
        - send_prd_ready_notification
        - send_changes_requested_notification
        - send_manual_interruption_notification
        - send_stalled_task_notification
        - scan_and_send_stalled_task_notifications

::: backend.dsl.services.task_schedule_service.TaskScheduleService
    handler: python
    options:
      members:
        - create_task_schedule
        - list_task_schedules
        - update_task_schedule
        - delete_task_schedule
        - list_task_schedule_runs

::: backend.dsl.services.task_scheduler_dispatcher.TaskSchedulerDispatcher
    handler: python
    options:
      members:
        - dispatch_due_schedules
        - dispatch_schedule_run_now

::: backend.dsl.services.log_service.LogService
    handler: python
    options:
      members:
        - parse_command
        - create_log
        - get_logs
        - get_log_by_id
        - get_review_queue
        - update_ai_review
        - count_logs_by_state

::: backend.dsl.services.task_qa_service.TaskQaService
    handler: python
    options:
      members:
        - list_messages
        - create_question
        - process_pending_reply
        - build_task_context_markdown
        - build_feedback_draft_from_message

::: backend.dsl.services.media_service.MediaService
    handler: python
    options:
      members:
        - ensure_media_directories
        - save_image
        - save_attachment
        - get_image_path

::: backend.dsl.services.chronicle_service.ChronicleService
    handler: python
    options:
      members:
        - get_timeline
        - get_task_chronicle
        - get_project_timeline
        - get_project_timeline_task_detail
        - summarize_project_timeline
        - export_markdown

::: backend.dsl.services.terminal_launcher
    handler: python
    options:
      members:
        - TerminalLaunchError
        - build_log_tail_terminal_command
        - open_log_tail_terminal

::: backend.dsl.services.automation_runner
    handler: python
    options:
      members:
        - get_current_runner_kind
        - is_task_automation_running
        - run_task_prd
        - run_task_implementation
        - run_task_review
        - run_task_self_review_resume
        - run_task_post_review_lint_resume
        - run_task_completion

::: backend.dsl.services.runners.registry
    handler: python
    options:
      members:
        - list_supported_runner_kind_list
        - get_runner_by_kind
        - resolve_runner_kind

::: backend.dsl.services.path_opener
    handler: python
    options:
      members:
        - PathOpenError
        - PathOpenTargetNotFoundError
        - PathOpenCommandError
        - build_path_open_command
        - open_path_in_editor

::: backend.dsl.services.codex_runner
    handler: python
    options:
      members:
        - get_task_log_path
        - build_codex_prompt
        - run_codex_prd
        - run_codex_task

## AI 工具层

::: ai_agent.utils.model_loader
    handler: python
    options:
      members:
        - ModelConfigError
        - load_models_config
        - list_models
        - resolve_model_credentials
        - create_chat_model
