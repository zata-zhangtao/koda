"""Codex 执行器服务模块.

负责构建任务 Prompt、以非交互方式调用 codex exec CLI，
并将执行过程的 stdout/stderr 实时写入 DevLog 时间线.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import signal
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from utils.database import SessionLocal
from utils.helpers import serialize_datetime_for_api, utc_now_naive
from utils.logger import logger


# codex exec 每次最多批量写入的行数
_LOG_BATCH_SIZE = 5

# 两次批量写入之间等待的最长秒数（缩短以实时展示）
_LOG_FLUSH_INTERVAL_SECONDS = 1.5

# 日志文件存放目录
_CODEX_LOG_DIR = Path("/tmp")

# 正在运行的 codex 进程注册表：task_id -> asyncio.subprocess.Process
_running_codex_processes: dict[str, "asyncio.subprocess.Process"] = {}

# 正在运行的后台任务集合：覆盖 codex 与非 codex 的任务收尾动作
_running_background_task_ids: set[str] = set()

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


@dataclass(slots=True)
class GitCompletionExecutionResult:
    """Describe the result of the deterministic Git completion flow.

    Attributes:
        merged_to_main: Whether the feature branch was merged into ``main``
        cleanup_succeeded: Whether worktree/branch cleanup finished successfully
        output_lines: Collected command output lines for logging
        feature_branch_name: Resolved feature branch name
        failure_reason_text: Human-readable failure reason
        worktree_removed: Whether the task worktree was removed from disk
    """

    merged_to_main: bool
    cleanup_succeeded: bool
    output_lines: list[str]
    feature_branch_name: str | None = None
    failure_reason_text: str | None = None
    worktree_removed: bool = False


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
        logger.info(
            f"Sent SIGKILL to process group for task {task_id_str[:8]}... (user cancel)"
        )
        return True
    except (ProcessLookupError, PermissionError, OSError):
        try:
            codex_process_obj.kill()
        except ProcessLookupError:
            pass
        _running_codex_processes.pop(task_id_str, None)
    return False


def is_codex_task_running(task_id_str: str) -> bool:
    """判断指定任务当前是否仍有 Codex 进程在运行.

    Args:
        task_id_str: 任务 UUID 字符串

    Returns:
        bool: 若存在未退出的 Codex 进程则返回 True
    """
    if task_id_str in _running_background_task_ids:
        return True

    codex_process_obj = _running_codex_processes.get(task_id_str)
    return codex_process_obj is not None and codex_process_obj.returncode is None


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
        f"{serialize_datetime_for_api(utc_now_naive())} ===\n"
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


def _append_output_block_to_task_log(task_log_path: Path, output_text_str: str) -> None:
    """Append multi-line command output to the task log.

    Args:
        task_log_path: Task log file path
        output_text_str: Multi-line output text
    """
    if not output_text_str.strip():
        return

    for output_line_str in output_text_str.rstrip().splitlines():
        _append_text_to_task_log(task_log_path, output_line_str)


def _build_completion_commit_message(
    task_id_str: str,
    task_title_str: str,
    task_summary_str: str | None,
    dev_log_text_list: list[str],
) -> str:
    """Build a short compliant commit subject from the task summary first.

    Args:
        task_id_str: Task UUID
        task_title_str: Task title, used only as a last-resort fallback
        task_summary_str: Task summary / requirement brief
        dev_log_text_list: Recent task logs, used as secondary fallback context

    Returns:
        str: Sanitized commit subject
    """
    commit_subject_candidate_list = [task_summary_str or ""]
    commit_subject_candidate_list.extend(reversed(dev_log_text_list))
    commit_subject_candidate_list.append(task_title_str)

    for raw_commit_subject_candidate_str in commit_subject_candidate_list:
        summary_subject_line_str = raw_commit_subject_candidate_str.splitlines()[
            0
        ].strip()
        normalized_commit_subject_str = " ".join(
            summary_subject_line_str.split()
        ).rstrip(".")
        if normalized_commit_subject_str:
            return normalized_commit_subject_str[:72].rstrip()

    return f"Task summary update {task_id_str[:8]}"


def _resolve_primary_repo_root_from_worktree(worktree_path: Path) -> Path:
    """Resolve the primary repository worktree from a task worktree.

    Args:
        worktree_path: Task worktree path

    Returns:
        Path: Primary repository root path

    Raises:
        ValueError: When the worktree does not resolve to a valid shared Git dir
    """
    completed_process = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=str(worktree_path),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    raw_common_dir_path = completed_process.stdout.strip()
    if not raw_common_dir_path:
        raise ValueError(f"无法解析 worktree 对应的 git common dir：{worktree_path}")

    git_common_dir_path = Path(raw_common_dir_path)
    if not git_common_dir_path.is_absolute():
        git_common_dir_path = (worktree_path / git_common_dir_path).resolve()

    resolved_repo_root_path = git_common_dir_path.parent
    if not resolved_repo_root_path.exists():
        raise ValueError(f"worktree 对应的主仓库目录不存在：{resolved_repo_root_path}")

    return resolved_repo_root_path


def _resolve_worktree_path_for_branch(
    repo_path: Path, branch_name_str: str
) -> Path | None:
    """Resolve the worktree path that currently has a branch checked out.

    Args:
        repo_path: Any repository or worktree path in the shared repo
        branch_name_str: Branch name to locate, for example ``main``

    Returns:
        Path | None: Worktree path for the branch when found
    """
    completed_process = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=str(repo_path),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    current_worktree_path: Path | None = None
    target_branch_ref_str = f"refs/heads/{branch_name_str}"
    for output_line_str in completed_process.stdout.splitlines():
        if output_line_str.startswith("worktree "):
            current_worktree_path = Path(
                output_line_str.removeprefix("worktree ").strip()
            )
            continue
        if output_line_str.startswith("branch ") and current_worktree_path is not None:
            branch_ref_str = output_line_str.removeprefix("branch ").strip()
            if branch_ref_str == target_branch_ref_str:
                return current_worktree_path
            current_worktree_path = None
    return None


def _run_logged_command(
    *,
    task_id_str: str,
    run_account_id_str: str,
    task_log_path: Path,
    command_argument_list: list[str],
    cwd_path: Path,
    command_log_label_str: str,
) -> subprocess.CompletedProcess[str]:
    """Run one command and mirror the result into the task log and DevLog.

    Args:
        task_id_str: Task UUID
        run_account_id_str: Run account UUID
        task_log_path: Task log file path
        command_argument_list: Command argument list
        cwd_path: Working directory
        command_log_label_str: Human-readable label for the command

    Returns:
        subprocess.CompletedProcess[str]: Completed process object
    """
    command_display_str = shlex.join(command_argument_list)
    _append_text_to_task_log(
        task_log_path, f"$ ({command_log_label_str}) {command_display_str}"
    )

    completed_process = subprocess.run(
        command_argument_list,
        cwd=str(cwd_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    command_output_parts = [
        text_part.strip()
        for text_part in [completed_process.stdout, completed_process.stderr]
        if text_part and text_part.strip()
    ]
    combined_output_text = "\n".join(command_output_parts)
    if combined_output_text:
        _append_output_block_to_task_log(task_log_path, combined_output_text)
    else:
        _append_text_to_task_log(task_log_path, "(no output)")

    _append_exit_code_to_task_log(task_log_path, completed_process.returncode)

    log_text_parts = [f"`{command_display_str}` -> exit {completed_process.returncode}"]
    if combined_output_text:
        log_text_parts.append(combined_output_text)
    _write_log_to_db(
        task_id_str,
        run_account_id_str,
        "\n".join(log_text_parts),
        "OPTIMIZATION" if completed_process.returncode == 0 else "BUG",
    )
    return completed_process


def _has_unmerged_conflicts(repo_path: Path) -> bool:
    """Check whether the current Git working tree still has unresolved conflicts.

    Args:
        repo_path: Repository or worktree path

    Returns:
        bool: Whether any unmerged paths remain
    """
    completed_process = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return bool((completed_process.stdout or "").strip())


def _is_git_operation_still_in_progress(
    repo_path: Path, operation_kind_str: str
) -> bool:
    """Check whether a rebase or merge is still active in the repository.

    Args:
        repo_path: Repository or worktree path
        operation_kind_str: Either ``rebase`` or ``merge``

    Returns:
        bool: Whether the requested Git operation is still active
    """
    if operation_kind_str == "merge":
        completed_process = subprocess.run(
            ["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return completed_process.returncode == 0

    rebase_marker_name_list = ["rebase-merge", "rebase-apply"]
    for rebase_marker_name_str in rebase_marker_name_list:
        marker_path_process = subprocess.run(
            ["git", "rev-parse", "--git-path", rebase_marker_name_str],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        marker_path_text = (marker_path_process.stdout or "").strip()
        if not marker_path_text:
            continue
        marker_path = Path(marker_path_text)
        if not marker_path.is_absolute():
            marker_path = (repo_path / marker_path).resolve()
        if marker_path.exists():
            return True
    return False


def _build_codex_conflict_resolution_prompt(
    *,
    task_title_str: str,
    dev_log_text_list: list[str],
    repo_path: Path,
    operation_kind_str: str,
) -> str:
    """Build the Codex prompt for automatic Git conflict resolution.

    Args:
        task_title_str: Task title
        dev_log_text_list: Recent task history
        repo_path: Repository or worktree path containing conflicts
        operation_kind_str: Either ``rebase`` or ``merge``

    Returns:
        str: Prompt text for ``codex exec``
    """
    recent_context_block_str = _build_recent_context_block(
        dev_log_text_list=dev_log_text_list,
        max_items_int=8,
        separator_str="\n\n---\n",
        empty_context_text_str="（暂无额外上下文，请基于当前冲突与代码状态自行判断）",
    )

    operation_continue_instruction_str = (
        "解决完冲突后执行 `git add .`，然后继续 `git rebase --continue`。"
        if operation_kind_str == "rebase"
        else "解决完冲突后执行 `git add .`，然后继续 `git merge --continue`；如果该命令不可用，则使用 `git commit --no-edit` 完成 merge。"
    )

    return f"""你现在处于 Koda 的自动 Git 冲突修复阶段，需要为当前任务自动处理 `{operation_kind_str}` 冲突。

