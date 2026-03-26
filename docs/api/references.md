# API 参考

本页通过 `mkdocstrings` 直接引用 Python 对象文档，避免手写重复说明。

## 应用入口

::: main.main
    handler: python

::: dsl.app.create_application
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

::: dsl.api.run_accounts
    handler: python
    options:
      members:
        - list_run_accounts
        - create_run_account
        - activate_run_account
        - get_current_run_account

::: dsl.api.projects
    handler: python
    options:
      members:
        - list_projects
        - create_project
        - get_project
        - open_project_in_trae
        - delete_project

::: dsl.api.email_settings
    handler: python
    options:
      members:
        - get_email_settings
        - upsert_email_settings
        - test_email_settings

::: dsl.api.tasks
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
        - resume_task
        - cancel_task
        - get_task_prd_file
        - open_task_in_trae
        - open_task_terminal
        - update_task
        - get_task

::: dsl.api.task_schedules
    handler: python
    options:
      members:
        - list_task_schedules
        - create_task_schedule
        - list_task_schedule_runs
        - run_task_schedule_now
        - update_task_schedule
        - delete_task_schedule

## 响应 Schema

::: dsl.schemas.task_schema.TaskCreateSchema
    handler: python

::: dsl.schemas.task_schema.TaskResponseSchema
    handler: python

::: dsl.schemas.task_schema.TaskCardMetadataSchema
    handler: python

::: dsl.schemas.task_schedule_schema.TaskScheduleResponseSchema
    handler: python

::: dsl.schemas.task_schedule_schema.TaskScheduleRunResponseSchema
    handler: python

::: dsl.api.logs
    handler: python
    options:
      members:
        - list_logs
        - create_log
        - parse_command
        - create_log_with_command
        - get_review_queue
        - update_ai_review

::: dsl.api.media
    handler: python
    options:
      members:
        - upload_image
        - upload_attachment
        - get_image

::: dsl.api.chronicle
    handler: python
    options:
      members:
        - get_timeline
        - get_task_chronicle
        - export_chronicle

## 数据模型

::: dsl.models.run_account.RunAccount
    handler: python

::: dsl.models.project.Project
    handler: python

::: dsl.models.task.Task
    handler: python

::: dsl.models.dev_log.DevLog
    handler: python

::: dsl.models.email_settings.EmailSettings
    handler: python

::: dsl.models.task_notification.TaskNotification
    handler: python

::: dsl.models.task_schedule.TaskSchedule
    handler: python

::: dsl.models.task_schedule_run.TaskScheduleRun
    handler: python

::: dsl.models.enums
    handler: python
    options:
      members:
        - DevLogStateTag
        - TaskLifecycleStatus
        - WorkflowStage
        - AIProcessingStatus
        - TaskNotificationEventType
        - TaskScheduleActionType
        - TaskScheduleTriggerType
        - TaskScheduleRunStatus

## 服务层

::: dsl.services.project_service.ProjectService
    handler: python
    options:
      members:
        - create_project
        - list_projects
        - get_project_by_id
        - delete_project

::: dsl.services.task_service.TaskService
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
        - update_task_title
        - get_active_task

::: dsl.services.task_notification_service.TaskNotificationService
    handler: python
    options:
      members:
        - send_prd_ready_notification
        - send_changes_requested_notification
        - send_manual_interruption_notification
        - send_stalled_task_notification
        - scan_and_send_stalled_task_notifications

::: dsl.services.task_schedule_service.TaskScheduleService
    handler: python
    options:
      members:
        - create_task_schedule
        - list_task_schedules
        - update_task_schedule
        - delete_task_schedule
        - list_task_schedule_runs

::: dsl.services.task_scheduler_dispatcher.TaskSchedulerDispatcher
    handler: python
    options:
      members:
        - dispatch_due_schedules
        - dispatch_schedule_run_now

::: dsl.services.log_service.LogService
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

::: dsl.services.media_service.MediaService
    handler: python
    options:
      members:
        - ensure_media_directories
        - save_image
        - save_attachment
        - get_image_path

::: dsl.services.chronicle_service.ChronicleService
    handler: python
    options:
      members:
        - get_timeline
        - get_task_chronicle
        - export_markdown

::: dsl.services.terminal_launcher
    handler: python
    options:
      members:
        - TerminalLaunchError
        - build_log_tail_terminal_command
        - open_log_tail_terminal

::: dsl.services.automation_runner
    handler: python
    options:
      members:
        - get_current_runner_kind
        - is_task_automation_running
        - run_task_prd
        - run_task_implementation
        - run_task_self_review_resume
        - run_task_post_review_lint_resume
        - run_task_completion

::: dsl.services.runners.registry
    handler: python
    options:
      members:
        - list_supported_runner_kind_list
        - get_runner_by_kind
        - resolve_runner_kind

::: dsl.services.codex_runner
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
