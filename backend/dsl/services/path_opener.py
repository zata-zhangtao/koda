"""Configurable helpers for opening local paths in a developer's editor.

This module centralizes template rendering, command splitting, and process
launching for "open project/worktree" actions so the task and project routers
share one implementation.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from utils.settings import config


class PathOpenError(RuntimeError):
    """Base error raised when Koda cannot open a local path in an editor."""


class PathOpenTargetNotFoundError(PathOpenError):
    """Raised when the requested local path does not exist."""


class PathOpenCommandError(PathOpenError):
    """Raised when the command template is invalid or cannot be executed."""


def build_path_open_command(
    target_path: Path,
    target_kind: str,
    path_open_command_template: str | None = None,
) -> list[str]:
    """Build the configured editor-launch command for a local path.

    Args:
        target_path: Absolute or relative local path that should be opened.
        target_kind: Semantic kind exposed to the command template.
        path_open_command_template: Optional template override for tests.

    Returns:
        list[str]: Command arguments suitable for `subprocess.Popen`.

    Raises:
        PathOpenTargetNotFoundError: Raised when `target_path` does not exist.
        PathOpenCommandError: Raised when the template is invalid or renders
            into an empty command.
    """
    normalized_target_path = target_path.expanduser()
    if not normalized_target_path.exists():
        raise PathOpenTargetNotFoundError(
            f"Target path does not exist: {normalized_target_path}"
        )

    resolved_target_path = normalized_target_path.resolve()
    resolved_path_open_command_template = (
        path_open_command_template
        if path_open_command_template is not None
        else config.OPEN_PATH_COMMAND_TEMPLATE
    )
    template_context = {
        "target_path": str(resolved_target_path),
        "target_path_shell": shlex.quote(str(resolved_target_path)),
        "target_kind": target_kind,
    }

    try:
        rendered_command = resolved_path_open_command_template.format(
            **template_context
        )
        command_argument_list = shlex.split(rendered_command)
    except KeyError as template_error:
        missing_placeholder_name = template_error.args[0]
        raise PathOpenCommandError(
            "Environment variable `KODA_OPEN_PATH_COMMAND_TEMPLATE` contains an "
            f"unknown placeholder: {missing_placeholder_name}. Available "
            "placeholders: `{target_path}`, `{target_path_shell}`, "
            "`{target_kind}`."
        ) from template_error
    except ValueError as template_error:
        raise PathOpenCommandError(
            "Environment variable `KODA_OPEN_PATH_COMMAND_TEMPLATE` is not a "
            f"valid command template: {template_error}"
        ) from template_error

    if not command_argument_list:
        raise PathOpenCommandError(
            "Environment variable `KODA_OPEN_PATH_COMMAND_TEMPLATE` rendered "
            "an empty command."
        )

    return command_argument_list


def open_path_in_editor(
    target_path: Path,
    target_kind: str,
    path_open_command_template: str | None = None,
) -> list[str]:
    """Open the given local path using the configured editor command.

    Args:
        target_path: Absolute or relative local path that should be opened.
        target_kind: Semantic kind exposed to the command template.
        path_open_command_template: Optional template override for tests.

    Returns:
        list[str]: The launched command arguments.

    Raises:
        PathOpenTargetNotFoundError: Raised when `target_path` does not exist.
        PathOpenCommandError: Raised when the template is invalid or the
            executable cannot be found.
    """
    command_argument_list = build_path_open_command(
        target_path=target_path,
        target_kind=target_kind,
        path_open_command_template=path_open_command_template,
    )

    try:
        subprocess.Popen(
            command_argument_list,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as launch_error:
        executable_name = command_argument_list[0]
        raise PathOpenCommandError(
            "Configured editor executable not found in PATH: "
            f"`{executable_name}`. Check `KODA_OPEN_PATH_COMMAND_TEMPLATE`."
        ) from launch_error

    return command_argument_list
