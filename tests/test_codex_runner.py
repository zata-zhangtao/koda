"""Tests for Codex runner phase orchestration."""

from __future__ import annotations

import asyncio
import subprocess
from datetime import timedelta
from pathlib import Path

import dsl.models  # noqa: F401
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dsl.models.dev_log import DevLog
from dsl.models.enums import TaskLifecycleStatus, WorkflowStage
from dsl.models.run_account import RunAccount
from dsl.models.task import Task
from dsl.services import codex_runner, email_service
from dsl.services.runners.claude_cli_runner import CLAUDE_CLI_RUNNER
from utils.database import Base
from utils.helpers import utc_now_naive


class FakeCodexStdout:
    """Async stdout stream for fake Codex subprocesses."""

    def __init__(self, output_line_list: list[str]) -> None:
        """Store encoded stdout lines for async iteration.

        Args:
            output_line_list: Plain-text output lines to emit
        """
        self._remaining_output_line_bytes_list = [
            f"{output_line_str}\n".encode("utf-8")
            for output_line_str in output_line_list
        ]

    def __aiter__(self) -> "FakeCodexStdout":
        """Return the async iterator instance."""
        return self

    async def __anext__(self) -> bytes:
        """Yield one encoded output line at a time.

        Returns:
            bytes: The next stdout line

        Raises:
            StopAsyncIteration: When no more output remains
        """
        if not self._remaining_output_line_bytes_list:
            raise StopAsyncIteration
        return self._remaining_output_line_bytes_list.pop(0)


class FakeCodexProcess:
    """Minimal asyncio subprocess stub for Codex phase tests."""

    def __init__(
        self,
        output_line_list: list[str],
        planned_return_code_int: int = 0,
        pid_int: int = 1000,
        include_stdin_bool: bool = False,
    ) -> None:
        """Initialize the fake process state.

        Args:
            output_line_list: Stdout lines produced by the fake process
            planned_return_code_int: Exit code returned by wait()
            pid_int: Fake process ID
            include_stdin_bool: Whether to expose a writable stdin stub
        """
        self.stdout = FakeCodexStdout(output_line_list)
        self.stdin = FakeCodexStdin() if include_stdin_bool else None
        self.returncode: int | None = None
        self._planned_return_code_int = planned_return_code_int
        self.pid = pid_int

    async def wait(self) -> int:
        """Return the configured process exit code."""
        self.returncode = self._planned_return_code_int
        return self.returncode

    def kill(self) -> None:
        """Mark the fake process as killed."""
        self.returncode = -9


class FakeCodexStdin:
    """Async stdin stub for fake subprocesses."""

    def __init__(self) -> None:
        """Initialize writable buffer state."""
        self.written_bytes = b""
        self.closed = False
        self.wait_closed_called = False

    def write(self, data_bytes: bytes) -> None:
        """Append prompt bytes to the buffer.

        Args:
            data_bytes: Prompt bytes written by the caller.
        """
        self.written_bytes += data_bytes

    async def drain(self) -> None:
        """Simulate an asyncio drain call."""

    def close(self) -> None:
        """Mark the stdin pipe as closed."""
        self.closed = True

    async def wait_closed(self) -> None:
        """Record that wait_closed was awaited."""
        self.wait_closed_called = True


def build_completed_process(
    *,
    command_argument_list: list[str],
    return_code_int: int,
    stdout_text: str = "",
    stderr_text: str = "",
) -> subprocess.CompletedProcess[str]:
    """Build a completed process object for command-level tests.

    Args:
        command_argument_list: Command arguments represented by the result
        return_code_int: Exit code to expose
        stdout_text: Stdout payload
        stderr_text: Stderr payload

    Returns:
        subprocess.CompletedProcess[str]: Completed process stub
    """
    return subprocess.CompletedProcess(
        args=command_argument_list,
        returncode=return_code_int,
        stdout=stdout_text,
        stderr=stderr_text,
    )


def _build_db_session_factory():
    """Build an in-memory session factory for persistence-oriented runner tests."""
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    return sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )


def test_finalize_completion_in_db_refreshes_stage_updated_at() -> None:
    """The completion finalizer should stamp DONE as a fresh stage window."""
    session_factory = _build_db_session_factory()
    seed_session = session_factory()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        seed_session.add(run_account_obj)
        seed_session.commit()

        original_stage_updated_at = utc_now_naive() - timedelta(minutes=45)
        task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Finalize completion timestamp",
            workflow_stage=WorkflowStage.PR_PREPARING,
            lifecycle_status=TaskLifecycleStatus.OPEN,
            stage_updated_at=original_stage_updated_at,
            worktree_path="/tmp/repo-wt-12345678",
        )
        seed_session.add(task_obj)
        seed_session.commit()
        task_id_str = task_obj.id

        original_session_local = codex_runner.SessionLocal
        codex_runner.SessionLocal = session_factory
        try:
            codex_runner._finalize_completion_in_db(
                task_id_str=task_id_str,
                clear_worktree_path_bool=True,
            )
        finally:
            codex_runner.SessionLocal = original_session_local

        verification_session = session_factory()
        try:
            reloaded_task_obj = (
                verification_session.query(Task).filter(Task.id == task_id_str).first()
            )
            assert reloaded_task_obj is not None
            assert reloaded_task_obj.workflow_stage == WorkflowStage.DONE
            assert reloaded_task_obj.lifecycle_status == TaskLifecycleStatus.CLOSED
            assert reloaded_task_obj.stage_updated_at is not None
            assert reloaded_task_obj.stage_updated_at > original_stage_updated_at
            assert reloaded_task_obj.closed_at == reloaded_task_obj.stage_updated_at
            assert reloaded_task_obj.worktree_path is None
        finally:
            verification_session.close()
    finally:
        seed_session.close()


def test_write_log_to_db_refreshes_last_ai_activity_at() -> None:
    """Automated log writes should also refresh the task-level AI activity timestamp."""
    session_factory = _build_db_session_factory()
    seed_session = session_factory()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        seed_session.add(run_account_obj)
        seed_session.commit()

        task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Refresh AI activity",
            workflow_stage=WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
            lifecycle_status=TaskLifecycleStatus.OPEN,
        )
        seed_session.add(task_obj)
        seed_session.commit()
        task_id_str = task_obj.id
        run_account_id_str = run_account_obj.id

        original_session_local = codex_runner.SessionLocal
        codex_runner.SessionLocal = session_factory
        try:
            codex_runner._write_log_to_db(
                task_id_str=task_id_str,
                run_account_id_str=run_account_id_str,
                text_content_str="Codex emitted a new line.",
            )
        finally:
            codex_runner.SessionLocal = original_session_local

        verification_session = session_factory()
        try:
            reloaded_task_obj = (
                verification_session.query(Task).filter(Task.id == task_id_str).first()
            )
            persisted_dev_log_obj = (
                verification_session.query(DevLog)
                .filter(DevLog.task_id == task_id_str)
                .first()
            )

            assert reloaded_task_obj is not None
            assert persisted_dev_log_obj is not None
            assert reloaded_task_obj.last_ai_activity_at is not None
            assert (
                reloaded_task_obj.last_ai_activity_at
                == persisted_dev_log_obj.created_at
            )
            assert persisted_dev_log_obj.text_content == "Codex emitted a new line."
        finally:
            verification_session.close()
    finally:
        seed_session.close()


def test_write_automation_transcript_chunk_to_db_persists_continuity_fields() -> None:
    """Transcript chunk writes should persist automation continuity metadata."""
    session_factory = _build_db_session_factory()
    seed_session = session_factory()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        seed_session.add(run_account_obj)
        seed_session.commit()

        task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Persist transcript metadata",
            workflow_stage=WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
            lifecycle_status=TaskLifecycleStatus.OPEN,
        )
        seed_session.add(task_obj)
        seed_session.commit()
        task_id_str = task_obj.id
        run_account_id_str = run_account_obj.id

        original_session_local = codex_runner.SessionLocal
        codex_runner.SessionLocal = session_factory
        try:
            codex_runner._write_automation_transcript_chunk_to_db(
                task_id_str=task_id_str,
                run_account_id_str=run_account_id_str,
                text_content_str="first line\nsecond line",
                automation_session_id_str="session-123",
                automation_sequence_index_int=2,
                automation_phase_label_str="codex-exec",
                automation_runner_kind_str="codex",
            )
        finally:
            codex_runner.SessionLocal = original_session_local

        verification_session = session_factory()
        try:
            persisted_dev_log_obj = (
                verification_session.query(DevLog)
                .filter(DevLog.task_id == task_id_str)
                .first()
            )
            assert persisted_dev_log_obj is not None
            assert persisted_dev_log_obj.text_content == "first line\nsecond line"
            assert persisted_dev_log_obj.automation_session_id == "session-123"
            assert persisted_dev_log_obj.automation_sequence_index == 2
            assert persisted_dev_log_obj.automation_phase_label == "codex-exec"
            assert persisted_dev_log_obj.automation_runner_kind == "codex"
        finally:
            verification_session.close()
    finally:
        seed_session.close()


def test_build_codex_prompt_requires_user_confirmation_before_commit() -> None:
    """Implementation prompt should forbid default commits before user confirmation."""
    implementation_prompt_text = codex_runner.build_codex_prompt(
        task_title="Implement the feature",
        dev_log_text_list=["Need a safe implementation flow."],
        worktree_path_str="/tmp/project-wt-12345678",
    )

    assert "不要默认执行 `git commit`" in implementation_prompt_text
    assert "提交动作必须等待用户确认" in implementation_prompt_text
    assert "git add -A" not in implementation_prompt_text


def test_build_codex_completion_prompt_describes_full_git_sequence() -> None:
    """Completion text should describe commit, rebase, merge, and cleanup order."""
    completion_prompt_text = codex_runner.build_codex_completion_prompt(
        task_title="Finalize branch",
        dev_log_text_list=["Implementation already passed review."],
        worktree_path_str="/tmp/project-wt-12345678",
    )

    assert "`git add .`" in completion_prompt_text
    assert "承载 `main` 的工作区" in completion_prompt_text
    assert "`git merge <task branch>`" in completion_prompt_text
    assert "AI summary" in completion_prompt_text
    assert "requirement brief" in completion_prompt_text
    assert "不要 push" in completion_prompt_text


