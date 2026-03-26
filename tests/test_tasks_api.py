"""Tests for task API helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import dsl.models  # noqa: F401
import dsl.api.tasks as tasks_api
from dsl.api.tasks import (
    complete_task,
    get_task,
    get_task_prd_file,
    list_task_card_metadata,
    list_tasks,
    regenerate_task_prd,
    resume_task,
)
from dsl.services import codex_runner
from dsl.models.dev_log import DevLog
from dsl.models.enums import DevLogStateTag, TaskLifecycleStatus, WorkflowStage
from dsl.models.run_account import RunAccount
from dsl.models.task import Task
from utils.database import Base
from utils.helpers import serialize_datetime_for_api


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite session for task API tests."""
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

    session = test_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def clear_codex_runtime_state() -> None:
    """Reset in-memory Codex runtime registries between tests."""
    codex_runner._running_background_task_ids.clear()
    codex_runner._running_codex_processes.clear()
    codex_runner._user_cancelled_tasks.clear()
    yield
    codex_runner._running_background_task_ids.clear()
    codex_runner._running_codex_processes.clear()
    codex_runner._user_cancelled_tasks.clear()


def test_get_task_prd_file_reads_fixed_task_specific_path(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """PRD file lookup should keep using `tasks/prd-{task_id[:8]}.md`."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title="PRD contract verification",
        worktree_path=str(tmp_path),
    )
    db_session.add(task_obj)
    db_session.commit()

    tasks_directory_path = tmp_path / "tasks"
    tasks_directory_path.mkdir()

    expected_prd_file_path = tasks_directory_path / f"prd-{task_obj.id[:8]}.md"
    expected_prd_file_path.write_text(
        "# PRD\n\n- 需求名称（AI 归纳）: PRD 输出合同\n",
        encoding="utf-8",
    )

    legacy_style_prd_file_path = tasks_directory_path / "20260317-prd-random.md"
    legacy_style_prd_file_path.write_text(
        "This older wildcard-style file should be ignored.",
        encoding="utf-8",
    )

    prd_file_response = get_task_prd_file(task_obj.id, db_session)

    assert prd_file_response["content"] == (
        "# PRD\n\n- 需求名称（AI 归纳）: PRD 输出合同\n"
    )
    assert prd_file_response["path"] == str(expected_prd_file_path)


def test_list_task_card_metadata_derives_waiting_user_without_changing_workflow_stage(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Card metadata should expose waiting_user as a display-only override."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    review_waiting_task = Task(
        run_account_id=run_account_obj.id,
        task_title="Self review waiting",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.SELF_REVIEW_IN_PROGRESS,
    )
    lint_waiting_task = Task(
        run_account_id=run_account_obj.id,
        task_title="Lint waiting",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.TEST_IN_PROGRESS,
    )
    still_running_task = Task(
        run_account_id=run_account_obj.id,
        task_title="Lint still running",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.TEST_IN_PROGRESS,
    )
    db_session.add_all([review_waiting_task, lint_waiting_task, still_running_task])
    db_session.commit()

    review_waiting_task.last_ai_activity_at = review_waiting_task.created_at
    lint_waiting_task.last_ai_activity_at = lint_waiting_task.created_at
    still_running_task.last_ai_activity_at = still_running_task.created_at
    db_session.add_all([review_waiting_task, lint_waiting_task, still_running_task])
    db_session.add_all(
        [
            DevLog(
                task_id=review_waiting_task.id,
                run_account_id=run_account_obj.id,
                text_content="AI 自检闭环完成",
                state_tag=DevLogStateTag.FIXED,
            ),
            DevLog(
                task_id=lint_waiting_task.id,
                run_account_id=run_account_obj.id,
                text_content="post-review lint 闭环完成：pre-commit 已通过",
                state_tag=DevLogStateTag.FIXED,
            ),
            DevLog(
                task_id=still_running_task.id,
                run_account_id=run_account_obj.id,
                text_content="post-review lint 闭环完成：pre-commit 已通过",
                state_tag=DevLogStateTag.FIXED,
            ),
        ]
    )
    db_session.commit()

    monkeypatch.setattr(
        tasks_api,
        "is_codex_task_running",
        lambda task_id: task_id == still_running_task.id,
    )

    task_card_metadata_list = list_task_card_metadata(db_session)
    task_card_metadata_by_task_id = {
        task_card_metadata.task_id: task_card_metadata
        for task_card_metadata in task_card_metadata_list
    }

    review_waiting_metadata = task_card_metadata_by_task_id[review_waiting_task.id]
    lint_waiting_metadata = task_card_metadata_by_task_id[lint_waiting_task.id]
    still_running_metadata = task_card_metadata_by_task_id[still_running_task.id]

    assert review_waiting_metadata.display_stage_key == "waiting_user"
    assert review_waiting_metadata.display_stage_label == "等待用户"
    assert review_waiting_metadata.is_waiting_for_user is True
    assert review_waiting_metadata.model_dump(mode="json")[
        "last_ai_activity_at"
    ] == serialize_datetime_for_api(review_waiting_task.last_ai_activity_at)

    assert lint_waiting_metadata.display_stage_key == "waiting_user"
    assert lint_waiting_metadata.display_stage_label == "等待用户"
    assert lint_waiting_metadata.is_waiting_for_user is True

    assert (
        still_running_metadata.display_stage_key == WorkflowStage.TEST_IN_PROGRESS.value
    )
    assert still_running_metadata.display_stage_label == "Testing"
    assert still_running_metadata.is_waiting_for_user is False


def test_regenerate_task_prd_schedules_background_job_with_media_context(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PRD regeneration should carry image and attachment file paths into context."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title="Regenerate with attachments",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.PRD_WAITING_CONFIRMATION,
        worktree_path=str(tmp_path),
    )
    db_session.add(task_obj)
    db_session.commit()

    monkeypatch.setattr(tasks_api.config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        tasks_api.config, "MEDIA_STORAGE_PATH", tmp_path / "data" / "media"
    )

    db_session.add_all(
        [
            DevLog(
                task_id=task_obj.id,
                run_account_id=run_account_obj.id,
                text_content="请根据截图和视频更新交互细节。",
                media_original_image_path="data/media/original/reference-shot.png",
            ),
            DevLog(
                task_id=task_obj.id,
                run_account_id=run_account_obj.id,
                text_content=(
                    "[Attachment: requirement-demo.mp4]"
                    "(/api/media/7399c41a6c63014b1d048062232027ee.mp4)"
                ),
            ),
        ]
    )
    db_session.commit()

    background_tasks = BackgroundTasks()
    updated_task = regenerate_task_prd(task_obj.id, background_tasks, db_session)

    serialized_context_block_str = "\n\n".join(
        background_tasks.tasks[0].kwargs["dev_log_text_list"]
    )

    assert updated_task.workflow_stage == WorkflowStage.PRD_GENERATING
    assert updated_task.is_codex_task_running is True
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0].func is tasks_api.run_codex_prd
    assert (
        str((tmp_path / "data" / "media" / "original" / "reference-shot.png").resolve())
        in serialized_context_block_str
    )
    assert (
        str(
            (
                tmp_path
                / "data"
                / "media"
                / "original"
                / "7399c41a6c63014b1d048062232027ee.mp4"
            ).resolve()
        )
        in serialized_context_block_str
    )
    assert "Attached local files:" in serialized_context_block_str


def test_complete_task_records_manual_override_for_unsettled_self_review(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manual completion should leave an audit log before self-review settles."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    worktree_path = tmp_path / "repo-wt-12345678"
    worktree_path.mkdir()

    task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title="Manual completion override",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.SELF_REVIEW_IN_PROGRESS,
        worktree_path=str(worktree_path),
    )
    db_session.add(task_obj)
    db_session.commit()

    db_session.add(
        DevLog(
            task_id=task_obj.id,
            run_account_id=run_account_obj.id,
            text_content="🔍 已进入 AI 自检阶段，开始第 1 轮代码评审（1/3）。",
            state_tag=DevLogStateTag.OPTIMIZATION,
        )
    )
    db_session.commit()

    monkeypatch.setattr(tasks_api, "is_codex_task_running", lambda task_id: False)

    background_tasks = BackgroundTasks()
    updated_task = complete_task(task_obj.id, background_tasks, db_session)

    recorded_log_list = (
        db_session.query(DevLog)
        .filter(DevLog.task_id == task_obj.id)
        .order_by(DevLog.created_at.asc(), DevLog.id.asc())
        .all()
    )

    assert updated_task.workflow_stage == WorkflowStage.PR_PREPARING
    assert updated_task.is_codex_task_running is True
    assert len(background_tasks.tasks) == 1
    assert any(
        "已记录人工接管" in log_item.text_content for log_item in recorded_log_list
    )


def test_complete_task_skips_manual_override_log_after_self_review_passed(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A settled self-review pass should not be logged as a manual override."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    worktree_path = tmp_path / "repo-wt-87654321"
    worktree_path.mkdir()

    task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title="Normal completion after review pass",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.SELF_REVIEW_IN_PROGRESS,
        worktree_path=str(worktree_path),
    )
    db_session.add(task_obj)
    db_session.commit()

    db_session.add_all(
        [
            DevLog(
                task_id=task_obj.id,
                run_account_id=run_account_obj.id,
                text_content="🔍 已进入 AI 自检阶段，开始第 1 轮代码评审（1/3）。",
                state_tag=DevLogStateTag.OPTIMIZATION,
            ),
            DevLog(
                task_id=task_obj.id,
                run_account_id=run_account_obj.id,
                text_content=(
                    "✅ AI 自检闭环完成：第 1 轮评审通过，未发现阻塞性问题。\n"
                    "当前阶段保持在：AI 自检中（self_review_in_progress）。"
                ),
                state_tag=DevLogStateTag.FIXED,
            ),
        ]
    )
    db_session.commit()

    monkeypatch.setattr(tasks_api, "is_codex_task_running", lambda task_id: False)

    background_tasks = BackgroundTasks()
    complete_task(task_obj.id, background_tasks, db_session)

    recorded_log_list = (
        db_session.query(DevLog)
        .filter(DevLog.task_id == task_obj.id)
        .order_by(DevLog.created_at.asc(), DevLog.id.asc())
        .all()
    )

    assert len(background_tasks.tasks) == 1
    assert not any(
        "已记录人工接管" in log_item.text_content for log_item in recorded_log_list
    )


def test_get_task_exposes_runtime_flag(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task detail responses should expose the backend runtime state."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title="Runtime flag visibility",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.SELF_REVIEW_IN_PROGRESS,
    )
    db_session.add(task_obj)
    db_session.commit()

    monkeypatch.setattr(
        tasks_api,
        "is_codex_task_running",
        lambda task_id: task_id == task_obj.id,
    )

    returned_task = get_task(task_obj.id, db_session)

    assert returned_task.is_codex_task_running is True


def test_resume_task_schedules_interrupted_self_review(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resume should restart the self-review chain when the task is stranded mid-review."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title="Resume interrupted self review",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.SELF_REVIEW_IN_PROGRESS,
        worktree_path="/tmp/repo-wt-self-review",
    )
    db_session.add(task_obj)
    db_session.commit()

    db_session.add(
        DevLog(
            task_id=task_obj.id,
            run_account_id=run_account_obj.id,
            text_content="🔍 已进入 AI 自检阶段，开始第 1 轮代码评审（1/3）。",
            state_tag=DevLogStateTag.OPTIMIZATION,
        )
    )
    db_session.commit()

    monkeypatch.setattr(tasks_api, "is_codex_task_running", lambda _task_id: False)

    background_tasks = BackgroundTasks()
    resumed_task = resume_task(task_obj.id, background_tasks, db_session)

    assert resumed_task.workflow_stage == WorkflowStage.SELF_REVIEW_IN_PROGRESS
    assert resumed_task.is_codex_task_running is True
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0].func is tasks_api.run_codex_review_resume


def test_resume_task_rejects_parked_self_review_after_pass(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resume should not restart a self-review that already passed and is waiting for Complete."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title="Parked self review",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.SELF_REVIEW_IN_PROGRESS,
        worktree_path="/tmp/repo-wt-parked-self-review",
    )
    db_session.add(task_obj)
    db_session.commit()

    db_session.add_all(
        [
            DevLog(
                task_id=task_obj.id,
                run_account_id=run_account_obj.id,
                text_content="🔍 已进入 AI 自检阶段，开始第 1 轮代码评审（1/3）。",
                state_tag=DevLogStateTag.OPTIMIZATION,
            ),
            DevLog(
                task_id=task_obj.id,
                run_account_id=run_account_obj.id,
                text_content=(
                    "✅ AI 自检闭环完成：第 1 轮评审通过，未发现阻塞性问题。\n"
                    "当前阶段保持在：AI 自检中（self_review_in_progress）。"
                ),
                state_tag=DevLogStateTag.FIXED,
            ),
        ]
    )
    db_session.commit()

    monkeypatch.setattr(tasks_api, "is_codex_task_running", lambda _task_id: False)

    background_tasks = BackgroundTasks()
    with pytest.raises(HTTPException) as raised_error:
        resume_task(task_obj.id, background_tasks, db_session)

    assert raised_error.value.status_code == 422
    assert "Self-review already passed" in str(raised_error.value.detail)
    assert len(background_tasks.tasks) == 0


def test_resume_task_schedules_interrupted_post_review_lint(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resume should restart the lint chain when the task is stranded in test_in_progress."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title="Resume interrupted lint",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.TEST_IN_PROGRESS,
        worktree_path="/tmp/repo-wt-test-stage",
    )
    db_session.add(task_obj)
    db_session.commit()

    db_session.add(
        DevLog(
            task_id=task_obj.id,
            run_account_id=run_account_obj.id,
            text_content="🧪 已进入自动化验证阶段，开始执行 post-review lint：`uv run pre-commit run --all-files`。",
            state_tag=DevLogStateTag.OPTIMIZATION,
        )
    )
    db_session.commit()

    monkeypatch.setattr(tasks_api, "is_codex_task_running", lambda _task_id: False)

    background_tasks = BackgroundTasks()
    resumed_task = resume_task(task_obj.id, background_tasks, db_session)

    assert resumed_task.workflow_stage == WorkflowStage.TEST_IN_PROGRESS
    assert resumed_task.is_codex_task_running is True
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0].func is tasks_api.run_post_review_lint_resume


def test_resume_task_rejects_parked_test_stage_after_lint_pass(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resume should not restart a parked test stage once lint already passed."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title="Parked lint stage",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.TEST_IN_PROGRESS,
        worktree_path="/tmp/repo-wt-parked-lint",
    )
    db_session.add(task_obj)
    db_session.commit()

    db_session.add_all(
        [
            DevLog(
                task_id=task_obj.id,
                run_account_id=run_account_obj.id,
                text_content="🧪 已进入自动化验证阶段，开始执行 post-review lint：`uv run pre-commit run --all-files`。",
                state_tag=DevLogStateTag.OPTIMIZATION,
            ),
            DevLog(
                task_id=task_obj.id,
                run_account_id=run_account_obj.id,
                text_content=(
                    "✅ post-review lint 闭环完成：pre-commit 已通过。\n"
                    "当前阶段保持在：自动化验证中（test_in_progress），等待用户点击 `Complete`。"
                ),
                state_tag=DevLogStateTag.FIXED,
            ),
        ]
    )
    db_session.commit()

    monkeypatch.setattr(tasks_api, "is_codex_task_running", lambda _task_id: False)

    background_tasks = BackgroundTasks()
    with pytest.raises(HTTPException) as raised_error:
        resume_task(task_obj.id, background_tasks, db_session)

    assert raised_error.value.status_code == 422
    assert "Post-review lint already passed" in str(raised_error.value.detail)
    assert len(background_tasks.tasks) == 0


def test_list_tasks_uses_precomputed_log_counts(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task list responses should use the grouped log count map on hot reads."""
    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title="Aggregate count path",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.BACKLOG,
    )
    db_session.add(task_obj)
    db_session.commit()

    monkeypatch.setattr(
        tasks_api.TaskService,
        "get_task_log_count_map",
        lambda _db_session, task_id_list: {
            task_id_str: 17 for task_id_str in task_id_list
        },
    )
    monkeypatch.setattr(tasks_api, "is_codex_task_running", lambda _task_id: False)

    returned_task_list = list_tasks(db_session=db_session)

    assert len(returned_task_list) == 1
    assert returned_task_list[0].id == task_obj.id
    assert returned_task_list[0].log_count == 17


