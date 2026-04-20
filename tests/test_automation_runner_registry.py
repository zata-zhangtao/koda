"""Tests for multi-runner registry and orchestration behavior."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from backend.dsl.services import automation_runner, codex_runner
from backend.dsl.services.runners.registry import (
    get_runner_by_kind,
    list_supported_runner_kind_list,
    resolve_runner_kind,
)


class _FakeStdout:
    """Async stdout stream for fake subprocesses."""

    def __init__(self, output_line_list: list[str]) -> None:
        """Initialize encoded lines.

        Args:
            output_line_list: Plain output lines.
        """
        self._remaining_line_bytes_list = [
            f"{output_line_str}\n".encode("utf-8")
            for output_line_str in output_line_list
        ]

    def __aiter__(self) -> "_FakeStdout":
        """Return iterator instance."""
        return self

    async def __anext__(self) -> bytes:
        """Yield one line at a time.

        Returns:
            bytes: Next line bytes.

        Raises:
            StopAsyncIteration: If no data left.
        """
        if not self._remaining_line_bytes_list:
            raise StopAsyncIteration
        return self._remaining_line_bytes_list.pop(0)


class _FakeProcess:
    """Minimal asyncio subprocess stub."""

    def __init__(self, output_line_list: list[str], return_code_int: int = 0) -> None:
        """Initialize fake process state.

        Args:
            output_line_list: Lines emitted from stdout.
            return_code_int: Planned wait() return code.
        """
        self.stdout = _FakeStdout(output_line_list)
        self.returncode: int | None = None
        self._return_code_int = return_code_int
        self.pid = 4321

    async def wait(self) -> int:
        """Return planned exit code.

        Returns:
            int: Exit code.
        """
        self.returncode = self._return_code_int
        return self._return_code_int

    def kill(self) -> None:
        """Mark process as killed."""
        self.returncode = -9


def _build_completed_process(
    command_argument_list: list[str],
    return_code_int: int,
    stdout_text_str: str,
) -> subprocess.CompletedProcess[str]:
    """Build a completed process stub.

    Args:
        command_argument_list: Command args.
        return_code_int: Exit code.
        stdout_text_str: stdout payload.

    Returns:
        subprocess.CompletedProcess[str]: Process result object.
    """
    return subprocess.CompletedProcess(
        args=command_argument_list,
        returncode=return_code_int,
        stdout=stdout_text_str,
        stderr="",
    )


def test_runner_registry_supports_codex_and_claude() -> None:
    """Registry should expose both built-in runner kinds."""
    supported_runner_kind_list = list_supported_runner_kind_list()

    assert supported_runner_kind_list == ["claude", "codex"]
    assert resolve_runner_kind(None) == "codex"
    assert resolve_runner_kind("CLAUDE") == "claude"
    assert get_runner_by_kind("codex").executable_name == "codex"
    assert get_runner_by_kind("claude").executable_name == "claude"


def test_runner_registry_rejects_unknown_runner_kind() -> None:
    """Unknown runner kind should raise actionable validation errors."""
    try:
        get_runner_by_kind("unknown")
        assert False, "expected ValueError"
    except ValueError as runner_error:
        assert "Supported values" in str(runner_error)


def test_run_codex_phase_records_runner_context_when_cli_missing(
    monkeypatch,
) -> None:
    """Missing runner CLI should include runner_kind context in failure logs."""
    recorded_log_entry_list: list[tuple[str, str]] = []

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    monkeypatch.setattr(codex_runner.config, "KODA_AUTOMATION_RUNNER", "claude")
    monkeypatch.setattr(codex_runner.shutil, "which", lambda _name: None)
    monkeypatch.setattr(codex_runner, "_write_log_to_db", fake_write_log_to_db)

    phase_result = asyncio.run(
        codex_runner._run_codex_phase(
            task_id_str="abcd1234-missing-runner",
            run_account_id_str="run-account-1",
            codex_prompt_text_str="hello",
            work_dir_path=Path("."),
            phase_log_label_str="claude-exec",
            phase_display_name_str="claude exec",
            cancelled_log_text_str="cancelled",
            overwrite_existing_log_bool=True,
        )
    )

    assert phase_result.success is False
    assert phase_result.output_lines == []
    assert any(
        "runner_kind=claude" in log_text and "executable=claude" in log_text
        for log_text, _ in recorded_log_entry_list
    )


def test_run_task_prd_forwards_auto_confirm_flag(monkeypatch) -> None:
    """The runner-agnostic PRD wrapper should preserve the auto-confirm flag."""
    recorded_call_dict: dict[str, object] = {}

    async def fake_run_codex_prd(
        *,
        task_id_str: str,
        run_account_id_str: str,
        task_title_str: str,
        dev_log_text_list: list[str],
        work_dir_path: Path,
        worktree_path_str: str | None = None,
        auto_confirm_prd_and_execute_bool: bool | None = None,
    ) -> None:
        recorded_call_dict.update(
            {
                "task_id_str": task_id_str,
                "run_account_id_str": run_account_id_str,
                "task_title_str": task_title_str,
                "dev_log_text_list": dev_log_text_list,
                "work_dir_path": work_dir_path,
                "worktree_path_str": worktree_path_str,
                "auto_confirm_prd_and_execute_bool": (
                    auto_confirm_prd_and_execute_bool
                ),
            }
        )

    monkeypatch.setattr(automation_runner, "run_codex_prd", fake_run_codex_prd)

    asyncio.run(
        automation_runner.run_task_prd(
            task_id_str="12345678-prd-wrapper",
            run_account_id_str="run-account-1",
            task_title_str="Forward auto confirm",
            dev_log_text_list=["ctx line"],
            work_dir_path=Path("/tmp/prd-wrapper"),
            worktree_path_str="/tmp/repo-wt-prd-wrapper",
            auto_confirm_prd_and_execute_bool=True,
        )
    )

    assert recorded_call_dict["task_id_str"] == "12345678-prd-wrapper"
    assert recorded_call_dict["run_account_id_str"] == "run-account-1"
    assert recorded_call_dict["task_title_str"] == "Forward auto confirm"
    assert recorded_call_dict["dev_log_text_list"] == ["ctx line"]
    assert recorded_call_dict["work_dir_path"] == Path("/tmp/prd-wrapper")
    assert recorded_call_dict["worktree_path_str"] == "/tmp/repo-wt-prd-wrapper"
    assert recorded_call_dict["auto_confirm_prd_and_execute_bool"] is True


def test_run_task_review_forwards_review_contract(monkeypatch) -> None:
    """The runner-agnostic review wrapper should preserve the review contract."""
    recorded_call_dict: dict[str, object] = {}

    async def fake_run_codex_review_only(
        *,
        task_id_str: str,
        run_account_id_str: str,
        task_title_str: str,
        dev_log_text_list: list[str],
        work_dir_path: Path,
        worktree_path_str: str | None = None,
    ) -> None:
        recorded_call_dict.update(
            {
                "task_id_str": task_id_str,
                "run_account_id_str": run_account_id_str,
                "task_title_str": task_title_str,
                "dev_log_text_list": dev_log_text_list,
                "work_dir_path": work_dir_path,
                "worktree_path_str": worktree_path_str,
            }
        )

    monkeypatch.setattr(
        automation_runner,
        "run_codex_review_only",
        fake_run_codex_review_only,
    )

    asyncio.run(
        automation_runner.run_task_review(
            task_id_str="12345678-review-wrapper",
            run_account_id_str="run-account-1",
            task_title_str="Forward standalone review",
            dev_log_text_list=["ctx line"],
            work_dir_path=Path("/tmp/review-wrapper"),
            worktree_path_str="/tmp/repo-wt-review-wrapper",
        )
    )

    assert recorded_call_dict["task_id_str"] == "12345678-review-wrapper"
    assert recorded_call_dict["run_account_id_str"] == "run-account-1"
    assert recorded_call_dict["task_title_str"] == "Forward standalone review"
    assert recorded_call_dict["dev_log_text_list"] == ["ctx line"]
    assert recorded_call_dict["work_dir_path"] == Path("/tmp/review-wrapper")
    assert recorded_call_dict["worktree_path_str"] == "/tmp/repo-wt-review-wrapper"


def test_run_task_completion_forwards_commit_information_contract(
    monkeypatch,
) -> None:
    """The runner-agnostic completion wrapper should preserve commit information."""
    recorded_call_dict: dict[str, object] = {}

    async def fake_run_codex_completion(
        *,
        task_id_str: str,
        run_account_id_str: str,
        task_title_str: str,
        commit_information_text_str: str,
        commit_information_source_str: str,
        dev_log_text_list: list[str],
        work_dir_path: Path,
        worktree_path_str: str,
    ) -> None:
        recorded_call_dict.update(
            {
                "task_id_str": task_id_str,
                "run_account_id_str": run_account_id_str,
                "task_title_str": task_title_str,
                "commit_information_text_str": commit_information_text_str,
                "commit_information_source_str": commit_information_source_str,
                "dev_log_text_list": dev_log_text_list,
                "work_dir_path": work_dir_path,
                "worktree_path_str": worktree_path_str,
            }
        )

    monkeypatch.setattr(
        automation_runner,
        "run_codex_completion",
        fake_run_codex_completion,
    )

    asyncio.run(
        automation_runner.run_task_completion(
            task_id_str="12345678-complete-wrapper",
            run_account_id_str="run-account-1",
            task_title_str="Forward completion info",
            commit_information_text_str="Summarize the completed branch behavior",
            commit_information_source_str="ai_summary",
            dev_log_text_list=["ctx line"],
            work_dir_path=Path("/tmp/complete-wrapper"),
            worktree_path_str="/tmp/repo-wt-complete-wrapper",
        )
    )

    assert recorded_call_dict["task_id_str"] == "12345678-complete-wrapper"
    assert recorded_call_dict["run_account_id_str"] == "run-account-1"
    assert recorded_call_dict["task_title_str"] == "Forward completion info"
    assert (
        recorded_call_dict["commit_information_text_str"]
        == "Summarize the completed branch behavior"
    )
    assert recorded_call_dict["commit_information_source_str"] == "ai_summary"
    assert recorded_call_dict["dev_log_text_list"] == ["ctx line"]
    assert recorded_call_dict["work_dir_path"] == Path("/tmp/complete-wrapper")
    assert recorded_call_dict["worktree_path_str"] == "/tmp/repo-wt-complete-wrapper"


def test_run_codex_task_with_claude_runner_keeps_stage_flow(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Claude runner should keep the same implementation -> review -> lint stage flow."""
    recorded_log_entry_list: list[tuple[str, str]] = []
    recorded_stage_value_list: list[str] = []
    fake_process_queue = [
        _FakeProcess(output_line_list=["implemented"], return_code_int=0),
        _FakeProcess(
            output_line_list=[
                "reviewed",
                "SELF_REVIEW_SUMMARY: looks good",
                "SELF_REVIEW_STATUS: PASS",
            ],
            return_code_int=0,
        ),
    ]

    async def fake_create_claude_subprocess(
        claude_executable_path_str: str,
        claude_prompt_text_str: str,
        work_dir_path: Path,
    ) -> _FakeProcess:
        del claude_executable_path_str, claude_prompt_text_str, work_dir_path
        return fake_process_queue.pop(0)

    def fake_write_log_to_db(
        task_id_str: str,
        run_account_id_str: str,
        text_content_str: str,
        state_tag_value: str = "OPTIMIZATION",
    ) -> None:
        recorded_log_entry_list.append((text_content_str, state_tag_value))

    def fake_advance_stage(task_id_str: str, next_stage_value: str) -> None:
        del task_id_str
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
        del (
            task_id_str,
            run_account_id_str,
            task_log_path,
            cwd_path,
            command_log_label_str,
        )
        return _build_completed_process(
            command_argument_list=command_argument_list,
            return_code_int=0,
            stdout_text_str="pre-commit checks passed",
        )

    monkeypatch.setattr(codex_runner.config, "KODA_AUTOMATION_RUNNER", "claude")
    monkeypatch.setattr(
        codex_runner.shutil,
        "which",
        lambda executable_name_str: (
            "/usr/bin/claude" if executable_name_str == "claude" else None
        ),
    )
    monkeypatch.setattr(
        codex_runner,
        "_create_claude_subprocess",
        fake_create_claude_subprocess,
    )
    monkeypatch.setattr(codex_runner, "_write_log_to_db", fake_write_log_to_db)
    monkeypatch.setattr(codex_runner, "_advance_stage_in_db", fake_advance_stage)
    monkeypatch.setattr(codex_runner, "_run_logged_command", fake_run_logged_command)
    monkeypatch.setattr(codex_runner, "_CODEX_LOG_DIR", tmp_path)

    try:
        asyncio.run(
            codex_runner.run_codex_task(
                task_id_str="12345678-claude-pass",
                run_account_id_str="run-account-1",
                task_title_str="Implement with claude",
                dev_log_text_list=["ctx"],
                work_dir_path=tmp_path,
                worktree_path_str=str(tmp_path / "repo-wt-12345678"),
            )
        )
    finally:
        codex_runner._running_codex_processes.clear()
        codex_runner._running_background_task_ids.clear()
        codex_runner._user_cancelled_tasks.clear()

    assert recorded_stage_value_list == ["self_review_in_progress", "test_in_progress"]
    assert any(
        "runner_kind=claude" in log_text for log_text, _ in recorded_log_entry_list
    )

    task_log_text = (tmp_path / "koda-12345678.log").read_text(encoding="utf-8")
    assert "=== Koda claude-exec" in task_log_text
    assert "=== Koda claude-review" in task_log_text
    assert "runner_kind=claude" in task_log_text
