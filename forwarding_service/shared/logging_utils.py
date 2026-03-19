"""Structured logging helpers for forwarding service components."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping
from typing import Any


def get_structured_logger(logger_name: str, log_level_name: str) -> logging.Logger:
    """Create or reuse a stream logger for JSON event logs.

    Args:
        logger_name (str): Logger name.
        log_level_name (str): Desired log level.

    Returns:
        logging.Logger: Configured logger instance.
    """
    structured_logger = logging.getLogger(logger_name)
    structured_logger.setLevel(getattr(logging, log_level_name.upper(), logging.INFO))

    if structured_logger.handlers:
        return structured_logger

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(structured_logger.level)
    stream_handler.setFormatter(logging.Formatter("%(message)s"))
    structured_logger.addHandler(stream_handler)
    structured_logger.propagate = False
    return structured_logger


def log_event(
    structured_logger: logging.Logger,
    level_name: str,
    event_name: str,
    event_fields: Mapping[str, Any] | None = None,
) -> None:
    """Emit a structured JSON log event.

    Args:
        structured_logger: Logger instance.
        level_name: Logging level name.
        event_name: Event type identifier.
        event_fields: Optional event payload.
    """
    payload_dict = {"event": event_name, **(dict(event_fields or {}))}
    log_method = getattr(structured_logger, level_name.lower(), structured_logger.info)
    log_method(json.dumps(payload_dict, ensure_ascii=False, sort_keys=True))
