"""Tests for project timeline APIs and task reference behavior."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import backend.dsl.models  # noqa: F401
from backend.dsl.api import chronicle as chronicle_api
from backend.dsl.api import tasks as tasks_api
from backend.dsl.models.dev_log import DevLog
from backend.dsl.models.enums import (
    DevLogStateTag,
    TaskArtifactType,
    TaskLifecycleStatus,
    WorkflowStage,
)
from backend.dsl.models.project import Project
from backend.dsl.models.run_account import RunAccount
from backend.dsl.models.task import TASK_REQUIREMENT_BRIEF_MAX_LENGTH, Task
from backend.dsl.models.task_artifact import TaskArtifact
from backend.dsl.models.task_reference_link import TaskReferenceLink
from backend.dsl.schemas.chronicle_schema import ProjectTimelineSummaryRequestSchema
from backend.dsl.schemas.task_schema import TaskReferenceCreateSchema
from utils.database import Base


def _create_test_session() -> Session:
    """Create an isolated SQLite session for project timeline tests."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    test_session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )
    Base.metadata.create_all(bind=test_engine)
    return test_session_factory()


def test_project_timeline_filters_by_project_and_status() -> None:
    """Project timeline should aggregate by project and lifecycle filters."""
    db_session = _create_test_session()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        db_session.add(run_account_obj)
        db_session.commit()

        left_project_obj = Project(
            display_name="Project Left",
            project_category="delivery",
            repo_path="/tmp/project-left",
        )
        right_project_obj = Project(
            display_name="Project Right",
            project_category="research",
            repo_path="/tmp/project-right",
        )
        db_session.add_all([left_project_obj, right_project_obj])
        db_session.commit()

        open_task_obj = Task(
            run_account_id=run_account_obj.id,
            project_id=left_project_obj.id,
            task_title="Open task",
            lifecycle_status=TaskLifecycleStatus.OPEN,
            workflow_stage=WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
        )
        abandoned_task_obj = Task(
            run_account_id=run_account_obj.id,
            project_id=left_project_obj.id,
            task_title="Abandoned task",
            lifecycle_status=TaskLifecycleStatus.ABANDONED,
            workflow_stage=WorkflowStage.CHANGES_REQUESTED,
        )
        other_project_task_obj = Task(
            run_account_id=run_account_obj.id,
            project_id=right_project_obj.id,
            task_title="Other project task",
            lifecycle_status=TaskLifecycleStatus.OPEN,
            workflow_stage=WorkflowStage.BACKLOG,
        )
        db_session.add_all([open_task_obj, abandoned_task_obj, other_project_task_obj])
        db_session.commit()

        db_session.add_all(
            [
                DevLog(
                    task_id=open_task_obj.id,
                    run_account_id=run_account_obj.id,
                    text_content="open bug",
                    state_tag=DevLogStateTag.BUG,
                ),
                DevLog(
                    task_id=open_task_obj.id,
                    run_account_id=run_account_obj.id,
                    text_content="open fixed",
                    state_tag=DevLogStateTag.FIXED,
                ),
                DevLog(
                    task_id=abandoned_task_obj.id,
                    run_account_id=run_account_obj.id,
                    text_content="abandoned marker",
                    state_tag=DevLogStateTag.NONE,
                ),
                DevLog(
                    task_id=other_project_task_obj.id,
                    run_account_id=run_account_obj.id,
                    text_content="other project log",
                    state_tag=DevLogStateTag.NONE,
                ),
            ]
        )
        db_session.commit()

        timeline_entry_list = chronicle_api.get_project_timeline(
            project_category="delivery",
            lifecycle_status=[
                TaskLifecycleStatus.OPEN,
                TaskLifecycleStatus.ABANDONED,
            ],
            db_session=db_session,
        )

        assert len(timeline_entry_list) == 2
        timeline_entry_by_task_id = {
            timeline_entry["task_id"]: timeline_entry
            for timeline_entry in timeline_entry_list
        }
        assert (
            timeline_entry_by_task_id[open_task_obj.id]["project_display_name"]
            == left_project_obj.display_name
        )
        assert (
            timeline_entry_by_task_id[open_task_obj.id]["project_category"]
            == "delivery"
        )
        assert timeline_entry_by_task_id[open_task_obj.id]["bug_count"] == 1
        assert timeline_entry_by_task_id[open_task_obj.id]["fix_count"] == 1
        assert (
            timeline_entry_by_task_id[abandoned_task_obj.id]["lifecycle_status"]
            == TaskLifecycleStatus.ABANDONED.value
        )
    finally:
        db_session.close()


