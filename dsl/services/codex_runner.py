"""Codex 执行器服务模块.

负责构建任务 Prompt、以非交互方式调用 codex exec CLI，
并将执行过程的 stdout/stderr 实时写入 DevLog 时间线.
"""

import asyncio
import os
import shutil
import signal
import uuid
from datetime import datetime
from pathlib import Path

from utils.database import SessionLocal
from utils.logger import logger
from utils.settings import config


# codex exec 每次最多批量写入的行数
_LOG_BATCH_SIZE = 5

# 两次批量写入之间等待的最长秒数（缩短以实时展示）
_LOG_FLUSH_INTERVAL_SECONDS = 1.5

# 日志文件存放目录
_CODEX_LOG_DIR = Path("/tmp")

# 正在运行的 codex 进程注册表：task_id -> asyncio.subprocess.Process
_running_codex_processes: dict[str, "asyncio.subprocess.Process"] = {}

# 用户主动取消的任务集合（用于区分「用户中断」与「意外中断」）
_user_cancelled_tasks: set[str] = set()

# 意外中断时的最大自动重试次数
_MAX_AUTO_RETRY = 2

# codex 意外中断时在输出中出现的标志性字符串
_CODEX_INTERRUPTED_MARKERS = ("task interrupted",)


def _output_contains_interruption(output_lines: list[str]) -> bool:
    """检查 codex 输出的末尾若干行是否包含中断标志.

    Args:
        output_lines: codex 输出行列表

    Returns:
        bool: 若最后 10 行中出现中断标志则返回 True
    """
    recent_lines_str = "\n".join(output_lines[-10:]).lower()
    return any(marker in recent_lines_str for marker in _CODEX_INTERRUPTED_MARKERS)


def cancel_codex_task(task_id_str: str) -> bool:
    """中断指定任务正在运行的 codex 进程（用户主动触发）.

    标记为用户取消后再发送 SIGKILL，使 run_codex_task/run_codex_prd
    的重试逻辑知道这是用户行为，不应自动重试。

    Args:
        task_id_str: 任务 UUID 字符串

    Returns:
        bool: 若找到并成功发送终止信号则返回 True，否则返回 False
    """
    # 先标记为用户主动取消，再 kill，防止竞态
    _user_cancelled_tasks.add(task_id_str)

    codex_proc = _running_codex_processes.get(task_id_str)
    if codex_proc is None:
        return False
    if codex_proc.returncode is not None:
        _running_codex_processes.pop(task_id_str, None)
        return False
    try:
        # 使用 killpg 杀死整个进程组（包含 codex 派生的所有子进程）
        os.killpg(os.getpgid(codex_proc.pid), signal.SIGKILL)
        logger.info(f"Sent SIGKILL to process group for task {task_id_str[:8]}... (user cancel)")
        return True
    except (ProcessLookupError, PermissionError, OSError):
        # 进程组不存在或无权限时，回退到直接 kill 进程本身
        try:
            codex_proc.kill()
        except ProcessLookupError:
            pass
        _running_codex_processes.pop(task_id_str, None)
        return False


def get_task_log_path(task_id_str: str) -> Path:
    """返回该任务的 codex 实时日志文件路径.

    Args:
        task_id_str: 任务 UUID 字符串

    Returns:
        Path: 日志文件绝对路径，如 /tmp/koda-{task_short}.log
    """
    return _CODEX_LOG_DIR / f"koda-{task_id_str[:8]}.log"


