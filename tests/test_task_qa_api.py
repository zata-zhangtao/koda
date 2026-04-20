"""Tests for task-scoped sidecar Q&A APIs and service behavior."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import backend.dsl.models  # noqa: F401
from backend.dsl.api.task_qa import (
    convert_task_qa_message_to_feedback_draft,
    create_task_qa_message,
    list_task_qa_messages,
)
from backend.dsl.models.dev_log import DevLog
from backend.dsl.models.enums import (
    DevLogStateTag,
    TaskLifecycleStatus,
    TaskQaContextScope,
    TaskQaGenerationStatus,
    TaskQaMessageRole,
    WorkflowStage,
)
from backend.dsl.models.run_account import RunAccount
from backend.dsl.models.task import Task
from backend.dsl.models.task_qa_message import TaskQaMessage
from backend.dsl.schemas.task_qa_schema import TaskQaMessageCreateSchema
from backend.dsl.services.task_qa_service import TaskQaService
from utils.database import Base


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite session for task Q&A tests."""
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


def _create_active_run_account(db_session: Session) -> RunAccount:
    """Create one active run account for direct route invocation tests.

    Args:
        db_session: Database session.

    Returns:
        RunAccount: Persisted active run account.
    """

    run_account_obj = RunAccount(
        account_display_name="Tester",
        user_name="tester",
        environment_os="Linux",
        git_branch_name=None,
        is_active=True,
    )
    db_session.add(run_account_obj)
    db_session.commit()
    db_session.refresh(run_account_obj)
    return run_account_obj


def _create_task(
    db_session: Session,
    run_account_id: str,
    *,
    workflow_stage: WorkflowStage = WorkflowStage.PRD_WAITING_CONFIRMATION,
    lifecycle_status: TaskLifecycleStatus = TaskLifecycleStatus.OPEN,
    worktree_path: str | None = None,
    requirement_brief: str | None = "Need a sidecar Q&A lane.",
) -> Task:
    """Create a persisted task for task-Q&A tests.

    Args:
        db_session: Database session.
        run_account_id: Active run account ID.
        workflow_stage: Initial workflow stage.
        lifecycle_status: Initial lifecycle status.
        worktree_path: Optional worktree path.
        requirement_brief: Optional requirement brief.

    Returns:
        Task: Persisted task object.
    """

    task_obj = Task(
        run_account_id=run_account_id,
        task_title="Sidecar Q&A task",
        lifecycle_status=lifecycle_status,
        workflow_stage=workflow_stage,
        worktree_path=worktree_path,
        requirement_brief=requirement_brief,
    )
    db_session.add(task_obj)
    db_session.commit()
    db_session.refresh(task_obj)
    return task_obj


def test_create_task_qa_message_schedules_pending_reply_without_stage_change(
    db_session: Session,
) -> None:
    """Submitting a sidecar question should not mutate the main workflow stage."""

    run_account_obj = _create_active_run_account(db_session)
    task_obj = _create_task(
        db_session,
        run_account_obj.id,
        workflow_stage=WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
    )

    background_tasks = BackgroundTasks()
    response_payload = create_task_qa_message(
        task_obj.id,
        TaskQaMessageCreateSchema(
            question_markdown="这个方案会不会打断当前 coding？",
            context_scope=TaskQaContextScope.IMPLEMENTATION,
        ),
        background_tasks,
        db_session,
    )

    db_session.refresh(task_obj)
    persisted_message_list = (
        db_session.query(TaskQaMessage)
        .filter(TaskQaMessage.task_id == task_obj.id)
        .order_by(TaskQaMessage.created_at.asc(), TaskQaMessage.id.asc())
        .all()
    )

    assert task_obj.workflow_stage == WorkflowStage.IMPLEMENTATION_IN_PROGRESS
    assert response_payload.user_message.role == TaskQaMessageRole.USER
    assert response_payload.assistant_message.role == TaskQaMessageRole.ASSISTANT
    assert (
        response_payload.assistant_message.generation_status
        == TaskQaGenerationStatus.PENDING
    )
    assert len(persisted_message_list) == 2
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0].func is TaskQaService.process_pending_reply


