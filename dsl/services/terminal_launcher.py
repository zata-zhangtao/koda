"""Terminal launch helpers for local developer workflows.

This module centralizes the logic for opening a new terminal window that tails
the per-task Codex log file. The launcher supports macOS, WSL, common Linux
desktop terminal emulators, and an explicit environment-variable override.
"""

from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from utils.settings import config


class TerminalLaunchError(RuntimeError):
    """Raised when Koda cannot determine how to open a terminal window."""


def build_log_tail_terminal_command(
    log_file_path: Path,
    operating_system_name: str | None = None,
    os_release_text: str | None = None,
    terminal_command_template: str | None = None,
    command_path_resolver: Callable[[str], str | None] | None = None,
) -> list[str]:
    """Build the command used to open a new terminal window for a task log.

    Args:
        log_file_path: Absolute path to the task log file that should be tailed.
        operating_system_name: Optional OS override used for tests.
        os_release_text: Optional Linux kernel release text override used for tests.
        terminal_command_template: Optional command template override used for tests.
        command_path_resolver: Optional resolver used to detect installed binaries.

    Returns:
        list[str]: Command arguments suitable for `subprocess.Popen`.

    Raises:
        TerminalLaunchError: Raised when no suitable launcher can be determined.
    """
    detected_operating_system_name = operating_system_name or platform.system()
    resolved_command_path = command_path_resolver or shutil.which
    resolved_terminal_command_template = (
        terminal_command_template
        if terminal_command_template is not None
        else config.TERMINAL_OPEN_COMMAND_TEMPLATE
    )
    tail_shell_command = f"tail -f {shlex.quote(str(log_file_path))}"

    if resolved_terminal_command_template:
        return _build_template_command(
            terminal_command_template=resolved_terminal_command_template,
            log_file_path=log_file_path,
            tail_shell_command=tail_shell_command,
        )

    normalized_operating_system_name = detected_operating_system_name.lower()
    if normalized_operating_system_name == "darwin":
        return [
            "osascript",
            "-e",
            f'tell application "Terminal" to do script "{tail_shell_command}"',
            "-e",
            'tell application "Terminal" to activate',
        ]

    if normalized_operating_system_name == "linux":
        detected_os_release_text = os_release_text or _read_linux_release_text()
        if "microsoft" in detected_os_release_text.lower():
            return _build_wsl_command(tail_shell_command)
        return _build_linux_terminal_command(
            tail_shell_command=tail_shell_command,
            command_path_resolver=resolved_command_path,
        )

    raise TerminalLaunchError(
        f"暂不支持在当前系统打开终端：{detected_operating_system_name}。"
    )


def open_log_tail_terminal(log_file_path: Path) -> str:
    """Open a new terminal window that tails the provided task log file.

    Args:
        log_file_path: Absolute path to the task log file that should be tailed.

    Returns:
        str: The launcher command that was selected.

    Raises:
        TerminalLaunchError: Raised when the launcher cannot be resolved or executed.
    """
    terminal_launch_command = build_log_tail_terminal_command(log_file_path)
    try:
        subprocess.Popen(
            terminal_launch_command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as launch_error:
        launcher_name = terminal_launch_command[0] if terminal_launch_command else "unknown"
        raise TerminalLaunchError(
            "无法打开终端：未找到可执行命令 "
            f"`{launcher_name}`。如在 WSL/Linux 环境，请设置环境变量 "
            "`KODA_OPEN_TERMINAL_COMMAND`。"
        ) from launch_error

    return terminal_launch_command[0]


def _build_template_command(
    terminal_command_template: str,
    log_file_path: Path,
    tail_shell_command: str,
) -> list[str]:
    """Render and split a user-provided terminal launch command template."""
    template_context = {
        "log_file": str(log_file_path),
        "log_file_shell": shlex.quote(str(log_file_path)),
        "tail_command": tail_shell_command,
        "tail_command_shell": shlex.quote(tail_shell_command),
    }
    try:
        rendered_command = terminal_command_template.format(**template_context)
        return shlex.split(rendered_command)
    except KeyError as template_error:
        missing_placeholder_name = template_error.args[0]
        raise TerminalLaunchError(
            "环境变量 `KODA_OPEN_TERMINAL_COMMAND` 包含未知占位符："
            f"{missing_placeholder_name}。可用占位符："
            "`{log_file}`、`{log_file_shell}`、`{tail_command}`、"
            "`{tail_command_shell}`。"
        ) from template_error
    except ValueError as template_error:
        raise TerminalLaunchError(
            "环境变量 `KODA_OPEN_TERMINAL_COMMAND` 不是有效的命令模板："
            f"{template_error}"
        ) from template_error


def _build_wsl_command(tail_shell_command: str) -> list[str]:
    """Build the default command used inside WSL."""
    wsl_command_list = ["wsl.exe"]
    wsl_distro_name = os.getenv("WSL_DISTRO_NAME")
    if wsl_distro_name:
        wsl_command_list.extend(["-d", wsl_distro_name])
    wsl_command_list.extend(["bash", "-lc", tail_shell_command])
    return ["cmd.exe", "/c", "start", "", *wsl_command_list]


def _build_linux_terminal_command(
    tail_shell_command: str,
    command_path_resolver: Callable[[str], str | None],
) -> list[str]:
    """Build the default command used on Linux desktop environments."""
    linux_terminal_launchers: list[tuple[str, Callable[[str], list[str]]]] = [
        (
            "x-terminal-emulator",
            lambda shell_command: [
                "x-terminal-emulator",
                "-e",
                "bash",
                "-lc",
                shell_command,
            ],
        ),
        (
            "gnome-terminal",
            lambda shell_command: ["gnome-terminal", "--", "bash", "-lc", shell_command],
        ),
        (
            "konsole",
            lambda shell_command: ["konsole", "-e", "bash", "-lc", shell_command],
        ),
        (
            "xfce4-terminal",
            lambda shell_command: [
                "xfce4-terminal",
                "--command",
                f"bash -lc {shlex.quote(shell_command)}",
            ],
        ),
        (
            "xterm",
            lambda shell_command: ["xterm", "-e", "bash", "-lc", shell_command],
        ),
        (
            "wezterm",
            lambda shell_command: [
                "wezterm",
                "start",
                "--",
                "bash",
                "-lc",
                shell_command,
            ],
        ),
        (
            "alacritty",
            lambda shell_command: ["alacritty", "-e", "bash", "-lc", shell_command],
        ),
        (
            "kitty",
            lambda shell_command: ["kitty", "bash", "-lc", shell_command],
        ),
    ]

    for launcher_name, launcher_builder in linux_terminal_launchers:
        if command_path_resolver(launcher_name):
            return launcher_builder(tail_shell_command)

    raise TerminalLaunchError(
        "当前 Linux 环境未检测到可用的终端启动器。"
        "请安装常见终端命令，或设置环境变量 "
        "`KODA_OPEN_TERMINAL_COMMAND`，例如："
        "`x-terminal-emulator -e bash -lc {tail_command_shell}`。"
    )


def _read_linux_release_text() -> str:
    """Read Linux release text for WSL detection."""
    os_release_path = Path("/proc/sys/kernel/osrelease")
    if os_release_path.exists():
        return os_release_path.read_text(encoding="utf-8")
    return platform.release()