def test_output_contains_interruption_ignores_negated_interrupted_phrase() -> None:
    """Interruption detection should not match negated interruption phrases."""
    assert (
        codex_runner._output_contains_interruption(
            ["All checks passed, execution was not interrupted."],
            CLAUDE_CLI_RUNNER.interruption_marker_tuple,
        )
        is False
    )


def test_output_contains_interruption_matches_positive_phrase() -> None:
    """Interruption detection should still match explicit interruption phrases."""
    assert codex_runner._output_contains_interruption(
        ["Execution interrupted by user cancellation."],
        CLAUDE_CLI_RUNNER.interruption_marker_tuple,
    )


def test_build_completion_commit_message_prefers_resolved_commit_information() -> None:
    """Commit subject generation should use resolved commit information first."""
    commit_message_text = codex_runner._build_completion_commit_message(
        task_id_str="12345678-commit-case",
        task_title_str="Fallback task title",
        commit_information_text_str="  Refine completion commit source. \nMore detail.",
    )

    assert commit_message_text == "Refine completion commit source"


def test_build_completion_commit_message_falls_back_to_task_title() -> None:
    """Blank commit information should fall back to the task title."""
    commit_message_text = codex_runner._build_completion_commit_message(
        task_id_str="12345678-title-fallback",
        task_title_str="Fallback task title",
        commit_information_text_str="   \n   ",
    )

    assert commit_message_text == "Fallback task title"


def test_build_codex_prd_prompt_requires_ai_requirement_name_contract() -> None:
    """PRD prompt should require semantic naming plus structured pending-question rules."""
    prd_prompt_text = codex_runner.build_codex_prd_prompt(
        task_title="I hope the generated PRD simultaneously includes the name of the requirement",
        dev_log_text_list=["Need the output contract captured in tests and docs."],
        task_id_str="cf2b9461-1234-5678-9012-abcdefabcdef",
        worktree_path_str="/tmp/project-wt-cf2b9461",
    )

    assert "原始需求标题" in prd_prompt_text
    assert "需求名称（AI 归纳）" in prd_prompt_text
    assert "位于主要章节之前" in prd_prompt_text
    assert "回退到原始需求标题的规范化版本" in prd_prompt_text
    assert "不得为空" in prd_prompt_text
    assert "`tasks/prd-cf2b9461-<requirement-slug>.md`" in prd_prompt_text
    assert "兼容中文输入" in prd_prompt_text
    assert "不得使用随机字符串" in prd_prompt_text
    assert "结束前必须自行修正" in prd_prompt_text
    assert "tasks/prd-cf2b9461-修改-prd-命令.md" in prd_prompt_text
    assert "必须真正写入文件" in prd_prompt_text
    assert "Attached local files:" in prd_prompt_text
    assert "`## 0. 待确认问题（结构化）`" in prd_prompt_text
    assert "fenced `json` code block" in prd_prompt_text
    assert "`pending_questions`" in prd_prompt_text
    assert "`recommended_option_key`" in prd_prompt_text
    assert "不要伪造空问题" in prd_prompt_text


def test_run_codex_prd_removes_all_existing_task_prd_files(tmp_path: Path) -> None:
    """PRD regeneration should clear both legacy and semantic task PRD files first."""
    tasks_directory_path = tmp_path / "tasks"
    tasks_directory_path.mkdir()

    legacy_prd_file_path = tasks_directory_path / "prd-cf2b9461.md"
    semantic_prd_file_path = tasks_directory_path / "prd-cf2b9461-refined-scope.md"
    legacy_prd_file_path.write_text("legacy", encoding="utf-8")
    semantic_prd_file_path.write_text("semantic", encoding="utf-8")

    async def fake_run_codex_phase(
        **_: object,
    ) -> codex_runner.CodexPhaseExecutionResult:
        generated_prd_file_path = tasks_directory_path / "prd-cf2b9461-refreshed-prd.md"
        generated_prd_file_path.write_text(
            "# PRD\n\n**需求名称（AI 归纳）**：Refreshed PRD\n",
            encoding="utf-8",
        )
        return codex_runner.CodexPhaseExecutionResult(
            success=True,
            output_lines=["PRD generated"],
        )

    original_run_codex_phase = codex_runner._run_codex_phase
    original_write_log_to_db = codex_runner._write_log_to_db
    original_advance_stage_in_db = codex_runner._advance_stage_in_db
    original_send_prd_ready_notification = email_service.send_prd_ready_notification

    try:
        codex_runner._run_codex_phase = fake_run_codex_phase
        codex_runner._write_log_to_db = lambda *args, **kwargs: None
        codex_runner._advance_stage_in_db = lambda *args, **kwargs: None
        email_service.send_prd_ready_notification = lambda *args, **kwargs: True

        asyncio.run(
            codex_runner.run_codex_prd(
                task_id_str="cf2b9461-1234-5678-9012-abcdefabcdef",
                run_account_id_str="run-account-1",
                task_title_str="Regenerate PRD",
                dev_log_text_list=["Need a refreshed PRD."],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path),
                auto_confirm_prd_and_execute_bool=False,
            )
        )
    finally:
        codex_runner._run_codex_phase = original_run_codex_phase
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._advance_stage_in_db = original_advance_stage_in_db
        email_service.send_prd_ready_notification = original_send_prd_ready_notification
        codex_runner._running_codex_processes.clear()
        codex_runner._running_background_task_ids.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert not legacy_prd_file_path.exists()
    assert not semantic_prd_file_path.exists()
    assert (tasks_directory_path / "prd-cf2b9461-refreshed-prd.md").exists()


def test_run_codex_prd_auto_corrects_legacy_file_name_after_success(
    tmp_path: Path,
) -> None:
    """Successful PRD generation should rename legacy output files to semantic names."""
    tasks_directory_path = tmp_path / "tasks"
    tasks_directory_path.mkdir()
    recorded_log_entry_list: list[tuple[str, str]] = []

    async def fake_run_codex_phase(
        **_: object,
    ) -> codex_runner.CodexPhaseExecutionResult:
        legacy_prd_file_path = tasks_directory_path / "prd-cf2b9461.md"
        legacy_prd_file_path.write_text(
            (
                "# PRD\n"
                "**原始需求标题**：修改 prd 命令\n"
                "**需求名称（AI 归纳）**：c3e023d8\n"
            ),
            encoding="utf-8",
        )
        return codex_runner.CodexPhaseExecutionResult(
            success=True,
            output_lines=["PRD generated"],
        )

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    original_run_codex_phase = codex_runner._run_codex_phase
    original_write_log_to_db = codex_runner._write_log_to_db
    original_advance_stage_in_db = codex_runner._advance_stage_in_db
    original_send_prd_ready_notification = email_service.send_prd_ready_notification

    try:
        codex_runner._run_codex_phase = fake_run_codex_phase
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._advance_stage_in_db = lambda *args, **kwargs: None
        email_service.send_prd_ready_notification = lambda *args, **kwargs: True

        asyncio.run(
            codex_runner.run_codex_prd(
                task_id_str="cf2b9461-1234-5678-9012-abcdefabcdef",
                run_account_id_str="run-account-1",
                task_title_str="修改 prd 命令",
                dev_log_text_list=["Need a refreshed PRD."],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path),
                auto_confirm_prd_and_execute_bool=False,
            )
        )
    finally:
        codex_runner._run_codex_phase = original_run_codex_phase
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._advance_stage_in_db = original_advance_stage_in_db
        email_service.send_prd_ready_notification = original_send_prd_ready_notification
        codex_runner._running_codex_processes.clear()
        codex_runner._running_background_task_ids.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert not (tasks_directory_path / "prd-cf2b9461.md").exists()
    assert (tasks_directory_path / "prd-cf2b9461-修改-prd-命令.md").exists()
    assert any("自动修正" in log_text for log_text, _ in recorded_log_entry_list)


def test_run_codex_prd_auto_corrects_short_random_suffix_after_success(
    tmp_path: Path,
) -> None:
    """Successful PRD generation should repair short random suffix filenames."""
    tasks_directory_path = tmp_path / "tasks"
    tasks_directory_path.mkdir()
    recorded_log_entry_list: list[tuple[str, str]] = []

    async def fake_run_codex_phase(
        **_: object,
    ) -> codex_runner.CodexPhaseExecutionResult:
        invalid_random_prd_file_path = tasks_directory_path / "prd-cf2b9461-k9m2qz.md"
        invalid_random_prd_file_path.write_text(
            (
                "# PRD\n"
                "**原始需求标题**：修改 prd 命令\n"
                "**需求名称（AI 归纳）**：k9m2qz\n"
            ),
            encoding="utf-8",
        )
        return codex_runner.CodexPhaseExecutionResult(
            success=True,
            output_lines=["PRD generated"],
        )

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    original_run_codex_phase = codex_runner._run_codex_phase
    original_write_log_to_db = codex_runner._write_log_to_db
    original_advance_stage_in_db = codex_runner._advance_stage_in_db
    original_send_prd_ready_notification = email_service.send_prd_ready_notification

    try:
        codex_runner._run_codex_phase = fake_run_codex_phase
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._advance_stage_in_db = lambda *args, **kwargs: None
        email_service.send_prd_ready_notification = lambda *args, **kwargs: True

        asyncio.run(
            codex_runner.run_codex_prd(
                task_id_str="cf2b9461-1234-5678-9012-abcdefabcdef",
                run_account_id_str="run-account-1",
                task_title_str="修改 prd 命令",
                dev_log_text_list=["Need a refreshed PRD."],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path),
                auto_confirm_prd_and_execute_bool=False,
            )
        )
    finally:
        codex_runner._run_codex_phase = original_run_codex_phase
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._advance_stage_in_db = original_advance_stage_in_db
        email_service.send_prd_ready_notification = original_send_prd_ready_notification
        codex_runner._running_codex_processes.clear()
        codex_runner._running_background_task_ids.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert not (tasks_directory_path / "prd-cf2b9461-k9m2qz.md").exists()
    assert (tasks_directory_path / "prd-cf2b9461-修改-prd-命令.md").exists()
    assert any("自动修正" in log_text for log_text, _ in recorded_log_entry_list)


