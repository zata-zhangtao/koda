"""Tests for terminal launcher command selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from dsl.services.terminal_launcher import (
    TerminalLaunchError,
    build_log_tail_terminal_command,
)


def test_build_log_tail_terminal_command_uses_custom_template() -> None:
    """Custom templates should take precedence over platform defaults."""
    log_file_path = Path("/tmp/koda-task.log")

    rendered_command = build_log_tail_terminal_command(
        log_file_path=log_file_path,
        operating_system_name="Linux",
        terminal_command_template="custom-terminal -- {tail_command_shell}",
        command_path_resolver=lambda _command_name: None,
    )

    assert rendered_command == [
        "custom-terminal",
        "--",
        "tail -f /tmp/koda-task.log",
    ]


def test_build_log_tail_terminal_command_uses_macos_default() -> None:
    """macOS should keep using Terminal.app via osascript by default."""
    log_file_path = Path("/tmp/koda-task.log")

    rendered_command = build_log_tail_terminal_command(
        log_file_path=log_file_path,
        operating_system_name="Darwin",
        command_path_resolver=lambda _command_name: None,
    )

    assert rendered_command == [
        "osascript",
        "-e",
        'tell application "Terminal" to do script "tail -f /tmp/koda-task.log"',
        "-e",
        'tell application "Terminal" to activate',
    ]


def test_build_log_tail_terminal_command_uses_wsl_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WSL should open a new Windows console running the current distro."""
    log_file_path = Path("/tmp/koda-task.log")
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")

    rendered_command = build_log_tail_terminal_command(
        log_file_path=log_file_path,
        operating_system_name="Linux",
        os_release_text="5.15.167.4-microsoft-standard-WSL2",
        command_path_resolver=lambda _command_name: None,
    )

    assert rendered_command == [
        "cmd.exe",
        "/c",
        "start",
        "",
        "wsl.exe",
        "-d",
        "Ubuntu",
        "bash",
        "-lc",
        "tail -f /tmp/koda-task.log",
    ]


def test_build_log_tail_terminal_command_uses_linux_terminal_launcher() -> None:
    """Desktop Linux should pick the first available terminal launcher."""
    log_file_path = Path("/tmp/koda-task.log")

    rendered_command = build_log_tail_terminal_command(
        log_file_path=log_file_path,
        operating_system_name="Linux",
        os_release_text="6.8.0-generic",
        command_path_resolver=lambda command_name: (
            f"/usr/bin/{command_name}"
            if command_name == "x-terminal-emulator"
            else None
        ),
    )

    assert rendered_command == [
        "x-terminal-emulator",
        "-e",
        "bash",
        "-lc",
        "tail -f /tmp/koda-task.log",
    ]


def test_build_log_tail_terminal_command_raises_without_linux_launcher() -> None:
    """Linux should fail clearly when no launcher can be resolved."""
    log_file_path = Path("/tmp/koda-task.log")

    with pytest.raises(TerminalLaunchError, match="KODA_OPEN_TERMINAL_COMMAND"):
        build_log_tail_terminal_command(
            log_file_path=log_file_path,
            operating_system_name="Linux",
            os_release_text="6.8.0-generic",
            command_path_resolver=lambda _command_name: None,
        )