def test_project_timeline_detail_captures_prd_and_planning_snapshots(
    tmp_path: Path,
) -> None:
    """Timeline detail should return PRD and planning-with-files snapshots."""
    db_session = _create_test_session()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        db_session.add(run_account_obj)
        db_session.commit()

        project_obj = Project(
            display_name="Project A",
            project_category="automation",
            repo_path=str(tmp_path / "repo"),
        )
        db_session.add(project_obj)
        db_session.commit()

        task_worktree_path = tmp_path / "worktree-task"
        task_worktree_path.mkdir(parents=True, exist_ok=True)
        task_obj = Task(
            run_account_id=run_account_obj.id,
            project_id=project_obj.id,
            task_title="Capture snapshots",
            lifecycle_status=TaskLifecycleStatus.OPEN,
            workflow_stage=WorkflowStage.PRD_WAITING_CONFIRMATION,
            worktree_path=str(task_worktree_path),
            requirement_brief="Need timeline snapshots.",
        )
        db_session.add(task_obj)
        db_session.commit()

        tasks_directory_path = task_worktree_path / "tasks"
        tasks_directory_path.mkdir(parents=True, exist_ok=True)
        prd_file_path = tasks_directory_path / f"prd-{task_obj.id[:8]}.md"
        prd_file_path.write_text("# PRD\n\nSnapshot content\n", encoding="utf-8")

        db_session.add(
            DevLog(
                task_id=task_obj.id,
                run_account_id=run_account_obj.id,
                text_content=(
                    "Planning with files:\n"
                    "- `frontend/src/App.tsx`\n"
                    "- `backend/dsl/api/chronicle.py`\n"
                ),
                state_tag=DevLogStateTag.OPTIMIZATION,
            )
        )
        db_session.commit()

        detail_response = chronicle_api.get_project_timeline_task_detail(
            task_id=task_obj.id,
            db_session=db_session,
        )

        assert detail_response["prd_snapshot"] is not None
        assert "Snapshot content" in detail_response["prd_snapshot"]["content_markdown"]
        assert detail_response["planning_snapshot"] is not None
        assert (
            detail_response["task"]["project_display_name"] == project_obj.display_name
        )
        assert detail_response["task"]["project_category"] == "automation"
        assert (
            "frontend/src/App.tsx"
            in detail_response["planning_snapshot"]["file_manifest"]
        )
        assert (
            db_session.query(TaskArtifact)
            .filter(TaskArtifact.task_id == task_obj.id)
            .count()
            >= 2
        )
    finally:
        db_session.close()


