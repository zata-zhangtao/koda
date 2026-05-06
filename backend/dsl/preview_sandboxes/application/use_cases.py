"""Application use cases for managed preview sandboxes."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.dsl.models.dev_log import DevLog
from backend.dsl.models.enums import DevLogStateTag, TaskArtifactType
from backend.dsl.models.task import Task
from backend.dsl.models.task_artifact import TaskArtifact
from backend.dsl.preview_sandboxes.domain.errors import (
    InvalidPreviewProfileError,
    PreviewCompletionBlockedError,
    PreviewNotAvailableError,
    TaskNotFoundError,
)
from backend.dsl.preview_sandboxes.domain.models import (
    PreviewApplicability,
    PreviewFailureKind,
    PreviewProfile,
    PreviewProfileFingerprint,
    PreviewRuntimeHandle,
    PreviewRuntimeKind,
    PreviewStatus,
    PreviewStatusSnapshot,
)
from backend.dsl.preview_sandboxes.infrastructure.docker_preview_runtime import (
    DockerPreviewRuntime,
)
from backend.dsl.preview_sandboxes.infrastructure.ai_preview_profile_generator import (
    CliAiPreviewProfileGenerator,
)
from backend.dsl.schemas.dev_log_schema import DevLogCreateSchema
from backend.dsl.services.log_service import LogService
from utils.settings import config

_PREVIEW_PROFILE_SOURCE_PATH = "preview-sandbox/profile"
_PREVIEW_BYPASS_MARKER = "<!-- preview-sandbox:bypass -->"
_PREVIEW_FAILURE_MARKER = "<!-- preview-sandbox:failure -->"
_PREVIEW_STARTED_MARKER = "<!-- preview-sandbox:started -->"
_PREVIEW_STOPPED_MARKER = "<!-- preview-sandbox:stopped -->"
_PREVIEW_START_ATTEMPTED_MARKER = "<!-- preview-sandbox:start-attempted -->"
_UNSAFE_COMMAND_PATTERN = re.compile(
    r"(\b docker\b|/var/run/docker\.sock|~[/\\]|\.ssh|git-credentials|>\s*|<\s*|\|\s*|&&|;)"
)
_ALLOWED_DEPENDENCY_COMMAND_PREFIX_TUPLE = (
    "npm install",
    "npm ci",
    "pnpm install",
    "yarn install",
    "uv sync",
    "pip install",
)


class InMemoryPreviewRuntimeRegistry:
    """Store machine-local preview runtime handles."""

    def __init__(self) -> None:
        """Initialize the runtime handle registry."""
        self._runtime_handle_by_task_id: dict[str, PreviewRuntimeHandle] = {}

    def get(self, task_id_str: str) -> PreviewRuntimeHandle | None:
        """Return the current runtime handle for a task.

        Args:
            task_id_str: Task UUID string.

        Returns:
            PreviewRuntimeHandle | None: Runtime handle if present.
        """
        return self._runtime_handle_by_task_id.get(task_id_str)

    def set(self, runtime_handle: PreviewRuntimeHandle) -> None:
        """Store a runtime handle.

        Args:
            runtime_handle: Runtime handle to store.
        """
        self._runtime_handle_by_task_id[runtime_handle.task_id] = runtime_handle

    def remove(self, task_id_str: str) -> PreviewRuntimeHandle | None:
        """Remove a runtime handle.

        Args:
            task_id_str: Task UUID string.

        Returns:
            PreviewRuntimeHandle | None: Removed handle if present.
        """
        return self._runtime_handle_by_task_id.pop(task_id_str, None)


preview_runtime_registry = InMemoryPreviewRuntimeRegistry()
docker_preview_runtime = DockerPreviewRuntime()
ai_preview_profile_generator = CliAiPreviewProfileGenerator()


def is_preview_enabled() -> bool:
    """Return whether preview sandbox automation is enabled.

    Returns:
        bool: True when preview is enabled.
    """
    return getattr(config, "KODA_PREVIEW_ENABLED", True)


def validate_preview_profile_dict(
    raw_preview_profile_dict: dict[str, Any],
    worktree_path: str | None,
) -> PreviewProfile:
    """Validate a raw preview profile dictionary.

    Args:
        raw_preview_profile_dict: Raw JSON-compatible profile data.
        worktree_path: Task worktree path used for path boundary validation.

    Returns:
        PreviewProfile: Validated profile.

    Raises:
        InvalidPreviewProfileError: Raised when the profile is unsafe or invalid.
    """
    try:
        preview_applicability = PreviewApplicability(
            raw_preview_profile_dict["applicability"]
        )
    except (KeyError, ValueError) as profile_error:
        raise InvalidPreviewProfileError(
            "Invalid preview applicability"
        ) from profile_error

    applicability_reason_str = str(
        raw_preview_profile_dict.get("applicability_reason") or ""
    ).strip()
    if not applicability_reason_str:
        raise InvalidPreviewProfileError("applicability_reason is required")

    runtime_kind = PreviewRuntimeKind(
        raw_preview_profile_dict.get("runtime_kind") or PreviewRuntimeKind.UNKNOWN.value
    )
    dependency_command_tuple = tuple(
        str(command_text).strip()
        for command_text in raw_preview_profile_dict.get("dependency_commands", [])
        if str(command_text).strip()
    )
    start_command_str = _optional_str(raw_preview_profile_dict.get("start_command"))
    working_directory_str = _optional_str(
        raw_preview_profile_dict.get("working_directory")
    )
    internal_port_int = raw_preview_profile_dict.get("internal_port")
    healthcheck_path_str = _optional_str(
        raw_preview_profile_dict.get("healthcheck_path")
    )
    preview_path_str = _optional_str(raw_preview_profile_dict.get("preview_path"))

    if preview_applicability == PreviewApplicability.NOT_APPLICABLE:
        if start_command_str or dependency_command_tuple:
            raise InvalidPreviewProfileError(
                "not_applicable profiles must not include commands"
            )
        return _build_preview_profile(
            raw_preview_profile_dict,
            preview_applicability,
            applicability_reason_str,
            runtime_kind,
            None,
            (),
            None,
            None,
            None,
            None,
        )

    if preview_applicability == PreviewApplicability.UNCERTAIN:
        if worktree_path and working_directory_str:
            _validate_relative_working_directory(working_directory_str, worktree_path)
        if healthcheck_path_str:
            _validate_url_path(healthcheck_path_str, "healthcheck_path")
        if preview_path_str:
            _validate_url_path(preview_path_str, "preview_path")
        for dependency_command_str in dependency_command_tuple:
            _validate_dependency_command(
                dependency_command_str,
                runtime_kind=runtime_kind,
            )
        if start_command_str:
            _validate_command(start_command_str)
        return _build_preview_profile(
            raw_preview_profile_dict,
            preview_applicability,
            applicability_reason_str,
            runtime_kind,
            working_directory_str,
            dependency_command_tuple,
            start_command_str,
            _validate_optional_port(internal_port_int),
            healthcheck_path_str,
            preview_path_str,
        )

    if not worktree_path:
        raise InvalidPreviewProfileError("worktree_path is required for preview")
    if not working_directory_str:
        raise InvalidPreviewProfileError("working_directory is required")
    if not start_command_str:
        raise InvalidPreviewProfileError("start_command is required")
    validated_internal_port_int = _validate_optional_port(internal_port_int)
    if validated_internal_port_int is None:
        raise InvalidPreviewProfileError("internal_port is required")
    _validate_relative_working_directory(working_directory_str, worktree_path)
    _validate_url_path(healthcheck_path_str, "healthcheck_path")
    _validate_url_path(preview_path_str, "preview_path")
    _validate_command(start_command_str)
    for dependency_command_str in dependency_command_tuple:
        _validate_dependency_command(
            dependency_command_str,
            runtime_kind=runtime_kind,
        )

    return _build_preview_profile(
        raw_preview_profile_dict,
        preview_applicability,
        applicability_reason_str,
        runtime_kind,
        working_directory_str,
        dependency_command_tuple,
        start_command_str,
        validated_internal_port_int,
        healthcheck_path_str,
        preview_path_str,
    )


@dataclass(frozen=True, slots=True)
class PreviewSandboxUseCase:
    """Coordinate preview profile persistence and status operations."""

    db_session: Session

    def get_status(self, task_id_str: str) -> PreviewStatusSnapshot:
        """Return preview status for a task.

        Args:
            task_id_str: Task UUID string.

        Returns:
            PreviewStatusSnapshot: Current preview status.
        """
        task_obj = self._get_task(task_id_str)
        if not is_preview_enabled():
            return PreviewStatusSnapshot(
                task_id=task_id_str,
                status=PreviewStatus.DISABLED,
            )

        latest_profile_artifact = self._get_latest_profile_artifact(task_id_str)
        latest_profile = _load_profile_from_artifact(
            latest_profile_artifact,
            task_obj.worktree_path,
        )
        latest_failure_log = self._get_latest_preview_failure_log(task_id_str)
        bypass_confirmed_bool = self._has_preview_bypass(task_id_str)
        runtime_handle = preview_runtime_registry.get(task_id_str)

        if runtime_handle is not None:
            return PreviewStatusSnapshot(
                task_id=task_id_str,
                status=PreviewStatus.RUNNING,
                applicability=(
                    latest_profile.applicability if latest_profile is not None else None
                ),
                preview_url=runtime_handle.preview_url,
                profile_summary=(
                    latest_profile_artifact.content_markdown
                    if latest_profile_artifact is not None
                    else None
                ),
                bypass_confirmed=bypass_confirmed_bool,
                log_tail=runtime_handle.log_tail,
                container_id=runtime_handle.container_id,
                host_port=runtime_handle.host_port,
                internal_port=runtime_handle.internal_port,
            )

        if latest_profile is not None:
            if latest_profile.applicability == PreviewApplicability.NOT_APPLICABLE:
                return PreviewStatusSnapshot(
                    task_id=task_id_str,
                    status=PreviewStatus.NOT_APPLICABLE,
                    applicability=latest_profile.applicability,
                    profile_summary=latest_profile_artifact.content_markdown,
                    bypass_confirmed=bypass_confirmed_bool,
                )
            if latest_profile.applicability == PreviewApplicability.UNCERTAIN:
                return PreviewStatusSnapshot(
                    task_id=task_id_str,
                    status=PreviewStatus.UNCERTAIN,
                    applicability=latest_profile.applicability,
                    profile_summary=latest_profile_artifact.content_markdown,
                    bypass_confirmed=bypass_confirmed_bool,
                )

        if latest_failure_log is not None:
            failure_kind = _extract_failure_kind(latest_failure_log.text_content)
            return PreviewStatusSnapshot(
                task_id=task_id_str,
                status=PreviewStatus.NEEDS_HUMAN_ACTION,
                applicability=(
                    latest_profile.applicability if latest_profile is not None else None
                ),
                profile_summary=(
                    latest_profile_artifact.content_markdown
                    if latest_profile_artifact is not None
                    else None
                ),
                failure_kind=failure_kind,
                failure_summary=_clean_marker_text(latest_failure_log.text_content),
                bypass_confirmed=bypass_confirmed_bool,
            )

        latest_preview_stop_log = self._get_latest_preview_stop_log(task_id_str)
        latest_preview_start_attempt_log = self._get_latest_preview_start_attempt_log(
            task_id_str
        )

        if (
            latest_profile is not None
            and latest_preview_stop_log is not None
            and (
                latest_preview_start_attempt_log is None
                or latest_preview_stop_log.created_at
                >= latest_preview_start_attempt_log.created_at
            )
        ):
            return PreviewStatusSnapshot(
                task_id=task_id_str,
                status=PreviewStatus.STOPPED,
                applicability=latest_profile.applicability,
                profile_summary=latest_profile_artifact.content_markdown,
                bypass_confirmed=bypass_confirmed_bool,
            )

        if (
            latest_profile is not None
            and task_obj.worktree_path
            and latest_preview_start_attempt_log is not None
        ):
            return PreviewStatusSnapshot(
                task_id=task_id_str,
                status=PreviewStatus.RUNTIME_STATE_LOST,
                applicability=latest_profile.applicability,
                profile_summary=latest_profile_artifact.content_markdown,
                bypass_confirmed=bypass_confirmed_bool,
            )

        return PreviewStatusSnapshot(
            task_id=task_id_str,
            status=PreviewStatus.NOT_STARTED,
            bypass_confirmed=bypass_confirmed_bool,
        )

    def store_profile(
        self,
        task_id_str: str,
        raw_preview_profile_dict: dict[str, Any],
    ) -> PreviewStatusSnapshot:
        """Validate and persist a preview profile.

        Args:
            task_id_str: Task UUID string.
            raw_preview_profile_dict: Raw profile dictionary.

        Returns:
            PreviewStatusSnapshot: Resulting status.
        """
        task_obj = self._get_task(task_id_str)
        preview_profile = validate_preview_profile_dict(
            raw_preview_profile_dict,
            task_obj.worktree_path,
        )
        profile_json_text = json.dumps(
            _profile_to_dict(preview_profile),
            ensure_ascii=False,
            sort_keys=True,
        )
        profile_summary_text = _build_profile_summary(preview_profile)
        profile_artifact = TaskArtifact(
            task_id=task_obj.id,
            artifact_type=TaskArtifactType.PREVIEW_PROFILE,
            source_path=_PREVIEW_PROFILE_SOURCE_PATH,
            content_markdown=profile_summary_text,
            file_manifest_json=profile_json_text,
        )
        self.db_session.add(profile_artifact)
        self.db_session.commit()
        self.db_session.refresh(profile_artifact)
        self._write_log(
            task_obj,
            f"Preview profile generated for Docker sandbox.\n\n{profile_summary_text}",
            DevLogStateTag.OPTIMIZATION,
        )
        return self.get_status(task_id_str)

    def start(self, task_id_str: str) -> PreviewStatusSnapshot:
        """Start or reuse a preview sandbox for a task.

        Args:
            task_id_str: Task UUID string.

        Returns:
            PreviewStatusSnapshot: Updated preview status.
        """
        task_obj = self._get_task(task_id_str)
        if not task_obj.worktree_path:
            raise PreviewNotAvailableError("Task has no worktree_path")
        existing_runtime_handle = preview_runtime_registry.get(task_id_str)
        if existing_runtime_handle is not None:
            return self.get_status(task_id_str)

        status_snapshot = self.get_status(task_id_str)
        if status_snapshot.status in {
            PreviewStatus.DISABLED,
            PreviewStatus.NOT_APPLICABLE,
        }:
            return status_snapshot

        latest_profile_artifact = self._get_latest_profile_artifact(task_id_str)
        latest_profile = _load_profile_from_artifact(
            latest_profile_artifact,
            task_obj.worktree_path,
        )
        if latest_profile is None:
            inferred_preview_profile = infer_preview_profile_for_worktree(
                task_obj.worktree_path,
            )
            if inferred_preview_profile is not None:
                if (
                    inferred_preview_profile.applicability
                    == PreviewApplicability.UNCERTAIN
                ):
                    ai_inferred_preview_profile = (
                        generate_ai_preview_profile_for_worktree(
                            task_obj.worktree_path,
                            deterministic_profile=inferred_preview_profile,
                        )
                    )
                    if ai_inferred_preview_profile is not None:
                        inferred_preview_profile = ai_inferred_preview_profile
                self.store_profile(
                    task_id_str,
                    _profile_to_dict(inferred_preview_profile),
                )
                latest_profile_artifact = self._get_latest_profile_artifact(task_id_str)
                latest_profile = _load_profile_from_artifact(
                    latest_profile_artifact,
                    task_obj.worktree_path,
                )
        elif latest_profile.applicability == PreviewApplicability.UNCERTAIN:
            ai_inferred_preview_profile = generate_ai_preview_profile_for_worktree(
                task_obj.worktree_path,
                deterministic_profile=latest_profile,
            )
            if ai_inferred_preview_profile is not None:
                self.store_profile(
                    task_id_str,
                    _profile_to_dict(ai_inferred_preview_profile),
                )
                latest_profile_artifact = self._get_latest_profile_artifact(task_id_str)
                latest_profile = _load_profile_from_artifact(
                    latest_profile_artifact,
                    task_obj.worktree_path,
                )
        if latest_profile is None:
            raise PreviewNotAvailableError(
                "No validated preview profile exists for this task"
            )
        if latest_profile.applicability != PreviewApplicability.APPLICABLE:
            return self.get_status(task_id_str)
        if latest_profile.internal_port is None:
            raise PreviewNotAvailableError("Preview profile has no internal port")

        self._write_log(
            task_obj,
            (f"{_PREVIEW_START_ATTEMPTED_MARKER}\nPreview sandbox start attempted."),
            DevLogStateTag.OPTIMIZATION,
        )
        try:
            runtime_handle = docker_preview_runtime.start(
                task_id_str=task_id_str,
                worktree_path=task_obj.worktree_path,
                preview_profile=latest_profile,
            )
        except PreviewNotAvailableError as preview_error:
            failure_summary_str = str(preview_error).strip() or (
                "Preview sandbox could not start."
            )
            return self.record_failure(
                task_id_str,
                PreviewFailureKind.SANDBOX_ERROR,
                failure_summary_str,
            )
        preview_runtime_registry.set(runtime_handle)
        self._write_log(
            task_obj,
            f"{_PREVIEW_STARTED_MARKER}\nPreview sandbox started: "
            f"{runtime_handle.preview_url}",
            DevLogStateTag.FIXED,
        )
        return self.get_status(task_id_str)

    def stop(self, task_id_str: str) -> PreviewStatusSnapshot:
        """Stop a running preview sandbox handle.

        Args:
            task_id_str: Task UUID string.

        Returns:
            PreviewStatusSnapshot: Updated status.
        """
        task_obj = self._get_task(task_id_str)
        removed_runtime_handle = preview_runtime_registry.remove(task_id_str)
        if removed_runtime_handle is not None:
            docker_preview_runtime.stop(removed_runtime_handle)
        self._write_log(
            task_obj,
            f"{_PREVIEW_STOPPED_MARKER}\nPreview sandbox stopped.",
            DevLogStateTag.OPTIMIZATION,
        )
        return PreviewStatusSnapshot(
            task_id=task_id_str,
            status=PreviewStatus.STOPPED,
            bypass_confirmed=self._has_preview_bypass(task_id_str),
        )

    def confirm_bypass(self, task_id_str: str) -> PreviewStatusSnapshot:
        """Record explicit user preview bypass.

        Args:
            task_id_str: Task UUID string.

        Returns:
            PreviewStatusSnapshot: Updated status.
        """
        task_obj = self._get_task(task_id_str)
        self._write_log(
            task_obj,
            (
                f"{_PREVIEW_BYPASS_MARKER}\n"
                "Preview bypass confirmed by user for the current task."
            ),
            DevLogStateTag.FIXED,
        )
        return self.get_status(task_id_str)

    def record_failure(
        self,
        task_id_str: str,
        failure_kind: PreviewFailureKind,
        failure_summary: str,
    ) -> PreviewStatusSnapshot:
        """Record a preview startup failure.

        Args:
            task_id_str: Task UUID string.
            failure_kind: Classified failure kind.
            failure_summary: Human-readable summary.

        Returns:
            PreviewStatusSnapshot: Updated status.
        """
        task_obj = self._get_task(task_id_str)
        self._write_log(
            task_obj,
            (
                f"{_PREVIEW_FAILURE_MARKER}\n"
                f"failure_kind={failure_kind.value}\n"
                f"{failure_summary}"
            ),
            DevLogStateTag.BUG,
        )
        return self.get_status(task_id_str)

    def assert_complete_allowed(self, task_id_str: str) -> None:
        """Raise when Complete must wait for preview retry or bypass.

        Args:
            task_id_str: Task UUID string.

        Raises:
            PreviewCompletionBlockedError: Raised when non-code preview failure
                has not been bypassed.
        """
        status_snapshot = self.get_status(task_id_str)
        if status_snapshot.bypass_confirmed:
            return
        if status_snapshot.status != PreviewStatus.NEEDS_HUMAN_ACTION:
            return
        if status_snapshot.failure_kind in {
            PreviewFailureKind.DEPENDENCY_ERROR,
            PreviewFailureKind.ENVIRONMENT_ERROR,
            PreviewFailureKind.SANDBOX_ERROR,
            PreviewFailureKind.UNKNOWN,
        }:
            raise PreviewCompletionBlockedError(
                "Preview failed due to a non-code or unknown issue. Retry preview "
                "or confirm preview bypass before Complete."
            )

    def _get_task(self, task_id_str: str) -> Task:
        task_obj = self.db_session.get(Task, task_id_str)
        if task_obj is None:
            raise TaskNotFoundError(f"Task with id {task_id_str} not found")
        return task_obj

    def _get_latest_profile_artifact(self, task_id_str: str) -> TaskArtifact | None:
        return (
            self.db_session.query(TaskArtifact)
            .filter(
                TaskArtifact.task_id == task_id_str,
                TaskArtifact.artifact_type == TaskArtifactType.PREVIEW_PROFILE,
            )
            .order_by(TaskArtifact.captured_at.desc(), TaskArtifact.id.desc())
            .first()
        )

    def _get_latest_preview_failure_log(self, task_id_str: str) -> DevLog | None:
        return (
            self.db_session.query(DevLog)
            .filter(
                DevLog.task_id == task_id_str,
                DevLog.text_content.contains(_PREVIEW_FAILURE_MARKER),
            )
            .order_by(DevLog.created_at.desc(), DevLog.id.desc())
            .first()
        )

    def _has_preview_bypass(self, task_id_str: str) -> bool:
        return (
            self.db_session.query(DevLog.id)
            .filter(
                DevLog.task_id == task_id_str,
                DevLog.text_content.contains(_PREVIEW_BYPASS_MARKER),
            )
            .first()
            is not None
        )

    def _get_latest_preview_stop_log(self, task_id_str: str) -> DevLog | None:
        return (
            self.db_session.query(DevLog)
            .filter(
                DevLog.task_id == task_id_str,
                DevLog.text_content.contains(_PREVIEW_STOPPED_MARKER),
            )
            .order_by(DevLog.created_at.desc(), DevLog.id.desc())
            .first()
        )

    def _get_latest_preview_start_attempt_log(self, task_id_str: str) -> DevLog | None:
        return (
            self.db_session.query(DevLog)
            .filter(
                DevLog.task_id == task_id_str,
                DevLog.text_content.contains(_PREVIEW_START_ATTEMPTED_MARKER),
            )
            .order_by(DevLog.created_at.desc(), DevLog.id.desc())
            .first()
        )

    def _write_log(
        self,
        task_obj: Task,
        log_text_content: str,
        state_tag: DevLogStateTag,
    ) -> None:
        LogService.create_internal_log(
            self.db_session,
            DevLogCreateSchema(
                task_id=task_obj.id,
                text_content=log_text_content,
                state_tag=state_tag,
            ),
            task_obj.run_account_id,
        )


def _optional_str(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    normalized_text = str(raw_value).strip()
    return normalized_text or None


def _validate_optional_port(raw_port_value: Any) -> int | None:
    if raw_port_value is None:
        return None
    try:
        port_int = int(raw_port_value)
    except (TypeError, ValueError) as port_error:
        raise InvalidPreviewProfileError(
            "internal_port must be an integer"
        ) from port_error
    if port_int < 1 or port_int > 65535:
        raise InvalidPreviewProfileError("internal_port must be between 1 and 65535")
    return port_int


def _validate_relative_working_directory(
    working_directory_str: str,
    worktree_path: str,
) -> None:
    working_directory_path = Path(working_directory_str)
    if working_directory_path.is_absolute() or ".." in working_directory_path.parts:
        raise InvalidPreviewProfileError("working_directory must stay inside worktree")
    resolved_worktree_path = Path(worktree_path).resolve()
    resolved_candidate_path = (
        resolved_worktree_path / working_directory_path
    ).resolve()
    if resolved_worktree_path not in (
        resolved_candidate_path,
        *resolved_candidate_path.parents,
    ):
        raise InvalidPreviewProfileError("working_directory escapes worktree")


def _validate_url_path(path_str: str | None, field_name_str: str) -> None:
    if not path_str or not path_str.startswith("/"):
        raise InvalidPreviewProfileError(f"{field_name_str} must start with /")


def _validate_command(command_str: str) -> None:
    if _UNSAFE_COMMAND_PATTERN.search(f" {command_str} "):
        raise InvalidPreviewProfileError("command contains unsafe shell tokens")


def _validate_dependency_command(
    command_str: str,
    *,
    runtime_kind: PreviewRuntimeKind | None = None,
) -> None:
    _validate_command(command_str)
    if not command_str.startswith(_ALLOWED_DEPENDENCY_COMMAND_PREFIX_TUPLE):
        raise InvalidPreviewProfileError("dependency command is not allowed")
    if runtime_kind == PreviewRuntimeKind.PYTHON and command_str.startswith("uv sync"):
        raise InvalidPreviewProfileError(
            "python preview profiles must not use uv sync inside Docker"
        )


def _build_preview_profile(
    raw_preview_profile_dict: dict[str, Any],
    preview_applicability: PreviewApplicability,
    applicability_reason_str: str,
    runtime_kind: PreviewRuntimeKind,
    working_directory_str: str | None,
    dependency_command_tuple: tuple[str, ...],
    start_command_str: str | None,
    internal_port_int: int | None,
    healthcheck_path_str: str | None,
    preview_path_str: str | None,
) -> PreviewProfile:
    raw_fingerprint_dict = raw_preview_profile_dict.get("profile_fingerprint") or {}
    return PreviewProfile(
        schema_version=int(raw_preview_profile_dict.get("schema_version") or 1),
        applicability=preview_applicability,
        applicability_reason=applicability_reason_str,
        runtime_kind=runtime_kind,
        working_directory=working_directory_str,
        dependency_commands=dependency_command_tuple,
        start_command=start_command_str,
        internal_port=internal_port_int,
        healthcheck_path=healthcheck_path_str,
        preview_path=preview_path_str,
        readiness_timeout_seconds=int(
            raw_preview_profile_dict.get("readiness_timeout_seconds") or 90
        ),
        notes=_optional_str(raw_preview_profile_dict.get("notes")),
        profile_fingerprint=PreviewProfileFingerprint(
            git_head=_optional_str(raw_fingerprint_dict.get("git_head")),
            dirty_diff_hash=(
                _optional_str(raw_fingerprint_dict.get("dirty_diff_hash"))
                or _build_profile_content_hash(raw_preview_profile_dict)
            ),
        ),
    )


def _build_profile_content_hash(raw_preview_profile_dict: dict[str, Any]) -> str:
    profile_json_bytes = json.dumps(
        raw_preview_profile_dict,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(profile_json_bytes).hexdigest()}"


def infer_preview_profile_for_worktree(
    worktree_path_str: str | None,
) -> PreviewProfile | None:
    """Build a deterministic preview profile from common repo markers.

    Args:
        worktree_path_str: Absolute task worktree path.

    Returns:
        PreviewProfile | None: Inferred profile or None when no worktree exists.
    """
    if not worktree_path_str:
        return None
    worktree_path = Path(worktree_path_str)
    if not worktree_path.exists():
        return None

    frontend_package_json_path = worktree_path / "frontend" / "package.json"
    if frontend_package_json_path.exists():
        return PreviewProfile(
            schema_version=1,
            applicability=PreviewApplicability.APPLICABLE,
            applicability_reason="Vite-style frontend detected from frontend/package.json.",
            runtime_kind=PreviewRuntimeKind.NODE,
            working_directory="frontend",
            dependency_commands=("npm install",),
            start_command="npm run dev -- --host 0.0.0.0 --port 5173",
            internal_port=5173,
            healthcheck_path="/",
            preview_path="/",
            readiness_timeout_seconds=90,
            notes="Deterministically inferred frontend preview profile.",
            profile_fingerprint=PreviewProfileFingerprint(
                git_head=None,
                dirty_diff_hash=f"sha256:{hashlib.sha256(str(worktree_path).encode('utf-8')).hexdigest()}",
            ),
        )

    pyproject_toml_path = worktree_path / "pyproject.toml"
    if pyproject_toml_path.exists():
        return PreviewProfile(
            schema_version=1,
            applicability=PreviewApplicability.UNCERTAIN,
            applicability_reason=(
                "Python project detected from pyproject.toml but no deterministic "
                "HTTP preview entrypoint was inferred."
            ),
            runtime_kind=PreviewRuntimeKind.PYTHON,
            working_directory=".",
            dependency_commands=("uv sync",),
            start_command=None,
            internal_port=None,
            healthcheck_path=None,
            preview_path=None,
            readiness_timeout_seconds=90,
            notes="Manual preview start or bypass is required.",
            profile_fingerprint=PreviewProfileFingerprint(
                git_head=None,
                dirty_diff_hash=f"sha256:{hashlib.sha256(str(worktree_path).encode('utf-8')).hexdigest()}",
            ),
        )

    return PreviewProfile(
        schema_version=1,
        applicability=PreviewApplicability.NOT_APPLICABLE,
        applicability_reason="No deterministic long-running HTTP preview target was detected.",
        runtime_kind=PreviewRuntimeKind.UNKNOWN,
        working_directory=None,
        dependency_commands=(),
        start_command=None,
        internal_port=None,
        healthcheck_path=None,
        preview_path=None,
        readiness_timeout_seconds=90,
        notes="Task appears to be backend-only, CLI-only, or otherwise not previewable.",
        profile_fingerprint=PreviewProfileFingerprint(
            git_head=None,
            dirty_diff_hash=f"sha256:{hashlib.sha256(str(worktree_path).encode('utf-8')).hexdigest()}",
        ),
    )


def generate_ai_preview_profile_for_worktree(
    worktree_path_str: str | None,
    *,
    deterministic_profile: PreviewProfile,
) -> PreviewProfile | None:
    """Generate a validated AI preview profile from an uncertain baseline.

    Args:
        worktree_path_str: Absolute task worktree path.
        deterministic_profile: Existing uncertain profile.

    Returns:
        PreviewProfile | None: Valid AI profile when it resolves uncertainty.
    """
    if not worktree_path_str:
        return None
    if deterministic_profile.applicability != PreviewApplicability.UNCERTAIN:
        return None

    raw_ai_profile_dict = ai_preview_profile_generator.generate_preview_profile_dict(
        worktree_path_str=worktree_path_str,
        deterministic_profile=deterministic_profile,
    )
    if raw_ai_profile_dict is None:
        return None

    try:
        ai_preview_profile = validate_preview_profile_dict(
            raw_ai_profile_dict,
            worktree_path=worktree_path_str,
        )
    except InvalidPreviewProfileError:
        return None

    if ai_preview_profile.applicability == PreviewApplicability.UNCERTAIN:
        return None
    return ai_preview_profile


def _profile_to_dict(preview_profile: PreviewProfile) -> dict[str, Any]:
    return {
        "schema_version": preview_profile.schema_version,
        "applicability": preview_profile.applicability.value,
        "applicability_reason": preview_profile.applicability_reason,
        "profile_fingerprint": {
            "git_head": preview_profile.profile_fingerprint.git_head,
            "dirty_diff_hash": preview_profile.profile_fingerprint.dirty_diff_hash,
        },
        "runtime_kind": preview_profile.runtime_kind.value,
        "working_directory": preview_profile.working_directory,
        "dependency_commands": list(preview_profile.dependency_commands),
        "start_command": preview_profile.start_command,
        "internal_port": preview_profile.internal_port,
        "healthcheck_path": preview_profile.healthcheck_path,
        "preview_path": preview_profile.preview_path,
        "readiness_timeout_seconds": preview_profile.readiness_timeout_seconds,
        "notes": preview_profile.notes,
    }


def _load_profile_from_artifact(
    profile_artifact: TaskArtifact | None,
    worktree_path: str | None,
) -> PreviewProfile | None:
    if profile_artifact is None or not profile_artifact.file_manifest_json:
        return None
    try:
        raw_profile_dict = json.loads(profile_artifact.file_manifest_json)
        return validate_preview_profile_dict(
            raw_profile_dict, worktree_path=worktree_path
        )
    except Exception:
        return None


def _build_profile_summary(preview_profile: PreviewProfile) -> str:
    summary_line_list = [
        f"Applicability: `{preview_profile.applicability.value}`",
        f"Reason: {preview_profile.applicability_reason}",
        f"Runtime: `{preview_profile.runtime_kind.value}`",
    ]
    if preview_profile.working_directory:
        summary_line_list.append(
            f"Working directory: `{preview_profile.working_directory}`"
        )
    if preview_profile.start_command:
        summary_line_list.append(f"Start command: `{preview_profile.start_command}`")
    if preview_profile.internal_port:
        summary_line_list.append(f"Internal port: `{preview_profile.internal_port}`")
    return "\n".join(f"- {summary_line}" for summary_line in summary_line_list)


def _extract_failure_kind(log_text_content: str) -> PreviewFailureKind:
    failure_kind_match = re.search(r"failure_kind=([a-z_]+)", log_text_content)
    if failure_kind_match is None:
        return PreviewFailureKind.UNKNOWN
    try:
        return PreviewFailureKind(failure_kind_match.group(1))
    except ValueError:
        return PreviewFailureKind.UNKNOWN


def _clean_marker_text(log_text_content: str) -> str:
    return (
        log_text_content.replace(_PREVIEW_FAILURE_MARKER, "")
        .replace(_PREVIEW_BYPASS_MARKER, "")
        .strip()
    )