def test_run_codex_prd_does_not_reuse_stale_invalid_prd_file(
    tmp_path: Path,
) -> None:
    """A stale invalid PRD file must not satisfy a new successful-but-empty run."""
    tasks_directory_path = tmp_path / "tasks"
    tasks_directory_path.mkdir()
    stale_invalid_prd_file_path = tasks_directory_path / "prd-cf2b9461-k9m2qz.md"
    stale_invalid_prd_file_path.write_text("# PRD\n", encoding="utf-8")
    recorded_log_entry_list: list[tuple[str, str]] = []
    recorded_stage_value_list: list[str] = []
    recorded_failure_notification_list: list[tuple[str, str, str]] = []

    async def fake_run_codex_phase(
        **_: object,
    ) -> codex_runner.CodexPhaseExecutionResult:
        return codex_runner.CodexPhaseExecutionResult(
            success=True,
            output_lines=["PRD generated"],
        )

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    def fake_advance_stage(task_id_str: str, next_stage_value: str) -> None:
        recorded_stage_value_list.append(next_stage_value)

    def fake_send_task_failed_notification(
        task_id_str: str,
        task_title_str: str,
        failure_reason_str: str = "",
    ) -> bool:
        recorded_failure_notification_list.append(
            (task_id_str, task_title_str, failure_reason_str)
        )
        return True

    original_run_codex_phase = codex_runner._run_codex_phase
    original_write_log_to_db = codex_runner._write_log_to_db
    original_advance_stage_in_db = codex_runner._advance_stage_in_db
    original_send_task_failed_notification = email_service.send_task_failed_notification
    original_send_prd_ready_notification = email_service.send_prd_ready_notification

    try:
        codex_runner._run_codex_phase = fake_run_codex_phase
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._advance_stage_in_db = fake_advance_stage
        email_service.send_task_failed_notification = fake_send_task_failed_notification
        email_service.send_prd_ready_notification = lambda *args, **kwargs: True

        asyncio.run(
            codex_runner.run_codex_prd(
                task_id_str="cf2b9461-1234-5678-9012-abcdefabcdef",
                run_account_id_str="run-account-1",
                task_title_str="修改 prd 命令",
                dev_log_text_list=["Need a refreshed PRD."],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path),
                auto_confirm_prd_and_execute_bool=False,
            )
        )
    finally:
        codex_runner._run_codex_phase = original_run_codex_phase
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._advance_stage_in_db = original_advance_stage_in_db
        email_service.send_task_failed_notification = (
            original_send_task_failed_notification
        )
        email_service.send_prd_ready_notification = original_send_prd_ready_notification
        codex_runner._running_codex_processes.clear()
        codex_runner._running_background_task_ids.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert not stale_invalid_prd_file_path.exists()
    assert recorded_stage_value_list == ["changes_requested"]
    assert recorded_failure_notification_list
    assert any(
        "未产出满足命名合同" in log_text for log_text, _ in recorded_log_entry_list
    )


def test_run_codex_prd_sends_prd_ready_notification_in_manual_mode(
    tmp_path: Path,
) -> None:
    """Manual PRD mode should stop at confirmation and send ready notification."""
    tasks_directory_path = tmp_path / "tasks"
    tasks_directory_path.mkdir()
    recorded_stage_value_list: list[str] = []
    recorded_ready_notification_list: list[tuple[str, str]] = []

    async def fake_run_codex_phase(
        **_: object,
    ) -> codex_runner.CodexPhaseExecutionResult:
        generated_prd_file_path = tasks_directory_path / "prd-manual-p-manual-prd.md"
        generated_prd_file_path.write_text(
            "# PRD\n\n**需求名称（AI 归纳）**：Manual PRD\n",
            encoding="utf-8",
        )
        return codex_runner.CodexPhaseExecutionResult(
            success=True,
            output_lines=["PRD generated"],
        )

    def fake_advance_stage(task_id_str: str, next_stage_value: str) -> None:
        recorded_stage_value_list.append(next_stage_value)

    def fake_send_prd_ready_notification(task_id_str: str, task_title_str: str) -> bool:
        recorded_ready_notification_list.append((task_id_str, task_title_str))
        return True

    original_run_codex_phase = codex_runner._run_codex_phase
    original_write_log_to_db = codex_runner._write_log_to_db
    original_advance_stage_in_db = codex_runner._advance_stage_in_db
    original_send_prd_ready_notification = email_service.send_prd_ready_notification

    try:
        codex_runner._run_codex_phase = fake_run_codex_phase
        codex_runner._write_log_to_db = lambda *args, **kwargs: None
        codex_runner._advance_stage_in_db = fake_advance_stage
        email_service.send_prd_ready_notification = fake_send_prd_ready_notification

        asyncio.run(
            codex_runner.run_codex_prd(
                task_id_str="manual-prd-task-id",
                run_account_id_str="run-account-1",
                task_title_str="Manual PRD",
                dev_log_text_list=["Need manual confirmation."],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path),
                auto_confirm_prd_and_execute_bool=False,
            )
        )
    finally:
        codex_runner._run_codex_phase = original_run_codex_phase
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._advance_stage_in_db = original_advance_stage_in_db
        email_service.send_prd_ready_notification = original_send_prd_ready_notification
        codex_runner._running_codex_processes.clear()
        codex_runner._running_background_task_ids.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert recorded_stage_value_list == ["prd_waiting_confirmation"]
    assert recorded_ready_notification_list == [("manual-prd-task-id", "Manual PRD")]


def test_run_codex_prd_auto_mode_skips_confirmation_and_starts_execution(
    tmp_path: Path,
) -> None:
    """Auto PRD mode should skip confirmation and directly start implementation."""
    recorded_stage_value_list: list[str] = []
    recorded_log_entry_list: list[str] = []
    recorded_run_codex_task_kwargs_list: list[dict[str, object]] = []

    async def fake_run_codex_phase(
        **_: object,
    ) -> codex_runner.CodexPhaseExecutionResult:
        return codex_runner.CodexPhaseExecutionResult(
            success=True,
            output_lines=["PRD generated output line"],
        )

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        del task_id_str, run_account_id_str, state_tag_value
        recorded_log_entry_list.append(text_content_str)

    def fake_advance_stage(task_id_str: str, next_stage_value: str) -> None:
        del task_id_str
        recorded_stage_value_list.append(next_stage_value)

    async def fake_run_codex_task(**kwargs: object) -> None:
        recorded_run_codex_task_kwargs_list.append(kwargs)

    def fail_send_prd_ready_notification(*_: object, **__: object) -> bool:
        raise AssertionError("Auto mode should not send PRD ready notification.")

    original_run_codex_phase = codex_runner._run_codex_phase
    original_write_log_to_db = codex_runner._write_log_to_db
    original_advance_stage_in_db = codex_runner._advance_stage_in_db
    original_run_codex_task = codex_runner.run_codex_task
    original_send_prd_ready_notification = email_service.send_prd_ready_notification

    try:
        codex_runner._run_codex_phase = fake_run_codex_phase
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._advance_stage_in_db = fake_advance_stage
        codex_runner.run_codex_task = fake_run_codex_task
        email_service.send_prd_ready_notification = fail_send_prd_ready_notification

        asyncio.run(
            codex_runner.run_codex_prd(
                task_id_str="auto-prd-task-id",
                run_account_id_str="run-account-1",
                task_title_str="Auto PRD",
                dev_log_text_list=["Need auto execution."],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path),
                auto_confirm_prd_and_execute_bool=True,
            )
        )
    finally:
        codex_runner._run_codex_phase = original_run_codex_phase
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._advance_stage_in_db = original_advance_stage_in_db
        codex_runner.run_codex_task = original_run_codex_task
        email_service.send_prd_ready_notification = original_send_prd_ready_notification
        codex_runner._running_codex_processes.clear()
        codex_runner._running_background_task_ids.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert recorded_stage_value_list == ["implementation_in_progress"]
    assert any(
        "自动确认并执行" in log_entry_text for log_entry_text in recorded_log_entry_list
    )
    assert len(recorded_run_codex_task_kwargs_list) == 1
    assert recorded_run_codex_task_kwargs_list[0]["task_id_str"] == "auto-prd-task-id"
    assert recorded_run_codex_task_kwargs_list[0]["dev_log_text_list"] == [
        "Need auto execution.",
        "PRD generated output line",
    ]


def test_build_codex_review_fix_prompt_preserves_full_latest_blocker_list() -> None:
    """Review-fix prompt should keep the full current-round blocker list without markers."""
    review_fix_prompt_text = codex_runner.build_codex_review_fix_prompt(
        task_title="Implement review remediation loop",
        dev_log_text_list=["The first review found blocker-level issues."],
        review_output_lines=[
            "blocker-01: docs/architecture/system-design.md is still outdated.",
            "blocker-02: tests/test_codex_runner.py needs a loop regression.",
            "blocker-03: ensure the continue shortcut does not restart a parked review.",
            "blocker-04: keep the completion button hidden before review passes.",
            "blocker-05: preserve the review summary in DevLog output.",
            "blocker-06: update the self-review banner wording.",
            "blocker-07: stop polling once the review loop has passed.",
            "blocker-08: keep the worktree path instruction in the prompt.",
            "blocker-09: retain the requirement title in the fix scope.",
            "blocker-10: include the current-round index.",
            "blocker-11: remove structured markers from the findings payload.",
            "blocker-12: do not re-run unrelated implementation work.",
            "blocker-13: keep the failure-notification timing unchanged.",
            "blocker-14: ensure no blocker is truncated from the prompt.",
            "SELF_REVIEW_SUMMARY: sync docs and tests with the loop",
            "SELF_REVIEW_STATUS: CHANGES_REQUESTED",
        ],
        fix_round_index_int=1,
        max_fix_rounds_int=2,
        self_review_summary_str="sync docs and tests with the loop",
        worktree_path_str="/tmp/project-wt-12345678",
    )

    assert "只修复最近一轮 review 明确指出的阻塞性问题" in review_fix_prompt_text
    assert "不要重新大范围发散实现" in review_fix_prompt_text
    assert "sync docs and tests with the loop" in review_fix_prompt_text
    assert (
        "blocker-01: docs/architecture/system-design.md is still outdated."
        in review_fix_prompt_text
    )
    assert (
        "blocker-14: ensure no blocker is truncated from the prompt."
        in review_fix_prompt_text
    )
    assert "SELF_REVIEW_STATUS: CHANGES_REQUESTED" not in review_fix_prompt_text


