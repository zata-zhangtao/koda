"""Tests for logger configuration."""

import logging
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

from utils.helpers import get_app_timezone
from utils.logger import AppTimezoneFormatter, Logger


def test_logger_uses_timed_rotating_file_handler() -> None:
    logger_instance = Logger().get_logger()
    handler_types = {type(handler) for handler in logger_instance.handlers}
    assert TimedRotatingFileHandler in handler_types


def test_timed_rotating_file_handler_suffix_set() -> None:
    logger_instance = Logger().get_logger()
    rotating_handlers = [
        handler
        for handler in logger_instance.handlers
        if isinstance(handler, TimedRotatingFileHandler)
    ]
    assert rotating_handlers, "TimedRotatingFileHandler is not configured."
    assert rotating_handlers[0].suffix == "%Y-%m-%d"


def test_logger_uses_app_timezone_formatter() -> None:
    """Logger handlers should format timestamps in the configured app timezone."""
    logger_instance = Logger().get_logger()

    for handler in logger_instance.handlers:
        assert isinstance(handler.formatter, AppTimezoneFormatter)


def test_app_timezone_formatter_includes_explicit_offset() -> None:
    """Formatted log timestamps should include an explicit timezone offset."""
    formatter = AppTimezoneFormatter(datefmt="%Y-%m-%d %H:%M:%S %z")
    log_record = logging.LogRecord(
        name="app",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="test",
        args=(),
        exc_info=None,
    )
    log_record.created = 0

    formatted_timestamp = formatter.formatTime(log_record, formatter.datefmt)

    assert formatted_timestamp.endswith(
        datetime.fromtimestamp(0, tz=get_app_timezone()).strftime("%z")
    )