def build_codex_prompt(
    task_title: str,
    dev_log_text_list: list[str],
    worktree_path_str: str | None = None,
) -> str:
    """根据任务标题和历史日志构建发给 codex 的 Prompt.

    若提供了 worktree_path_str，提示中会要求 codex 创建 git worktree 并在其中实现需求。

    Args:
        task_title: 需求卡片标题
        dev_log_text_list: 该任务下已有日志的 text_content 列表（时间正序）
        worktree_path_str: 预期的 git worktree 绝对路径（可选）

    Returns:
        str: 完整的 codex Prompt 文本
    """
    prd_section_lines: list[str] = []
    for raw_log_text in dev_log_text_list[-10:]:
        stripped_text = raw_log_text.strip()
        if stripped_text:
            prd_section_lines.append(stripped_text)

    prd_context_block = (
        "\n\n---\n".join(prd_section_lines)
        if prd_section_lines
        else "（暂无额外上下文，请根据需求标题自行判断实现范围）"
    )

    if worktree_path_str:
        worktree_instruction_block = f"""
## Git Worktree 说明
当前已在 git worktree 目录中工作：`{worktree_path_str}`
- 直接在此目录中完成所有代码修改，无需再创建 worktree
- 实现完成后提交代码：`git add -A && git commit -m "feat: <简短描述>"`
"""
    else:
        worktree_instruction_block = ""

    constructed_prompt_text = f"""你是一个高效的 AI 编码助手，正在处理如下需求卡片。

## 需求标题
{task_title}

## 需求上下文（来自历史日志）
{prd_context_block}
{worktree_instruction_block}
## 执行要求
1. 请仔细阅读需求上下文，理解需要实现的功能范围。
2. 在当前代码仓库中定位相关文件，根据项目现有代码风格完成实现。
3. 遵循项目规范：Python 使用 Google Style Docstring，前端使用 TypeScript + React，所有文件读写显式指定 encoding='utf-8'。
4. 完成后简要输出：修改了哪些文件、实现了什么逻辑、需要注意什么。
5. 如果需求描述不够清晰，请做出合理假设并在输出中说明。

请开始执行。"""

    return constructed_prompt_text


def _write_log_to_db(
    task_id_str: str,
    run_account_id_str: str,
    text_content_str: str,
    state_tag_value: str = "OPTIMIZATION",
) -> None:
    """向数据库写入一条 DevLog（同步，供 asyncio.to_thread 使用）.

    Args:
        task_id_str: 关联任务 ID
        run_account_id_str: 运行账户 ID
        text_content_str: 日志文本内容
        state_tag_value: DevLogStateTag 枚举值字符串
    """
    from dsl.models.dev_log import DevLog
    from dsl.models.enums import DevLogStateTag

    db_session = SessionLocal()
    try:
        new_dev_log = DevLog(
            id=str(uuid.uuid4()),
            task_id=task_id_str,
            run_account_id=run_account_id_str,
            text_content=text_content_str,
            state_tag=DevLogStateTag(state_tag_value),
            created_at=datetime.utcnow(),
        )
        db_session.add(new_dev_log)
        db_session.commit()
    except Exception as db_write_error:
        logger.error(f"Failed to write DevLog for task {task_id_str[:8]}...: {db_write_error}")
        db_session.rollback()
    finally:
        db_session.close()


def _advance_stage_in_db(task_id_str: str, next_stage_value: str) -> None:
    """更新任务 workflow_stage（同步，供 asyncio.to_thread 使用）.

    Args:
        task_id_str: 任务 ID
        next_stage_value: WorkflowStage 枚举值字符串
    """
    from dsl.models.enums import WorkflowStage
    from dsl.models.task import Task

    db_session = SessionLocal()
    try:
        task_obj = db_session.query(Task).filter(Task.id == task_id_str).first()
        if task_obj:
            task_obj.workflow_stage = WorkflowStage(next_stage_value)
            db_session.commit()
            logger.info(f"Task {task_id_str[:8]}... stage advanced to {next_stage_value}")
    except Exception as stage_update_error:
        logger.error(
            f"Failed to advance stage for task {task_id_str[:8]}...: {stage_update_error}"
        )
        db_session.rollback()
    finally:
        db_session.close()