def test_build_codex_lint_fix_prompt_preserves_latest_lint_output() -> None:
    """Lint-fix prompt should focus on the latest pre-commit output and forbid Git finalization."""
    lint_fix_prompt_text = codex_runner.build_codex_lint_fix_prompt(
        task_title="Implement post-review lint automation",
        dev_log_text_list=[
            "Self review already passed; lint is now blocking completion."
        ],
        lint_output_lines=[
            "ruff.....................................................................Failed",
            "tests/test_codex_runner.py:10:1: F401 `unused_import` imported but unused",
            "files were modified by this hook",
        ],
        fix_round_index_int=1,
        max_fix_rounds_int=2,
        worktree_path_str="/tmp/project-wt-12345678",
    )

    assert "只修复最近一次 lint 输出明确指出的问题" in lint_fix_prompt_text
    assert "uv run pre-commit run --all-files" in lint_fix_prompt_text
    assert "tests/test_codex_runner.py:10:1: F401" in lint_fix_prompt_text
    assert "不要执行 `git commit`" in lint_fix_prompt_text


def test_create_codex_subprocess_sends_prompt_via_stdin(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Codex subprocess wrapper should avoid prompt argv inflation by using stdin."""
    recorded_call_dict: dict[str, object] = {}
    fake_process = FakeCodexProcess(
        output_line_list=[],
        include_stdin_bool=True,
    )

    async def fake_create_subprocess_exec(*args, **kwargs) -> FakeCodexProcess:
        recorded_call_dict["args"] = args
        recorded_call_dict["kwargs"] = kwargs
        return fake_process

    monkeypatch.setattr(
        codex_runner.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    created_process = asyncio.run(
        codex_runner._create_codex_subprocess(
            codex_executable_path_str="/usr/bin/codex",
            codex_prompt_text_str="large prompt body",
            work_dir_path=tmp_path,
        )
    )

    assert created_process is fake_process
    assert recorded_call_dict["args"] == (
        "/usr/bin/codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "-",
    )
    recorded_kwargs = recorded_call_dict["kwargs"]
    assert recorded_kwargs["cwd"] == str(tmp_path)
    assert recorded_kwargs["stdin"] == asyncio.subprocess.PIPE
    assert fake_process.stdin is not None
    assert fake_process.stdin.written_bytes == b"large prompt body"
    assert fake_process.stdin.closed is True
    assert fake_process.stdin.wait_closed_called is True


def test_create_claude_subprocess_sends_prompt_via_stdin(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Claude subprocess wrapper should avoid prompt argv inflation by using stdin."""
    recorded_call_dict: dict[str, object] = {}
    fake_process = FakeCodexProcess(
        output_line_list=[],
        include_stdin_bool=True,
    )

    async def fake_create_subprocess_exec(*args, **kwargs) -> FakeCodexProcess:
        recorded_call_dict["args"] = args
        recorded_call_dict["kwargs"] = kwargs
        return fake_process

    monkeypatch.setattr(
        codex_runner.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    created_process = asyncio.run(
        codex_runner._create_claude_subprocess(
            claude_executable_path_str="/usr/bin/claude",
            claude_prompt_text_str="claude prompt body",
            work_dir_path=tmp_path,
        )
    )

    assert created_process is fake_process
    assert recorded_call_dict["args"] == (
        "/usr/bin/claude",
        "-p",
        "--dangerously-skip-permissions",
    )
    recorded_kwargs = recorded_call_dict["kwargs"]
    assert recorded_kwargs["cwd"] == str(tmp_path)
    assert recorded_kwargs["stdin"] == asyncio.subprocess.PIPE
    assert fake_process.stdin is not None
    assert fake_process.stdin.written_bytes == b"claude prompt body"
    assert fake_process.stdin.closed is True
    assert fake_process.stdin.wait_closed_called is True


def test_run_logged_runner_conflict_resolution_passes_prompt_via_stdin(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Conflict resolution should send large runner prompts through stdin instead of argv."""
    recorded_run_call_dict: dict[str, object] = {}
    task_log_path = tmp_path / "task.log"

    def fake_subprocess_run(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        recorded_run_call_dict["args"] = args
        recorded_run_call_dict["kwargs"] = kwargs
        return build_completed_process(
            command_argument_list=list(args[0]),
            return_code_int=0,
            stdout_text="resolved conflicts",
        )

    monkeypatch.setattr(codex_runner.shutil, "which", lambda _name: "/usr/bin/codex")
    monkeypatch.setattr(codex_runner.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(codex_runner, "_write_log_to_db", lambda *args, **kwargs: None)

    completed_process = codex_runner._run_logged_runner_conflict_resolution(
        task_id_str="12345678-conflict",
        run_account_id_str="run-account-1",
        task_log_path=task_log_path,
        task_title_str="ARG_LENGTH_GUARD_TITLE",
        dev_log_text_list=["recent automation history"],
        repo_path=tmp_path,
        operation_kind_str="rebase",
    )

    assert completed_process is not None
    recorded_command_argument_list = list(recorded_run_call_dict["args"][0])
    recorded_run_kwargs = recorded_run_call_dict["kwargs"]
    assert recorded_command_argument_list == [
        "/usr/bin/codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "-",
    ]
    assert recorded_run_kwargs["input"] is not None
    assert "ARG_LENGTH_GUARD_TITLE" in recorded_run_kwargs["input"]
    assert "ARG_LENGTH_GUARD_TITLE" not in " ".join(recorded_command_argument_list)


def test_run_codex_prd_moves_to_changes_requested_and_sends_failure_notification(
    tmp_path: Path,
) -> None:
    """A failed PRD generation should notify through the unified changes-requested path."""
    recorded_log_entry_list: list[tuple[str, str]] = []
    recorded_stage_value_list: list[str] = []
    recorded_failure_notification_list: list[tuple[str, str, str]] = []

    async def fake_run_codex_phase(
        *args, **kwargs
    ) -> codex_runner.CodexPhaseExecutionResult:
        return codex_runner.CodexPhaseExecutionResult(
            success=False,
            output_lines=["PRD generation failed after retries."],
        )

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    def fake_advance_stage(task_id_str: str, next_stage_value: str) -> None:
        recorded_stage_value_list.append(next_stage_value)

    def fake_send_task_failed_notification(
        task_id_str: str,
        task_title_str: str,
        failure_reason_str: str = "",
    ) -> bool:
        recorded_failure_notification_list.append(
            (task_id_str, task_title_str, failure_reason_str)
        )
        return True

    original_run_codex_phase = codex_runner._run_codex_phase
    original_write_log_to_db = codex_runner._write_log_to_db
    original_advance_stage_in_db = codex_runner._advance_stage_in_db
    original_send_task_failed_notification = email_service.send_task_failed_notification

    try:
        codex_runner._run_codex_phase = fake_run_codex_phase
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._advance_stage_in_db = fake_advance_stage
        email_service.send_task_failed_notification = fake_send_task_failed_notification

        asyncio.run(
            codex_runner.run_codex_prd(
                task_id_str="12345678-prd-fail",
                run_account_id_str="run-account-prd",
                task_title_str="Generate PRD",
                dev_log_text_list=["Need a PRD before implementation."],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path / "repo-wt-12345678"),
            )
        )
    finally:
        codex_runner._run_codex_phase = original_run_codex_phase
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._advance_stage_in_db = original_advance_stage_in_db
        email_service.send_task_failed_notification = (
            original_send_task_failed_notification
        )
        codex_runner._running_background_task_ids.clear()
        codex_runner._running_codex_processes.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert recorded_stage_value_list == ["changes_requested"]
    assert recorded_failure_notification_list == [
        (
            "12345678-prd-fail",
            "Generate PRD",
            "PRD 生成阶段执行失败，未能自动产出可确认的 PRD。",
        )
    ]
    assert any("PRD 生成失败" in log_text for log_text, _ in recorded_log_entry_list)


def test_run_codex_prd_unexpected_preflight_exception_writes_task_log_and_fails(
    tmp_path: Path,
) -> None:
    """Unexpected pre-phase errors should still create a task log and fail cleanly."""
    recorded_log_entry_list: list[tuple[str, str]] = []
    recorded_stage_value_list: list[str] = []
    recorded_failure_notification_list: list[tuple[str, str, str]] = []

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    def fake_advance_stage(task_id_str: str, next_stage_value: str) -> None:
        recorded_stage_value_list.append(next_stage_value)

    def fake_send_task_failed_notification(
        task_id_str: str,
        task_title_str: str,
        failure_reason_str: str = "",
    ) -> bool:
        recorded_failure_notification_list.append(
            (task_id_str, task_title_str, failure_reason_str)
        )
        return True

    def fake_list_all_task_prd_file_paths(
        worktree_dir_path: Path,
        task_id_str: str,
    ) -> list[Path]:
        raise RuntimeError("preflight exploded")

    original_write_log_to_db = codex_runner._write_log_to_db
    original_advance_stage_in_db = codex_runner._advance_stage_in_db
    original_send_task_failed_notification = email_service.send_task_failed_notification
    original_list_all_task_prd_file_paths = codex_runner.list_all_task_prd_file_paths
    original_codex_log_dir = codex_runner._CODEX_LOG_DIR

    try:
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._advance_stage_in_db = fake_advance_stage
        email_service.send_task_failed_notification = fake_send_task_failed_notification
        codex_runner.list_all_task_prd_file_paths = (
            fake_list_all_task_prd_file_paths
        )
        codex_runner._CODEX_LOG_DIR = tmp_path

        asyncio.run(
            codex_runner.run_codex_prd(
                task_id_str="12345678-prd-boom",
                run_account_id_str="run-account-prd",
                task_title_str="Generate PRD",
                dev_log_text_list=["Need a PRD before implementation."],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path / "repo-wt-12345678"),
            )
        )
    finally:
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._advance_stage_in_db = original_advance_stage_in_db
        email_service.send_task_failed_notification = (
            original_send_task_failed_notification
        )
        codex_runner.list_all_task_prd_file_paths = (
            original_list_all_task_prd_file_paths
        )
        codex_runner._CODEX_LOG_DIR = original_codex_log_dir
        codex_runner._running_background_task_ids.clear()
        codex_runner._running_codex_processes.clear()
        codex_runner._user_cancelled_tasks.clear()

    task_log_path = tmp_path / "koda-12345678.log"
    assert task_log_path.exists() is True
    assert "preflight exploded" in task_log_path.read_text(encoding="utf-8")
    assert recorded_stage_value_list == ["changes_requested"]
    assert any(
        "PRD 生成在启动阶段发生异常" in log_text
        for log_text, _ in recorded_log_entry_list
    )
    assert recorded_failure_notification_list == [
        (
            "12345678-prd-boom",
            "Generate PRD",
            "runner_kind=codex PRD 生成在启动阶段发生异常，未能进入正式执行。",
        )
    ]


def test_run_codex_phase_missing_runner_writes_task_log(
    tmp_path: Path,
) -> None:
    """Missing runner executables should still create a readable task log."""
    recorded_log_entry_list: list[tuple[str, str]] = []

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    original_which = codex_runner.shutil.which
    original_write_log_to_db = codex_runner._write_log_to_db
    original_codex_log_dir = codex_runner._CODEX_LOG_DIR

    try:
        codex_runner.shutil.which = lambda _name: None
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._CODEX_LOG_DIR = tmp_path

        phase_result = asyncio.run(
            codex_runner._run_codex_phase(
                task_id_str="12345678-no-cli",
                run_account_id_str="run-account-prd",
                codex_prompt_text_str="Generate a PRD",
                work_dir_path=tmp_path,
                phase_log_label_str="codex-prd",
                phase_display_name_str="PRD 生成",
                cancelled_log_text_str="cancelled",
                overwrite_existing_log_bool=True,
            )
        )
    finally:
        codex_runner.shutil.which = original_which
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._CODEX_LOG_DIR = original_codex_log_dir
        codex_runner._running_background_task_ids.clear()
        codex_runner._running_codex_processes.clear()
        codex_runner._user_cancelled_tasks.clear()

    task_log_path = tmp_path / "koda-12345678.log"
    assert phase_result.success is False
    assert task_log_path.exists() is True
    assert "未找到目标执行器可执行文件" in task_log_path.read_text(encoding="utf-8")
    assert any(
        "未找到目标执行器可执行文件" in log_text
        for log_text, _ in recorded_log_entry_list
    )


def test_run_codex_task_moves_to_changes_requested_and_sends_failure_notification_on_initial_exec_failure(
    tmp_path: Path,
) -> None:
    """An implementation-phase failure should notify through the unified changes-requested path."""
    recorded_log_entry_list: list[tuple[str, str]] = []
    recorded_stage_value_list: list[str] = []
    recorded_failure_notification_list: list[tuple[str, str, str]] = []

    async def fake_run_codex_phase(
        *args, **kwargs
    ) -> codex_runner.CodexPhaseExecutionResult:
        return codex_runner.CodexPhaseExecutionResult(
            success=False,
            output_lines=["Initial implementation failed after retries."],
        )

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    def fake_advance_stage(task_id_str: str, next_stage_value: str) -> None:
        recorded_stage_value_list.append(next_stage_value)

    def fake_send_task_failed_notification(
        task_id_str: str,
        task_title_str: str,
        failure_reason_str: str = "",
    ) -> bool:
        recorded_failure_notification_list.append(
            (task_id_str, task_title_str, failure_reason_str)
        )
        return True

    original_run_codex_phase = codex_runner._run_codex_phase
    original_write_log_to_db = codex_runner._write_log_to_db
    original_advance_stage_in_db = codex_runner._advance_stage_in_db
    original_send_task_failed_notification = email_service.send_task_failed_notification

    try:
        codex_runner._run_codex_phase = fake_run_codex_phase
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._advance_stage_in_db = fake_advance_stage
        email_service.send_task_failed_notification = fake_send_task_failed_notification

        asyncio.run(
            codex_runner.run_codex_task(
                task_id_str="12345678-exec-fail",
                run_account_id_str="run-account-exec",
                task_title_str="Implement automation",
                dev_log_text_list=["Implementation should start from this context."],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path / "repo-wt-12345678"),
            )
        )
    finally:
        codex_runner._run_codex_phase = original_run_codex_phase
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._advance_stage_in_db = original_advance_stage_in_db
        email_service.send_task_failed_notification = (
            original_send_task_failed_notification
        )
        codex_runner._running_background_task_ids.clear()
        codex_runner._running_codex_processes.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert recorded_stage_value_list == ["changes_requested"]
    assert recorded_failure_notification_list == [
        (
            "12345678-exec-fail",
            "Implement automation",
            "codex exec 执行失败，AI 未能完成初次实现阶段。",
        )
    ]
    assert any(
        "codex exec 执行失败" in log_text for log_text, _ in recorded_log_entry_list
    )


def test_run_codex_task_executes_self_review_and_continues_into_lint_stage_on_pass(
    tmp_path: Path,
) -> None:
    """A passing self review should continue into post-review lint and park in test_in_progress."""
    recorded_prompt_text_list: list[str] = []
    recorded_log_entry_list: list[tuple[str, str]] = []
    recorded_stage_value_list: list[str] = []
    recorded_command_label_list: list[str] = []
    fake_process_queue = [
        FakeCodexProcess(
            output_line_list=["Implemented the requested flow."],
            planned_return_code_int=0,
            pid_int=1111,
        ),
        FakeCodexProcess(
            output_line_list=[
                "Reviewed current changes and docs.",
                "SELF_REVIEW_SUMMARY: no blocking issues found",
                "SELF_REVIEW_STATUS: PASS",
            ],
            planned_return_code_int=0,
            pid_int=2222,
        ),
    ]

    async def fake_create_subprocess_exec(*args, **kwargs) -> FakeCodexProcess:
        recorded_prompt_text_list.append(kwargs["codex_prompt_text_str"])
        return fake_process_queue.pop(0)

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    def fake_advance_stage(task_id_str: str, next_stage_value: str) -> None:
        recorded_stage_value_list.append(next_stage_value)

    def fake_run_logged_command(
        *,
        task_id_str: str,
        run_account_id_str: str,
        task_log_path: Path,
        command_argument_list: list[str],
        cwd_path: Path,
        command_log_label_str: str,
    ) -> subprocess.CompletedProcess[str]:
        recorded_command_label_list.append(command_log_label_str)
        return build_completed_process(
            command_argument_list=command_argument_list,
            return_code_int=0,
            stdout_text="pre-commit checks passed",
        )

    original_which = codex_runner.shutil.which
    original_create_codex_subprocess = codex_runner._create_codex_subprocess
    original_write_log_to_db = codex_runner._write_log_to_db
    original_advance_stage_in_db = codex_runner._advance_stage_in_db
    original_run_logged_command = codex_runner._run_logged_command
    original_codex_log_dir = codex_runner._CODEX_LOG_DIR

    try:
        codex_runner.shutil.which = lambda executable_name_str: "/usr/bin/codex"
        codex_runner._create_codex_subprocess = fake_create_subprocess_exec
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._advance_stage_in_db = fake_advance_stage
        codex_runner._run_logged_command = fake_run_logged_command
        codex_runner._CODEX_LOG_DIR = tmp_path

        asyncio.run(
            codex_runner.run_codex_task(
                task_id_str="12345678-pass-case",
                run_account_id_str="run-account-1",
                task_title_str="Implement review automation",
                dev_log_text_list=["User requested a real self review phase."],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path / "repo-wt-12345678"),
            )
        )
    finally:
        codex_runner.shutil.which = original_which
        codex_runner._create_codex_subprocess = original_create_codex_subprocess
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._advance_stage_in_db = original_advance_stage_in_db
        codex_runner._run_logged_command = original_run_logged_command
        codex_runner._CODEX_LOG_DIR = original_codex_log_dir
        codex_runner._running_codex_processes.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert len(recorded_prompt_text_list) == 2
    assert "不要默认执行 `git commit`" in recorded_prompt_text_list[0]
    assert "SELF_REVIEW_STATUS: PASS" in recorded_prompt_text_list[1]
    assert "当前是第 1/3 轮 AI 自检" in recorded_prompt_text_list[1]
    assert recorded_stage_value_list == ["self_review_in_progress", "test_in_progress"]
    assert recorded_command_label_list == ["post-review-lint"]
    assert any(
        "开始第 1 轮代码评审" in log_text for log_text, _ in recorded_log_entry_list
    )
    assert any("AI 自检闭环完成" in log_text for log_text, _ in recorded_log_entry_list)
    assert any(
        "post-review lint 闭环完成" in log_text
        for log_text, _ in recorded_log_entry_list
    )

    task_log_text = (tmp_path / "koda-12345678.log").read_text(encoding="utf-8")
    assert "=== Koda codex-exec" in task_log_text
    assert "=== Koda codex-review" in task_log_text
    assert "=== Koda post-review-lint" in task_log_text


def test_run_codex_review_resume_continues_into_post_review_lint_on_pass(
    tmp_path: Path,
) -> None:
    """Resuming self-review should advance to lint and clear runtime state on success."""
    recorded_log_entry_list: list[tuple[str, str]] = []
    recorded_stage_value_list: list[str] = []
    recorded_lint_call_argument_list: list[tuple[str, str, str, Path, str | None]] = []

    async def fake_run_codex_review(
        **kwargs: object,
    ) -> codex_runner.SelfReviewExecutionResult:
        return codex_runner.SelfReviewExecutionResult(
            passed=True,
            context_log_text_list=["review passed after resume"],
            self_review_summary_str="resume path ok",
        )

    async def fake_run_post_review_lint(
        *,
        task_id_str: str,
        run_account_id_str: str,
        task_title_str: str,
        dev_log_text_list: list[str],
        work_dir_path: Path,
        worktree_path_str: str | None = None,
    ) -> codex_runner.PostReviewLintExecutionResult:
        recorded_lint_call_argument_list.append(
            (
                task_id_str,
                run_account_id_str,
                task_title_str,
                work_dir_path,
                worktree_path_str,
            )
        )
        return codex_runner.PostReviewLintExecutionResult(
            passed=True,
            context_log_text_list=dev_log_text_list,
            latest_lint_output_line_list=["pre-commit passed"],
        )

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    def fake_advance_stage(task_id_str: str, next_stage_value: str) -> None:
        recorded_stage_value_list.append(next_stage_value)

    original_run_codex_review = codex_runner.run_codex_review
    original_run_post_review_lint = codex_runner.run_post_review_lint
    original_write_log_to_db = codex_runner._write_log_to_db
    original_advance_stage_in_db = codex_runner._advance_stage_in_db

    try:
        codex_runner.run_codex_review = fake_run_codex_review
        codex_runner.run_post_review_lint = fake_run_post_review_lint
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._advance_stage_in_db = fake_advance_stage

        asyncio.run(
            codex_runner.run_codex_review_resume(
                task_id_str="review-resume-01",
                run_account_id_str="run-account-1",
                task_title_str="Resume self review",
                dev_log_text_list=["task context before review resume"],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path / "repo-wt-review-resume"),
            )
        )
    finally:
        codex_runner.run_codex_review = original_run_codex_review
        codex_runner.run_post_review_lint = original_run_post_review_lint
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._advance_stage_in_db = original_advance_stage_in_db
        codex_runner._running_background_task_ids.clear()

    assert recorded_stage_value_list == ["test_in_progress"]
    assert len(recorded_lint_call_argument_list) == 1
    assert any(
        "正在从 AI 自检阶段继续执行" in log_text
        for log_text, _ in recorded_log_entry_list
    )
    assert "review-resume-01" not in codex_runner._running_background_task_ids


def test_run_post_review_lint_resume_reuses_lint_pipeline_and_clears_runtime_state(
    tmp_path: Path,
) -> None:
    """Resuming lint should call the existing lint loop and clear runtime state afterward."""
    recorded_log_entry_list: list[tuple[str, str]] = []
    recorded_lint_call_argument_list: list[tuple[str, str, str, Path, str | None]] = []

    async def fake_run_post_review_lint(
        *,
        task_id_str: str,
        run_account_id_str: str,
        task_title_str: str,
        dev_log_text_list: list[str],
        work_dir_path: Path,
        worktree_path_str: str | None = None,
    ) -> codex_runner.PostReviewLintExecutionResult:
        recorded_lint_call_argument_list.append(
            (
                task_id_str,
                run_account_id_str,
                task_title_str,
                work_dir_path,
                worktree_path_str,
            )
        )
        return codex_runner.PostReviewLintExecutionResult(
            passed=True,
            context_log_text_list=dev_log_text_list,
            latest_lint_output_line_list=["pre-commit passed"],
        )

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    original_run_post_review_lint = codex_runner.run_post_review_lint
    original_write_log_to_db = codex_runner._write_log_to_db

    try:
        codex_runner.run_post_review_lint = fake_run_post_review_lint
        codex_runner._write_log_to_db = fake_write_log_to_db

        asyncio.run(
            codex_runner.run_post_review_lint_resume(
                task_id_str="lint-resume-01",
                run_account_id_str="run-account-2",
                task_title_str="Resume lint",
                dev_log_text_list=["task context before lint resume"],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path / "repo-wt-lint-resume"),
            )
        )
    finally:
        codex_runner.run_post_review_lint = original_run_post_review_lint
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._running_background_task_ids.clear()

    assert len(recorded_lint_call_argument_list) == 1
    assert any(
        "正在从 post-review lint 阶段继续执行" in log_text
        for log_text, _ in recorded_log_entry_list
    )
    assert "lint-resume-01" not in codex_runner._running_background_task_ids


def test_run_codex_task_retries_review_findings_and_keeps_stage_on_loop_pass(
    tmp_path: Path,
) -> None:
    """A blocking review should trigger auto-remediation and re-review before passing."""
    recorded_prompt_text_list: list[str] = []
    recorded_log_entry_list: list[tuple[str, str]] = []
    recorded_stage_value_list: list[str] = []
    recorded_command_label_list: list[str] = []
    fake_process_queue = [
        FakeCodexProcess(
            output_line_list=["Implemented the requested flow."],
            planned_return_code_int=0,
            pid_int=3333,
        ),
        FakeCodexProcess(
            output_line_list=[
                "Found missing error handling in the new path.",
                "SELF_REVIEW_SUMMARY: add error-path handling before testing",
                "SELF_REVIEW_STATUS: CHANGES_REQUESTED",
            ],
            planned_return_code_int=0,
            pid_int=4444,
        ),
        FakeCodexProcess(
            output_line_list=[
                "Patched the missing error-path handling and updated the regression tests.",
            ],
            planned_return_code_int=0,
            pid_int=5555,
        ),
        FakeCodexProcess(
            output_line_list=[
                "Re-reviewed the patched flow.",
                "SELF_REVIEW_SUMMARY: blocker resolved after targeted fix",
                "SELF_REVIEW_STATUS: PASS",
            ],
            planned_return_code_int=0,
            pid_int=6666,
        ),
    ]

    async def fake_create_subprocess_exec(*args, **kwargs) -> FakeCodexProcess:
        recorded_prompt_text_list.append(kwargs["codex_prompt_text_str"])
        return fake_process_queue.pop(0)

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    def fake_advance_stage(task_id_str: str, next_stage_value: str) -> None:
        recorded_stage_value_list.append(next_stage_value)

    def fake_run_logged_command(
        *,
        task_id_str: str,
        run_account_id_str: str,
        task_log_path: Path,
        command_argument_list: list[str],
        cwd_path: Path,
        command_log_label_str: str,
    ) -> subprocess.CompletedProcess[str]:
        recorded_command_label_list.append(command_log_label_str)
        return build_completed_process(
            command_argument_list=command_argument_list,
            return_code_int=0,
            stdout_text="pre-commit checks passed after review fix",
        )

    original_which = codex_runner.shutil.which
    original_create_codex_subprocess = codex_runner._create_codex_subprocess
    original_write_log_to_db = codex_runner._write_log_to_db
    original_advance_stage_in_db = codex_runner._advance_stage_in_db
    original_run_logged_command = codex_runner._run_logged_command
    original_codex_log_dir = codex_runner._CODEX_LOG_DIR

    try:
        codex_runner.shutil.which = lambda executable_name_str: "/usr/bin/codex"
        codex_runner._create_codex_subprocess = fake_create_subprocess_exec
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._advance_stage_in_db = fake_advance_stage
        codex_runner._run_logged_command = fake_run_logged_command
        codex_runner._CODEX_LOG_DIR = tmp_path

        asyncio.run(
            codex_runner.run_codex_task(
                task_id_str="12345678-fail-case",
                run_account_id_str="run-account-2",
                task_title_str="Implement review automation",
                dev_log_text_list=["User requested a real self review phase."],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path / "repo-wt-12345678"),
            )
        )
    finally:
        codex_runner.shutil.which = original_which
        codex_runner._create_codex_subprocess = original_create_codex_subprocess
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._advance_stage_in_db = original_advance_stage_in_db
        codex_runner._run_logged_command = original_run_logged_command
        codex_runner._CODEX_LOG_DIR = original_codex_log_dir
        codex_runner._running_codex_processes.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert len(recorded_prompt_text_list) == 4
    assert "只修复最近一轮 review 明确指出的阻塞性问题" in recorded_prompt_text_list[2]
    assert "当前是第 2/3 轮 AI 自检" in recorded_prompt_text_list[3]
    assert recorded_stage_value_list == ["self_review_in_progress", "test_in_progress"]
    assert recorded_command_label_list == ["post-review-lint"]
    assert any(
        "第 1 轮 AI 自检发现阻塞性问题" in log_text
        for log_text, _ in recorded_log_entry_list
    )
    assert any(
        "第 1 轮自动回改完成" in log_text for log_text, _ in recorded_log_entry_list
    )
    assert any(
        "AI 自检闭环完成：第 2 轮评审通过" in log_text
        for log_text, _ in recorded_log_entry_list
    )
    assert any(
        "post-review lint 闭环完成" in log_text
        for log_text, _ in recorded_log_entry_list
    )

    task_log_text = (tmp_path / "koda-12345678.log").read_text(encoding="utf-8")
    assert "=== Koda codex-review" in task_log_text
    assert "=== Koda codex-review-fix-round-1" in task_log_text
    assert "=== Koda codex-review-round-2" in task_log_text
    assert "=== Koda post-review-lint" in task_log_text


def test_run_codex_task_moves_to_changes_requested_after_review_loop_exhausted(
    tmp_path: Path,
) -> None:
    """The task should only regress after the review-fix loop exhausts its retries."""
    recorded_log_entry_list: list[tuple[str, str]] = []
    recorded_stage_value_list: list[str] = []
    recorded_failure_notification_list: list[tuple[str, str, str]] = []
    fake_process_queue = [
        FakeCodexProcess(
            output_line_list=["Implemented the requested flow."],
            planned_return_code_int=0,
            pid_int=7001,
        ),
        FakeCodexProcess(
            output_line_list=[
                "Found missing error handling in the new path.",
                "SELF_REVIEW_SUMMARY: add error-path handling before testing",
                "SELF_REVIEW_STATUS: CHANGES_REQUESTED",
            ],
            planned_return_code_int=0,
            pid_int=7002,
        ),
        FakeCodexProcess(
            output_line_list=["Applied the first targeted fix round."],
            planned_return_code_int=0,
            pid_int=7003,
        ),
        FakeCodexProcess(
            output_line_list=[
                "Found a second blocker in the fallback branch.",
                "SELF_REVIEW_SUMMARY: patch the fallback branch before release",
                "SELF_REVIEW_STATUS: CHANGES_REQUESTED",
            ],
            planned_return_code_int=0,
            pid_int=7004,
        ),
        FakeCodexProcess(
            output_line_list=["Applied the second targeted fix round."],
            planned_return_code_int=0,
            pid_int=7005,
        ),
        FakeCodexProcess(
            output_line_list=[
                "Still missing the rollback guard in the last error path.",
                "SELF_REVIEW_SUMMARY: rollback guard is still missing",
                "SELF_REVIEW_STATUS: CHANGES_REQUESTED",
            ],
            planned_return_code_int=0,
            pid_int=7006,
        ),
    ]

    async def fake_create_subprocess_exec(*args, **kwargs) -> FakeCodexProcess:
        return fake_process_queue.pop(0)

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    def fake_advance_stage(task_id_str: str, next_stage_value: str) -> None:
        recorded_stage_value_list.append(next_stage_value)

    def fake_send_task_failed_notification(
        task_id_str: str,
        task_title_str: str,
        failure_reason_str: str = "",
    ) -> bool:
        recorded_failure_notification_list.append(
            (task_id_str, task_title_str, failure_reason_str)
        )
        return True

    original_which = codex_runner.shutil.which
    original_create_codex_subprocess = codex_runner._create_codex_subprocess
    original_write_log_to_db = codex_runner._write_log_to_db
    original_advance_stage_in_db = codex_runner._advance_stage_in_db
    original_send_task_failed_notification = email_service.send_task_failed_notification
    original_codex_log_dir = codex_runner._CODEX_LOG_DIR

    try:
        codex_runner.shutil.which = lambda executable_name_str: "/usr/bin/codex"
        codex_runner._create_codex_subprocess = fake_create_subprocess_exec
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._advance_stage_in_db = fake_advance_stage
        email_service.send_task_failed_notification = fake_send_task_failed_notification
        codex_runner._CODEX_LOG_DIR = tmp_path

        asyncio.run(
            codex_runner.run_codex_task(
                task_id_str="12345678-loop-fail",
                run_account_id_str="run-account-3",
                task_title_str="Implement review automation",
                dev_log_text_list=["User requested a real self review phase."],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path / "repo-wt-12345678"),
            )
        )
    finally:
        codex_runner.shutil.which = original_which
        codex_runner._create_codex_subprocess = original_create_codex_subprocess
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._advance_stage_in_db = original_advance_stage_in_db
        email_service.send_task_failed_notification = (
            original_send_task_failed_notification
        )
        codex_runner._CODEX_LOG_DIR = original_codex_log_dir
        codex_runner._running_codex_processes.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert recorded_stage_value_list == [
        "self_review_in_progress",
        "changes_requested",
    ]
    assert recorded_failure_notification_list == [
        (
            "12345678-loop-fail",
            "Implement review automation",
            "AI 自检在 2 轮自动回改后仍存在阻塞性问题：rollback guard is still missing",
        )
    ]
    assert any(
        "第 1 轮 AI 自检发现阻塞性问题" in log_text
        for log_text, _ in recorded_log_entry_list
    )
    assert any(
        "第 2 轮自动回改完成" in log_text for log_text, _ in recorded_log_entry_list
    )
    assert any(
        "已用尽 2 轮自动回改次数" in log_text for log_text, _ in recorded_log_entry_list
    )
    assert not any(
        "等待人工确认" in log_text for log_text, _ in recorded_log_entry_list
    )


def test_run_post_review_lint_runs_lint_fix_after_second_failed_lint_and_passes(
    tmp_path: Path,
) -> None:
    """A failed lint rerun should trigger Codex lint-fix before returning success."""
    recorded_prompt_text_list: list[str] = []
    recorded_log_entry_list: list[tuple[str, str]] = []
    recorded_command_label_list: list[str] = []
    lint_process_queue = [
        build_completed_process(
            command_argument_list=codex_runner._POST_REVIEW_LINT_COMMAND_ARGUMENT_LIST,
            return_code_int=1,
            stdout_text="ruff.....................................................................Failed",
        ),
        build_completed_process(
            command_argument_list=codex_runner._POST_REVIEW_LINT_COMMAND_ARGUMENT_LIST,
            return_code_int=1,
            stdout_text="tests/test_codex_runner.py:10:1: F401 `unused_import` imported but unused",
        ),
        build_completed_process(
            command_argument_list=codex_runner._POST_REVIEW_LINT_COMMAND_ARGUMENT_LIST,
            return_code_int=0,
            stdout_text="All pre-commit checks passed",
        ),
    ]
    fake_process_queue = [
        FakeCodexProcess(
            output_line_list=[
                "Removed the unused import and normalized formatting.",
            ],
            planned_return_code_int=0,
            pid_int=8101,
        ),
    ]

    async def fake_create_subprocess_exec(*args, **kwargs) -> FakeCodexProcess:
        recorded_prompt_text_list.append(kwargs["codex_prompt_text_str"])
        return fake_process_queue.pop(0)

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    def fake_run_logged_command(
        *,
        task_id_str: str,
        run_account_id_str: str,
        task_log_path: Path,
        command_argument_list: list[str],
        cwd_path: Path,
        command_log_label_str: str,
    ) -> subprocess.CompletedProcess[str]:
        recorded_command_label_list.append(command_log_label_str)
        return lint_process_queue.pop(0)

    original_which = codex_runner.shutil.which
    original_create_codex_subprocess = codex_runner._create_codex_subprocess
    original_write_log_to_db = codex_runner._write_log_to_db
    original_run_logged_command = codex_runner._run_logged_command
    original_codex_log_dir = codex_runner._CODEX_LOG_DIR

    try:
        codex_runner.shutil.which = lambda executable_name_str: "/usr/bin/codex"
        codex_runner._create_codex_subprocess = fake_create_subprocess_exec
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._run_logged_command = fake_run_logged_command
        codex_runner._CODEX_LOG_DIR = tmp_path

        lint_result = asyncio.run(
            codex_runner.run_post_review_lint(
                task_id_str="12345678-lint-pass",
                run_account_id_str="run-account-4",
                task_title_str="Implement post-review lint automation",
                dev_log_text_list=["Self review already passed."],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path / "repo-wt-12345678"),
            )
        )
    finally:
        codex_runner.shutil.which = original_which
        codex_runner._create_codex_subprocess = original_create_codex_subprocess
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._run_logged_command = original_run_logged_command
        codex_runner._CODEX_LOG_DIR = original_codex_log_dir
        codex_runner._running_codex_processes.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert lint_result.passed is True
    assert recorded_command_label_list == [
        "post-review-lint",
        "post-review-lint-rerun",
        "post-review-lint-round-1",
    ]
    assert len(recorded_prompt_text_list) == 1
    assert (
        "tests/test_codex_runner.py:10:1: F401 `unused_import` imported but unused"
        in recorded_prompt_text_list[0]
    )
    assert "uv run pre-commit run --all-files" in recorded_prompt_text_list[0]
    assert any(
        "开始第 1/2 轮 AI lint 定向修复" in log_text
        for log_text, _ in recorded_log_entry_list
    )
    assert any(
        "post-review lint 闭环完成" in log_text
        for log_text, _ in recorded_log_entry_list
    )

    task_log_text = (tmp_path / "koda-12345678.log").read_text(encoding="utf-8")
    assert "=== Koda post-review-lint" in task_log_text
    assert "=== Koda codex-lint-fix-round-1" in task_log_text


def test_run_post_review_lint_moves_to_changes_requested_after_lint_fix_exhausted(
    tmp_path: Path,
) -> None:
    """The task should only regress after all lint-fix rounds fail."""
    recorded_log_entry_list: list[tuple[str, str]] = []
    recorded_stage_value_list: list[str] = []
    recorded_failure_notification_list: list[tuple[str, str, str]] = []
    lint_process_queue = [
        build_completed_process(
            command_argument_list=codex_runner._POST_REVIEW_LINT_COMMAND_ARGUMENT_LIST,
            return_code_int=1,
            stdout_text="ruff.....................................................................Failed",
        ),
        build_completed_process(
            command_argument_list=codex_runner._POST_REVIEW_LINT_COMMAND_ARGUMENT_LIST,
            return_code_int=1,
            stdout_text="tests/test_codex_runner.py:20:1: F401 first blocker",
        ),
        build_completed_process(
            command_argument_list=codex_runner._POST_REVIEW_LINT_COMMAND_ARGUMENT_LIST,
            return_code_int=1,
            stdout_text="ruff.....................................................................Failed again",
        ),
        build_completed_process(
            command_argument_list=codex_runner._POST_REVIEW_LINT_COMMAND_ARGUMENT_LIST,
            return_code_int=1,
            stdout_text="tests/test_codex_runner.py:30:1: F401 second blocker",
        ),
        build_completed_process(
            command_argument_list=codex_runner._POST_REVIEW_LINT_COMMAND_ARGUMENT_LIST,
            return_code_int=1,
            stdout_text="ruff.....................................................................Still failing",
        ),
        build_completed_process(
            command_argument_list=codex_runner._POST_REVIEW_LINT_COMMAND_ARGUMENT_LIST,
            return_code_int=1,
            stdout_text="tests/test_codex_runner.py:40:1: F401 final blocker",
        ),
    ]
    fake_process_queue = [
        FakeCodexProcess(
            output_line_list=["Applied the first lint fix round."],
            planned_return_code_int=0,
            pid_int=8201,
        ),
        FakeCodexProcess(
            output_line_list=["Applied the second lint fix round."],
            planned_return_code_int=0,
            pid_int=8202,
        ),
    ]

    async def fake_create_subprocess_exec(*args, **kwargs) -> FakeCodexProcess:
        return fake_process_queue.pop(0)

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    def fake_run_logged_command(
        *,
        task_id_str: str,
        run_account_id_str: str,
        task_log_path: Path,
        command_argument_list: list[str],
        cwd_path: Path,
        command_log_label_str: str,
    ) -> subprocess.CompletedProcess[str]:
        return lint_process_queue.pop(0)

    def fake_advance_stage(task_id_str: str, next_stage_value: str) -> None:
        recorded_stage_value_list.append(next_stage_value)

    def fake_send_task_failed_notification(
        task_id_str: str,
        task_title_str: str,
        failure_reason_str: str = "",
    ) -> bool:
        recorded_failure_notification_list.append(
            (task_id_str, task_title_str, failure_reason_str)
        )
        return True

    original_which = codex_runner.shutil.which
    original_create_codex_subprocess = codex_runner._create_codex_subprocess
    original_write_log_to_db = codex_runner._write_log_to_db
    original_run_logged_command = codex_runner._run_logged_command
    original_advance_stage_in_db = codex_runner._advance_stage_in_db
    original_send_task_failed_notification = email_service.send_task_failed_notification
    original_codex_log_dir = codex_runner._CODEX_LOG_DIR

    try:
        codex_runner.shutil.which = lambda executable_name_str: "/usr/bin/codex"
        codex_runner._create_codex_subprocess = fake_create_subprocess_exec
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._run_logged_command = fake_run_logged_command
        codex_runner._advance_stage_in_db = fake_advance_stage
        email_service.send_task_failed_notification = fake_send_task_failed_notification
        codex_runner._CODEX_LOG_DIR = tmp_path

        lint_result = asyncio.run(
            codex_runner.run_post_review_lint(
                task_id_str="12345678-lint-fail",
                run_account_id_str="run-account-5",
                task_title_str="Implement post-review lint automation",
                dev_log_text_list=["Self review already passed."],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path / "repo-wt-12345678"),
            )
        )
    finally:
        codex_runner.shutil.which = original_which
        codex_runner._create_codex_subprocess = original_create_codex_subprocess
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._run_logged_command = original_run_logged_command
        codex_runner._advance_stage_in_db = original_advance_stage_in_db
        email_service.send_task_failed_notification = (
            original_send_task_failed_notification
        )
        codex_runner._CODEX_LOG_DIR = original_codex_log_dir
        codex_runner._running_codex_processes.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert lint_result.passed is False
    assert recorded_stage_value_list == ["changes_requested"]
    assert recorded_failure_notification_list == [
        (
            "12345678-lint-fail",
            "Implement post-review lint automation",
            "post-review lint 在 2 轮 AI lint 定向修复后仍未通过：tests/test_codex_runner.py:40:1: F401 final blocker",
        )
    ]
    assert any(
        "开始第 1/2 轮 AI lint 定向修复" in log_text
        for log_text, _ in recorded_log_entry_list
    )
    assert any(
        "开始第 2/2 轮 AI lint 定向修复" in log_text
        for log_text, _ in recorded_log_entry_list
    )
    assert any(
        "已用尽 2 轮 AI lint 定向修复次数" in log_text
        for log_text, _ in recorded_log_entry_list
    )


def test_run_codex_completion_advances_task_to_done_on_success(
    tmp_path: Path,
) -> None:
    """A successful completion flow should finalize the task after merge and cleanup."""
    recorded_log_entry_list: list[tuple[str, str]] = []
    recorded_stage_value_list: list[str] = []
    recorded_finalize_call_list: list[tuple[str, bool]] = []

    def fake_execute_git_completion_flow(
        *,
        task_id_str: str,
        run_account_id_str: str,
        task_title_str: str,
        commit_information_text_str: str | None,
        dev_log_text_list: list[str],
        worktree_path_str: str,
    ) -> codex_runner.GitCompletionExecutionResult:
        assert task_id_str == "12345678-done-case"
        assert run_account_id_str == "run-account-3"
        assert task_title_str == "Finalize branch"
        assert commit_information_text_str == "Implement the reviewed branch flow"
        assert dev_log_text_list == ["Implementation already passed review."]
        assert worktree_path_str == str(tmp_path / "repo-wt-12345678")
        return codex_runner.GitCompletionExecutionResult(
            merged_to_main=True,
            cleanup_succeeded=True,
            output_lines=["Merged feature branch into main."],
            feature_branch_name="task/12345678",
            worktree_removed=True,
        )

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    def fake_advance_stage(task_id_str: str, next_stage_value: str) -> None:
        recorded_stage_value_list.append(next_stage_value)

    def fake_finalize_completion_in_db(
        task_id_str: str,
        clear_worktree_path_bool: bool,
    ) -> None:
        recorded_finalize_call_list.append((task_id_str, clear_worktree_path_bool))

    original_execute_git_completion_flow = codex_runner._execute_git_completion_flow
    original_write_log_to_db = codex_runner._write_log_to_db
    original_advance_stage_in_db = codex_runner._advance_stage_in_db
    original_finalize_completion_in_db = codex_runner._finalize_completion_in_db

    try:
        codex_runner._execute_git_completion_flow = fake_execute_git_completion_flow
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._advance_stage_in_db = fake_advance_stage
        codex_runner._finalize_completion_in_db = fake_finalize_completion_in_db

        asyncio.run(
            codex_runner.run_codex_completion(
                task_id_str="12345678-done-case",
                run_account_id_str="run-account-3",
                task_title_str="Finalize branch",
                commit_information_text_str="Implement the reviewed branch flow",
                commit_information_source_str="ai_summary",
                dev_log_text_list=["Implementation already passed review."],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path / "repo-wt-12345678"),
            )
        )
    finally:
        codex_runner._execute_git_completion_flow = original_execute_git_completion_flow
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._advance_stage_in_db = original_advance_stage_in_db
        codex_runner._finalize_completion_in_db = original_finalize_completion_in_db
        codex_runner._running_background_task_ids.clear()
        codex_runner._running_codex_processes.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert recorded_stage_value_list == []
    assert recorded_finalize_call_list == [("12345678-done-case", True)]
    assert any("git add ." in log_text for log_text, _ in recorded_log_entry_list)
    assert any("合并到 `main`" in log_text for log_text, _ in recorded_log_entry_list)


def test_run_codex_completion_marks_done_with_warning_when_cleanup_fails(
    tmp_path: Path,
) -> None:
    """A merge success with cleanup failure should still finalize the task with a warning."""
    recorded_log_entry_list: list[tuple[str, str]] = []
    recorded_stage_value_list: list[str] = []
    recorded_finalize_call_list: list[tuple[str, bool]] = []

    def fake_execute_git_completion_flow(
        *,
        task_id_str: str,
        run_account_id_str: str,
        task_title_str: str,
        commit_information_text_str: str | None,
        dev_log_text_list: list[str],
        worktree_path_str: str,
    ) -> codex_runner.GitCompletionExecutionResult:
        assert commit_information_text_str == "Implement the reviewed branch flow"
        return codex_runner.GitCompletionExecutionResult(
            merged_to_main=True,
            cleanup_succeeded=False,
            output_lines=["Merged feature branch into main."],
            feature_branch_name="task/12345678",
            failure_reason_text="cleanup script failed",
            worktree_removed=False,
        )

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    def fake_advance_stage(task_id_str: str, next_stage_value: str) -> None:
        recorded_stage_value_list.append(next_stage_value)

    def fake_finalize_completion_in_db(
        task_id_str: str,
        clear_worktree_path_bool: bool,
    ) -> None:
        recorded_finalize_call_list.append((task_id_str, clear_worktree_path_bool))

    original_execute_git_completion_flow = codex_runner._execute_git_completion_flow
    original_write_log_to_db = codex_runner._write_log_to_db
    original_advance_stage_in_db = codex_runner._advance_stage_in_db
    original_finalize_completion_in_db = codex_runner._finalize_completion_in_db

    try:
        codex_runner._execute_git_completion_flow = fake_execute_git_completion_flow
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._advance_stage_in_db = fake_advance_stage
        codex_runner._finalize_completion_in_db = fake_finalize_completion_in_db

        asyncio.run(
            codex_runner.run_codex_completion(
                task_id_str="12345678-clean-warn",
                run_account_id_str="run-account-5",
                task_title_str="Finalize branch",
                commit_information_text_str="Implement the reviewed branch flow",
                commit_information_source_str="requirement_brief",
                dev_log_text_list=["Implementation already passed review."],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path / "repo-wt-12345678"),
            )
        )
    finally:
        codex_runner._execute_git_completion_flow = original_execute_git_completion_flow
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._advance_stage_in_db = original_advance_stage_in_db
        codex_runner._finalize_completion_in_db = original_finalize_completion_in_db
        codex_runner._running_background_task_ids.clear()
        codex_runner._running_codex_processes.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert recorded_stage_value_list == []
    assert recorded_finalize_call_list == [("12345678-clean-warn", False)]
    assert any(
        "自动清理没有完全成功" in log_text for log_text, _ in recorded_log_entry_list
    )


def test_run_codex_completion_moves_task_to_changes_requested_on_failure(
    tmp_path: Path,
) -> None:
    """A failed completion flow should regress the task to changes requested."""
    recorded_log_entry_list: list[tuple[str, str]] = []
    recorded_stage_value_list: list[str] = []
    recorded_finalize_call_list: list[tuple[str, bool]] = []
    recorded_failure_notification_list: list[tuple[str, str, str]] = []

    def fake_execute_git_completion_flow(
        *,
        task_id_str: str,
        run_account_id_str: str,
        task_title_str: str,
        commit_information_text_str: str | None,
        dev_log_text_list: list[str],
        worktree_path_str: str,
    ) -> codex_runner.GitCompletionExecutionResult:
        assert commit_information_text_str == "Implement the reviewed branch flow"
        return codex_runner.GitCompletionExecutionResult(
            merged_to_main=False,
            cleanup_succeeded=False,
            output_lines=["Rebase conflict on app.py"],
            feature_branch_name="task/12345678",
            failure_reason_text="rebase conflict on app.py",
        )

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    def fake_advance_stage(task_id_str: str, next_stage_value: str) -> None:
        recorded_stage_value_list.append(next_stage_value)

    def fake_finalize_completion_in_db(
        task_id_str: str,
        clear_worktree_path_bool: bool,
    ) -> None:
        recorded_finalize_call_list.append((task_id_str, clear_worktree_path_bool))

    def fake_send_task_failed_notification(
        task_id_str: str,
        task_title_str: str,
        failure_reason_str: str = "",
    ) -> bool:
        recorded_failure_notification_list.append(
            (task_id_str, task_title_str, failure_reason_str)
        )
        return True

    original_execute_git_completion_flow = codex_runner._execute_git_completion_flow
    original_write_log_to_db = codex_runner._write_log_to_db
    original_advance_stage_in_db = codex_runner._advance_stage_in_db
    original_finalize_completion_in_db = codex_runner._finalize_completion_in_db
    original_send_task_failed_notification = email_service.send_task_failed_notification

    try:
        codex_runner._execute_git_completion_flow = fake_execute_git_completion_flow
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._advance_stage_in_db = fake_advance_stage
        codex_runner._finalize_completion_in_db = fake_finalize_completion_in_db
        email_service.send_task_failed_notification = fake_send_task_failed_notification

        asyncio.run(
            codex_runner.run_codex_completion(
                task_id_str="12345678-finish-fail",
                run_account_id_str="run-account-4",
                task_title_str="Finalize branch",
                commit_information_text_str="Implement the reviewed branch flow",
                commit_information_source_str="task_title",
                dev_log_text_list=["Implementation already passed review."],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path / "repo-wt-12345678"),
            )
        )
    finally:
        codex_runner._execute_git_completion_flow = original_execute_git_completion_flow
        codex_runner._write_log_to_db = original_write_log_to_db
        codex_runner._advance_stage_in_db = original_advance_stage_in_db
        codex_runner._finalize_completion_in_db = original_finalize_completion_in_db
        email_service.send_task_failed_notification = (
            original_send_task_failed_notification
        )
        codex_runner._running_background_task_ids.clear()
        codex_runner._running_codex_processes.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert recorded_stage_value_list == ["changes_requested"]
    assert recorded_finalize_call_list == []
    assert recorded_failure_notification_list == [
        (
            "12345678-finish-fail",
            "Finalize branch",
            "rebase conflict on app.py",
        )
    ]
    assert any(
        "未能完成分支收尾与合并" in log_text for log_text, _ in recorded_log_entry_list
    )