## 任务标题
{task_title_str}

## 最近上下文
{recent_context_block_str}

## 当前目录
`{repo_path}`

## 执行要求
1. 先检查 `git status` 和当前冲突文件，识别所有未解决的冲突。
2. 直接修改冲突文件，保留本任务已经完成的正确实现，并吸收 `main` 上需要保留的改动。
3. 如果冲突涉及文档、类型或配置，保持它们与最终代码一致。
4. {operation_continue_instruction_str}
5. 如果继续过程中再次出现新的冲突，继续重复“解决冲突 -> add -> continue”，直到当前 `{operation_kind_str}` 真正结束。
6. 不要 `git rebase --abort`、不要 `git merge --abort`、不要 push。
7. 最后输出：解决了哪些冲突文件、`{operation_kind_str}` 是否已经完成、是否还需要人工处理。

请现在直接执行。"""


def _run_logged_codex_conflict_resolution(
    *,
    task_id_str: str,
    run_account_id_str: str,
    task_log_path: Path,
    task_title_str: str,
    dev_log_text_list: list[str],
    repo_path: Path,
    operation_kind_str: str,
) -> subprocess.CompletedProcess[str] | None:
    """Invoke Codex to resolve a rebase or merge conflict in place.

    Args:
        task_id_str: Task UUID
        run_account_id_str: Run account UUID
        task_log_path: Task log file path
        task_title_str: Task title
        dev_log_text_list: Recent task history
        repo_path: Repository or worktree path containing conflicts
        operation_kind_str: Either ``rebase`` or ``merge``

    Returns:
        subprocess.CompletedProcess[str] | None: Completed process object, or None if Codex is unavailable
    """
    codex_executable_path_str = shutil.which("codex")
    if not codex_executable_path_str:
        missing_codex_text = f"❌ 检测到 `{operation_kind_str}` 冲突，但当前环境未找到 codex CLI，无法自动修复。"
        _append_text_to_task_log(task_log_path, missing_codex_text)
        _write_log_to_db(task_id_str, run_account_id_str, missing_codex_text, "BUG")
        return None

    codex_prompt_text_str = _build_codex_conflict_resolution_prompt(
        task_title_str=task_title_str,
        dev_log_text_list=dev_log_text_list,
        repo_path=repo_path,
        operation_kind_str=operation_kind_str,
    )
    command_display_str = (
        f"codex exec --dangerously-bypass-approvals-and-sandbox "
        f"<{operation_kind_str}-conflict-prompt>"
    )
    _append_text_to_task_log(
        task_log_path, f"$ (codex-{operation_kind_str}-conflict) {command_display_str}"
    )

    _CODEX_CONFLICT_RESOLUTION_TIMEOUT_SECONDS = 300

    try:
        completed_process = subprocess.run(
            [
                codex_executable_path_str,
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                codex_prompt_text_str,
            ],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_CODEX_CONFLICT_RESOLUTION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        timeout_text = (
            f"❌ Codex conflict resolution ({operation_kind_str}) timed out after "
            f"{_CODEX_CONFLICT_RESOLUTION_TIMEOUT_SECONDS}s — aborting {operation_kind_str}."
        )
        _append_text_to_task_log(task_log_path, timeout_text)
        _write_log_to_db(task_id_str, run_account_id_str, timeout_text, "BUG")
        return None

    command_output_parts = [
        text_part.strip()
        for text_part in [completed_process.stdout, completed_process.stderr]
        if text_part and text_part.strip()
    ]
    combined_output_text = "\n".join(command_output_parts)
    if combined_output_text:
        _append_output_block_to_task_log(task_log_path, combined_output_text)
    else:
        _append_text_to_task_log(task_log_path, "(no output)")
    _append_exit_code_to_task_log(task_log_path, completed_process.returncode)

    resolution_status_text = f"Codex conflict resolution ({operation_kind_str}) -> exit {completed_process.returncode}"
    if combined_output_text:
        resolution_status_text += f"\n{combined_output_text}"
    _write_log_to_db(
        task_id_str,
        run_account_id_str,
        resolution_status_text,
        "OPTIMIZATION" if completed_process.returncode == 0 else "BUG",
    )
    return completed_process


def _finalize_completion_in_db(
    task_id_str: str, clear_worktree_path_bool: bool
) -> None:
    """Mark a task as done after a successful completion flow.

    Args:
        task_id_str: Task UUID
        clear_worktree_path_bool: Whether to clear the stored worktree path
    """
    from dsl.models.enums import TaskLifecycleStatus, WorkflowStage
    from dsl.models.task import Task
    from utils.helpers import utc_now_naive

    db_session = SessionLocal()
    try:
        task_obj = db_session.query(Task).filter(Task.id == task_id_str).first()
        if task_obj is None:
            return

        task_obj.workflow_stage = WorkflowStage.DONE
        task_obj.lifecycle_status = TaskLifecycleStatus.CLOSED
        task_obj.closed_at = utc_now_naive()
        if clear_worktree_path_bool:
            task_obj.worktree_path = None
        db_session.commit()
        logger.info(
            "Task %s... completion finalized (clear_worktree_path=%s)",
            task_id_str[:8],
            clear_worktree_path_bool,
        )
    except Exception as completion_finalize_error:
        logger.error(
            "Failed to finalize completion for task %s...: %s",
            task_id_str[:8],
            completion_finalize_error,
        )
        db_session.rollback()
    finally:
        db_session.close()


def _execute_git_completion_flow(
    *,
    task_id_str: str,
    run_account_id_str: str,
    task_title_str: str,
    task_summary_str: str | None,
    dev_log_text_list: list[str],
    worktree_path_str: str,
) -> GitCompletionExecutionResult:
    """Run the deterministic Git completion sequence for a task worktree.

    Args:
        task_id_str: Task UUID
        run_account_id_str: Run account UUID
        task_title_str: Task title used as fallback context
        task_summary_str: Task summary / requirement brief used for the commit subject
        dev_log_text_list: Recent task history for commit-message fallback and conflict resolution
        worktree_path_str: Task worktree path

    Returns:
        GitCompletionExecutionResult: Completion outcome metadata
    """
    from dsl.services.git_worktree_service import GitWorktreeService

    task_log_path = get_task_log_path(task_id_str)
    worktree_path = Path(worktree_path_str)
    output_line_list: list[str] = []
    _write_phase_log_header(
        task_log_path=task_log_path,
        task_id_str=task_id_str,
        phase_log_label_str="git-complete",
        overwrite_existing_log_bool=False,
    )

    try:
        repo_root_path = _resolve_primary_repo_root_from_worktree(worktree_path)
    except (subprocess.CalledProcessError, ValueError) as resolve_error:
        failure_reason_text = str(resolve_error)
        _append_text_to_task_log(task_log_path, failure_reason_text)
        return GitCompletionExecutionResult(
            merged_to_main=False,
            cleanup_succeeded=False,
            output_lines=[failure_reason_text],
            failure_reason_text=failure_reason_text,
        )

    branch_name_process = _run_logged_command(
        task_id_str=task_id_str,
        run_account_id_str=run_account_id_str,
        task_log_path=task_log_path,
        command_argument_list=["git", "symbolic-ref", "--short", "HEAD"],
        cwd_path=worktree_path,
        command_log_label_str="resolve-branch",
    )
    output_line_list.extend((branch_name_process.stdout or "").splitlines())
    if branch_name_process.returncode != 0:
        failure_reason_text = "无法解析当前任务 worktree 的分支名。"
        return GitCompletionExecutionResult(
            merged_to_main=False,
            cleanup_succeeded=False,
            output_lines=output_line_list,
            failure_reason_text=failure_reason_text,
        )

    feature_branch_name = (branch_name_process.stdout or "").strip()
    if not feature_branch_name:
        failure_reason_text = "当前任务 worktree 未处于命名分支，无法执行合并。"
        _append_text_to_task_log(task_log_path, failure_reason_text)
        return GitCompletionExecutionResult(
            merged_to_main=False,
            cleanup_succeeded=False,
            output_lines=output_line_list,
            failure_reason_text=failure_reason_text,
        )

    merge_target_worktree_path = _resolve_worktree_path_for_branch(
        repo_root_path, "main"
    )
    if merge_target_worktree_path is None:
        merge_target_worktree_path = repo_root_path

    repo_status_process = _run_logged_command(
        task_id_str=task_id_str,
        run_account_id_str=run_account_id_str,
        task_log_path=task_log_path,
        command_argument_list=["git", "status", "--short"],
        cwd_path=merge_target_worktree_path,
        command_log_label_str="repo-status",
    )
    output_line_list.extend((repo_status_process.stdout or "").splitlines())
    if repo_status_process.returncode != 0:
        failure_reason_text = "无法检查主仓库状态。"
        return GitCompletionExecutionResult(
            merged_to_main=False,
            cleanup_succeeded=False,
            output_lines=output_line_list,
            feature_branch_name=feature_branch_name,
            failure_reason_text=failure_reason_text,
        )

    if (repo_status_process.stdout or "").strip():
        failure_reason_text = (
            "承载 `main` 分支的工作区不是干净状态，无法自动执行 merge。"
        )
        _append_text_to_task_log(task_log_path, failure_reason_text)
        return GitCompletionExecutionResult(
            merged_to_main=False,
            cleanup_succeeded=False,
            output_lines=output_line_list,
            feature_branch_name=feature_branch_name,
            failure_reason_text=failure_reason_text,
        )

    merge_target_branch_process = _run_logged_command(
        task_id_str=task_id_str,
        run_account_id_str=run_account_id_str,
        task_log_path=task_log_path,
        command_argument_list=["git", "branch", "--show-current"],
        cwd_path=merge_target_worktree_path,
        command_log_label_str="main-worktree-branch",
    )
    output_line_list.extend((merge_target_branch_process.stdout or "").splitlines())
    if merge_target_branch_process.returncode != 0:
        failure_reason_text = "无法确认承载 `main` 分支的工作区当前分支。"
        return GitCompletionExecutionResult(
            merged_to_main=False,
            cleanup_succeeded=False,
            output_lines=output_line_list,
            feature_branch_name=feature_branch_name,
            failure_reason_text=failure_reason_text,
        )

    current_merge_target_branch_name = (
        merge_target_branch_process.stdout or ""
    ).strip()
    commit_message_str = _build_completion_commit_message(
        task_id_str=task_id_str,
        task_title_str=task_title_str,
        task_summary_str=task_summary_str,
        dev_log_text_list=dev_log_text_list,
    )
    command_plan = [
        ("worktree-status", ["git", "status", "--short"], worktree_path),
        ("git-add", ["git", "add", "."], worktree_path),
        ("git-commit", ["git", "commit", "-m", commit_message_str], worktree_path),
        ("git-rebase-main", ["git", "rebase", "main"], worktree_path),
    ]
    if current_merge_target_branch_name != "main":
        command_plan.append(
            ("checkout-main", ["git", "checkout", "main"], merge_target_worktree_path)
        )
    command_plan.append(
        (
            "merge-feature",
            ["git", "merge", feature_branch_name],
            merge_target_worktree_path,
        )
    )

    merge_completed_bool = False
    for command_log_label_str, command_argument_list, command_cwd_path in command_plan:
        completed_process = _run_logged_command(
            task_id_str=task_id_str,
            run_account_id_str=run_account_id_str,
            task_log_path=task_log_path,
            command_argument_list=command_argument_list,
            cwd_path=command_cwd_path,
            command_log_label_str=command_log_label_str,
        )
        output_line_list.extend((completed_process.stdout or "").splitlines())
        output_line_list.extend((completed_process.stderr or "").splitlines())
        if completed_process.returncode != 0:
            operation_kind_str = ""
            if command_log_label_str == "git-rebase-main" and _has_unmerged_conflicts(
                command_cwd_path
            ):
                operation_kind_str = "rebase"
            elif command_log_label_str == "merge-feature" and _has_unmerged_conflicts(
                command_cwd_path
            ):
                operation_kind_str = "merge"

            if operation_kind_str:
                codex_resolution_process = _run_logged_codex_conflict_resolution(
                    task_id_str=task_id_str,
                    run_account_id_str=run_account_id_str,
                    task_log_path=task_log_path,
                    task_title_str=task_title_str,
                    dev_log_text_list=dev_log_text_list,
                    repo_path=command_cwd_path,
                    operation_kind_str=operation_kind_str,
                )
                if codex_resolution_process is not None:
                    output_line_list.extend(
                        (codex_resolution_process.stdout or "").splitlines()
                    )
                    output_line_list.extend(
                        (codex_resolution_process.stderr or "").splitlines()
                    )
                if (
                    codex_resolution_process is not None
                    and codex_resolution_process.returncode == 0
                    and not _has_unmerged_conflicts(command_cwd_path)
                    and not _is_git_operation_still_in_progress(
                        command_cwd_path, operation_kind_str
                    )
                ):
                    if command_log_label_str == "merge-feature":
                        merge_completed_bool = True
                    continue

                failure_reason_text = (
                    f"{operation_kind_str} 冲突已触发 Codex 自动修复，但未能成功完成："
                    f"{shlex.join(command_argument_list)}"
                )
            else:
                failure_reason_text = f"命令失败：{shlex.join(command_argument_list)}"
            return GitCompletionExecutionResult(
                merged_to_main=merge_completed_bool,
                cleanup_succeeded=False,
                output_lines=output_line_list,
                feature_branch_name=feature_branch_name,
                failure_reason_text=failure_reason_text,
            )
        if command_log_label_str == "merge-feature":
            merge_completed_bool = True

    cleanup_script_path = GitWorktreeService.resolve_cleanup_script_path(repo_root_path)
    if cleanup_script_path is not None:
        cleanup_process = _run_logged_command(
            task_id_str=task_id_str,
            run_account_id_str=run_account_id_str,
            task_log_path=task_log_path,
            command_argument_list=[
                str(cleanup_script_path),
                feature_branch_name,
                "main",
                "--delete",
                "--worktree-path",
                worktree_path_str,
            ],
            cwd_path=merge_target_worktree_path,
            command_log_label_str="cleanup-script",
        )
        output_line_list.extend((cleanup_process.stdout or "").splitlines())
        output_line_list.extend((cleanup_process.stderr or "").splitlines())
        cleanup_succeeded_bool = cleanup_process.returncode == 0
        return GitCompletionExecutionResult(
            merged_to_main=True,
            cleanup_succeeded=cleanup_succeeded_bool,
            output_lines=output_line_list,
            feature_branch_name=feature_branch_name,
            failure_reason_text=(
                None
                if cleanup_succeeded_bool
                else "分支已合并到 main，但 repo-local cleanup 脚本执行失败。"
            ),
            worktree_removed=not worktree_path.exists(),
        )

    cleanup_command_plan = [
        (
            "remove-worktree",
            ["git", "worktree", "remove", worktree_path_str],
            merge_target_worktree_path,
        ),
        (
            "delete-branch",
            ["git", "branch", "-d", feature_branch_name],
            merge_target_worktree_path,
        ),
    ]
    for (
        command_log_label_str,
        command_argument_list,
        command_cwd_path,
    ) in cleanup_command_plan:
        completed_process = _run_logged_command(
            task_id_str=task_id_str,
            run_account_id_str=run_account_id_str,
            task_log_path=task_log_path,
            command_argument_list=command_argument_list,
            cwd_path=command_cwd_path,
            command_log_label_str=command_log_label_str,
        )
        output_line_list.extend((completed_process.stdout or "").splitlines())
        output_line_list.extend((completed_process.stderr or "").splitlines())
        if completed_process.returncode != 0:
            return GitCompletionExecutionResult(
                merged_to_main=True,
                cleanup_succeeded=False,
                output_lines=output_line_list,
                feature_branch_name=feature_branch_name,
                failure_reason_text="分支已合并到 main，但清理 task worktree 或分支失败。",
                worktree_removed=not worktree_path.exists(),
            )

    return GitCompletionExecutionResult(
        merged_to_main=True,
        cleanup_succeeded=True,
        output_lines=output_line_list,
        feature_branch_name=feature_branch_name,
        worktree_removed=not worktree_path.exists(),
    )


async def _create_codex_subprocess(
    codex_executable_path_str: str,
    codex_prompt_text_str: str,
    work_dir_path: Path,
) -> asyncio.subprocess.Process:
    """创建 Codex CLI 子进程.

    单独抽出该包装器，便于测试时稳定地替换 subprocess 行为，而不必直接 monkeypatch
    `asyncio.create_subprocess_exec`。

    Args:
        codex_executable_path_str: codex 可执行文件路径
        codex_prompt_text_str: 发给 codex exec 的 Prompt
        work_dir_path: codex 运行目录

    Returns:
        asyncio.subprocess.Process: 已启动的子进程对象
    """
    return await asyncio.create_subprocess_exec(
        codex_executable_path_str,
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        codex_prompt_text_str,
        cwd=str(work_dir_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )


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


def build_codex_prd_prompt(
    task_title: str,
    dev_log_text_list: list[str],
    task_id_str: str,
    worktree_path_str: str | None = None,
) -> str:
    """根据任务标题和历史日志构建 PRD 生成 Prompt.

    Args:
        task_title: 需求卡片标题
        dev_log_text_list: 该任务下已有日志的 text_content 列表（时间正序）
        task_id_str: 任务 UUID 字符串
        worktree_path_str: 预期的 git worktree 绝对路径（可选）

    Returns:
        str: 完整的 PRD 生成 Prompt 文本
    """
    prd_context_block_str = _build_recent_context_block(
        dev_log_text_list=dev_log_text_list,
        max_items_int=5,
        separator_str="\n---\n",
        empty_context_text_str="（无额外上下文，请根据需求标题判断范围）",
    )
    prd_output_relative_path_str = f"tasks/prd-{task_id_str[:8]}.md"

    if worktree_path_str:
        prd_worktree_instruction_block_str = f"""
