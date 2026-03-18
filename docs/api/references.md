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

::: dsl.api.tasks
    handler: python
    options:
      members:
        - list_tasks
        - create_task
        - update_task_status
        - update_task_stage
        - start_task
        - execute_task
        - get_task_prd_file
        - open_task_in_trae
        - open_task_terminal
        - update_task
        - get_task

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

::: dsl.models.enums
    handler: python
    options:
      members:
        - DevLogStateTag
        - TaskLifecycleStatus
        - WorkflowStage
        - AIProcessingStatus

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
