"""Codex 执行器服务模块.

负责构建任务 Prompt、以非交互方式调用 codex exec CLI，
并将执行过程的 stdout/stderr 实时写入 DevLog 时间线.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
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

# self-review 输出中的结构化状态标记
_SELF_REVIEW_STATUS_MARKER = "SELF_REVIEW_STATUS"
_SELF_REVIEW_SUMMARY_MARKER = "SELF_REVIEW_SUMMARY"
_SELF_REVIEW_STATUS_PASS = "PASS"
_SELF_REVIEW_STATUS_CHANGES_REQUESTED = "CHANGES_REQUESTED"


@dataclass(slots=True)
class CodexPhaseExecutionResult:
    """描述一次 Codex 阶段执行的结果.

    Attributes:
        success: 阶段是否成功完成
        output_lines: 本次阶段输出的所有行
        was_cancelled: 是否由用户主动取消
    """

    success: bool
    output_lines: list[str]
    was_cancelled: bool = False


def _output_contains_interruption(output_lines: list[str]) -> bool:
    """检查 codex 输出的末尾若干行是否包含中断标志.

    Args:
        output_lines: codex 输出行列表

    Returns:
        bool: 若最后 10 行中出现中断标志则返回 True
    """
    recent_lines_str = "\n".join(output_lines[-10:]).lower()
    return any(marker in recent_lines_str for marker in _CODEX_INTERRUPTED_MARKERS)


def _extract_trailing_marker_value(
    output_lines: list[str],
    marker_name_str: str,
) -> str | None:
    """从输出尾部提取结构化标记的值.

    Args:
        output_lines: codex 输出行列表
        marker_name_str: 标记名，例如 SELF_REVIEW_STATUS

    Returns:
        str | None: 标记值，不存在时返回 None
    """
    marker_prefix_upper_str = f"{marker_name_str}:".upper()
    for raw_output_line_str in reversed(output_lines):
        stripped_output_line_str = raw_output_line_str.strip()
        if stripped_output_line_str.upper().startswith(marker_prefix_upper_str):
            marker_value_str = stripped_output_line_str.split(":", 1)[1].strip()
            return marker_value_str or None
    return None


def _extract_self_review_status(output_lines: list[str]) -> str | None:
    """解析 self-review 的结构化状态.

    Args:
        output_lines: self-review 阶段输出行列表

    Returns:
        str | None: PASS 或 CHANGES_REQUESTED；无有效标记时返回 None
    """
    extracted_status_str = _extract_trailing_marker_value(
        output_lines,
        _SELF_REVIEW_STATUS_MARKER,
    )
    if not extracted_status_str:
        return None

    normalized_status_str = extracted_status_str.upper()
    if normalized_status_str in {
        _SELF_REVIEW_STATUS_PASS,
        _SELF_REVIEW_STATUS_CHANGES_REQUESTED,
    }:
        return normalized_status_str
    return None


def _extract_self_review_summary(output_lines: list[str]) -> str | None:
    """解析 self-review 的摘要文本.

    Args:
        output_lines: self-review 阶段输出行列表

    Returns:
        str | None: 摘要文本；不存在时返回 None
    """
    return _extract_trailing_marker_value(output_lines, _SELF_REVIEW_SUMMARY_MARKER)


def _build_recent_context_block(
    dev_log_text_list: list[str],
    max_items_int: int,
    separator_str: str,
    empty_context_text_str: str,
) -> str:
    """构造最近若干条日志组成的上下文块.

    Args:
        dev_log_text_list: 历史日志文本列表
        max_items_int: 取最近多少条
        separator_str: 多条日志之间的分隔符
        empty_context_text_str: 无上下文时的占位文本

    Returns:
        str: 供 Prompt 使用的上下文块
    """
    non_empty_context_line_list: list[str] = []
    for raw_log_text_str in dev_log_text_list[-max_items_int:]:
        stripped_log_text_str = raw_log_text_str.strip()
        if stripped_log_text_str:
            non_empty_context_line_list.append(stripped_log_text_str)

    if non_empty_context_line_list:
        return separator_str.join(non_empty_context_line_list)
    return empty_context_text_str


def cancel_codex_task(task_id_str: str) -> bool:
    """中断指定任务正在运行的 codex 进程（用户主动触发）.

    标记为用户取消后再发送 SIGKILL，使后台重试逻辑知道这是用户行为，
    不应自动重试。

    Args:
        task_id_str: 任务 UUID 字符串

    Returns:
        bool: 若找到并成功发送终止信号则返回 True，否则返回 False
    """
    _user_cancelled_tasks.add(task_id_str)

    codex_process_obj = _running_codex_processes.get(task_id_str)
    if codex_process_obj is None:
        return False
    if codex_process_obj.returncode is not None:
        _running_codex_processes.pop(task_id_str, None)
        return False

    try:
        os.killpg(os.getpgid(codex_process_obj.pid), signal.SIGKILL)
        logger.info(f"Sent SIGKILL to process group for task {task_id_str[:8]}... (user cancel)")
        return True
    except (ProcessLookupError, PermissionError, OSError):
        try:
            codex_process_obj.kill()
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


def _write_phase_log_header(
    task_log_path: Path,
    task_id_str: str,
    phase_log_label_str: str,
    overwrite_existing_log_bool: bool,
) -> None:
    """写入任务日志文件的阶段头部.

    Args:
        task_log_path: 任务日志文件路径
        task_id_str: 任务 UUID 字符串
        phase_log_label_str: 阶段标签，如 codex-exec 或 codex-review
        overwrite_existing_log_bool: 是否覆盖旧文件
    """
    header_text_str = (
        f"=== Koda {phase_log_label_str} | task {task_id_str[:8]} | "
        f"{datetime.now(UTC).replace(tzinfo=None).isoformat()} ===\n"
    )

    if overwrite_existing_log_bool:
        task_log_path.write_text(header_text_str, encoding="utf-8")
        return

    existing_file_has_content_bool = (
        task_log_path.exists() and task_log_path.stat().st_size > 0
    )
    with task_log_path.open("a", encoding="utf-8") as log_file_handle:
        if existing_file_has_content_bool:
            log_file_handle.write("\n")
        log_file_handle.write(header_text_str)


def _append_text_to_task_log(task_log_path: Path, appended_text_str: str) -> None:
    """向任务日志文件追加一行文本.

    Args:
        task_log_path: 任务日志文件路径
        appended_text_str: 要追加的文本
    """
    with task_log_path.open("a", encoding="utf-8") as log_file_handle:
        log_file_handle.write(appended_text_str + "\n")


def _append_exit_code_to_task_log(task_log_path: Path, exit_code_int: int) -> None:
    """向任务日志文件追加退出码标记.

    Args:
        task_log_path: 任务日志文件路径
        exit_code_int: 子进程退出码
    """
    with task_log_path.open("a", encoding="utf-8") as log_file_handle:
        log_file_handle.write(f"\n=== exit code: {exit_code_int} ===\n")


def build_codex_prompt(
    task_title: str,
    dev_log_text_list: list[str],
    worktree_path_str: str | None = None,
) -> str:
    """根据任务标题和历史日志构建实现阶段 Prompt.

    若提供了 worktree_path_str，提示中会要求 codex 直接在该 worktree 中实现需求。

    Args:
        task_title: 需求卡片标题
        dev_log_text_list: 该任务下已有日志的 text_content 列表（时间正序）
        worktree_path_str: 预期的 git worktree 绝对路径（可选）

    Returns:
        str: 完整的 codex Prompt 文本
    """
    task_context_block_str = _build_recent_context_block(
        dev_log_text_list=dev_log_text_list,
        max_items_int=10,
        separator_str="\n\n---\n",
        empty_context_text_str="（暂无额外上下文，请根据需求标题自行判断实现范围）",
    )

    if worktree_path_str:
        worktree_instruction_block_str = f"""