## Git Worktree 说明
当前工作目录是 git worktree：`{worktree_path_str}`
- 直接在此目录中生成并写入 PRD 文件，无需切换到其他目录
"""
    else:
        prd_worktree_instruction_block_str = ""

    constructed_prd_prompt_text = f"""请为以下需求生成 PRD 文档。

## 原始需求标题
{task_title}

## 需求背景/上下文
{prd_context_block_str}
{prd_worktree_instruction_block_str}
## PRD 输出合同
1. 使用 `/prd` skill 生成 PRD，并将原始需求标题和上下文作为输入。
2. 在 PRD 顶部的元数据区域（位于主要章节之前），必须同时包含以下字段：
   - `原始需求标题`：保留用户提供的标题，不得省略。
   - `需求名称（AI 归纳）`：基于任务标题和上下文总结出的规范化需求名称，不得为空。
3. 不得只保留 `需求名称（AI 归纳）`；`原始需求标题` 必须与 AI 归纳名称同时出现。
4. 当上下文不足时，`需求名称（AI 归纳）` 必须回退到原始需求标题的规范化版本，输出值不能为空。
5. 其余 PRD 章节继续按 `/prd` skill 的规范完成。

## 文件输出要求
1. 生成完成后，将完整 PRD 内容保存到文件：`{prd_output_relative_path_str}`
2. 必须真正写入文件，不只是输出到终端。
3. 写完后输出文件路径。
"""

    return constructed_prd_prompt_text


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


def build_codex_completion_prompt(
    task_title: str,
    dev_log_text_list: list[str],
    worktree_path_str: str,
) -> str:
    """根据任务标题和历史日志构建完成阶段说明文本.

    当前完成阶段已改为后端直接执行 Git 命令，这个文本主要用于描述
    `Complete` 对应的精确命令顺序，便于测试与文档保持一致。

    Args:
        task_title: 需求卡片标题
        dev_log_text_list: 该任务下已有日志的 text_content 列表（时间正序）
        worktree_path_str: 任务对应的 git worktree 绝对路径

    Returns:
        str: 完整的完成阶段说明文本
    """
    completion_context_block_str = _build_recent_context_block(
        dev_log_text_list=dev_log_text_list,
        max_items_int=8,
        separator_str="\n\n---\n",
        empty_context_text_str="（暂无额外上下文，请根据需求标题和当前工作区改动完成收尾）",
    )

    constructed_completion_prompt_text = f"""你现在处于 Koda 工作流的完成阶段，需要在任务对应的 git worktree 中完成最终 Git 收尾动作。