def test_project_timeline_detail_reads_planning_files_snapshot_from_worktree(
    tmp_path: Path,
) -> None:
    """Timeline detail should snapshot planning files directly from worktree."""
    db_session = _create_test_session()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        db_session.add(run_account_obj)
        db_session.commit()

        project_obj = Project(
            display_name="Project Planning",
            project_category="ops",
            repo_path=str(tmp_path / "repo"),
        )
        db_session.add(project_obj)
        db_session.commit()

        task_worktree_path = tmp_path / "worktree-planning"
        planning_directory_path = (
            task_worktree_path / ".claude" / "planning" / "current"
        )
        planning_directory_path.mkdir(parents=True, exist_ok=True)

        task_obj = Task(
            run_account_id=run_account_obj.id,
            project_id=project_obj.id,
            task_title="Planning snapshot from files",
            lifecycle_status=TaskLifecycleStatus.OPEN,
            workflow_stage=WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
            worktree_path=str(task_worktree_path),
        )
        db_session.add(task_obj)
        db_session.commit()

        (planning_directory_path / "task_plan.md").write_text(
            "# Task Plan\n\n- verify planning snapshot\n",
            encoding="utf-8",
        )
        (planning_directory_path / "findings.md").write_text(
            "# Findings\n\n- planning files exist in worktree\n",
            encoding="utf-8",
        )
        (planning_directory_path / "progress.md").write_text(
            "# Progress\n\n- test in progress\n",
            encoding="utf-8",
        )

        detail_response = chronicle_api.get_project_timeline_task_detail(
            task_id=task_obj.id,
            db_session=db_session,
        )

        assert detail_response["planning_snapshot"] is not None
        assert detail_response["planning_snapshot"]["file_manifest"] == [
            ".claude/planning/current/task_plan.md",
            ".claude/planning/current/findings.md",
            ".claude/planning/current/progress.md",
        ]
        assert (
            "verify planning snapshot"
            in detail_response["planning_snapshot"]["content_markdown"]
        )
        assert (
            "planning files exist in worktree"
            in detail_response["planning_snapshot"]["content_markdown"]
        )
        assert (
            "test in progress"
            in detail_response["planning_snapshot"]["content_markdown"]
        )
        assert (
            db_session.query(TaskArtifact)
            .filter(
                TaskArtifact.task_id == task_obj.id,
                TaskArtifact.artifact_type == TaskArtifactType.PLANNING_WITH_FILES,
            )
            .count()
            == 1
        )
    finally:
        db_session.close()


def test_create_task_reference_appends_requirement_context() -> None:
    """Creating a task reference should add DevLog evidence and append summary."""
    db_session = _create_test_session()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        db_session.add(run_account_obj)
        db_session.commit()

        source_task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Source requirement",
            lifecycle_status=TaskLifecycleStatus.CLOSED,
            workflow_stage=WorkflowStage.DONE,
            requirement_brief="Source requirement summary.",
        )
        target_task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Target requirement",
            lifecycle_status=TaskLifecycleStatus.OPEN,
            workflow_stage=WorkflowStage.BACKLOG,
            requirement_brief="Target requirement summary.",
        )
        db_session.add_all([source_task_obj, target_task_obj])
        db_session.commit()

        reference_response = tasks_api.create_task_reference(
            target_task_id=target_task_obj.id,
            reference_create_schema=TaskReferenceCreateSchema(
                source_task_id=source_task_obj.id,
                append_to_requirement_brief=True,
                reference_note="Reuse source context",
            ),
            db_session=db_session,
        )

        db_session.refresh(target_task_obj)
        created_reference_log_obj = (
            db_session.query(DevLog)
            .filter(DevLog.id == reference_response.reference_log_id)
            .first()
        )
        task_reference_link_obj = (
            db_session.query(TaskReferenceLink)
            .filter(
                TaskReferenceLink.source_task_id == source_task_obj.id,
                TaskReferenceLink.target_task_id == target_task_obj.id,
            )
            .first()
        )

        assert reference_response.target_task_id == target_task_obj.id
        assert reference_response.source_task_id == source_task_obj.id
        assert reference_response.requirement_brief_appended is True
        assert created_reference_log_obj is not None
        assert task_reference_link_obj is not None
        assert (
            task_reference_link_obj.reference_log_id
            == reference_response.reference_log_id
        )
        assert task_reference_link_obj.requirement_brief_appended is True
        assert created_reference_log_obj.state_tag == DevLogStateTag.TRANSFERRED
        assert (
            "<!-- requirement-reference:add -->"
            in created_reference_log_obj.text_content
        )
        assert source_task_obj.id in (target_task_obj.requirement_brief or "")
    finally:
        db_session.close()


