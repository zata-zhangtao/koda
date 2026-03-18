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


def test_run_codex_task_executes_self_review_and_keeps_stage_on_pass(
    monkeypatch,
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
        recorded_prompt_text_list.append(args[3])
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

    monkeypatch.setattr(codex_runner.shutil, "which", lambda executable_name_str: "/usr/bin/codex")
    monkeypatch.setattr(codex_runner.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(codex_runner, "_write_log_to_db", fake_write_log_to_db)
    monkeypatch.setattr(codex_runner, "_advance_stage_in_db", fake_advance_stage)
    monkeypatch.setattr(codex_runner, "_CODEX_LOG_DIR", tmp_path)

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

    assert len(recorded_prompt_text_list) == 2
    assert "不要默认执行 `git commit`" in recorded_prompt_text_list[0]
    assert "SELF_REVIEW_STATUS: PASS" in recorded_prompt_text_list[1]
    assert recorded_stage_value_list == ["self_review_in_progress"]
    assert any("开始执行代码评审" in log_text for log_text, _ in recorded_log_entry_list)
    assert any("AI 自检完成，未发现阻塞性问题" in log_text for log_text, _ in recorded_log_entry_list)

    task_log_text = (tmp_path / "koda-12345678.log").read_text(encoding="utf-8")
    assert "=== Koda codex-exec" in task_log_text
    assert "=== Koda codex-review" in task_log_text


def test_run_codex_task_moves_to_changes_requested_on_review_findings(
    monkeypatch,
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

    monkeypatch.setattr(codex_runner.shutil, "which", lambda executable_name_str: "/usr/bin/codex")
    monkeypatch.setattr(codex_runner.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(codex_runner, "_write_log_to_db", fake_write_log_to_db)
    monkeypatch.setattr(codex_runner, "_advance_stage_in_db", fake_advance_stage)
    monkeypatch.setattr(codex_runner, "_CODEX_LOG_DIR", tmp_path)

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

    assert recorded_stage_value_list == [
        "self_review_in_progress",
        "changes_requested",
    ]
    assert any("AI 自检发现阻塞性问题" in log_text for log_text, _ in recorded_log_entry_list)
