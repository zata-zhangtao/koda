"""Domain errors for PRD source staging."""

from __future__ import annotations


class PrdSourceError(Exception):
    """Base class for PRD source domain/application errors."""


class TaskNotFoundError(PrdSourceError):
    """Raised when the target task cannot be found."""


class TaskAutomationRunningError(PrdSourceError):
    """Raised when a task already has running automation."""


class InvalidTaskStageError(PrdSourceError):
    """Raised when the task stage does not allow PRD staging."""


class PendingPrdNotFoundError(PrdSourceError):
    """Raised when a selected pending PRD does not exist."""


class UnsafePrdPathError(PrdSourceError):
    """Raised when a PRD path escapes the allowed pending/tasks boundary."""


class InvalidPrdContentError(PrdSourceError):
    """Raised when imported or selected PRD content is invalid."""


class PrdAlreadyExistsError(PrdSourceError):
    """Raised when the task already has a staged PRD file."""