## 需求标题
{task_title}

## 最近上下文（来自任务日志）
{completion_context_block_str}

## Git Worktree 说明
当前工作目录就是任务对应的 git worktree：`{worktree_path_str}`
- `git add .`、`git commit`、`git rebase main` 在当前 worktree 中执行
- merge 会复用当前持有 `main` 分支的工作区；只有找不到该工作区时才会尝试 `git checkout main`
- 不要创建新 worktree、不要 push

## 执行要求
1. 先查看当前 `git status`，确认本次任务的工作区状态。
2. 严格按顺序执行：`git add .`、`git commit -m "<task summary>"`、`git rebase main`，然后在承载 `main` 的工作区执行 `git merge <task branch>`。
3. `git commit` 的提交消息要使用任务摘要 / requirement brief，而不是直接复用任务标题。
4. 如果 `git rebase main` 发生冲突，自动调用 Codex 修复冲突并继续 rebase；如果 merge 发生冲突，也要自动调用 Codex 修复后继续。
5. 如果工作区没有可提交的变更、缺少 `main`、Codex 也无法修好冲突、或 merge 最终失败，停止继续操作，并明确输出失败原因。
6. merge 成功后，需要清理 task worktree 与本地任务分支；不要 push。
7. 最后简要输出：提交结果、rebase 结果、merge 结果、是否还需要人工处理。

