"""Filesystem repository for PRD source staging."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import uuid

from backend.dsl.prd_sources.domain.errors import (
    InvalidPrdContentError,
    PendingPrdNotFoundError,
    PrdAlreadyExistsError,
    UnsafePrdPathError,
)
from backend.dsl.prd_sources.domain.models import (
    PendingPrdCandidate,
    PrdSourceType,
    StagedPrdDocument,
)
from backend.dsl.prd_sources.domain.policies import (
    MAX_PRD_MARKDOWN_BYTES,
    extract_prd_metadata_value,
    validate_pending_prd_relative_path,
    validate_prd_markdown_text,
)


class FilesystemPrdRepository:
    """Filesystem implementation for PRD source repository operations."""

    def list_pending_prd_candidates(
        self,
        workspace_dir_path: Path,
    ) -> list[PendingPrdCandidate]:
        """List pending Markdown PRDs in a workspace.

        Args:
            workspace_dir_path: Effective task workspace directory.

        Returns:
            list[PendingPrdCandidate]: Pending PRD files sorted newest first.
        """
        pending_directory_path = workspace_dir_path / "tasks" / "pending"
        if not pending_directory_path.exists():
            return []

        resolved_pending_directory_path = pending_directory_path.resolve()
        pending_candidate_list: list[PendingPrdCandidate] = []
        for pending_file_path in sorted(pending_directory_path.glob("*.md")):
            if not pending_file_path.is_file():
                continue
            resolved_pending_file_path = pending_file_path.resolve()
            if not _is_relative_to(
                resolved_pending_file_path,
                resolved_pending_directory_path,
            ):
                continue

            try:
                pending_file_stat = pending_file_path.stat()
            except OSError:
                continue

            title_preview_text = self._read_title_preview(pending_file_path)
            pending_candidate_list.append(
                PendingPrdCandidate(
                    file_name_str=pending_file_path.name,
                    relative_path_str=f"tasks/pending/{pending_file_path.name}",
                    size_bytes_int=int(pending_file_stat.st_size),
                    updated_at=datetime.fromtimestamp(pending_file_stat.st_mtime),
                    title_preview_text=title_preview_text,
                )
            )

        return sorted(
            pending_candidate_list,
            key=lambda pending_candidate: (
                pending_candidate.updated_at,
                pending_candidate.file_name_str,
            ),
            reverse=True,
        )

    def read_pending_prd_markdown(
        self,
        workspace_dir_path: Path,
        pending_relative_path_str: str,
    ) -> str:
        """Read a pending PRD as UTF-8 Markdown.

        Args:
            workspace_dir_path: Effective task workspace directory.
            pending_relative_path_str: Workspace-relative pending PRD path.

        Returns:
            str: Decoded Markdown content.
        """
        pending_file_path = self._resolve_pending_prd_path(
            workspace_dir_path,
            pending_relative_path_str,
        )
        self._validate_file_size(pending_file_path)
        try:
            pending_prd_markdown_text = pending_file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as unicode_decode_error:
            raise InvalidPrdContentError(
                "Pending PRD file must be encoded as UTF-8 Markdown."
            ) from unicode_decode_error
        except OSError as os_error:
            raise PendingPrdNotFoundError(
                "Pending PRD file cannot be read."
            ) from os_error

        validate_prd_markdown_text(pending_prd_markdown_text)
        return pending_prd_markdown_text

    def ensure_task_prd_absent(
        self,
        workspace_dir_path: Path,
        task_id_str: str,
    ) -> None:
        """Raise if a task-scoped PRD already exists.

        Args:
            workspace_dir_path: Effective task workspace directory.
            task_id_str: Task UUID string.

        Raises:
            PrdAlreadyExistsError: If a matching PRD already exists.
        """
        tasks_directory_path = workspace_dir_path / "tasks"
        task_short_id_str = task_id_str[:8]
        legacy_task_prd_file_path_list = []
        if tasks_directory_path.exists():
            legacy_task_prd_file_path_list = list(
                tasks_directory_path.glob(f"prd-{task_short_id_str}*.md")
            )
        if legacy_task_prd_file_path_list:
            raise PrdAlreadyExistsError(
                "This task already has a PRD file. Replace is not supported yet."
            )

    def move_pending_prd_to_tasks_root(
        self,
        workspace_dir_path: Path,
        pending_relative_path_str: str,
        target_file_name_str: str,
    ) -> StagedPrdDocument:
        """Move a pending PRD into the workspace `tasks/` root.

        Args:
            workspace_dir_path: Effective task workspace directory.
            pending_relative_path_str: Workspace-relative pending PRD path.
            target_file_name_str: Target task PRD filename.

        Returns:
            StagedPrdDocument: Staged PRD metadata.
        """
        source_pending_file_path = self._resolve_pending_prd_path(
            workspace_dir_path,
            pending_relative_path_str,
        )
        target_prd_file_path = self._resolve_target_prd_path(
            workspace_dir_path,
            target_file_name_str,
        )
        if target_prd_file_path.exists():
            raise PrdAlreadyExistsError("Target PRD file already exists.")

        target_prd_file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            source_pending_file_path.replace(target_prd_file_path)
        except OSError as os_error:
            raise InvalidPrdContentError(
                "Failed to move selected pending PRD."
            ) from os_error

        return StagedPrdDocument(
            file_name_str=target_prd_file_path.name,
            relative_path_str=f"tasks/{target_prd_file_path.name}",
            absolute_path=target_prd_file_path,
            source_type=PrdSourceType.PENDING,
        )

    def stage_pending_prd_to_tasks_root(
        self,
        source_workspace_dir_path: Path,
        target_workspace_dir_path: Path,
        pending_relative_path_str: str,
        target_file_name_str: str,
        pending_prd_markdown_text: str,
    ) -> StagedPrdDocument:
        """Stage a pending PRD into a target workspace and remove the source file.

        This supports backlog tasks whose pending files are listed from the
        project repository before a task worktree exists. Once staging starts,
        the task worktree may become the target workspace, so source and target
        are not always the same directory.

        Args:
            source_workspace_dir_path: Workspace containing the pending PRD.
            target_workspace_dir_path: Workspace receiving the staged PRD.
            pending_relative_path_str: Workspace-relative pending PRD path.
            target_file_name_str: Target task PRD filename.
            pending_prd_markdown_text: Validated Markdown content read from source.

        Returns:
            StagedPrdDocument: Staged PRD metadata.
        """
        if source_workspace_dir_path.resolve() == target_workspace_dir_path.resolve():
            return self.move_pending_prd_to_tasks_root(
                workspace_dir_path=target_workspace_dir_path,
                pending_relative_path_str=pending_relative_path_str,
                target_file_name_str=target_file_name_str,
            )

        source_pending_file_path = self._resolve_pending_prd_path(
            source_workspace_dir_path,
            pending_relative_path_str,
        )
        target_prd_file_path = self._resolve_target_prd_path(
            target_workspace_dir_path,
            target_file_name_str,
        )
        if target_prd_file_path.exists():
            raise PrdAlreadyExistsError("Target PRD file already exists.")

        validate_prd_markdown_text(pending_prd_markdown_text)
        target_prd_file_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_prd_file_path = target_prd_file_path.with_name(
            f".{target_prd_file_path.name}.tmp-{uuid.uuid4().hex}"
        )
        try:
            temporary_prd_file_path.write_text(
                pending_prd_markdown_text,
                encoding="utf-8",
            )
            temporary_prd_file_path.replace(target_prd_file_path)
            source_pending_file_path.unlink()
        except OSError as os_error:
            raise InvalidPrdContentError(
                "Failed to stage selected pending PRD."
            ) from os_error
        finally:
            if temporary_prd_file_path.exists():
                temporary_prd_file_path.unlink(missing_ok=True)

        return StagedPrdDocument(
            file_name_str=target_prd_file_path.name,
            relative_path_str=f"tasks/{target_prd_file_path.name}",
            absolute_path=target_prd_file_path,
            source_type=PrdSourceType.PENDING,
        )

    def import_prd_to_tasks_root(
        self,
        workspace_dir_path: Path,
        target_file_name_str: str,
        prd_markdown_text: str,
    ) -> StagedPrdDocument:
        """Write imported PRD Markdown into the workspace `tasks/` root.

        Args:
            workspace_dir_path: Effective task workspace directory.
            target_file_name_str: Target task PRD filename.
            prd_markdown_text: Decoded PRD Markdown.

        Returns:
            StagedPrdDocument: Staged PRD metadata.
        """
        validate_prd_markdown_text(prd_markdown_text)
        target_prd_file_path = self._resolve_target_prd_path(
            workspace_dir_path,
            target_file_name_str,
        )
        if target_prd_file_path.exists():
            raise PrdAlreadyExistsError("Target PRD file already exists.")

        target_prd_file_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_prd_file_path = target_prd_file_path.with_name(
            f".{target_prd_file_path.name}.tmp-{uuid.uuid4().hex}"
        )
        try:
            temporary_prd_file_path.write_text(prd_markdown_text, encoding="utf-8")
            temporary_prd_file_path.replace(target_prd_file_path)
        except OSError as os_error:
            raise InvalidPrdContentError("Failed to write imported PRD.") from os_error
        finally:
            if temporary_prd_file_path.exists():
                temporary_prd_file_path.unlink(missing_ok=True)

        return StagedPrdDocument(
            file_name_str=target_prd_file_path.name,
            relative_path_str=f"tasks/{target_prd_file_path.name}",
            absolute_path=target_prd_file_path,
            source_type=PrdSourceType.MANUAL_IMPORT,
        )

    def _resolve_pending_prd_path(
        self,
        workspace_dir_path: Path,
        pending_relative_path_str: str,
    ) -> Path:
        """Resolve and validate a pending PRD path inside a workspace."""
        normalized_pending_relative_path_str = validate_pending_prd_relative_path(
            pending_relative_path_str
        )
        pending_directory_path = (workspace_dir_path / "tasks" / "pending").resolve()
        pending_file_path = (
            workspace_dir_path / normalized_pending_relative_path_str
        ).resolve()
        if not _is_relative_to(pending_file_path, pending_directory_path):
            raise UnsafePrdPathError("Pending PRD path escapes tasks/pending.")
        if not pending_file_path.exists() or not pending_file_path.is_file():
            raise PendingPrdNotFoundError("Pending PRD file was not found.")
        if pending_file_path.suffix.lower() != ".md":
            raise InvalidPrdContentError("Only Markdown PRD files are supported.")
        return pending_file_path

    def _resolve_target_prd_path(
        self,
        workspace_dir_path: Path,
        target_file_name_str: str,
    ) -> Path:
        """Resolve a target PRD path under the workspace tasks root."""
        if Path(target_file_name_str).name != target_file_name_str:
            raise UnsafePrdPathError("Target PRD filename must not contain paths.")
        if not target_file_name_str.endswith(".md"):
            raise InvalidPrdContentError("Target PRD filename must be Markdown.")

        tasks_directory_path = (workspace_dir_path / "tasks").resolve()
        target_prd_file_path = (tasks_directory_path / target_file_name_str).resolve()
        if not _is_relative_to(target_prd_file_path, tasks_directory_path):
            raise UnsafePrdPathError("Target PRD path escapes tasks root.")
        return target_prd_file_path

    def _validate_file_size(self, pending_file_path: Path) -> None:
        """Validate a pending PRD file size."""
        try:
            pending_file_size_int = pending_file_path.stat().st_size
        except OSError as os_error:
            raise PendingPrdNotFoundError(
                "Pending PRD file cannot be stat'ed."
            ) from os_error
        if pending_file_size_int <= 0:
            raise InvalidPrdContentError("PRD file cannot be empty.")
        if pending_file_size_int > MAX_PRD_MARKDOWN_BYTES:
            raise InvalidPrdContentError("PRD file is larger than the supported limit.")

    def _read_title_preview(self, pending_file_path: Path) -> str | None:
        """Read a small title preview for list responses."""
        try:
            pending_markdown_text = pending_file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        metadata_title_text = extract_prd_metadata_value(
            pending_markdown_text, "需求名称（AI 归纳）"
        ) or extract_prd_metadata_value(pending_markdown_text, "原始需求标题")
        if metadata_title_text:
            return metadata_title_text[:120]

        for markdown_line_text in pending_markdown_text.splitlines():
            stripped_line_text = markdown_line_text.strip()
            if stripped_line_text.startswith("#"):
                return stripped_line_text.lstrip("#").strip()[:120] or None
        return None


def _is_relative_to(candidate_path: Path, parent_path: Path) -> bool:
    """Return whether `candidate_path` is under `parent_path`."""
    try:
        candidate_path.relative_to(parent_path)
        return True
    except ValueError:
        return False
