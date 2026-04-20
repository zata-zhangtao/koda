"""Tests for PRD source application use cases."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.dsl.prd_sources.application.use_cases import (
    ImportPrdUseCase,
    SelectPendingPrdUseCase,
)
from backend.dsl.prd_sources.domain.errors import UnsafePrdPathError
from backend.dsl.prd_sources.domain.models import (
    PendingPrdCandidate,
    PrdSourceType,
    PrdTaskContext,
    StagedPrdDocument,
)


class FakeTaskWorkflowPort:
    """Fake task workflow port for use-case tests."""

    def __init__(self, workspace_dir_path: Path) -> None:
        """Initialize the fake workflow port."""
        self.task_context = PrdTaskContext(
            task_id_str="cf2b9461-0000-4000-8000-000000000000",
            run_account_id_str="run-account",
            task_title_str="导入 PRD",
            workspace_dir_path=workspace_dir_path,
            worktree_path_str=str(workspace_dir_path),
            auto_confirm_prd_and_execute_bool=False,
        )
        self.marked_ready_bool = False

    def resolve_task_context(self, task_id_str: str) -> PrdTaskContext:
        """Return the fake task context."""
        return self.task_context

    def prepare_prd_workspace(self, task_id_str: str) -> PrdTaskContext:
        """Return the prepared fake task context."""
        return self.task_context

    def mark_prd_ready(
        self,
        task_context: PrdTaskContext,
        staged_prd_document: StagedPrdDocument,
    ) -> bool:
        """Record that the task was marked PRD-ready."""
        self.marked_ready_bool = True
        return False


class FakePrdSourceRepository:
    """Fake PRD source repository for use-case tests."""

    def __init__(self) -> None:
        """Initialize the fake repository."""
        self.ensure_absent_called_bool = False
        self.moved_pending_relative_path_str: str | None = None
        self.imported_markdown_text: str | None = None

    def list_pending_prd_candidates(
        self,
        workspace_dir_path: Path,
    ) -> list[PendingPrdCandidate]:
        """Return no pending candidates."""
        return []

    def read_pending_prd_markdown(
        self,
        workspace_dir_path: Path,
        pending_relative_path_str: str,
    ) -> str:
        """Return fake pending PRD Markdown."""
        return "**需求名称（AI 归纳）**：选择已有 PRD\n"

    def ensure_task_prd_absent(
        self,
        workspace_dir_path: Path,
        task_id_str: str,
    ) -> None:
        """Record conflict validation."""
        self.ensure_absent_called_bool = True

    def move_pending_prd_to_tasks_root(
        self,
        workspace_dir_path: Path,
        pending_relative_path_str: str,
        target_file_name_str: str,
    ) -> StagedPrdDocument:
        """Record a fake pending move."""
        self.moved_pending_relative_path_str = pending_relative_path_str
        return StagedPrdDocument(
            file_name_str=target_file_name_str,
            relative_path_str=f"tasks/{target_file_name_str}",
            absolute_path=workspace_dir_path / "tasks" / target_file_name_str,
            source_type=PrdSourceType.PENDING,
        )

    def import_prd_to_tasks_root(
        self,
        workspace_dir_path: Path,
        target_file_name_str: str,
        prd_markdown_text: str,
    ) -> StagedPrdDocument:
        """Record a fake import."""
        self.imported_markdown_text = prd_markdown_text
        return StagedPrdDocument(
            file_name_str=target_file_name_str,
            relative_path_str=f"tasks/{target_file_name_str}",
            absolute_path=workspace_dir_path / "tasks" / target_file_name_str,
            source_type=PrdSourceType.MANUAL_IMPORT,
        )


def test_select_pending_prd_use_case_validates_path_before_ports(
    tmp_path: Path,
) -> None:
    """Unsafe pending paths should fail before workspace or repository actions."""
    workflow_port = FakeTaskWorkflowPort(tmp_path)
    repository = FakePrdSourceRepository()
    use_case = SelectPendingPrdUseCase(
        task_workflow_port=workflow_port,
        prd_source_repository=repository,
    )

    with pytest.raises(UnsafePrdPathError):
        use_case.execute(
            "cf2b9461-0000-4000-8000-000000000000",
            "tasks/pending/../secret.md",
        )

    assert workflow_port.marked_ready_bool is False
    assert repository.ensure_absent_called_bool is False


def test_import_prd_use_case_stages_markdown_and_marks_ready(tmp_path: Path) -> None:
    """Manual import should stage Markdown and transition the task to PRD-ready."""
    workflow_port = FakeTaskWorkflowPort(tmp_path)
    repository = FakePrdSourceRepository()
    use_case = ImportPrdUseCase(
        task_workflow_port=workflow_port,
        prd_source_repository=repository,
    )

    outcome = use_case.execute(
        task_id_str="cf2b9461-0000-4000-8000-000000000000",
        original_file_name_str="manual.md",
        raw_prd_file_bytes="**需求名称（AI 归纳）**：手动导入 PRD\n".encode("utf-8"),
    )

    assert repository.ensure_absent_called_bool is True
    assert (
        repository.imported_markdown_text == "**需求名称（AI 归纳）**：手动导入 PRD\n"
    )
    assert workflow_port.marked_ready_bool is True
    assert outcome.staged_relative_path_str == "tasks/prd-cf2b9461-手动导入-prd.md"
    assert outcome.auto_started_implementation_bool is False


def test_import_prd_use_case_accepts_pasted_markdown(tmp_path: Path) -> None:
    """Pasted Markdown should reuse the manual import staging flow."""
    workflow_port = FakeTaskWorkflowPort(tmp_path)
    repository = FakePrdSourceRepository()
    use_case = ImportPrdUseCase(
        task_workflow_port=workflow_port,
        prd_source_repository=repository,
    )

    outcome = use_case.execute_pasted_markdown(
        task_id_str="cf2b9461-0000-4000-8000-000000000000",
        original_file_name_str="pasted-prd.md",
        prd_markdown_text="**需求名称（AI 归纳）**：粘贴导入 PRD\n",
    )

    assert repository.ensure_absent_called_bool is True
    assert repository.imported_markdown_text == "**需求名称（AI 归纳）**：粘贴导入 PRD\n"
    assert workflow_port.marked_ready_bool is True
    assert outcome.staged_relative_path_str == "tasks/prd-cf2b9461-粘贴导入-prd.md"
    assert outcome.auto_started_implementation_bool is False