## Git Worktree 说明
当前已在 git worktree 目录中工作：`{worktree_path_str}`
- 直接在此目录中完成所有代码修改，无需再创建 worktree
- 不要默认执行 `git commit`；代码提交必须等待用户确认后再进行
"""
    else:
        worktree_instruction_block_str = ""

    constructed_prompt_text = f"""你是一个高效的 AI 编码助手，正在处理如下需求卡片。

## 需求标题
{task_title}

## 需求上下文（来自历史日志）
{task_context_block_str}
{worktree_instruction_block_str}
## 执行要求
1. 请仔细阅读需求上下文，理解需要实现的功能范围。
2. 在当前代码仓库中定位相关文件，根据项目现有代码风格完成实现。
3. 遵循项目规范：Python 使用 Google Style Docstring，前端使用 TypeScript + React，所有文件读写显式指定 encoding='utf-8'。
4. 不要默认执行 `git commit`、不要推送分支；提交动作必须等待用户确认。
5. 完成后简要输出：修改了哪些文件、实现了什么逻辑、需要注意什么。
6. 如果需求描述不够清晰，请做出合理假设并在输出中说明。

请开始执行。"""

    return constructed_prompt_text


def build_codex_review_prompt(
    task_title: str,
    dev_log_text_list: list[str],
    worktree_path_str: str | None = None,
) -> str:
    """根据任务标题和历史日志构建 self-review Prompt.

    Args:
        task_title: 需求卡片标题
        dev_log_text_list: 该任务下已有日志的 text_content 列表（时间正序）
        worktree_path_str: 预期的 git worktree 绝对路径（可选）

    Returns:
        str: 完整的 self-review Prompt 文本
    """
    review_context_block_str = _build_recent_context_block(
        dev_log_text_list=dev_log_text_list,
        max_items_int=12,
        separator_str="\n\n---\n",
        empty_context_text_str="（暂无额外上下文，请根据需求标题和当前代码自行判断实现范围）",
    )

    if worktree_path_str:
        review_worktree_instruction_block_str = f"""