def test_create_task_reference_reuses_existing_link_without_duplicates() -> None:
    """Repeated source-target references should reuse the stored relation and evidence."""
    db_session = _create_test_session()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        db_session.add(run_account_obj)
        db_session.commit()

        source_task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Reusable source",
            lifecycle_status=TaskLifecycleStatus.CLOSED,
            workflow_stage=WorkflowStage.DONE,
            requirement_brief="Reusable source summary.",
        )
        target_task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Current target",
            lifecycle_status=TaskLifecycleStatus.OPEN,
            workflow_stage=WorkflowStage.BACKLOG,
            requirement_brief="Current target summary.",
        )
        db_session.add_all([source_task_obj, target_task_obj])
        db_session.commit()

        first_response = tasks_api.create_task_reference(
            target_task_id=target_task_obj.id,
            reference_create_schema=TaskReferenceCreateSchema(
                source_task_id=source_task_obj.id,
                append_to_requirement_brief=True,
                reference_note="Reuse source context",
            ),
            db_session=db_session,
        )
        second_response = tasks_api.create_task_reference(
            target_task_id=target_task_obj.id,
            reference_create_schema=TaskReferenceCreateSchema(
                source_task_id=source_task_obj.id,
                append_to_requirement_brief=True,
                reference_note="Reuse source context",
            ),
            db_session=db_session,
        )

        db_session.refresh(target_task_obj)
        task_reference_link_list = (
            db_session.query(TaskReferenceLink)
            .filter(
                TaskReferenceLink.source_task_id == source_task_obj.id,
                TaskReferenceLink.target_task_id == target_task_obj.id,
            )
            .all()
        )
        reference_log_list = (
            db_session.query(DevLog)
            .filter(
                DevLog.task_id == target_task_obj.id,
                DevLog.state_tag == DevLogStateTag.TRANSFERRED,
            )
            .all()
        )

        assert first_response.reference_log_id == second_response.reference_log_id
        assert second_response.requirement_brief_appended is True
        assert len(task_reference_link_list) == 1
        assert len(reference_log_list) == 1
        assert (target_task_obj.requirement_brief or "").count(
            "## Referenced Requirement Context"
        ) == 1
    finally:
        db_session.close()


def test_create_task_reference_falls_back_to_compact_requirement_appendix() -> None:
    """Oversized reference summaries should degrade to a compact appendix instead of overflowing."""
    db_session = _create_test_session()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        db_session.add(run_account_obj)
        db_session.commit()

        long_source_summary_text = "LONG-SOURCE-CONTEXT " * 120
        target_requirement_seed_text = "T" * (TASK_REQUIREMENT_BRIEF_MAX_LENGTH - 260)
        source_task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Oversized source",
            lifecycle_status=TaskLifecycleStatus.CLOSED,
            workflow_stage=WorkflowStage.DONE,
            requirement_brief=long_source_summary_text,
        )
        target_task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Nearly full target",
            lifecycle_status=TaskLifecycleStatus.OPEN,
            workflow_stage=WorkflowStage.BACKLOG,
            requirement_brief=target_requirement_seed_text,
        )
        db_session.add_all([source_task_obj, target_task_obj])
        db_session.commit()

        reference_response = tasks_api.create_task_reference(
            target_task_id=target_task_obj.id,
            reference_create_schema=TaskReferenceCreateSchema(
                source_task_id=source_task_obj.id,
                append_to_requirement_brief=True,
            ),
            db_session=db_session,
        )

        db_session.refresh(target_task_obj)

        assert reference_response.requirement_brief_appended is True
        assert (
            len(target_task_obj.requirement_brief or "")
            <= TASK_REQUIREMENT_BRIEF_MAX_LENGTH
        )
        assert f"- Source Task ID: {source_task_obj.id}" in (
            target_task_obj.requirement_brief or ""
        )
        assert "Full reference summary moved to the structured reference log" in (
            target_task_obj.requirement_brief or ""
        )
        assert long_source_summary_text not in (target_task_obj.requirement_brief or "")
    finally:
        db_session.close()


