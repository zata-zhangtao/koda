"""Domain errors for preview sandbox operations."""

from __future__ import annotations


class PreviewSandboxError(Exception):
    """Base class for preview sandbox failures."""


class TaskNotFoundError(PreviewSandboxError):
    """Raised when a task cannot be found."""


class PreviewNotAvailableError(PreviewSandboxError):
    """Raised when preview cannot be used for a task in its current state."""


class InvalidPreviewProfileError(PreviewSandboxError):
    """Raised when a generated preview profile violates policy."""


class PreviewCompletionBlockedError(PreviewSandboxError):
    """Raised when Complete must wait for preview retry or bypass."""