## Git Worktree 说明
当前工作目录是任务对应的 git worktree：`{worktree_path_str}`
- 优先基于当前工作区内的改动、`git status`、`git diff` 和相关文件进行审查
"""
    else:
        review_worktree_instruction_block_str = ""

    constructed_review_prompt_text = f"""你现在处于 Koda 工作流的 AI 自检阶段，需要对刚完成的实现做一次代码评审。

## 需求标题
{task_title}

## 最近上下文（来自任务日志）
{review_context_block_str}
{review_worktree_instruction_block_str}
## 评审要求
1. 这是 review-only 阶段：不要修改任何文件、不要执行 `git commit`、不要创建 PR。
2. 优先检查当前实现是否覆盖需求、是否引入明显回归、文档是否同步、错误路径是否被遗漏。
3. 如果仓库支持 git，请主动查看当前工作区改动；如果不支持，也要基于当前文件内容完成审查。
4. 输出 review 结论时，请尽量给出具体文件路径、风险点和影响。
5. 在输出末尾，必须额外给出且只给出以下两行结构化结果：
   - `{_SELF_REVIEW_SUMMARY_MARKER}: <一句话摘要>`
   - `{_SELF_REVIEW_STATUS_MARKER}: PASS` 或 `{_SELF_REVIEW_STATUS_MARKER}: CHANGES_REQUESTED`
6. 只有在没有阻塞性问题时才能输出 `PASS`；只要发现需要回改的阻塞问题，就输出 `CHANGES_REQUESTED`。