def test_create_task_reference_rejects_append_when_no_space_remains() -> None:
    """Reference append should fail fast with 422 when even the compact stub cannot fit."""
    db_session = _create_test_session()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        db_session.add(run_account_obj)
        db_session.commit()

        original_requirement_brief = "X" * (TASK_REQUIREMENT_BRIEF_MAX_LENGTH - 8)
        source_task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Compact source",
            lifecycle_status=TaskLifecycleStatus.CLOSED,
            workflow_stage=WorkflowStage.DONE,
            requirement_brief="Compact source summary.",
        )
        target_task_obj = Task(
            run_account_id=run_account_obj.id,
            task_title="Full target",
            lifecycle_status=TaskLifecycleStatus.OPEN,
            workflow_stage=WorkflowStage.BACKLOG,
            requirement_brief=original_requirement_brief,
        )
        db_session.add_all([source_task_obj, target_task_obj])
        db_session.commit()

        with pytest.raises(HTTPException, match="5000 characters"):
            tasks_api.create_task_reference(
                target_task_id=target_task_obj.id,
                reference_create_schema=TaskReferenceCreateSchema(
                    source_task_id=source_task_obj.id,
                    append_to_requirement_brief=True,
                ),
                db_session=db_session,
            )

        db_session.refresh(target_task_obj)

        assert target_task_obj.requirement_brief == original_requirement_brief
        assert (
            db_session.query(TaskReferenceLink)
            .filter(
                TaskReferenceLink.source_task_id == source_task_obj.id,
                TaskReferenceLink.target_task_id == target_task_obj.id,
            )
            .count()
            == 0
        )
        assert (
            db_session.query(DevLog)
            .filter(
                DevLog.task_id == target_task_obj.id,
                DevLog.state_tag == DevLogStateTag.TRANSFERRED,
            )
            .count()
            == 0
        )
    finally:
        db_session.close()


def test_project_timeline_summary_returns_structured_sections() -> None:
    """Project timeline summary endpoint should return milestones/risks/actions."""
    db_session = _create_test_session()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        db_session.add(run_account_obj)
        db_session.commit()

        project_obj = Project(
            display_name="Summary project",
            project_category="delivery",
            repo_path="/tmp/summary-repo",
        )
        db_session.add(project_obj)
        db_session.commit()

        closed_task_obj = Task(
            run_account_id=run_account_obj.id,
            project_id=project_obj.id,
            task_title="Closed requirement",
            lifecycle_status=TaskLifecycleStatus.CLOSED,
            workflow_stage=WorkflowStage.DONE,
        )
        open_task_obj = Task(
            run_account_id=run_account_obj.id,
            project_id=project_obj.id,
            task_title="Open requirement",
            lifecycle_status=TaskLifecycleStatus.OPEN,
            workflow_stage=WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
        )
        db_session.add_all([closed_task_obj, open_task_obj])
        db_session.commit()

        db_session.add(
            DevLog(
                task_id=open_task_obj.id,
                run_account_id=run_account_obj.id,
                text_content="Found blocker",
                state_tag=DevLogStateTag.BUG,
            )
        )
        db_session.commit()

        summary_response = chronicle_api.summarize_project_timeline(
            summary_request=ProjectTimelineSummaryRequestSchema(
                project_category="delivery",
                lifecycle_status_list=[
                    TaskLifecycleStatus.OPEN,
                    TaskLifecycleStatus.CLOSED,
                ],
                summary_focus="progress",
            ),
            db_session=db_session,
        )

        assert isinstance(summary_response["summary_text"], str)
        assert len(summary_response["milestones"]) > 0
        assert len(summary_response["risks"]) > 0
        assert len(summary_response["next_actions"]) > 0
        assert closed_task_obj.id in summary_response["source_task_ids"]
        assert open_task_obj.id in summary_response["source_task_ids"]
    finally:
        db_session.close()


