"""Codex 执行器服务模块.

负责构建任务 Prompt、以非交互方式调用 codex exec CLI，
并将执行过程的 stdout/stderr 实时写入 DevLog 时间线.
"""

import asyncio
import shutil
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

    from datetime import datetime as _dt

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

    prd_prompt = f"""你是一个经验丰富的技术产品经理，请为以下需求生成一份完整的技术 PRD 文档。
{worktree_note}

## 需求标题
{task_title_str}

## 需求背景/上下文
{prd_context_block}

## PRD 生成规范（必须严格遵守）

### Step 1: 分析项目结构
先扫描当前代码库，了解技术栈、目录结构、代码风格。

### Step 2: 生成 PRD 文档，包含以下章节（Markdown 格式）

1. **Introduction & Goals** - 简述需求目标
2. **Implementation Guide（技术方案）**
   - **2.1 Change Matrix（必须）**: 表格，列：Change Target / Current State / Target State / How to Modify / Affected Files
   - **2.2 Flow Diagram（必须）**: Mermaid flowchart 图
   - **2.3 Low-Fidelity Prototype（必须）**: ASCII wireframe 或 Mermaid 布局图
   - **2.4 ER Diagram（条件必须）**: 涉及数据模型变更时包含 Mermaid erDiagram
3. **Definition of Done** - 验收标准清单
4. **User Stories** - 格式：US-001 title / Description / Acceptance Criteria
5. **Functional Requirements** - FR-1, FR-2... 编号列表
6. **Non-Goals** - 明确不在范围内的内容

### Step 3: 保存文件
将生成的 PRD 保存到：
`tasks/{{当前时间 YYYYMMDD-HHMMSS}}-prd-{{需求名称 kebab-case}}.md`

**重要**：必须真正写入文件，不只是输出到终端。写完后输出文件路径。

请开始执行。"""

    codex_process: asyncio.subprocess.Process | None = None
    task_log_path = get_task_log_path(task_id_str)
    try:
        # 清空/创建日志文件，写入标题行
        task_log_path.write_text(
            f"=== Koda codex-prd | task {task_id_str[:8]} | {datetime.utcnow().isoformat()} ===\n",
            encoding="utf-8",
        )

        codex_process = await asyncio.create_subprocess_exec(
            codex_executable_path,
            "exec",
            prd_prompt,
            cwd=str(work_dir_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

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

        assert codex_process.stdout is not None
        async for raw_line in codex_process.stdout:
            decoded = raw_line.decode("utf-8", errors="replace").rstrip()
            if decoded:
                pending_lines.append(decoded)
                logger.debug(f"[codex-prd:{task_id_str[:8]}] {decoded}")
                # 同步写入实时日志文件（追加）
                with task_log_path.open("a", encoding="utf-8") as log_file_handle:
                    log_file_handle.write(decoded + "\n")
            await flush_prd()

        return_code_int = await codex_process.wait()
        await flush_prd(force=True)
        # 写入结束标记
        with task_log_path.open("a", encoding="utf-8") as log_file_handle:
            log_file_handle.write(f"\n=== exit code: {return_code_int} ===\n")

        if return_code_int == 0:
            await asyncio.to_thread(
                _write_log_to_db,
                task_id_str,
                run_account_id_str,
                "✅ PRD 已生成，请确认后点击「开始执行」触发 AI 编码。",
                "FIXED",
            )
            await asyncio.to_thread(_advance_stage_in_db, task_id_str, "prd_waiting_confirmation")
            logger.info(f"Task {task_id_str[:8]}... PRD generated → prd_waiting_confirmation")
        else:
            await asyncio.to_thread(
                _write_log_to_db,
                task_id_str,
                run_account_id_str,
                f"❌ PRD 生成失败（exit {return_code_int}）。",
                "BUG",
            )
            await asyncio.to_thread(_advance_stage_in_db, task_id_str, "changes_requested")

    except Exception as err:
        logger.exception(f"run_codex_prd unexpected error for {task_id_str[:8]}...")
        await asyncio.to_thread(
            _write_log_to_db, task_id_str, run_account_id_str,
            f"❌ PRD 生成过程中发生错误：{err}", "BUG"
        )
        await asyncio.to_thread(_advance_stage_in_db, task_id_str, "changes_requested")
    finally:
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

    codex_process: asyncio.subprocess.Process | None = None
    task_log_path = get_task_log_path(task_id_str)

    try:
        # 清空/创建日志文件，写入标题行
        task_log_path.write_text(
            f"=== Koda codex-exec | task {task_id_str[:8]} | {datetime.utcnow().isoformat()} ===\n",
            encoding="utf-8",
        )

        codex_process = await asyncio.create_subprocess_exec(
            codex_executable_path,
            "exec",
            constructed_codex_prompt,
            cwd=str(work_dir_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # 合并 stderr 到 stdout
        )

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

        # 逐行读取 codex 输出，每行都追加到 pending，定期 flush
        assert codex_process.stdout is not None
        async for raw_stdout_line in codex_process.stdout:
            decoded_line_str = raw_stdout_line.decode("utf-8", errors="replace").rstrip()
            if decoded_line_str:
                pending_lines.append(decoded_line_str)
                logger.debug(f"[codex:{task_id_str[:8]}] {decoded_line_str}")
                # 同步写入实时日志文件（追加）
                with task_log_path.open("a", encoding="utf-8") as log_file_handle:
                    log_file_handle.write(decoded_line_str + "\n")
            await flush_pending()

        # 等待进程退出
        return_code_int = await codex_process.wait()

        # 写入剩余行
        await flush_pending(force=True)
        # 写入结束标记
        with task_log_path.open("a", encoding="utf-8") as log_file_handle:
            log_file_handle.write(f"\n=== exit code: {return_code_int} ===\n")

        if return_code_int == 0:
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
            logger.info(f"Task {task_id_str[:8]}... codex exec succeeded.")
        else:
            failure_log_text = (
                f"❌ codex exec 以非零状态退出（exit {return_code_int}）。\n"
                "工作流阶段回退至：修改请求（changes_requested）。"
            )
            await asyncio.to_thread(
                _write_log_to_db,
                task_id_str,
                run_account_id_str,
                failure_log_text,
                "BUG",
            )
            await asyncio.to_thread(
                _advance_stage_in_db, task_id_str, "changes_requested"
            )
            logger.warning(
                f"Task {task_id_str[:8]}... codex exec failed with exit code {return_code_int}."
            )

    except FileNotFoundError:
        error_log_text = (
            f"❌ 无法启动 codex（路径：{codex_executable_path}）。\n"
            "请检查 codex CLI 是否正确安装。"
        )
        await asyncio.to_thread(
            _write_log_to_db, task_id_str, run_account_id_str, error_log_text, "BUG"
        )
        await asyncio.to_thread(_advance_stage_in_db, task_id_str, "changes_requested")

    except Exception as unexpected_error:
        error_log_text = f"❌ codex 执行过程中发生意外错误：{unexpected_error}"
        logger.exception(f"Unexpected error in run_codex_task for {task_id_str[:8]}...")
        await asyncio.to_thread(
            _write_log_to_db, task_id_str, run_account_id_str, error_log_text, "BUG"
        )
        await asyncio.to_thread(_advance_stage_in_db, task_id_str, "changes_requested")

    finally:
        if codex_process and codex_process.returncode is None:
            try:
                codex_process.kill()
            except ProcessLookupError:
                pass
