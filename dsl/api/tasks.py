"""Task API 路由.

提供任务的创建、查询、状态更新、工作流阶段管理和执行触发功能.
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from dsl.models.task import Task
from dsl.schemas.task_schema import (
    TaskCreateSchema,
    TaskResponseSchema,
    TaskStageUpdateSchema,
    TaskStatusUpdateSchema,
    TaskUpdateSchema,
)
from dsl.services.codex_runner import (
    cancel_codex_task,
    get_task_log_path,
    is_codex_task_running,
    run_codex_completion,
    run_codex_prd,
    run_codex_task,
)
from dsl.services.terminal_launcher import TerminalLaunchError, open_log_tail_terminal
from dsl.services.task_service import TaskService
from utils.database import get_db
from utils.settings import config

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _get_current_run_account_id(db_session: Session) -> str:
    """获取当前活跃账户 ID.

    Args:
        db_session: 数据库会话

    Returns:
        str: 当前活跃账户 ID

    Raises:
        HTTPException: 当没有活跃账户时返回 400
    """
    from dsl.models.run_account import RunAccount

    active_account = (
        db_session.query(RunAccount).filter(RunAccount.is_active == True).first()
    )
    if not active_account:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active run account. Please create a run account first.",
        )
    return active_account.id


@router.get("", response_model=list[TaskResponseSchema])
def list_tasks(
    db_session: Annotated[Session, Depends(get_db)],
) -> list[Task]:
    """列出当前账户的任务.

    Args:
        db_session: 数据库会话

    Returns:
        list[Task]: 任务列表，按创建时间倒序排列
    """
    run_account_id = _get_current_run_account_id(db_session)
    task_list = TaskService.get_tasks(db_session, run_account_id)

    for task_item in task_list:
        task_item.log_count = len(task_item.dev_logs)

    return task_list


@router.post("", response_model=TaskResponseSchema, status_code=status.HTTP_201_CREATED)
def create_task(
    task_create_schema: TaskCreateSchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """创建新任务.

    新任务默认 lifecycle_status=PENDING，workflow_stage=backlog.

    Args:
        task_create_schema: 任务创建数据
        db_session: 数据库会话

    Returns:
        Task: 新创建的任务

    Raises:
        HTTPException: 当关联的 Project 不存在时返回 422
    """
    run_account_id = _get_current_run_account_id(db_session)
    try:
        new_task = TaskService.create_task(db_session, task_create_schema, run_account_id)
    except ValueError as validation_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(validation_error),
        ) from validation_error
    new_task.log_count = 0
    return new_task


@router.put("/{task_id}/status", response_model=TaskResponseSchema)
def update_task_status(
    task_id: str,
    status_update: TaskStatusUpdateSchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """更新任务生命周期状态.

    Args:
        task_id: 任务 ID
        status_update: 状态更新数据
        db_session: 数据库会话

    Returns:
        Task: 更新后的任务

    Raises:
        HTTPException: 当任务不存在时返回 404
    """
    updated_task = TaskService.update_task_status(db_session, task_id, status_update)
    if not updated_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )
    updated_task.log_count = len(updated_task.dev_logs)
    return updated_task


@router.put("/{task_id}/stage", response_model=TaskResponseSchema)
def update_task_stage(
    task_id: str,
    stage_update: TaskStageUpdateSchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """更新任务工作流阶段.

    通用阶段更新接口，供各阶段按钮（如「确认 PRD」、「验收通过」等）使用.
    当阶段更新为 done 时，自动将 lifecycle_status 设为 CLOSED.

    Args:
        task_id: 任务 ID
        stage_update: 阶段更新数据
        db_session: 数据库会话

    Returns:
        Task: 更新后的任务

    Raises:
        HTTPException: 当任务不存在时返回 404
    """
    updated_task = TaskService.update_workflow_stage(db_session, task_id, stage_update)
    if not updated_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )
    updated_task.log_count = len(updated_task.dev_logs)
    return updated_task


@router.post("/{task_id}/start", response_model=TaskResponseSchema)
def start_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """启动任务：创建 git worktree 并进入 PRD_GENERATING 阶段.

    仅允许从 backlog 阶段触发。若任务关联了 Project，将立即在项目仓库中创建
    git worktree（分支名：task/<task_id[:8]>）。

    Args:
        task_id: 任务 ID
        db_session: 数据库会话

    Returns:
        Task: 已更新为 prd_generating 的任务对象

    Raises:
        HTTPException: 任务不存在（404）、阶段不合法（422）或 worktree 创建失败（422）
    """
    try:
        started_task = TaskService.start_task(db_session, task_id)
    except ValueError as start_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(start_error),
        ) from start_error

    if not started_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    # 收集快照（session 关闭前读取）
    dev_log_text_snapshot_list: list[str] = [
        dev_log_item.text_content for dev_log_item in started_task.dev_logs
    ]
    task_title_snapshot_str: str = started_task.task_title
    run_account_id_snapshot_str: str = started_task.run_account_id
    worktree_path_snapshot_str: str | None = started_task.worktree_path

    # 确定 codex 工作目录（worktree > project repo > koda 自身）
    from pathlib import Path as _Path

    effective_work_dir_path = config.BASE_DIR
    if worktree_path_snapshot_str:
        wt_dir = _Path(worktree_path_snapshot_str)
        if wt_dir.exists():
            effective_work_dir_path = wt_dir
    elif started_task.project_id:
        from dsl.models.project import Project

        project_obj = db_session.query(Project).filter(
            Project.id == started_task.project_id
        ).first()
        if project_obj:
            effective_work_dir_path = _Path(project_obj.repo_path)

    # 在后台让 codex 生成 PRD，完成后自动推进至 prd_waiting_confirmation
    background_tasks.add_task(
        run_codex_prd,
        task_id_str=task_id,
        run_account_id_str=run_account_id_snapshot_str,
        task_title_str=task_title_snapshot_str,
        dev_log_text_list=dev_log_text_snapshot_list,
        work_dir_path=effective_work_dir_path,
        worktree_path_str=worktree_path_snapshot_str,
    )

    started_task.log_count = len(started_task.dev_logs)
    return started_task


@router.post("/{task_id}/execute", response_model=TaskResponseSchema)
def execute_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """触发任务进入执行阶段并启动 codex exec 后台任务.

    原子操作：
    1. 将 workflow_stage 更新为 implementation_in_progress
    2. 在后台异步启动 codex exec，输出实时写入 DevLog 时间线
    3. 实现完成后自动推进至 self_review_in_progress，并立即执行 AI 自检 / 代码评审
    4. 若自检发现阻塞问题或执行失败，则回退至 changes_requested

    仅允许从 prd_waiting_confirmation 或 changes_requested 阶段触发.

    Args:
        task_id: 任务 ID
        background_tasks: FastAPI 后台任务注入
        db_session: 数据库会话

    Returns:
        Task: 已更新为 implementation_in_progress 的任务对象

    Raises:
        HTTPException: 当任务不存在时返回 404；阶段不合法时返回 422
    """
    try:
        executed_task = TaskService.execute_task(db_session, task_id)
    except ValueError as stage_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(stage_error),
        ) from stage_error

    if not executed_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    # 收集日志文本供 Prompt 构建（在 session 关闭前读取）
    dev_log_text_snapshot_list: list[str] = [
        dev_log_item.text_content
        for dev_log_item in executed_task.dev_logs
    ]
    task_title_snapshot_str: str = executed_task.task_title
    run_account_id_snapshot_str: str = executed_task.run_account_id
    worktree_path_snapshot_str: str | None = executed_task.worktree_path

    # 决定 codex 工作目录：优先使用已创建的 worktree，其次项目根，最后 Koda 自身目录
    from pathlib import Path as _Path

    effective_work_dir_path = config.BASE_DIR
    if executed_task.worktree_path:
        worktree_dir = _Path(executed_task.worktree_path)
        if worktree_dir.exists():
            effective_work_dir_path = worktree_dir
    elif executed_task.project_id:
        from dsl.models.project import Project

        project_obj = db_session.query(Project).filter(
            Project.id == executed_task.project_id
        ).first()
        if project_obj:
            effective_work_dir_path = _Path(project_obj.repo_path)

    # 在后台异步运行实现阶段；成功后会继续进入真实的 self-review 阶段
    background_tasks.add_task(
        run_codex_task,
        task_id_str=task_id,
        run_account_id_str=run_account_id_snapshot_str,
        task_title_str=task_title_snapshot_str,
        dev_log_text_list=dev_log_text_snapshot_list,
        work_dir_path=effective_work_dir_path,
        worktree_path_str=worktree_path_snapshot_str,
    )

    executed_task.log_count = len(executed_task.dev_logs)
    return executed_task


@router.post("/{task_id}/complete", response_model=TaskResponseSchema)
def complete_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """触发任务进入完成收尾阶段，并在 worktree 中执行 Git 收尾动作.

    收尾动作由 Codex 在任务 worktree 中执行，顺序固定为：
    1. 先提交当前改动
    2. 再执行 `git rebase main`

    若收尾成功，任务自动推进到 `done`；若失败，则回退到 `changes_requested`。

    Args:
        task_id: 任务 ID
        background_tasks: FastAPI 后台任务注入
        db_session: 数据库会话

    Returns:
        Task: 已更新为 `pr_preparing` 的任务对象

    Raises:
        HTTPException: 当任务不存在时返回 404；阶段不合法、worktree 缺失或目录不存在时返回 422；
            若当前任务已存在运行中的 Codex 进程则返回 409
    """
    if is_codex_task_running(task_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Codex is already running for this task.",
        )

    try:
        completion_task = TaskService.prepare_task_completion(db_session, task_id)
    except ValueError as completion_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(completion_error),
        ) from completion_error

    if not completion_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    if not completion_task.worktree_path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Task has no worktree_path. Complete is only available for worktree-backed tasks.",
        )

    from pathlib import Path as _Path

    worktree_dir_path = _Path(completion_task.worktree_path)
    if not worktree_dir_path.exists():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Worktree directory does not exist yet: {worktree_dir_path}",
        )

    dev_log_text_snapshot_list: list[str] = [
        dev_log_item.text_content for dev_log_item in completion_task.dev_logs
    ]
    task_title_snapshot_str: str = completion_task.task_title
    run_account_id_snapshot_str: str = completion_task.run_account_id
    worktree_path_snapshot_str: str = completion_task.worktree_path

    background_tasks.add_task(
        run_codex_completion,
        task_id_str=task_id,
        run_account_id_str=run_account_id_snapshot_str,
        task_title_str=task_title_snapshot_str,
        dev_log_text_list=dev_log_text_snapshot_list,
        work_dir_path=worktree_dir_path,
        worktree_path_str=worktree_path_snapshot_str,
    )

    completion_task.log_count = len(completion_task.dev_logs)
    return completion_task


@router.post("/{task_id}/cancel", response_model=TaskResponseSchema)
def cancel_task(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """中断正在运行的 codex 进程并将任务回退至 changes_requested 阶段.

    若该任务没有正在运行的 codex 进程，仍会将 workflow_stage 强制回退至
    changes_requested，确保 UI 可以解除阻塞。

    Args:
        task_id: 任务 ID
        db_session: 数据库会话

    Returns:
        Task: 已回退为 changes_requested 的任务对象

    Raises:
        HTTPException: 当任务不存在时返回 404
    """
    from dsl.schemas.task_schema import TaskStageUpdateSchema
    from dsl.models.enums import WorkflowStage

    task_obj = TaskService.get_task_by_id(db_session, task_id)
    if not task_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    # 尝试终止正在运行的 codex 进程
    cancel_codex_task(task_id)

    # 强制将阶段回退至 changes_requested，解除 UI 阻塞
    stage_update_schema = TaskStageUpdateSchema(workflow_stage=WorkflowStage.CHANGES_REQUESTED)
    updated_task = TaskService.update_workflow_stage(db_session, task_id, stage_update_schema)
    if not updated_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )
    updated_task.log_count = len(updated_task.dev_logs)
    return updated_task


@router.get("/{task_id}/prd-file")
def get_task_prd_file(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> dict:
    """读取任务 worktree 中该任务专属的 PRD 文件内容.

    固定文件名为 tasks/prd-{task_id[:8]}.md，避免读到其他任务遗留的 PRD 文件。

    Args:
        task_id: 任务 ID
        db_session: 数据库会话

    Returns:
        dict: {"content": str, "path": str} 或 {"content": null, "path": null}
    """
    from pathlib import Path as _Path

    task_obj = TaskService.get_task_by_id(db_session, task_id)
    if not task_obj or not task_obj.worktree_path:
        return {"content": None, "path": None}

    worktree_dir = _Path(task_obj.worktree_path)
    if not worktree_dir.exists():
        return {"content": None, "path": None}

    prd_file_path = worktree_dir / "tasks" / f"prd-{task_id[:8]}.md"
    if not prd_file_path.exists():
        return {"content": None, "path": None}

    try:
        prd_content = prd_file_path.read_text(encoding="utf-8")
        return {"content": prd_content, "path": str(prd_file_path)}
    except OSError:
        return {"content": None, "path": None}


@router.post("/{task_id}/open-in-trae", status_code=status.HTTP_200_OK)
def open_task_in_trae(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> dict:
    """使用 trae-cn 打开任务对应的 git worktree 目录.

    需要任务已有 worktree_path（即已触发过执行），且该路径在文件系统中存在。

    Args:
        task_id: 任务 ID
        db_session: 数据库会话

    Returns:
        dict: 包含打开路径的确认信息

    Raises:
        HTTPException: 任务不存在（404）、worktree 未设置（422）或路径不存在（422）
    """
    import subprocess
    from pathlib import Path as _Path

    task_obj = TaskService.get_task_by_id(db_session, task_id)
    if not task_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )

    if not task_obj.worktree_path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Task has no worktree_path. Execute the task first.",
        )

    worktree_dir_path = _Path(task_obj.worktree_path)
    if not worktree_dir_path.exists():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Worktree directory does not exist yet: {worktree_dir_path}",
        )

    try:
        subprocess.Popen(
            ["trae-cn", str(worktree_dir_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="trae-cn executable not found in PATH.",
        )

    return {"opened": str(worktree_dir_path)}


@router.post("/{task_id}/open-terminal", status_code=status.HTTP_200_OK)
def open_task_terminal(
    task_id: str,
) -> dict:
    """打开一个新的终端窗口，实时查看该任务的 codex 输出日志.

    默认支持 macOS、WSL 与常见 Linux 桌面终端；也可通过
    `KODA_OPEN_TERMINAL_COMMAND` 自定义启动命令。日志文件由
    codex_runner 在任务执行时自动写入 `/tmp/koda-{task_id[:8]}.log`。

    Args:
        task_id: 任务 ID

    Returns:
        dict: 包含日志文件路径的确认信息

    Raises:
        HTTPException: 日志文件不存在（404）或终端无法打开（500）
    """
    log_file_path = get_task_log_path(task_id)

    if not log_file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"尚无日志文件（{log_file_path}）。请先启动任务。",
        )

    try:
        open_log_tail_terminal(log_file_path)
    except TerminalLaunchError as launch_error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(launch_error),
        ) from launch_error

    return {"log_file": str(log_file_path)}


@router.patch("/{task_id}", response_model=TaskResponseSchema)
def update_task(
    task_id: str,
    task_update_schema: TaskUpdateSchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """更新任务内容.

    Args:
        task_id: 任务 ID
        task_update_schema: 任务更新数据
        db_session: 数据库会话

    Returns:
        Task: 更新后的任务

    Raises:
        HTTPException: 当任务不存在时返回 404
    """
    updated_task = TaskService.update_task_title(db_session, task_id, task_update_schema)
    if not updated_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )
    updated_task.log_count = len(updated_task.dev_logs)
    return updated_task


@router.get("/{task_id}", response_model=TaskResponseSchema)
def get_task(
    task_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> Task:
    """获取单个任务详情.

    Args:
        task_id: 任务 ID
        db_session: 数据库会话

    Returns:
        Task: 任务详情

    Raises:
        HTTPException: 当任务不存在时返回 404
    """
    task_obj = TaskService.get_task_by_id(db_session, task_id)
    if not task_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found",
        )
    task_obj.log_count = len(task_obj.dev_logs)
    return task_obj
