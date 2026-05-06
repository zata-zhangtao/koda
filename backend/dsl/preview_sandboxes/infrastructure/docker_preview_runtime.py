"""Docker runtime adapter for managed preview sandboxes."""

from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from backend.dsl.preview_sandboxes.domain.errors import PreviewNotAvailableError
from backend.dsl.preview_sandboxes.domain.models import (
    PreviewProfile,
    PreviewRuntimeHandle,
    PreviewRuntimeKind,
)


@dataclass(frozen=True, slots=True)
class DockerPreviewRuntime:
    """Small Docker adapter for starting and stopping preview containers."""

    host_port_start_int: int = 31000
    host_port_end_int: int = 31999

    def start(
        self,
        *,
        task_id_str: str,
        worktree_path: str,
        preview_profile: PreviewProfile,
    ) -> PreviewRuntimeHandle:
        """Start a detached Docker container for a preview profile.

        Args:
            task_id_str: Task UUID string.
            worktree_path: Task worktree path.
            preview_profile: Validated preview profile.

        Returns:
            PreviewRuntimeHandle: Machine-local runtime handle.

        Raises:
            PreviewNotAvailableError: Raised when Docker cannot start a valid preview.
        """
        if preview_profile.internal_port is None:
            raise PreviewNotAvailableError("Preview profile has no internal port")

        self._ensure_docker_available()
        host_port_int = self._allocate_host_port()
        container_name_str = f"koda-preview-{task_id_str[:8]}"
        working_directory_text = preview_profile.working_directory or "."
        workspace_mount_path = Path(worktree_path).resolve()
        container_workdir_text = f"/workspace/{working_directory_text}".rstrip("/")
        runtime_image_str = self._resolve_image(preview_profile.runtime_kind)
        command_text = preview_profile.start_command
        if command_text is None:
            raise PreviewNotAvailableError("Preview profile has no start command")

        dependency_command_list = list(preview_profile.dependency_commands)
        chained_command_text = " && ".join([*dependency_command_list, command_text])
        docker_command_argument_list = [
            "docker",
            "run",
            "--rm",
            "-d",
            "--name",
            container_name_str,
            "-p",
            f"127.0.0.1:{host_port_int}:{preview_profile.internal_port}",
            "-v",
            f"{workspace_mount_path}:/workspace",
            "-w",
            container_workdir_text or "/workspace",
            runtime_image_str,
            "sh",
            "-lc",
            chained_command_text,
        ]
        completed_process = subprocess.run(
            docker_command_argument_list,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed_process.returncode != 0:
            raise PreviewNotAvailableError(
                "Docker preview start failed: "
                f"{(completed_process.stderr or completed_process.stdout).strip()}"
            )

        container_id_str = (completed_process.stdout or "").strip() or None
        preview_path_text = preview_profile.preview_path or "/"
        return PreviewRuntimeHandle(
            task_id=task_id_str,
            container_id=container_id_str,
            host_port=host_port_int,
            internal_port=preview_profile.internal_port,
            preview_url=f"http://127.0.0.1:{host_port_int}{preview_path_text}",
            log_tail=self._read_log_tail(container_id_str),
        )

    def stop(self, runtime_handle: PreviewRuntimeHandle) -> None:
        """Stop and remove a preview container if it still exists.

        Args:
            runtime_handle: Existing runtime handle.
        """
        if not runtime_handle.container_id:
            return
        subprocess.run(
            ["docker", "rm", "-f", runtime_handle.container_id],
            capture_output=True,
            text=True,
            check=False,
        )

    def diagnose(self, runtime_handle: PreviewRuntimeHandle) -> str:
        """Return a short log tail for the current container.

        Args:
            runtime_handle: Existing runtime handle.

        Returns:
            str: Sanitized log tail text.
        """
        return self._read_log_tail(runtime_handle.container_id)

    def _ensure_docker_available(self) -> None:
        completed_process = subprocess.run(
            ["docker", "version", "--format", "{{json .Client.Version}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed_process.returncode != 0:
            raise PreviewNotAvailableError("Docker is unavailable on this machine")

    def _allocate_host_port(self) -> int:
        for host_port_int in range(
            self.host_port_start_int, self.host_port_end_int + 1
        ):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_socket:
                tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    tcp_socket.bind(("127.0.0.1", host_port_int))
                except OSError:
                    continue
                return host_port_int
        raise PreviewNotAvailableError("No free host port is available for preview")

    def _resolve_image(self, runtime_kind: PreviewRuntimeKind) -> str:
        if runtime_kind == PreviewRuntimeKind.NODE:
            return "node:20-alpine"
        if runtime_kind == PreviewRuntimeKind.PYTHON:
            return "python:3.12-slim"
        if runtime_kind == PreviewRuntimeKind.STATIC:
            return "node:20-alpine"
        return "python:3.12-slim"

    def _read_log_tail(self, container_id_str: str | None) -> str:
        if not container_id_str:
            return ""
        completed_process = subprocess.run(
            ["docker", "logs", "--tail", "40", container_id_str],
            capture_output=True,
            text=True,
            check=False,
        )
        log_text = (completed_process.stdout or completed_process.stderr or "").strip()
        return _sanitize_log_text(log_text)


def _sanitize_log_text(log_text: str) -> str:
    """Redact simple token-like assignments from preview logs.

    Args:
        log_text: Raw container log tail.

    Returns:
        str: Sanitized log text.
    """
    sanitized_line_list: list[str] = []
    for raw_log_line in log_text.splitlines():
        if "=" in raw_log_line and raw_log_line.split("=", 1)[0].isupper():
            env_key_text, _env_value_text = raw_log_line.split("=", 1)
            sanitized_line_list.append(f"{env_key_text}=***")
            continue
        sanitized_line_list.append(raw_log_line)
    return "\n".join(sanitized_line_list)