请开始执行。"""

    return constructed_completion_prompt_text


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
            created_at=utc_now_naive(),
        )
        db_session.add(new_dev_log)
        db_session.commit()
    except Exception as db_write_error:
        logger.error(
            f"Failed to write DevLog for task {task_id_str[:8]}...: {db_write_error}"
        )
        db_session.rollback()
    finally:
        db_session.close()


def _advance_stage_in_db(task_id_str: str, next_stage_value: str) -> None:
    """更新任务 workflow_stage（同步，供 asyncio.to_thread 使用）.

    Args:
        task_id_str: 任务 ID
        next_stage_value: WorkflowStage 枚举值字符串
    """
    from dsl.models.enums import TaskLifecycleStatus, WorkflowStage
    from dsl.models.task import Task
    from utils.helpers import utc_now_naive

    db_session = SessionLocal()
    try:
        task_obj = db_session.query(Task).filter(Task.id == task_id_str).first()
        if task_obj:
            next_workflow_stage = WorkflowStage(next_stage_value)
            task_obj.workflow_stage = next_workflow_stage
            if next_workflow_stage == WorkflowStage.DONE:
                task_obj.lifecycle_status = TaskLifecycleStatus.CLOSED
                task_obj.closed_at = utc_now_naive()
            else:
                if task_obj.lifecycle_status in {
                    TaskLifecycleStatus.PENDING,
                    TaskLifecycleStatus.CLOSED,
                }:
                    task_obj.lifecycle_status = TaskLifecycleStatus.OPEN
                task_obj.closed_at = None
            db_session.commit()
            logger.info(
                f"Task {task_id_str[:8]}... stage advanced to {next_stage_value}"
            )
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
        missing_codex_log_text = (
            "❌ 未找到 codex 可执行文件，请确认 codex CLI 已安装并在 PATH 中。"
        )
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
        return CodexPhaseExecutionResult(
            success=False, output_lines=[], was_cancelled=True
        )

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
            codex_process_obj = await _create_codex_subprocess(
                codex_executable_path_str=codex_executable_path_str,
                codex_prompt_text_str=codex_prompt_text_str,
                work_dir_path=work_dir_path,
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

                elapsed_seconds_float = (
                    asyncio.get_running_loop().time() - last_flush_time_float
                )
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
                    logger.debug(
                        f"[{phase_log_label_str}:{task_id_str[:8]}] {decoded_stdout_line_str}"
                    )
                    _append_text_to_task_log(task_log_path, decoded_stdout_line_str)
                await flush_pending_output_lines()

            phase_return_code_int = await codex_process_obj.wait()
            await flush_pending_output_lines(force=True)
            _append_exit_code_to_task_log(task_log_path, phase_return_code_int)

            if phase_return_code_int == 0 and not _output_contains_interruption(
                aggregated_output_line_list
            ):
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
                return CodexPhaseExecutionResult(
                    success=False, output_lines=[], was_cancelled=True
                )

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
    prd_prompt_text_str = build_codex_prd_prompt(
        task_title=task_title_str,
        dev_log_text_list=dev_log_text_list,
        task_id_str=task_id_str,
        worktree_path_str=worktree_path_str,
    )

    task_prd_file_path = work_dir_path / "tasks" / f"prd-{task_id_str[:8]}.md"
    if task_prd_file_path.exists():
        try:
            task_prd_file_path.unlink()
            logger.info(f"Removed old PRD file: {task_prd_file_path}")
        except OSError as cleanup_error:
            logger.warning(
                f"Could not remove old PRD file {task_prd_file_path}: {cleanup_error}"
            )

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
    await asyncio.to_thread(
        _advance_stage_in_db, task_id_str, "prd_waiting_confirmation"
    )
    logger.info(f"Task {task_id_str[:8]}... PRD generated → prd_waiting_confirmation")

    # 发送邮件通知：PRD 已生成，等待用户确认
    try:
        from dsl.services.email_service import send_prd_ready_notification

        await asyncio.to_thread(
            send_prd_ready_notification, task_id_str, task_title_str
        )
    except Exception as email_error:
        logger.warning(
            f"Failed to send PRD ready email for task {task_id_str[:8]}...: {email_error}"
        )


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

    self_review_status_str = _extract_self_review_status(
        review_phase_result.output_lines
    )
    self_review_summary_str = _extract_self_review_summary(
        review_phase_result.output_lines
    )

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

        # 发送邮件通知：AI 自检发现阻塞性问题
        try:
            from dsl.services.email_service import send_task_failed_notification

            await asyncio.to_thread(
                send_task_failed_notification,
                task_id_str,
                task_title_str,
                self_review_summary_str or "AI 自检发现阻塞性问题",
            )
        except Exception as email_error:
            logger.warning(
                f"Failed to send changes_requested email for task {task_id_str[:8]}...: {email_error}"
            )
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
    await asyncio.to_thread(
        _advance_stage_in_db, task_id_str, "self_review_in_progress"
    )
    await asyncio.to_thread(
        _write_log_to_db,
        task_id_str,
        run_account_id_str,
        "🔍 已进入 AI 自检阶段，开始执行代码评审。",
        "OPTIMIZATION",
    )
    logger.info(
        f"Task {task_id_str[:8]}... implementation completed, starting self review."
    )

    review_context_log_list = (
        dev_log_text_list + implementation_phase_result.output_lines
    )
    await run_codex_review(
        task_id_str=task_id_str,
        run_account_id_str=run_account_id_str,
        task_title_str=task_title_str,
        dev_log_text_list=review_context_log_list,
        work_dir_path=work_dir_path,
        worktree_path_str=worktree_path_str,
    )


async def run_codex_completion(
    task_id_str: str,
    run_account_id_str: str,
    task_title_str: str,
    task_summary_str: str | None,
    dev_log_text_list: list[str],
    work_dir_path: Path,
    worktree_path_str: str,
) -> None:
    """在任务 worktree 中执行确定性的 Git 收尾与合并动作.

    完成阶段会在后台按顺序执行：
    `git add .` -> `git commit -m "<task summary>"` -> `git rebase main`
    -> 复用承载 `main` 的工作区执行 `git merge <task branch>` -> 清理 worktree/分支。
    若 `git rebase main` 发生冲突，会自动调用 Codex 修复冲突并继续 rebase。
    若合并成功，任务自动推进到 `done`；若在合并前失败，任务回退到 `changes_requested`。

    Args:
        task_id_str: 任务 UUID 字符串
        run_account_id_str: 运行账户 UUID 字符串
        task_title_str: 任务标题，用于补充上下文
        task_summary_str: 任务摘要 / requirement brief，用于 commit message
        dev_log_text_list: 历史日志文本列表，用于 commit message 回退和冲突修复上下文
        work_dir_path: 保留参数；当前应为任务 worktree
        worktree_path_str: 任务对应的 git worktree 绝对路径
    """
    del work_dir_path

    _running_background_task_ids.add(task_id_str)
    try:
        await asyncio.to_thread(
            _write_log_to_db,
            task_id_str,
            run_account_id_str,
            "🚀 已收到完成请求，Koda 正在执行：`git add .` -> `git commit` -> `git rebase main`。若 rebase 冲突，会自动调用 Codex 修复；随后会在承载 `main` 的工作区完成 merge 与清理。",
            "OPTIMIZATION",
        )

        completion_result = await asyncio.to_thread(
            _execute_git_completion_flow,
            task_id_str=task_id_str,
            run_account_id_str=run_account_id_str,
            task_title_str=task_title_str,
            task_summary_str=task_summary_str,
            dev_log_text_list=dev_log_text_list,
            worktree_path_str=worktree_path_str,
        )

        if not completion_result.merged_to_main:
            failure_reason_text = completion_result.failure_reason_text or (
                "Git 收尾在合并到 main 之前失败。"
            )
            await asyncio.to_thread(
                _write_log_to_db,
                task_id_str,
                run_account_id_str,
                "❌ Koda 未能完成分支收尾与合并："
                f"{failure_reason_text}\n"
                "任务已回退至：待修改（changes_requested）。",
                "BUG",
            )
            await asyncio.to_thread(
                _advance_stage_in_db, task_id_str, "changes_requested"
            )
            return

        if completion_result.cleanup_succeeded:
            await asyncio.to_thread(
                _write_log_to_db,
                task_id_str,
                run_account_id_str,
                "✅ Koda 已完成分支收尾并合并到 `main`，task worktree 与分支也已清理。任务已标记为完成。",
                "FIXED",
            )
            await asyncio.to_thread(_finalize_completion_in_db, task_id_str, True)
            logger.info(
                f"Task {task_id_str[:8]}... completion flow merged and cleaned up."
            )
            return

        cleanup_warning_text = completion_result.failure_reason_text or (
            "分支已合并到 main，但 worktree 清理未完成。"
        )
        await asyncio.to_thread(
            _write_log_to_db,
            task_id_str,
            run_account_id_str,
            "⚠️ Koda 已把任务分支合并到 `main`，但自动清理没有完全成功："
            f"{cleanup_warning_text}\n"
            "任务仍会标记为完成，请按日志提示手动处理残留 worktree/branch。",
            "BUG",
        )
        await asyncio.to_thread(
            _finalize_completion_in_db,
            task_id_str,
            completion_result.worktree_removed,
        )
        logger.info(
            "Task %s... completion flow merged successfully but cleanup needs attention.",
            task_id_str[:8],
        )
    finally:
        _running_background_task_ids.discard(task_id_str)