def test_create_task_qa_message_rejects_when_another_reply_is_pending(
    db_session: Session,
) -> None:
    """A task should allow at most one pending assistant reply at a time."""

    run_account_obj = _create_active_run_account(db_session)
    task_obj = _create_task(db_session, run_account_obj.id)

    TaskQaService.create_question(
        db_session,
        task_obj.id,
        run_account_obj.id,
        TaskQaMessageCreateSchema(
            question_markdown="第一个问题",
            context_scope=TaskQaContextScope.PRD_CONFIRMATION,
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        create_task_qa_message(
            task_obj.id,
            TaskQaMessageCreateSchema(
                question_markdown="第二个问题",
                context_scope=TaskQaContextScope.PRD_CONFIRMATION,
            ),
            BackgroundTasks(),
            db_session,
        )

    assert exc_info.value.status_code == 409
    assert "pending" in str(exc_info.value.detail).lower()


def test_task_qa_database_constraint_rejects_second_pending_reply(
    db_session: Session,
) -> None:
    """The SQLite schema should reject a second pending assistant reply."""

    run_account_obj = _create_active_run_account(db_session)
    task_obj = _create_task(db_session, run_account_obj.id)

    first_user_message_obj = TaskQaMessage(
        task_id=task_obj.id,
        run_account_id=run_account_obj.id,
        role=TaskQaMessageRole.USER,
        context_scope=TaskQaContextScope.PRD_CONFIRMATION,
        generation_status=TaskQaGenerationStatus.COMPLETED,
        content_markdown="第一个问题",
    )
    db_session.add(first_user_message_obj)
    db_session.flush()
    first_pending_assistant_message_obj = TaskQaMessage(
        task_id=task_obj.id,
        run_account_id=run_account_obj.id,
        role=TaskQaMessageRole.ASSISTANT,
        context_scope=TaskQaContextScope.PRD_CONFIRMATION,
        generation_status=TaskQaGenerationStatus.PENDING,
        reply_to_message_id=first_user_message_obj.id,
        content_markdown="",
    )
    db_session.add(first_pending_assistant_message_obj)
    db_session.commit()

    second_user_message_obj = TaskQaMessage(
        task_id=task_obj.id,
        run_account_id=run_account_obj.id,
        role=TaskQaMessageRole.USER,
        context_scope=TaskQaContextScope.PRD_CONFIRMATION,
        generation_status=TaskQaGenerationStatus.COMPLETED,
        content_markdown="第二个问题",
    )
    db_session.add(second_user_message_obj)
    db_session.flush()
    second_pending_assistant_message_obj = TaskQaMessage(
        task_id=task_obj.id,
        run_account_id=run_account_obj.id,
        role=TaskQaMessageRole.ASSISTANT,
        context_scope=TaskQaContextScope.PRD_CONFIRMATION,
        generation_status=TaskQaGenerationStatus.PENDING,
        reply_to_message_id=second_user_message_obj.id,
        content_markdown="",
    )
    db_session.add(second_pending_assistant_message_obj)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    persisted_pending_assistant_message_list = (
        db_session.query(TaskQaMessage)
        .filter(
            TaskQaMessage.task_id == task_obj.id,
            TaskQaMessage.role == TaskQaMessageRole.ASSISTANT,
            TaskQaMessage.generation_status == TaskQaGenerationStatus.PENDING,
        )
        .all()
    )

    assert len(persisted_pending_assistant_message_list) == 1


def test_create_question_translates_pending_integrity_error_to_value_error(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service should convert database pending conflicts into the same user error."""

    run_account_obj = _create_active_run_account(db_session)
    task_obj = _create_task(db_session, run_account_obj.id)
    pending_lookup_call_count = 0

    def _fake_get_pending_assistant_message(
        _db_session: Session,
        _task_id: str,
        _run_account_id: str,
    ) -> TaskQaMessage | None:
        nonlocal pending_lookup_call_count
        pending_lookup_call_count += 1
        if pending_lookup_call_count == 1:
            return None
        return TaskQaMessage(
            task_id=task_obj.id,
            run_account_id=run_account_obj.id,
            role=TaskQaMessageRole.ASSISTANT,
            context_scope=TaskQaContextScope.PRD_CONFIRMATION,
            generation_status=TaskQaGenerationStatus.PENDING,
            content_markdown="",
        )

    def _raise_pending_integrity_error() -> None:
        raise IntegrityError(
            "INSERT INTO task_qa_messages ...",
            {},
            Exception("UNIQUE constraint failed: task_qa_messages.task_id"),
        )

    monkeypatch.setattr(
        TaskQaService,
        "_get_pending_assistant_message",
        _fake_get_pending_assistant_message,
    )
    monkeypatch.setattr(db_session, "commit", _raise_pending_integrity_error)

    with pytest.raises(
        ValueError,
        match="Another sidecar Q&A reply is still pending for this task.",
    ):
        TaskQaService.create_question(
            db_session,
            task_obj.id,
            run_account_obj.id,
            TaskQaMessageCreateSchema(
                question_markdown="这个冲突要怎么翻译？",
                context_scope=TaskQaContextScope.PRD_CONFIRMATION,
            ),
        )

    assert db_session.query(TaskQaMessage).count() == 0


def test_task_qa_message_create_schema_rejects_blank_question_markdown() -> None:
    """Whitespace-only question payloads should fail schema validation."""

    with pytest.raises(ValidationError, match="must not be blank"):
        TaskQaMessageCreateSchema(
            question_markdown="   ",
            context_scope=TaskQaContextScope.PRD_CONFIRMATION,
        )


def test_create_question_rejects_blank_question_after_service_normalization(
    db_session: Session,
) -> None:
    """Service-side normalization should still reject blank questions defensively."""

    run_account_obj = _create_active_run_account(db_session)
    task_obj = _create_task(db_session, run_account_obj.id)
    invalid_task_qa_message_create = TaskQaMessageCreateSchema.model_construct(
        question_markdown="   ",
        context_scope=TaskQaContextScope.PRD_CONFIRMATION,
    )

    with pytest.raises(ValueError, match="must not be blank"):
        TaskQaService.create_question(
            db_session,
            task_obj.id,
            run_account_obj.id,
            invalid_task_qa_message_create,
        )


def test_list_task_qa_messages_releases_expired_pending_reply(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Polling should automatically fail stale pending replies."""

    run_account_obj = _create_active_run_account(db_session)
    task_obj = _create_task(db_session, run_account_obj.id)
    stale_created_at = datetime(2026, 3, 26, 9, 0, 0)
    monkeypatch.setattr(
        "backend.dsl.services.task_qa_service._TASK_QA_PENDING_REPLY_EXPIRATION_SECONDS",
        30.0,
    )
    monkeypatch.setattr(
        "backend.dsl.services.task_qa_service.utc_now_naive",
        lambda: datetime(2026, 3, 26, 9, 1, 0),
    )

    user_message_obj = TaskQaMessage(
        task_id=task_obj.id,
        run_account_id=run_account_obj.id,
        role=TaskQaMessageRole.USER,
        context_scope=TaskQaContextScope.PRD_CONFIRMATION,
        generation_status=TaskQaGenerationStatus.COMPLETED,
        content_markdown="这个 pending 会自己恢复吗？",
        created_at=stale_created_at,
    )
    db_session.add(user_message_obj)
    db_session.flush()

    assistant_message_obj = TaskQaMessage(
        task_id=task_obj.id,
        run_account_id=run_account_obj.id,
        role=TaskQaMessageRole.ASSISTANT,
        context_scope=TaskQaContextScope.PRD_CONFIRMATION,
        generation_status=TaskQaGenerationStatus.PENDING,
        reply_to_message_id=user_message_obj.id,
        content_markdown="",
        created_at=stale_created_at,
    )
    db_session.add(assistant_message_obj)
    db_session.commit()

    listed_message_list = list_task_qa_messages(task_obj.id, db_session)
    db_session.refresh(assistant_message_obj)

    assert assistant_message_obj.generation_status == TaskQaGenerationStatus.FAILED
    assert "released from pending" in (assistant_message_obj.error_text or "")
    listed_assistant_message_obj = next(
        listed_message_obj
        for listed_message_obj in listed_message_list
        if listed_message_obj.id == assistant_message_obj.id
    )
    assert (
        listed_assistant_message_obj.generation_status == TaskQaGenerationStatus.FAILED
    )


def test_create_question_releases_expired_pending_reply_before_accepting_new_one(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Submitting a new question should clear only stale pending blockers."""

    run_account_obj = _create_active_run_account(db_session)
    task_obj = _create_task(db_session, run_account_obj.id)
    stale_created_at = datetime(2026, 3, 26, 9, 0, 0)
    monkeypatch.setattr(
        "backend.dsl.services.task_qa_service._TASK_QA_PENDING_REPLY_EXPIRATION_SECONDS",
        30.0,
    )
    monkeypatch.setattr(
        "backend.dsl.services.task_qa_service.utc_now_naive",
        lambda: datetime(2026, 3, 26, 9, 1, 0),
    )

    stale_user_message_obj = TaskQaMessage(
        task_id=task_obj.id,
        run_account_id=run_account_obj.id,
        role=TaskQaMessageRole.USER,
        context_scope=TaskQaContextScope.IMPLEMENTATION,
        generation_status=TaskQaGenerationStatus.COMPLETED,
        content_markdown="旧问题",
        created_at=stale_created_at,
    )
    db_session.add(stale_user_message_obj)
    db_session.flush()

    stale_assistant_message_obj = TaskQaMessage(
        task_id=task_obj.id,
        run_account_id=run_account_obj.id,
        role=TaskQaMessageRole.ASSISTANT,
        context_scope=TaskQaContextScope.IMPLEMENTATION,
        generation_status=TaskQaGenerationStatus.PENDING,
        reply_to_message_id=stale_user_message_obj.id,
        content_markdown="",
        created_at=stale_created_at,
    )
    db_session.add(stale_assistant_message_obj)
    db_session.commit()

    (
        _new_user_message_obj,
        new_assistant_message_obj,
    ) = TaskQaService.create_question(
        db_session,
        task_obj.id,
        run_account_obj.id,
        TaskQaMessageCreateSchema(
            question_markdown="新问题",
            context_scope=TaskQaContextScope.IMPLEMENTATION,
        ),
    )
    db_session.refresh(stale_assistant_message_obj)

    assert (
        stale_assistant_message_obj.generation_status == TaskQaGenerationStatus.FAILED
    )
    assert "released from pending" in (stale_assistant_message_obj.error_text or "")
    assert new_assistant_message_obj.generation_status == TaskQaGenerationStatus.PENDING


def test_build_task_context_markdown_degrades_gracefully_without_prd_file(
    db_session: Session,
) -> None:
    """Missing PRD files should not prevent sidecar Q&A context construction."""

    run_account_obj = _create_active_run_account(db_session)
    task_obj = _create_task(
        db_session,
        run_account_obj.id,
        workflow_stage=WorkflowStage.PRD_WAITING_CONFIRMATION,
        requirement_brief="Need to clarify how sidecar Q&A avoids mutating execution.",
    )
    db_session.add(
        DevLog(
            task_id=task_obj.id,
            run_account_id=run_account_obj.id,
            created_at=datetime(2026, 3, 26, 9, 0, 0),
            text_content="User asked whether Q&A should stay out of DevLog prompt context.",
            state_tag=DevLogStateTag.OPTIMIZATION,
        )
    )
    db_session.commit()

    context_markdown = TaskQaService.build_task_context_markdown(
        db_session=db_session,
        task_id=task_obj.id,
        run_account_id=run_account_obj.id,
        latest_user_question_markdown="如果没有 PRD 文件怎么办？",
        task_qa_context_scope=TaskQaContextScope.PRD_CONFIRMATION,
    )

    assert "Sidecar Q&A task" in context_markdown
    assert "prd_waiting_confirmation" in context_markdown
    assert "No PRD file is currently available" in context_markdown
    assert "User asked whether Q&A should stay out of DevLog prompt context." in (
        context_markdown
    )


def test_process_pending_reply_marks_message_completed_on_success(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Successful model generation should complete the pending assistant reply."""

    class _FakeResponse:
        """Minimal fake LangChain response object."""

        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeChatModel:
        """Minimal fake LangChain chat model."""

        def invoke(self, _messages: list[object]) -> _FakeResponse:
            return _FakeResponse("不会。sidecar Q&A 默认不会触发 execute 或 resume。")

    run_account_obj = _create_active_run_account(db_session)
    worktree_path = tmp_path / "repo"
    task_obj = _create_task(
        db_session,
        run_account_obj.id,
        workflow_stage=WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
        worktree_path=str(worktree_path),
    )
    (worktree_path / "tasks").mkdir(parents=True)
    (worktree_path / "tasks" / f"prd-{task_obj.id[:8]}.md").write_text(
        "# PRD\n\n当前有一份可读 PRD。\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "backend.dsl.services.task_qa_service.create_task_qa_chat_model",
        lambda **_kwargs: _FakeChatModel(),
    )

    (
        _user_message_obj,
        assistant_message_obj,
    ) = TaskQaService.create_question(
        db_session,
        task_obj.id,
        run_account_obj.id,
        TaskQaMessageCreateSchema(
            question_markdown="这会不会打断当前 coding？",
            context_scope=TaskQaContextScope.IMPLEMENTATION,
        ),
    )

    TaskQaService._process_pending_reply_in_session(
        db_session, assistant_message_obj.id
    )
    db_session.refresh(assistant_message_obj)

    assert assistant_message_obj.generation_status == TaskQaGenerationStatus.COMPLETED
    assert "不会" in assistant_message_obj.content_markdown
    assert assistant_message_obj.error_text is None


def test_process_pending_reply_marks_message_failed_on_model_error(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Model errors should fail only the assistant message itself."""

    run_account_obj = _create_active_run_account(db_session)
    task_obj = _create_task(db_session, run_account_obj.id)

    def _raise_model_error(**_kwargs: object) -> object:
        raise RuntimeError("missing API key")

    monkeypatch.setattr(
        "backend.dsl.services.task_qa_service.create_task_qa_chat_model",
        _raise_model_error,
    )

    (
        _user_message_obj,
        assistant_message_obj,
    ) = TaskQaService.create_question(
        db_session,
        task_obj.id,
        run_account_obj.id,
        TaskQaMessageCreateSchema(
            question_markdown="为什么失败了？",
            context_scope=TaskQaContextScope.PRD_CONFIRMATION,
        ),
    )

    TaskQaService._process_pending_reply_in_session(
        db_session, assistant_message_obj.id
    )
    db_session.refresh(assistant_message_obj)
    db_session.refresh(task_obj)

    assert assistant_message_obj.generation_status == TaskQaGenerationStatus.FAILED
    assert "missing API key" in (assistant_message_obj.error_text or "")
    assert task_obj.workflow_stage == WorkflowStage.PRD_WAITING_CONFIRMATION


def test_generate_answer_markdown_passes_timeout_controls_to_chat_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sidecar generation should set explicit timeout and retry controls."""

    captured_model_kwargs: dict[str, object] = {}

    class _FakeResponse:
        """Minimal fake LangChain response object."""

        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeChatModel:
        """Minimal fake chat model."""

        def invoke(self, _messages: list[object]) -> _FakeResponse:
            return _FakeResponse("回答完成")

    def _fake_create_task_qa_chat_model(**model_kwargs: object) -> _FakeChatModel:
        captured_model_kwargs.update(model_kwargs)
        return _FakeChatModel()

    monkeypatch.setattr(
        "backend.dsl.services.task_qa_service.create_task_qa_chat_model",
        _fake_create_task_qa_chat_model,
    )

    assistant_reply_markdown = TaskQaService.generate_answer_markdown(
        task_context_markdown="上下文",
        user_question_markdown="问题",
    )

    assert assistant_reply_markdown == "回答完成"
    assert captured_model_kwargs["client_kwargs"] == {
        "timeout": 60.0,
        "max_retries": 1,
    }


def test_convert_task_qa_message_to_feedback_draft_uses_answer_content(
    db_session: Session,
) -> None:
    """Converting a completed answer should return a reusable feedback draft."""

    run_account_obj = _create_active_run_account(db_session)
    task_obj = _create_task(
        db_session,
        run_account_obj.id,
        workflow_stage=WorkflowStage.IMPLEMENTATION_IN_PROGRESS,
    )

    user_message_obj = TaskQaMessage(
        task_id=task_obj.id,
        run_account_id=run_account_obj.id,
        role=TaskQaMessageRole.USER,
        context_scope=TaskQaContextScope.IMPLEMENTATION,
        generation_status=TaskQaGenerationStatus.COMPLETED,
        content_markdown="这个结论能不能整理成正式反馈？",
    )
    db_session.add(user_message_obj)
    db_session.flush()

    assistant_message_obj = TaskQaMessage(
        task_id=task_obj.id,
        run_account_id=run_account_obj.id,
        role=TaskQaMessageRole.ASSISTANT,
        context_scope=TaskQaContextScope.IMPLEMENTATION,
        generation_status=TaskQaGenerationStatus.COMPLETED,
        reply_to_message_id=user_message_obj.id,
        content_markdown="可以，但需要用户确认后再作为正式反馈提交。",
        model_name="qwen-plus",
    )
    db_session.add(assistant_message_obj)
    db_session.commit()
    db_session.refresh(assistant_message_obj)

    draft_response = convert_task_qa_message_to_feedback_draft(
        task_obj.id,
        assistant_message_obj.id,
        db_session,
    )

    assert draft_response.source_message_id == assistant_message_obj.id
    assert "这个结论能不能整理成正式反馈？" in draft_response.draft_markdown
    assert "需要用户确认后再作为正式反馈提交" in draft_response.draft_markdown


def test_list_task_qa_messages_returns_chronological_order(
    db_session: Session,
) -> None:
    """Listing messages should return them in ascending creation order."""

    run_account_obj = _create_active_run_account(db_session)
    task_obj = _create_task(db_session, run_account_obj.id)
    db_session.add_all(
        [
            TaskQaMessage(
                task_id=task_obj.id,
                run_account_id=run_account_obj.id,
                role=TaskQaMessageRole.USER,
                context_scope=TaskQaContextScope.PRD_CONFIRMATION,
                generation_status=TaskQaGenerationStatus.COMPLETED,
                content_markdown="first",
                created_at=datetime(2026, 3, 26, 9, 0, 0),
            ),
            TaskQaMessage(
                task_id=task_obj.id,
                run_account_id=run_account_obj.id,
                role=TaskQaMessageRole.ASSISTANT,
                context_scope=TaskQaContextScope.PRD_CONFIRMATION,
                generation_status=TaskQaGenerationStatus.COMPLETED,
                content_markdown="second",
                created_at=datetime(2026, 3, 26, 9, 0, 1),
            ),
        ]
    )
    db_session.commit()

    listed_message_list = list_task_qa_messages(task_obj.id, db_session)

    assert [message.content_markdown for message in listed_message_list] == [
        "first",
        "second",
    ]


def test_list_task_qa_messages_allows_deleted_task_history_reads(
    db_session: Session,
) -> None:
    """Deleted tasks should still expose archived sidecar Q&A history."""

    run_account_obj = _create_active_run_account(db_session)
    deleted_task_obj = _create_task(
        db_session,
        run_account_obj.id,
        lifecycle_status=TaskLifecycleStatus.DELETED,
    )
    archived_user_message_obj = TaskQaMessage(
        task_id=deleted_task_obj.id,
        run_account_id=run_account_obj.id,
        role=TaskQaMessageRole.USER,
        context_scope=TaskQaContextScope.IMPLEMENTATION,
        generation_status=TaskQaGenerationStatus.COMPLETED,
        content_markdown="删除归档后还能看到这段历史吗？",
    )
    db_session.add(archived_user_message_obj)
    db_session.flush()

    archived_assistant_message_obj = TaskQaMessage(
        task_id=deleted_task_obj.id,
        run_account_id=run_account_obj.id,
        role=TaskQaMessageRole.ASSISTANT,
        context_scope=TaskQaContextScope.IMPLEMENTATION,
        generation_status=TaskQaGenerationStatus.COMPLETED,
        reply_to_message_id=archived_user_message_obj.id,
        content_markdown="可以，删除归档后仍然保留只读 sidecar 历史。",
    )
    db_session.add(archived_assistant_message_obj)
    db_session.commit()

    listed_message_list = list_task_qa_messages(deleted_task_obj.id, db_session)

    assert [message.content_markdown for message in listed_message_list] == [
        "删除归档后还能看到这段历史吗？",
        "可以，删除归档后仍然保留只读 sidecar 历史。",
    ]