请开始执行代码评审。"""

    return constructed_review_prompt_text


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
            created_at=datetime.now(UTC).replace(tzinfo=None),
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


async def _run_codex_phase(
    task_id_str: str,
    run_account_id_str: str,
    codex_prompt_text_str: str,
    work_dir_path: Path,
    phase_log_label_str: str,
    phase_display_name_str: str,
    cancelled_log_text_str: str,
    overwrite_existing_log_bool: bool,
    clear_cancel_marker_at_start_bool: bool = True,
) -> CodexPhaseExecutionResult:
    """执行一个通用的 Codex 阶段，统一处理日志、重试和取消逻辑.

    Args:
        task_id_str: 任务 UUID 字符串
        run_account_id_str: 运行账户 UUID 字符串
        codex_prompt_text_str: 发给 codex exec 的 Prompt
        work_dir_path: codex 的工作目录
        phase_log_label_str: 本地日志中的阶段标签
        phase_display_name_str: 用户可见的阶段名，用于日志文案
        cancelled_log_text_str: 用户取消时要写入的日志文本
        overwrite_existing_log_bool: 是否覆盖旧的任务日志文件
        clear_cancel_marker_at_start_bool: 是否在阶段开始时清除旧的取消标记

    Returns:
        CodexPhaseExecutionResult: 本次阶段执行结果
    """
    codex_executable_path_str = shutil.which("codex")
    if not codex_executable_path_str:
        missing_codex_log_text = "❌ 未找到 codex 可执行文件，请确认 codex CLI 已安装并在 PATH 中。"
        await asyncio.to_thread(
            _write_log_to_db,
            task_id_str,
            run_account_id_str,
            missing_codex_log_text,
            "BUG",
        )
        return CodexPhaseExecutionResult(success=False, output_lines=[])

    if clear_cancel_marker_at_start_bool:
        _user_cancelled_tasks.discard(task_id_str)
    elif task_id_str in _user_cancelled_tasks:
        _user_cancelled_tasks.discard(task_id_str)
        await asyncio.to_thread(
            _write_log_to_db,
            task_id_str,
            run_account_id_str,
            cancelled_log_text_str,
            "BUG",
        )
        return CodexPhaseExecutionResult(success=False, output_lines=[], was_cancelled=True)

    task_log_path = get_task_log_path(task_id_str)
    _write_phase_log_header(
        task_log_path=task_log_path,
        task_id_str=task_id_str,
        phase_log_label_str=phase_log_label_str,
        overwrite_existing_log_bool=overwrite_existing_log_bool,
    )

    for attempt_index in range(_MAX_AUTO_RETRY + 1):
        codex_process_obj: asyncio.subprocess.Process | None = None
        try:
            codex_process_obj = await asyncio.create_subprocess_exec(
                codex_executable_path_str,
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                codex_prompt_text_str,
                cwd=str(work_dir_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            _running_codex_processes[task_id_str] = codex_process_obj

            pending_output_line_list: list[str] = []
            aggregated_output_line_list: list[str] = []
            last_flush_time_float = asyncio.get_running_loop().time()

            async def flush_pending_output_lines(force: bool = False) -> None:
                """将积累的输出批量写入一条 DevLog."""
                nonlocal last_flush_time_float
                if not pending_output_line_list:
                    return

                elapsed_seconds_float = asyncio.get_running_loop().time() - last_flush_time_float
                if (
                    force
                    or len(pending_output_line_list) >= _LOG_BATCH_SIZE
                    or elapsed_seconds_float >= _LOG_FLUSH_INTERVAL_SECONDS
                ):
                    await asyncio.to_thread(
                        _write_log_to_db,
                        task_id_str,
                        run_account_id_str,
                        "\n".join(pending_output_line_list),
                        "OPTIMIZATION",
                    )
                    pending_output_line_list.clear()
                    last_flush_time_float = asyncio.get_running_loop().time()

            assert codex_process_obj.stdout is not None
            async for raw_stdout_line_bytes in codex_process_obj.stdout:
                decoded_stdout_line_str = raw_stdout_line_bytes.decode(
                    "utf-8",
                    errors="replace",
                ).rstrip()
                if decoded_stdout_line_str:
                    pending_output_line_list.append(decoded_stdout_line_str)
                    aggregated_output_line_list.append(decoded_stdout_line_str)
                    logger.debug(f"[{phase_log_label_str}:{task_id_str[:8]}] {decoded_stdout_line_str}")
                    _append_text_to_task_log(task_log_path, decoded_stdout_line_str)
                await flush_pending_output_lines()

            phase_return_code_int = await codex_process_obj.wait()
            await flush_pending_output_lines(force=True)
            _append_exit_code_to_task_log(task_log_path, phase_return_code_int)

            if phase_return_code_int == 0 and not _output_contains_interruption(aggregated_output_line_list):
                return CodexPhaseExecutionResult(
                    success=True,
                    output_lines=aggregated_output_line_list,
                )

            if phase_return_code_int == 0:
                phase_return_code_int = -1

            if task_id_str in _user_cancelled_tasks:
                _user_cancelled_tasks.discard(task_id_str)
                await asyncio.to_thread(
                    _write_log_to_db,
                    task_id_str,
                    run_account_id_str,
                    cancelled_log_text_str,
                    "BUG",
                )
                return CodexPhaseExecutionResult(
                    success=False,
                    output_lines=aggregated_output_line_list,
                    was_cancelled=True,
                )

            if attempt_index < _MAX_AUTO_RETRY:
                retry_log_text_str = (
                    f"⚠️ {phase_display_name_str}阶段意外中断（exit {phase_return_code_int}），"
                    f"自动重试（{attempt_index + 1}/{_MAX_AUTO_RETRY}）..."
                )
                await asyncio.to_thread(
                    _write_log_to_db,
                    task_id_str,
                    run_account_id_str,
                    retry_log_text_str,
                    "BUG",
                )
                _append_text_to_task_log(task_log_path, retry_log_text_str)
                logger.warning(
                    f"Task {task_id_str[:8]}... {phase_display_name_str} interrupted, "
                    f"retrying ({attempt_index + 1}/{_MAX_AUTO_RETRY})"
                )
                continue

            exhausted_retry_log_text_str = (
                f"❌ {phase_display_name_str}阶段失败（exit {phase_return_code_int}），"
                f"已重试 {_MAX_AUTO_RETRY} 次。"
            )
            await asyncio.to_thread(
                _write_log_to_db,
                task_id_str,
                run_account_id_str,
                exhausted_retry_log_text_str,
                "BUG",
            )
            logger.warning(
                f"Task {task_id_str[:8]}... {phase_display_name_str} failed after "
                f"{_MAX_AUTO_RETRY} retries."
            )
            return CodexPhaseExecutionResult(
                success=False,
                output_lines=aggregated_output_line_list,
            )

        except Exception as unexpected_phase_error:
            logger.exception(
                f"Unexpected error in {phase_log_label_str} for {task_id_str[:8]}... "
                f"(attempt {attempt_index + 1})"
            )

            if task_id_str in _user_cancelled_tasks:
                _user_cancelled_tasks.discard(task_id_str)
                await asyncio.to_thread(
                    _write_log_to_db,
                    task_id_str,
                    run_account_id_str,
                    cancelled_log_text_str,
                    "BUG",
                )
                return CodexPhaseExecutionResult(success=False, output_lines=[], was_cancelled=True)

            if attempt_index < _MAX_AUTO_RETRY:
                retry_log_text_str = (
                    f"⚠️ {phase_display_name_str}阶段意外异常（{unexpected_phase_error}），"
                    f"自动重试（{attempt_index + 1}/{_MAX_AUTO_RETRY}）..."
                )
                await asyncio.to_thread(
                    _write_log_to_db,
                    task_id_str,
                    run_account_id_str,
                    retry_log_text_str,
                    "BUG",
                )
                continue

            unexpected_failure_log_text_str = (
                f"❌ {phase_display_name_str}阶段发生意外错误：{unexpected_phase_error}"
            )
            await asyncio.to_thread(
                _write_log_to_db,
                task_id_str,
                run_account_id_str,
                unexpected_failure_log_text_str,
                "BUG",
            )
            return CodexPhaseExecutionResult(success=False, output_lines=[])

        finally:
            _running_codex_processes.pop(task_id_str, None)
            if codex_process_obj and codex_process_obj.returncode is None:
                try:
                    codex_process_obj.kill()
                except ProcessLookupError:
                    pass

    return CodexPhaseExecutionResult(success=False, output_lines=[])


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
    prd_context_block_str = _build_recent_context_block(
        dev_log_text_list=dev_log_text_list,
        max_items_int=5,
        separator_str="\n---\n",
        empty_context_text_str="（无额外上下文，请根据需求标题判断范围）",
    )

    worktree_note_str = (
        f"\n当前工作目录是 git worktree：`{worktree_path_str}`"
        if worktree_path_str
        else ""
    )

    prd_prompt_text_str = f"""请为以下需求生成 PRD 文档。{worktree_note_str}

