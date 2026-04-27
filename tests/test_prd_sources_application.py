"""Tests for PRD source application use cases."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from backend.dsl.prd_sources.application.use_cases import (
    BuildPrdTaskDraftUseCase,
    CreateTaskFromImportedPrdUseCase,
    CreateTaskFromPendingPrdUseCase,
    ImportPrdUseCase,
    SelectPendingPrdUseCase,
)
from backend.dsl.prd_sources.domain.errors import (
    StalePendingPrdError,
    UnsafePrdPathError,
)
from backend.dsl.prd_sources.domain.models import (
    PendingPrdCandidate,
    PrdSourceType,
    PrdTaskContext,
    PrdTasklessSourceContext,
    StagedPrdDocument,
)


class FakeTaskWorkflowPort:
    """Fake task workflow port for use-case tests."""

    def __init__(
        self,
        workspace_dir_path: Path,
        prepared_workspace_dir_path: Path | None = None,
    ) -> None:
        """Initialize the fake workflow port."""
        self.task_context = PrdTaskContext(
            task_id_str="cf2b9461-0000-4000-8000-000000000000",
            run_account_id_str="run-account",
            task_title_str="导入 PRD",
            workspace_dir_path=workspace_dir_path,
            worktree_path_str=str(workspace_dir_path),
            auto_confirm_prd_and_execute_bool=False,
        )
        self.prepared_task_context = PrdTaskContext(
            task_id_str="cf2b9461-0000-4000-8000-000000000000",
            run_account_id_str="run-account",
            task_title_str="导入 PRD",
            workspace_dir_path=prepared_workspace_dir_path or workspace_dir_path,
            worktree_path_str=str(prepared_workspace_dir_path or workspace_dir_path),
            auto_confirm_prd_and_execute_bool=False,
        )
        self.marked_ready_bool = False
        self.created_task_id_str = "created-task-0000-4000-8000-000000000000"
        self.created_task_payload: dict[str, object] | None = None

    def resolve_task_context(self, task_id_str: str) -> PrdTaskContext:
        """Return the fake task context."""
        return self.task_context

    def resolve_pending_source_context(self, task_id_str: str) -> PrdTaskContext:
        """Return the fake pending source task context."""
        return self.task_context

    def prepare_prd_workspace(self, task_id_str: str) -> PrdTaskContext:
        """Return the prepared fake task context."""
        return self.prepared_task_context

    def mark_prd_ready(
        self,
        task_context: PrdTaskContext,
        staged_prd_document: StagedPrdDocument,
    ) -> bool:
        """Record that the task was marked PRD-ready."""
        self.marked_ready_bool = True
        return False

    def resolve_taskless_pending_source_context(
        self,
        project_id_str: str | None,
    ) -> PrdTasklessSourceContext:
        """Return the fake taskless source context."""
        return PrdTasklessSourceContext(
            run_account_id_str="run-account",
            project_id_str=project_id_str,
            workspace_dir_path=self.task_context.workspace_dir_path,
        )

    def create_task_from_prd_draft(
        self,
        *,
        task_title_str: str,
        project_id_str: str | None,
        worktree_base_branch_name_str: str,
        requirement_brief_str: str,
        auto_confirm_prd_and_execute_bool: bool,
    ) -> str:
        """Record a fake task creation request."""
        self.created_task_payload = {
            "task_title": task_title_str,
            "project_id": project_id_str,
            "worktree_base_branch_name": worktree_base_branch_name_str,
            "requirement_brief": requirement_brief_str,
            "auto_confirm_prd_and_execute": auto_confirm_prd_and_execute_bool,
        }
        return self.created_task_id_str


class FakePrdSourceRepository:
    """Fake PRD source repository for use-case tests."""

    def __init__(self) -> None:
        """Initialize the fake repository."""
        self.pending_candidate_list = [
            PendingPrdCandidate(
                file_name_str="manual.md",
                relative_path_str="tasks/pending/manual.md",
                size_bytes_int=100,
                updated_at=datetime(2026, 4, 23, 13, 5, 0),
                title_preview_text="选择已有 PRD",
            )
        ]
        self.pending_markdown_text = "**需求名称（AI 归纳）**：选择已有 PRD\n"
        self.ensure_absent_called_bool = False
        self.ensure_absent_workspace_dir_path: Path | None = None
        self.moved_pending_relative_path_str: str | None = None
        self.pending_stage_call_tuple: tuple[Path, Path, str] | None = None
        self.imported_markdown_text: str | None = None

    def list_pending_prd_candidates(
        self,
        workspace_dir_path: Path,
    ) -> list[PendingPrdCandidate]:
        """Return configured pending candidates."""
        return self.pending_candidate_list

    def read_pending_prd_markdown(
        self,
        workspace_dir_path: Path,
        pending_relative_path_str: str,
    ) -> str:
        """Return fake pending PRD Markdown."""
        return self.pending_markdown_text

    def ensure_task_prd_absent(
        self,
        workspace_dir_path: Path,
        task_id_str: str,
    ) -> None:
        """Record conflict validation."""
        self.ensure_absent_called_bool = True
        self.ensure_absent_workspace_dir_path = workspace_dir_path

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

    def stage_pending_prd_to_tasks_root(
        self,
        source_workspace_dir_path: Path,
        target_workspace_dir_path: Path,
        pending_relative_path_str: str,
        target_file_name_str: str,
        pending_prd_markdown_text: str,
    ) -> StagedPrdDocument:
        """Record fake cross-workspace pending staging."""
        self.pending_stage_call_tuple = (
            source_workspace_dir_path,
            target_workspace_dir_path,
            pending_relative_path_str,
        )
        return StagedPrdDocument(
            file_name_str=target_file_name_str,
            relative_path_str=f"tasks/{target_file_name_str}",
            absolute_path=target_workspace_dir_path / "tasks" / target_file_name_str,
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


def test_build_prd_task_draft_use_case_returns_pending_timestamp(
    tmp_path: Path,
) -> None:
    """Pending draft suggestions should include source metadata for stale checks."""
    workflow_port = FakeTaskWorkflowPort(tmp_path)
    repository = FakePrdSourceRepository()
    repository.pending_markdown_text = (
        "# PRD\n\n**需求名称（AI 归纳）**：PRD 先行任务\n\n"
        "用户选择 pending PRD 后确认 task 草稿。\n"
    )
    use_case = BuildPrdTaskDraftUseCase(
        task_workflow_port=workflow_port,
        prd_source_repository=repository,
    )

    draft_suggestion = use_case.execute_pending(
        project_id_str=None,
        pending_relative_path_str="tasks/pending/manual.md",
    )

    assert draft_suggestion.suggested_task_title_str == "PRD 先行任务"
    assert "用户选择 pending PRD" in draft_suggestion.suggested_requirement_brief_str
    assert draft_suggestion.source_relative_path_str == "tasks/pending/manual.md"
    assert draft_suggestion.source_updated_at == datetime(2026, 4, 23, 13, 5, 0)


def test_select_pending_prd_use_case_stages_from_source_into_prepared_workspace(
    tmp_path: Path,
) -> None:
    """Pending selection should survive worktree creation changing workspace roots."""
    source_workspace_dir_path = tmp_path / "project"
    target_workspace_dir_path = tmp_path / "task-worktree"
    workflow_port = FakeTaskWorkflowPort(
        source_workspace_dir_path,
        target_workspace_dir_path,
    )
    repository = FakePrdSourceRepository()
    use_case = SelectPendingPrdUseCase(
        task_workflow_port=workflow_port,
        prd_source_repository=repository,
    )

    outcome = use_case.execute(
        "cf2b9461-0000-4000-8000-000000000000",
        "tasks/pending/manual.md",
        reference_datetime=datetime(2026, 4, 23, 13, 5, 0),
    )

    assert repository.ensure_absent_workspace_dir_path == target_workspace_dir_path
    assert repository.pending_stage_call_tuple == (
        source_workspace_dir_path,
        target_workspace_dir_path,
        "tasks/pending/manual.md",
    )
    assert workflow_port.marked_ready_bool is True
    assert outcome.source_type == PrdSourceType.PENDING
    assert (
        outcome.staged_relative_path_str == "tasks/20260423-130500-prd-选择已有-prd.md"
    )


def test_create_task_from_pending_prd_rejects_stale_source_timestamp(
    tmp_path: Path,
) -> None:
    """Final create should reject pending PRDs changed after draft generation."""
    workflow_port = FakeTaskWorkflowPort(tmp_path)
    repository = FakePrdSourceRepository()
    use_case = CreateTaskFromPendingPrdUseCase(
        task_workflow_port=workflow_port,
        prd_source_repository=repository,
    )

    with pytest.raises(StalePendingPrdError):
        use_case.execute(
            task_title_str="Confirmed title",
            project_id_str=None,
            worktree_base_branch_name_str="main",
            requirement_brief_str="Confirmed description",
            auto_confirm_prd_and_execute_bool=False,
            pending_relative_path_str="tasks/pending/manual.md",
            expected_source_updated_at=datetime(2026, 4, 23, 13, 6, 0),
        )

    assert workflow_port.created_task_payload is None


def test_create_task_from_imported_prd_creates_task_then_stages_import(
    tmp_path: Path,
) -> None:
    """Imported PRD final create should create a task and reuse import staging."""
    workflow_port = FakeTaskWorkflowPort(tmp_path)
    repository = FakePrdSourceRepository()
    use_case = CreateTaskFromImportedPrdUseCase(
        task_workflow_port=workflow_port,
        prd_source_repository=repository,
    )

    outcome = use_case.execute_pasted_markdown(
        task_title_str="Confirmed imported PRD",
        project_id_str=None,
        worktree_base_branch_name_str="main",
        requirement_brief_str="Confirmed description",
        auto_confirm_prd_and_execute_bool=False,
        original_file_name_str="pasted-prd.md",
        prd_markdown_text="**需求名称（AI 归纳）**：导入后创建\n",
    )

    assert workflow_port.created_task_payload == {
        "task_title": "Confirmed imported PRD",
        "project_id": None,
        "worktree_base_branch_name": "main",
        "requirement_brief": "Confirmed description",
        "auto_confirm_prd_and_execute": False,
    }
    assert repository.imported_markdown_text == "**需求名称（AI 归纳）**：导入后创建\n"
    assert outcome.task_id_str == workflow_port.prepared_task_context.task_id_str


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
        reference_datetime=datetime(2026, 4, 23, 13, 5, 0),
    )

    assert repository.ensure_absent_called_bool is True
    assert (
        repository.imported_markdown_text == "**需求名称（AI 归纳）**：手动导入 PRD\n"
    )
    assert workflow_port.marked_ready_bool is True
    assert (
        outcome.staged_relative_path_str == "tasks/20260423-130500-prd-手动导入-prd.md"
    )
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
        reference_datetime=datetime(2026, 4, 23, 13, 5, 0),
    )

    assert repository.ensure_absent_called_bool is True
    assert (
        repository.imported_markdown_text == "**需求名称（AI 归纳）**：粘贴导入 PRD\n"
    )
    assert workflow_port.marked_ready_bool is True
    assert (
        outcome.staged_relative_path_str == "tasks/20260423-130500-prd-粘贴导入-prd.md"
    )
    assert outcome.auto_started_implementation_bool is False
