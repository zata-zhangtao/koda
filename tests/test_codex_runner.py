"""Tests for Codex runner phase orchestration."""

from __future__ import annotations

import asyncio
from pathlib import Path

from dsl.services import codex_runner


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
    ) -> None:
        """Initialize the fake process state.

        Args:
            output_line_list: Stdout lines produced by the fake process
            planned_return_code_int: Exit code returned by wait()
            pid_int: Fake process ID
        """
        self.stdout = FakeCodexStdout(output_line_list)
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
    assert "任务摘要 / requirement brief" in completion_prompt_text
    assert "不要 push" in completion_prompt_text


def test_build_codex_prd_prompt_requires_ai_requirement_name_contract() -> None:
    """PRD prompt should require both titles, fallback guidance, and the fixed file path."""
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
    assert "`tasks/prd-cf2b9461.md`" in prd_prompt_text
    assert "必须真正写入文件" in prd_prompt_text


def test_run_codex_task_executes_self_review_and_keeps_stage_on_pass(
    tmp_path: Path,
) -> None:
    """A passing self review should run automatically and keep the review stage."""
    recorded_prompt_text_list: list[str] = []
    recorded_log_entry_list: list[tuple[str, str]] = []
    recorded_stage_value_list: list[str] = []
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

    original_which = codex_runner.shutil.which
    original_create_codex_subprocess = codex_runner._create_codex_subprocess
    original_write_log_to_db = codex_runner._write_log_to_db
    original_advance_stage_in_db = codex_runner._advance_stage_in_db
    original_codex_log_dir = codex_runner._CODEX_LOG_DIR

    try:
        codex_runner.shutil.which = lambda executable_name_str: "/usr/bin/codex"
        codex_runner._create_codex_subprocess = fake_create_subprocess_exec
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._advance_stage_in_db = fake_advance_stage
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
        codex_runner._CODEX_LOG_DIR = original_codex_log_dir
        codex_runner._running_codex_processes.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert len(recorded_prompt_text_list) == 2
    assert "不要默认执行 `git commit`" in recorded_prompt_text_list[0]
    assert "SELF_REVIEW_STATUS: PASS" in recorded_prompt_text_list[1]
    assert recorded_stage_value_list == ["self_review_in_progress"]
    assert any(
        "开始执行代码评审" in log_text for log_text, _ in recorded_log_entry_list
    )
    assert any(
        "AI 自检完成，未发现阻塞性问题" in log_text
        for log_text, _ in recorded_log_entry_list
    )

    task_log_text = (tmp_path / "koda-12345678.log").read_text(encoding="utf-8")
    assert "=== Koda codex-exec" in task_log_text
    assert "=== Koda codex-review" in task_log_text


def test_run_codex_task_moves_to_changes_requested_on_review_findings(
    tmp_path: Path,
) -> None:
    """Blocking self-review findings should regress the task to changes requested."""
    recorded_log_entry_list: list[tuple[str, str]] = []
    recorded_stage_value_list: list[str] = []
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

    original_which = codex_runner.shutil.which
    original_create_codex_subprocess = codex_runner._create_codex_subprocess
    original_write_log_to_db = codex_runner._write_log_to_db
    original_advance_stage_in_db = codex_runner._advance_stage_in_db
    original_codex_log_dir = codex_runner._CODEX_LOG_DIR

    try:
        codex_runner.shutil.which = lambda executable_name_str: "/usr/bin/codex"
        codex_runner._create_codex_subprocess = fake_create_subprocess_exec
        codex_runner._write_log_to_db = fake_write_log_to_db
        codex_runner._advance_stage_in_db = fake_advance_stage
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
        codex_runner._CODEX_LOG_DIR = original_codex_log_dir
        codex_runner._running_codex_processes.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert recorded_stage_value_list == [
        "self_review_in_progress",
        "changes_requested",
    ]
    assert any(
        "AI 自检发现阻塞性问题" in log_text for log_text, _ in recorded_log_entry_list
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
        task_summary_str: str | None,
        dev_log_text_list: list[str],
        worktree_path_str: str,
    ) -> codex_runner.GitCompletionExecutionResult:
        assert task_id_str == "12345678-done-case"
        assert run_account_id_str == "run-account-3"
        assert task_title_str == "Finalize branch"
        assert task_summary_str == "Implement the reviewed branch flow"
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
                task_summary_str="Implement the reviewed branch flow",
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
        task_summary_str: str | None,
        dev_log_text_list: list[str],
        worktree_path_str: str,
    ) -> codex_runner.GitCompletionExecutionResult:
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
                task_summary_str="Implement the reviewed branch flow",
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

    def fake_execute_git_completion_flow(
        *,
        task_id_str: str,
        run_account_id_str: str,
        task_title_str: str,
        task_summary_str: str | None,
        dev_log_text_list: list[str],
        worktree_path_str: str,
    ) -> codex_runner.GitCompletionExecutionResult:
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
                task_id_str="12345678-finish-fail",
                run_account_id_str="run-account-4",
                task_title_str="Finalize branch",
                task_summary_str="Implement the reviewed branch flow",
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

    assert recorded_stage_value_list == ["changes_requested"]
    assert recorded_finalize_call_list == []
    assert any(
        "未能完成分支收尾与合并" in log_text for log_text, _ in recorded_log_entry_list
    )