def test_project_timeline_date_filter_uses_in_scope_activity_and_log_stats() -> None:
    """Project timeline date filtering should keep in-window activity and stats only."""
    db_session = _create_test_session()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        db_session.add(run_account_obj)
        db_session.commit()

        project_obj = Project(
            display_name="Delivery Project",
            project_category="delivery",
            repo_path="/tmp/delivery-project",
        )
        db_session.add(project_obj)
        db_session.commit()

        scoped_task_obj = Task(
            run_account_id=run_account_obj.id,
            project_id=project_obj.id,
            task_title="Scoped task",
            lifecycle_status=TaskLifecycleStatus.CLOSED,
            workflow_stage=WorkflowStage.DONE,
            created_at=datetime(2026, 3, 1, 0, 0, 0),
            stage_updated_at=datetime(2026, 3, 2, 0, 0, 0),
            closed_at=datetime(2026, 3, 10, 0, 0, 0),
        )
        db_session.add(scoped_task_obj)
        db_session.commit()

        db_session.add_all(
            [
                DevLog(
                    task_id=scoped_task_obj.id,
                    run_account_id=run_account_obj.id,
                    text_content="bug inside window",
                    state_tag=DevLogStateTag.BUG,
                    created_at=datetime(2026, 3, 5, 0, 0, 0),
                ),
                DevLog(
                    task_id=scoped_task_obj.id,
                    run_account_id=run_account_obj.id,
                    text_content="fix outside window",
                    state_tag=DevLogStateTag.FIXED,
                    created_at=datetime(2026, 3, 9, 0, 0, 0),
                ),
            ]
        )
        db_session.commit()

        timeline_entry_list = chronicle_api.get_project_timeline(
            project_category="delivery",
            lifecycle_status=[TaskLifecycleStatus.CLOSED],
            start_date=datetime(2026, 3, 4, 0, 0, 0),
            end_date=datetime(2026, 3, 6, 23, 59, 59),
            db_session=db_session,
        )

        assert len(timeline_entry_list) == 1
        timeline_entry = timeline_entry_list[0]
        assert timeline_entry["task_id"] == scoped_task_obj.id
        assert timeline_entry["total_logs"] == 1
        assert timeline_entry["bug_count"] == 1
        assert timeline_entry["fix_count"] == 0
        assert "2026-03-05" in timeline_entry["last_activity_at"]
    finally:
        db_session.close()


def test_project_timeline_summary_respects_date_scoped_log_stats() -> None:
    """Project timeline summary should derive risks from in-window log stats."""
    db_session = _create_test_session()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        db_session.add(run_account_obj)
        db_session.commit()

        project_obj = Project(
            display_name="Risk Project",
            project_category="delivery",
            repo_path="/tmp/risk-project",
        )
        db_session.add(project_obj)
        db_session.commit()

        open_task_obj = Task(
            run_account_id=run_account_obj.id,
            project_id=project_obj.id,
            task_title="Open risk task",
            lifecycle_status=TaskLifecycleStatus.OPEN,
            workflow_stage=WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
            created_at=datetime(2026, 3, 1, 0, 0, 0),
            stage_updated_at=datetime(2026, 3, 2, 0, 0, 0),
        )
        db_session.add(open_task_obj)
        db_session.commit()

        db_session.add_all(
            [
                DevLog(
                    task_id=open_task_obj.id,
                    run_account_id=run_account_obj.id,
                    text_content="bug inside window",
                    state_tag=DevLogStateTag.BUG,
                    created_at=datetime(2026, 3, 5, 0, 0, 0),
                ),
                DevLog(
                    task_id=open_task_obj.id,
                    run_account_id=run_account_obj.id,
                    text_content="fix outside window",
                    state_tag=DevLogStateTag.FIXED,
                    created_at=datetime(2026, 3, 9, 0, 0, 0),
                ),
            ]
        )
        db_session.commit()

        summary_response = chronicle_api.summarize_project_timeline(
            summary_request=ProjectTimelineSummaryRequestSchema(
                project_category="delivery",
                lifecycle_status_list=[TaskLifecycleStatus.OPEN],
                start_date=datetime(2026, 3, 4, 0, 0, 0),
                end_date=datetime(2026, 3, 6, 23, 59, 59),
                summary_focus="risk",
            ),
            db_session=db_session,
        )

        assert open_task_obj.id in summary_response["source_task_ids"]
        assert any(
            "Open risk task" in risk_text for risk_text in summary_response["risks"]
        )
        assert any(
            "Open risk task" in next_action_text
            for next_action_text in summary_response["next_actions"]
        )
    finally:
        db_session.close()


