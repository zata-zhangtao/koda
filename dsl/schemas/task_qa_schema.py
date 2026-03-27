"""Task sidecar Q&A Pydantic schema definitions.

Defines request and response contracts for task-scoped independent Q&A so the
frontend can query messages, submit questions, and convert conclusions into
feedback drafts without mutating the main execution workflow.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from pydantic import ConfigDict, Field, field_validator

from dsl.models.enums import (
    TaskQaContextScope,
    TaskQaGenerationStatus,
    TaskQaMessageRole,
)
from dsl.schemas.base import DSLBaseSchema, DSLResponseSchema


class TaskQaMessageCreateSchema(DSLBaseSchema):
    """Task sidecar Q&A question submission payload.

    Attributes:
        question_markdown: User-authored markdown question content.
        context_scope: Requested context scope for this question.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    question_markdown: str = Field(
        ...,
        min_length=1,
        description="User-authored markdown question content.",
    )
    context_scope: TaskQaContextScope = Field(
        ...,
        description="Requested context scope for this question.",
    )

    @field_validator("question_markdown")
    @classmethod
    def validate_question_markdown(cls, raw_question_markdown: str) -> str:
        """Reject blank question payloads after whitespace normalization.

        Args:
            raw_question_markdown: Raw markdown submitted by the client.

        Returns:
            str: Normalized markdown question content.

        Raises:
            ValueError: If the normalized question is blank.
        """

        normalized_question_markdown = raw_question_markdown.strip()
        if not normalized_question_markdown:
            raise ValueError("Question markdown must not be blank.")
        return normalized_question_markdown


class TaskQaMessageResponseSchema(DSLResponseSchema):
    """Task sidecar Q&A message response schema.

    Attributes:
        id: UUID primary key.
        task_id: Owning task ID.
        run_account_id: Owning run account ID.
        role: Message role.
        context_scope: Context scope used for the question.
        generation_status: Message generation status.
        reply_to_message_id: Linked user-question message ID for AI replies.
        model_name: Model name used to generate the assistant reply.
        content_markdown: Markdown message content.
        error_text: Visible error text when generation fails.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: str = Field(..., description="UUID primary key.")
    task_id: str = Field(..., description="Owning task ID.")
    run_account_id: str = Field(..., description="Owning run account ID.")
    role: TaskQaMessageRole = Field(..., description="Message role.")
    context_scope: TaskQaContextScope = Field(
        ...,
        description="Context scope used for the question.",
    )
    generation_status: TaskQaGenerationStatus = Field(
        ...,
        description="Message generation status.",
    )
    reply_to_message_id: str | None = Field(
        None,
        description="Linked user-question message ID for AI replies.",
    )
    model_name: str | None = Field(
        None,
        description="Model name used to generate the assistant reply.",
    )
    content_markdown: str = Field(..., description="Markdown message content.")
    error_text: str | None = Field(
        None,
        description="Visible error text when generation fails.",
    )
    created_at: datetime = Field(..., description="Creation timestamp.")
    updated_at: datetime = Field(..., description="Last update timestamp.")


class TaskQaCreateResponseSchema(DSLBaseSchema):
    """Response payload for a newly submitted task Q&A question.

    Attributes:
        user_message: Persisted user question message.
        assistant_message: Persisted pending assistant reply placeholder.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    user_message: TaskQaMessageResponseSchema = Field(
        ...,
        description="Persisted user question message.",
    )
    assistant_message: TaskQaMessageResponseSchema = Field(
        ...,
        description="Persisted pending assistant reply placeholder.",
    )


class TaskQaFeedbackDraftResponseSchema(DSLBaseSchema):
    """Response payload for converting a Q&A conclusion into a feedback draft.

    Attributes:
        source_message_id: Assistant message used as the source conclusion.
        draft_markdown: Generated feedback draft text for the main feedback channel.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    source_message_id: str = Field(
        ...,
        description="Assistant message used as the source conclusion.",
    )
    draft_markdown: str = Field(
        ...,
        description="Generated feedback draft text for the main feedback channel.",
    )