def test_cancel_task_sends_manual_interruption_notification(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancel should move the task to changes_requested and emit the manual interruption email."""
    from dsl.services import email_service

    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()

    task_obj = Task(
        run_account_id=run_account_obj.id,
        task_title="Manual interruption target",
        lifecycle_status=TaskLifecycleStatus.OPEN,
        workflow_stage=WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
    )
    db_session.add(task_obj)
    db_session.commit()

    recorded_notification_argument_list: list[tuple[str, str, str | None]] = []

    monkeypatch.setattr(tasks_api, "cancel_codex_task", lambda task_id: True)
    monkeypatch.setattr(
        tasks_api, "clear_task_background_activity", lambda task_id: None
    )
    monkeypatch.setattr(
        email_service,
        "send_manual_interruption_notification",
        lambda task_id_str, task_title_str, interrupted_stage_value_str=None: (
            recorded_notification_argument_list.append(
                (task_id_str, task_title_str, interrupted_stage_value_str)
            )
            or True
        ),
    )

    updated_task = tasks_api.cancel_task(task_obj.id, db_session)

    assert updated_task.workflow_stage == WorkflowStage.CHANGES_REQUESTED
    assert updated_task.is_codex_task_running is False
    assert recorded_notification_argument_list == [
        (
            task_obj.id,
            "Manual interruption target",
            WorkflowStage.IMPLEMENTATION_IN_PROGRESS.value,
        )
    ]