def test_project_timeline_summary_excludes_out_of_window_closure_milestones() -> None:
    """Closed tasks should only become milestones when the close event is in scope."""
    db_session = _create_test_session()
    try:
        run_account_obj = RunAccount(
            account_display_name="Tester",
            user_name="tester",
            environment_os="Linux",
            git_branch_name=None,
            is_active=True,
        )
        db_session.add(run_account_obj)
        db_session.commit()

        project_obj = Project(
            display_name="Delivery Project",
            project_category="delivery",
            repo_path="/tmp/delivery-project",
        )
        db_session.add(project_obj)
        db_session.commit()

        scoped_task_obj = Task(
            run_account_id=run_account_obj.id,
            project_id=project_obj.id,
            task_title="Scoped close task",
            lifecycle_status=TaskLifecycleStatus.CLOSED,
            workflow_stage=WorkflowStage.DONE,
            created_at=datetime(2026, 3, 1, 0, 0, 0),
            stage_updated_at=datetime(2026, 3, 2, 0, 0, 0),
            closed_at=datetime(2026, 3, 10, 0, 0, 0),
        )
        db_session.add(scoped_task_obj)
        db_session.commit()

        db_session.add(
            DevLog(
                task_id=scoped_task_obj.id,
                run_account_id=run_account_obj.id,
                text_content="bug inside window",
                state_tag=DevLogStateTag.BUG,
                created_at=datetime(2026, 3, 5, 0, 0, 0),
            )
        )
        db_session.commit()

        summary_response = chronicle_api.summarize_project_timeline(
            summary_request=ProjectTimelineSummaryRequestSchema(
                project_category="delivery",
                lifecycle_status_list=[TaskLifecycleStatus.CLOSED],
                start_date=datetime(2026, 3, 4, 0, 0, 0),
                end_date=datetime(2026, 3, 6, 23, 59, 59),
                summary_focus="progress",
            ),
            db_session=db_session,
        )

        assert scoped_task_obj.id in summary_response["source_task_ids"]
        assert "当前筛选范围内暂无已完成里程碑。" in summary_response["milestones"]
        assert all(
            "Scoped close task》已完成" not in milestone
            for milestone in summary_response["milestones"]
        )
        assert any(
            "Scoped close task" in risk_text for risk_text in summary_response["risks"]
        )
    finally:
        db_session.close()


def test_project_timeline_page_default_status_filter_includes_pending() -> None:
    """Project timeline page should share a default status list that includes PENDING."""
    timeline_page_source_text = Path(
        "frontend/src/pages/ProjectTimelinePage.tsx"
    ).read_text(encoding="utf-8")
    frontend_types_source_text = Path("frontend/src/types/index.ts").read_text(
        encoding="utf-8"
    )

    assert "PROJECT_TIMELINE_DEFAULT_STATUS_FILTER_LIST" in timeline_page_source_text
    default_status_match = re.search(
        r"PROJECT_TIMELINE_DEFAULT_STATUS_FILTER_LIST: TaskLifecycleStatus\[\] = \[(.*?)\]",
        frontend_types_source_text,
        re.DOTALL,
    )
    assert default_status_match is not None
    assert "TaskLifecycleStatus.PENDING" in default_status_match.group(1)


def test_project_timeline_page_css_exposes_scroll_container() -> None:
    """Standalone project timeline page should be vertically scrollable."""
    index_css_source_text = Path("frontend/src/index.css").read_text(encoding="utf-8")

    ptl_page_match = re.search(
        r"\.ptl-page\s*\{(?P<ptl_page_body>.*?)\}",
        index_css_source_text,
        re.DOTALL,
    )
    assert ptl_page_match is not None
    ptl_page_body_text = ptl_page_match.group("ptl_page_body")
    assert "height: 100%;" in ptl_page_body_text
    assert "overflow-y: auto;" in ptl_page_body_text


def test_app_exposes_abandon_action_for_abandoned_status() -> None:
    """Main task UI should expose a reachable abandon action."""
    app_source_text = Path("frontend/src/App.tsx").read_text(encoding="utf-8")

    assert (
        "async function handleAbandonRequirement(taskItem: Task): Promise<void>"
        in app_source_text
    )
    assert (
        "taskApi.updateStatus(taskItem.id, TaskLifecycleStatus.ABANDONED)"
        in app_source_text
    )
    assert "buildRequirementAbandonLog(" in app_source_text
    assert "<span>Abandon</span>" in app_source_text