## 需求标题
{task_title_str}

## 需求背景/上下文
{prd_context_block_str}

## 执行步骤

使用 `/prd` skill 生成 PRD，将需求标题和上下文作为输入。

生成完成后，将 PRD 内容保存到文件：
`tasks/prd-{task_id_str[:8]}.md`

**重要**：必须真正写入文件，不只是输出到终端。写完后输出文件路径。"""

    task_prd_file_path = work_dir_path / "tasks" / f"prd-{task_id_str[:8]}.md"
    if task_prd_file_path.exists():
        try:
            task_prd_file_path.unlink()
            logger.info(f"Removed old PRD file: {task_prd_file_path}")
        except OSError as cleanup_error:
            logger.warning(f"Could not remove old PRD file {task_prd_file_path}: {cleanup_error}")

    prd_phase_result = await _run_codex_phase(
        task_id_str=task_id_str,
        run_account_id_str=run_account_id_str,
        codex_prompt_text_str=prd_prompt_text_str,
        work_dir_path=work_dir_path,
        phase_log_label_str="codex-prd",
        phase_display_name_str="PRD 生成",
        cancelled_log_text_str="🛑 用户手动中断了 PRD 生成。",
        overwrite_existing_log_bool=True,
    )

    if not prd_phase_result.success:
        await asyncio.to_thread(_advance_stage_in_db, task_id_str, "changes_requested")
        return

    await asyncio.to_thread(
        _write_log_to_db,
        task_id_str,
        run_account_id_str,
        "✅ PRD 已生成，请先由用户确认 PRD，再决定是否进入后续执行阶段。",
        "FIXED",
    )
    await asyncio.to_thread(_advance_stage_in_db, task_id_str, "prd_waiting_confirmation")
    logger.info(f"Task {task_id_str[:8]}... PRD generated → prd_waiting_confirmation")


async def run_codex_review(
    task_id_str: str,
    run_account_id_str: str,
    task_title_str: str,
    dev_log_text_list: list[str],
    work_dir_path: Path,
    worktree_path_str: str | None = None,
) -> None:
    """执行 AI 自检阶段的代码评审.

    Args:
        task_id_str: 任务 UUID 字符串
        run_account_id_str: 运行账户 UUID 字符串
        task_title_str: 任务标题
        dev_log_text_list: 历史日志文本列表
        work_dir_path: codex 的工作目录
        worktree_path_str: 预期的 git worktree 路径（可选）
    """
    review_prompt_text_str = build_codex_review_prompt(
        task_title=task_title_str,
        dev_log_text_list=dev_log_text_list,
        worktree_path_str=worktree_path_str,
    )

    review_phase_result = await _run_codex_phase(
        task_id_str=task_id_str,
        run_account_id_str=run_account_id_str,
        codex_prompt_text_str=review_prompt_text_str,
        work_dir_path=work_dir_path,
        phase_log_label_str="codex-review",
        phase_display_name_str="AI 自检",
        cancelled_log_text_str="🛑 用户手动中断了 AI 自检。",
        overwrite_existing_log_bool=False,
        clear_cancel_marker_at_start_bool=False,
    )

    if not review_phase_result.success:
        await asyncio.to_thread(_advance_stage_in_db, task_id_str, "changes_requested")
        return

    self_review_status_str = _extract_self_review_status(review_phase_result.output_lines)
    self_review_summary_str = _extract_self_review_summary(review_phase_result.output_lines)

    if self_review_status_str == _SELF_REVIEW_STATUS_PASS:
        review_pass_log_text = (
            "✅ AI 自检完成，未发现阻塞性问题。\n"
            "当前阶段保持在：AI 自检中（self_review_in_progress）。"
        )
        if self_review_summary_str:
            review_pass_log_text += f"\n摘要：{self_review_summary_str}"
        await asyncio.to_thread(
            _write_log_to_db,
            task_id_str,
            run_account_id_str,
            review_pass_log_text,
            "FIXED",
        )
        logger.info(f"Task {task_id_str[:8]}... self review passed.")
        return

    if self_review_status_str == _SELF_REVIEW_STATUS_CHANGES_REQUESTED:
        review_blocker_log_text = (
            "❌ AI 自检发现阻塞性问题，任务已回退至：待修改（changes_requested）。"
        )
        if self_review_summary_str:
            review_blocker_log_text += f"\n摘要：{self_review_summary_str}"
        await asyncio.to_thread(
            _write_log_to_db,
            task_id_str,
            run_account_id_str,
            review_blocker_log_text,
            "BUG",
        )
        await asyncio.to_thread(_advance_stage_in_db, task_id_str, "changes_requested")
        logger.info(f"Task {task_id_str[:8]}... self review requested changes.")
        return

    missing_status_log_text = (
        "⚠️ AI 自检已执行，但未产出有效的结构化状态标记，"
        "任务已回退至：待修改（changes_requested），等待人工确认。"
    )
    if self_review_summary_str:
        missing_status_log_text += f"\n摘要：{self_review_summary_str}"
    await asyncio.to_thread(
        _write_log_to_db,
        task_id_str,
        run_account_id_str,
        missing_status_log_text,
        "BUG",
    )
    await asyncio.to_thread(_advance_stage_in_db, task_id_str, "changes_requested")
    logger.warning(f"Task {task_id_str[:8]}... self review missing status marker.")


async def run_codex_task(
    task_id_str: str,
    run_account_id_str: str,
    task_title_str: str,
    dev_log_text_list: list[str],
    work_dir_path: Path,
    worktree_path_str: str | None = None,
) -> None:
    """非交互方式运行 codex exec，并在成功后进入真实的 self-review 阶段.

    整个函数设计为 fire-and-forget（后台任务），不向调用方抛出异常。
    执行失败时将 workflow_stage 回退至 changes_requested。

    Args:
        task_id_str: 任务 UUID 字符串
        run_account_id_str: 运行账户 UUID 字符串
        task_title_str: 任务标题，用于构建 Prompt
        dev_log_text_list: 历史日志文本列表，用于构建上下文
        work_dir_path: codex 的工作目录（代码仓库根路径）
        worktree_path_str: 预期的 git worktree 路径（可选）
    """
    implementation_prompt_text_str = build_codex_prompt(
        task_title=task_title_str,
        dev_log_text_list=dev_log_text_list,
        worktree_path_str=worktree_path_str,
    )

    logger.info(
        f"Starting codex exec for task {task_id_str[:8]}... in work_dir={work_dir_path}"
    )

    implementation_phase_result = await _run_codex_phase(
        task_id_str=task_id_str,
        run_account_id_str=run_account_id_str,
        codex_prompt_text_str=implementation_prompt_text_str,
        work_dir_path=work_dir_path,
        phase_log_label_str="codex-exec",
        phase_display_name_str="codex exec",
        cancelled_log_text_str="🛑 用户手动中断了任务执行。",
        overwrite_existing_log_bool=True,
    )

    if not implementation_phase_result.success:
        await asyncio.to_thread(_advance_stage_in_db, task_id_str, "changes_requested")
        return

    completion_log_text = (
        "✅ codex exec 执行完成（exit 0）。\n"
        "工作流阶段即将推进至：AI 自检中（self_review_in_progress）。"
    )
    await asyncio.to_thread(
        _write_log_to_db,
        task_id_str,
        run_account_id_str,
        completion_log_text,
        "FIXED",
    )
    await asyncio.to_thread(_advance_stage_in_db, task_id_str, "self_review_in_progress")
    await asyncio.to_thread(
        _write_log_to_db,
        task_id_str,
        run_account_id_str,
        "🔍 已进入 AI 自检阶段，开始执行代码评审。",
        "OPTIMIZATION",
    )
    logger.info(f"Task {task_id_str[:8]}... implementation completed, starting self review.")

    review_context_log_list = dev_log_text_list + implementation_phase_result.output_lines
    await run_codex_review(
        task_id_str=task_id_str,
        run_account_id_str=run_account_id_str,
        task_title_str=task_title_str,
        dev_log_text_list=review_context_log_list,
        work_dir_path=work_dir_path,
        worktree_path_str=worktree_path_str,
    )