async def run_codex_prd(
    task_id_str: str,
    run_account_id_str: str,
    task_title_str: str,
    dev_log_text_list: list[str],
    work_dir_path: Path,
    worktree_path_str: str | None = None,
) -> None:
    """调用 codex 生成 PRD，完成后自动推进至 prd_waiting_confirmation.

    fire-and-forget，不向调用方抛出异常。

    Args:
        task_id_str: 任务 UUID 字符串
        run_account_id_str: 运行账户 UUID 字符串
        task_title_str: 任务标题
        dev_log_text_list: 历史日志文本列表
        work_dir_path: codex 工作目录
        worktree_path_str: git worktree 路径（可选）
    """
    codex_executable_path = shutil.which("codex")
    if not codex_executable_path:
        error_msg = "❌ 未找到 codex 可执行文件，请确认 codex CLI 已安装并在 PATH 中。"
        await asyncio.to_thread(
            _write_log_to_db, task_id_str, run_account_id_str, error_msg, "BUG"
        )
        await asyncio.to_thread(_advance_stage_in_db, task_id_str, "changes_requested")
        return

    prd_context_lines: list[str] = []
    for raw_log_text in dev_log_text_list[-5:]:
        stripped = raw_log_text.strip()
        if stripped:
            prd_context_lines.append(stripped)
    prd_context_block = (
        "\n---\n".join(prd_context_lines)
        if prd_context_lines
        else "（无额外上下文，请根据需求标题判断范围）"
    )

    worktree_note = (
        f"\n当前工作目录是 git worktree：`{worktree_path_str}`"
        if worktree_path_str
        else ""
    )

    prd_prompt = f"""请为以下需求生成 PRD 文档。{worktree_note}

## 需求标题
{task_title_str}

## 需求背景/上下文
{prd_context_block}

## 执行步骤

使用 `/prd` skill 生成 PRD，将需求标题和上下文作为输入。

生成完成后，将 PRD 内容保存到文件：
`tasks/prd-{task_id_str[:8]}.md`

**重要**：必须真正写入文件，不只是输出到终端。写完后输出文件路径。"""

    task_log_path = get_task_log_path(task_id_str)

    # 清除可能残留的取消标记，避免上次取消影响本次运行
    _user_cancelled_tasks.discard(task_id_str)

    # 清空/创建日志文件，写入标题行
    task_log_path.write_text(
        f"=== Koda codex-prd | task {task_id_str[:8]} | {datetime.utcnow().isoformat()} ===\n",
        encoding="utf-8",
    )

    # 清理该任务的旧 PRD 文件，确保显示的是本次生成的最新内容
    task_prd_file_path = work_dir_path / "tasks" / f"prd-{task_id_str[:8]}.md"
    if task_prd_file_path.exists():
        try:
            task_prd_file_path.unlink()
            logger.info(f"Removed old PRD file: {task_prd_file_path}")
        except OSError as cleanup_err:
            logger.warning(f"Could not remove old PRD file {task_prd_file_path}: {cleanup_err}")

    for attempt_index in range(_MAX_AUTO_RETRY + 1):
        codex_process: asyncio.subprocess.Process | None = None
        try:
            codex_process = await asyncio.create_subprocess_exec(
                codex_executable_path,
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                prd_prompt,
                cwd=str(work_dir_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,  # 独立进程组，确保 killpg 能杀死所有子进程
            )
            _running_codex_processes[task_id_str] = codex_process

            pending_lines: list[str] = []
            last_flush_time = asyncio.get_event_loop().time()

            async def flush_prd(force: bool = False) -> None:
                nonlocal last_flush_time
                if not pending_lines:
                    return
                elapsed = asyncio.get_event_loop().time() - last_flush_time
                if force or len(pending_lines) >= _LOG_BATCH_SIZE or elapsed >= _LOG_FLUSH_INTERVAL_SECONDS:
                    await asyncio.to_thread(
                        _write_log_to_db,
                        task_id_str,
                        run_account_id_str,
                        "\n".join(pending_lines),
                        "OPTIMIZATION",
                    )
                    pending_lines.clear()
                    last_flush_time = asyncio.get_event_loop().time()

            all_output_lines: list[str] = []
            assert codex_process.stdout is not None
            async for raw_line in codex_process.stdout:
                decoded = raw_line.decode("utf-8", errors="replace").rstrip()
                if decoded:
                    pending_lines.append(decoded)
                    all_output_lines.append(decoded)
                    logger.debug(f"[codex-prd:{task_id_str[:8]}] {decoded}")
                    with task_log_path.open("a", encoding="utf-8") as log_file_handle:
                        log_file_handle.write(decoded + "\n")
                await flush_prd()

            return_code_int = await codex_process.wait()
            await flush_prd(force=True)
            with task_log_path.open("a", encoding="utf-8") as log_file_handle:
                log_file_handle.write(f"\n=== exit code: {return_code_int} ===\n")

            if return_code_int == 0 and not _output_contains_interruption(all_output_lines):
                await asyncio.to_thread(
                    _write_log_to_db,
                    task_id_str,
                    run_account_id_str,
                    "✅ PRD 已生成，请确认后点击「开始执行」触发 AI 编码。",
                    "FIXED",
                )
                await asyncio.to_thread(_advance_stage_in_db, task_id_str, "prd_waiting_confirmation")
                logger.info(f"Task {task_id_str[:8]}... PRD generated → prd_waiting_confirmation")
                return

            if return_code_int == 0:
                return_code_int = -1  # 标准化为失败码，触发后续重试逻辑

            # 非零退出：判断是否为用户取消
            if task_id_str in _user_cancelled_tasks:
                _user_cancelled_tasks.discard(task_id_str)
                await asyncio.to_thread(
                    _write_log_to_db, task_id_str, run_account_id_str,
                    "🛑 用户手动中断了 PRD 生成。", "BUG"
                )
                await asyncio.to_thread(_advance_stage_in_db, task_id_str, "changes_requested")
                return

            # 意外中断，判断是否还有重试次数
            if attempt_index < _MAX_AUTO_RETRY:
                retry_msg = (
                    f"⚠️ PRD 生成意外中断（exit {return_code_int}），"
                    f"自动重试（{attempt_index + 1}/{_MAX_AUTO_RETRY}）..."
                )
                await asyncio.to_thread(
                    _write_log_to_db, task_id_str, run_account_id_str, retry_msg, "BUG"
                )
                with task_log_path.open("a", encoding="utf-8") as log_file_handle:
                    log_file_handle.write(retry_msg + "\n")
                logger.warning(f"Task {task_id_str[:8]}... PRD interrupted, retrying ({attempt_index + 1}/{_MAX_AUTO_RETRY})")
                continue

            # 重试耗尽
            await asyncio.to_thread(
                _write_log_to_db, task_id_str, run_account_id_str,
                f"❌ PRD 生成失败（exit {return_code_int}），已重试 {_MAX_AUTO_RETRY} 次。", "BUG"
            )
            await asyncio.to_thread(_advance_stage_in_db, task_id_str, "changes_requested")

        except Exception as err:
            logger.exception(f"run_codex_prd unexpected error for {task_id_str[:8]}... (attempt {attempt_index + 1})")

            if task_id_str in _user_cancelled_tasks:
                _user_cancelled_tasks.discard(task_id_str)
                await asyncio.to_thread(
                    _write_log_to_db, task_id_str, run_account_id_str,
                    "🛑 用户手动中断了 PRD 生成。", "BUG"
                )
                await asyncio.to_thread(_advance_stage_in_db, task_id_str, "changes_requested")
                return

            if attempt_index < _MAX_AUTO_RETRY:
                retry_msg = (
                    f"⚠️ PRD 生成意外异常（{err}），"
                    f"自动重试（{attempt_index + 1}/{_MAX_AUTO_RETRY}）..."
                )
                await asyncio.to_thread(
                    _write_log_to_db, task_id_str, run_account_id_str, retry_msg, "BUG"
                )
                continue

            await asyncio.to_thread(
                _write_log_to_db, task_id_str, run_account_id_str,
                f"❌ PRD 生成过程中发生错误：{err}", "BUG"
            )
            await asyncio.to_thread(_advance_stage_in_db, task_id_str, "changes_requested")

        finally:
            _running_codex_processes.pop(task_id_str, None)
            if codex_process and codex_process.returncode is None:
                try:
                    codex_process.kill()
                except ProcessLookupError:
                    pass


async def run_codex_task(
    task_id_str: str,
    run_account_id_str: str,
    task_title_str: str,
    dev_log_text_list: list[str],
    work_dir_path: Path,
    worktree_path_str: str | None = None,
) -> None:
    """非交互方式运行 codex exec，并将输出实时写入 DevLog 时间线.

    整个函数设计为 fire-and-forget（后台任务），不向调用方抛出异常。
    执行完成后自动将 workflow_stage 推进至 self_review_in_progress。
    执行失败时将 workflow_stage 回退至 changes_requested。

    Args:
        task_id_str: 任务 UUID 字符串
        run_account_id_str: 运行账户 UUID 字符串
        task_title_str: 任务标题，用于构建 Prompt
        dev_log_text_list: 历史日志文本列表，用于构建上下文
        work_dir_path: codex 的工作目录（代码仓库根路径）
        worktree_path_str: 预期的 git worktree 路径（可选，供 codex 创建）
    """
    codex_executable_path = shutil.which("codex")
    if not codex_executable_path:
        error_msg = "❌ 未找到 codex 可执行文件，请确认 codex CLI 已安装并在 PATH 中。"
        await asyncio.to_thread(
            _write_log_to_db, task_id_str, run_account_id_str, error_msg, "BUG"
        )
        await asyncio.to_thread(
            _advance_stage_in_db, task_id_str, "changes_requested"
        )
        return

    constructed_codex_prompt = build_codex_prompt(
        task_title_str, dev_log_text_list, worktree_path_str
    )

    logger.info(
        f"Starting codex exec for task {task_id_str[:8]}... "
        f"in work_dir={work_dir_path}"
    )

    task_log_path = get_task_log_path(task_id_str)

    # 清除可能残留的取消标记，避免上次取消影响本次运行
    _user_cancelled_tasks.discard(task_id_str)

    # 清空/创建日志文件，写入标题行
    task_log_path.write_text(
        f"=== Koda codex-exec | task {task_id_str[:8]} | {datetime.utcnow().isoformat()} ===\n",
        encoding="utf-8",
    )

    for attempt_index in range(_MAX_AUTO_RETRY + 1):
        codex_process: asyncio.subprocess.Process | None = None
        try:
            codex_process = await asyncio.create_subprocess_exec(
                codex_executable_path,
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                constructed_codex_prompt,
                cwd=str(work_dir_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,  # 独立进程组，确保 killpg 能杀死所有子进程
            )
            _running_codex_processes[task_id_str] = codex_process

            pending_lines: list[str] = []
            last_flush_time = asyncio.get_event_loop().time()

            async def flush_pending(force: bool = False) -> None:
                """将积累的行合并写入一条 DevLog."""
                nonlocal last_flush_time
                if not pending_lines:
                    return
                elapsed = asyncio.get_event_loop().time() - last_flush_time
                if force or len(pending_lines) >= _LOG_BATCH_SIZE or elapsed >= _LOG_FLUSH_INTERVAL_SECONDS:
                    await asyncio.to_thread(
                        _write_log_to_db,
                        task_id_str,
                        run_account_id_str,
                        "\n".join(pending_lines),
                        "OPTIMIZATION",
                    )
                    pending_lines.clear()
                    last_flush_time = asyncio.get_event_loop().time()

            all_output_lines: list[str] = []
            assert codex_process.stdout is not None
            async for raw_stdout_line in codex_process.stdout:
                decoded_line_str = raw_stdout_line.decode("utf-8", errors="replace").rstrip()
                if decoded_line_str:
                    pending_lines.append(decoded_line_str)
                    all_output_lines.append(decoded_line_str)
                    logger.debug(f"[codex:{task_id_str[:8]}] {decoded_line_str}")
                    with task_log_path.open("a", encoding="utf-8") as log_file_handle:
                        log_file_handle.write(decoded_line_str + "\n")
                await flush_pending()

            return_code_int = await codex_process.wait()
            await flush_pending(force=True)
            with task_log_path.open("a", encoding="utf-8") as log_file_handle:
                log_file_handle.write(f"\n=== exit code: {return_code_int} ===\n")

            # 即使 exit 0，若输出中包含中断标志，也视为意外中断需要重试
            if return_code_int == 0 and not _output_contains_interruption(all_output_lines):
                completion_log_text = (
                    "✅ codex exec 执行完成（exit 0）。\n"
                    "工作流阶段即将推进至：AI 自检中（self_review_in_progress）。"
                )
                await asyncio.to_thread(
                    _write_log_to_db, task_id_str, run_account_id_str, completion_log_text, "FIXED"
                )
                await asyncio.to_thread(_advance_stage_in_db, task_id_str, "self_review_in_progress")
                logger.info(f"Task {task_id_str[:8]}... codex exec succeeded.")
                return

            # exit 0 但含中断标志，或非零退出，均视为失败
            if return_code_int == 0:
                return_code_int = -1  # 标准化为失败码，触发后续重试逻辑

            # 非零退出：判断是否为用户取消
            if task_id_str in _user_cancelled_tasks:
                _user_cancelled_tasks.discard(task_id_str)
                await asyncio.to_thread(
                    _write_log_to_db, task_id_str, run_account_id_str,
                    "🛑 用户手动中断了任务执行。", "BUG"
                )
                await asyncio.to_thread(_advance_stage_in_db, task_id_str, "changes_requested")
                return

            # 意外中断，判断是否还有重试次数
            if attempt_index < _MAX_AUTO_RETRY:
                retry_msg = (
                    f"⚠️ codex exec 意外中断（exit {return_code_int}），"
                    f"自动重试（{attempt_index + 1}/{_MAX_AUTO_RETRY}）..."
                )
                await asyncio.to_thread(
                    _write_log_to_db, task_id_str, run_account_id_str, retry_msg, "BUG"
                )
                with task_log_path.open("a", encoding="utf-8") as log_file_handle:
                    log_file_handle.write(retry_msg + "\n")
                logger.warning(f"Task {task_id_str[:8]}... interrupted, retrying ({attempt_index + 1}/{_MAX_AUTO_RETRY})")
                continue

            # 重试耗尽
            await asyncio.to_thread(
                _write_log_to_db, task_id_str, run_account_id_str,
                f"❌ codex exec 失败（exit {return_code_int}），已重试 {_MAX_AUTO_RETRY} 次。", "BUG"
            )
            await asyncio.to_thread(_advance_stage_in_db, task_id_str, "changes_requested")
            logger.warning(f"Task {task_id_str[:8]}... codex exec failed after {_MAX_AUTO_RETRY} retries.")

        except Exception as unexpected_error:
            logger.exception(f"Unexpected error in run_codex_task for {task_id_str[:8]}... (attempt {attempt_index + 1})")

            if task_id_str in _user_cancelled_tasks:
                _user_cancelled_tasks.discard(task_id_str)
                await asyncio.to_thread(
                    _write_log_to_db, task_id_str, run_account_id_str,
                    "🛑 用户手动中断了任务执行。", "BUG"
                )
                await asyncio.to_thread(_advance_stage_in_db, task_id_str, "changes_requested")
                return

            if attempt_index < _MAX_AUTO_RETRY:
                retry_msg = (
                    f"⚠️ codex 执行意外异常（{unexpected_error}），"
                    f"自动重试（{attempt_index + 1}/{_MAX_AUTO_RETRY}）..."
                )
                await asyncio.to_thread(
                    _write_log_to_db, task_id_str, run_account_id_str, retry_msg, "BUG"
                )
                continue

            await asyncio.to_thread(
                _write_log_to_db, task_id_str, run_account_id_str,
                f"❌ codex 执行过程中发生意外错误：{unexpected_error}", "BUG"
            )
            await asyncio.to_thread(_advance_stage_in_db, task_id_str, "changes_requested")

        finally:
            _running_codex_processes.pop(task_id_str, None)
            if codex_process and codex_process.returncode is None:
                try:
                    codex_process.kill()
                except ProcessLookupError:
                    pass
