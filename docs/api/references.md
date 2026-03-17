# API 参考

本页通过 `mkdocstrings` 直接引用 Python 对象文档，避免手写重复说明。

## 配置

::: utils.settings.Config
    handler: python

## 数据库

::: utils.database
    handler: python
    options:
      members:
        - create_database_engine
        - create_tables
        - get_db
        - init_database

## 任务服务

::: dsl.services.task_service.TaskService
    handler: python
    options:
      members:
        - create_task
        - get_tasks
        - get_task_by_id
        - update_task_status
        - update_task_title
        - get_active_task

## AI 模型加载

::: ai_agent.utils.model_loader
    handler: python
    options:
      members:
        - ModelConfigError
        - load_models_config
        - list_models
