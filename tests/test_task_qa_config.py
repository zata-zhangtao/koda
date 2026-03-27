"""Regression tests for task sidecar Q&A configuration defaults."""

from __future__ import annotations

import pytest

from ai_agent.utils.model_loader import (
    DEFAULT_TASK_QA_CHAT_MODEL_NAME,
    resolve_task_qa_chat_model_name,
)
from utils import settings as settings_module


def test_resolve_task_qa_chat_model_name_prefers_explicit_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit overrides should win over environment defaults."""
    monkeypatch.setenv("TASK_QA_MODEL_NAME", "qwen-max")

    resolved_task_qa_model_name = resolve_task_qa_chat_model_name("gpt-4o-mini")

    assert resolved_task_qa_model_name == "gpt-4o-mini"


def test_resolve_task_qa_chat_model_name_uses_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The chat-model branch should respect TASK_QA_MODEL_NAME when set."""
    monkeypatch.setenv("TASK_QA_MODEL_NAME", " qwen-max ")

    resolved_task_qa_model_name = resolve_task_qa_chat_model_name()

    assert resolved_task_qa_model_name == "qwen-max"


def test_resolve_task_qa_chat_model_name_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing overrides should fall back to the baked-in chat-model default."""
    monkeypatch.delenv("TASK_QA_MODEL_NAME", raising=False)

    resolved_task_qa_model_name = resolve_task_qa_chat_model_name()

    assert resolved_task_qa_model_name == DEFAULT_TASK_QA_CHAT_MODEL_NAME


def test_load_task_qa_backend_defaults_to_chat_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task sidecar Q&A should default to the model_loader chat-model path."""
    monkeypatch.delenv("TASK_QA_BACKEND", raising=False)

    resolved_task_qa_backend = settings_module._load_task_qa_backend()

    assert resolved_task_qa_backend == "chat_model"


def test_load_task_qa_backend_rejects_invalid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid task Q&A backends should fail fast."""
    monkeypatch.setenv("TASK_QA_BACKEND", "codex")

    with pytest.raises(ValueError, match="TASK_QA_BACKEND"):
        settings_module._load_task_qa_backend()
