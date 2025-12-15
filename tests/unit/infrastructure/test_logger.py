# tests/unit/infrastructure/test_logger.py
from __future__ import annotations

import json
import logging
import os

import pytest

from arche_api.infrastructure.logging.logger import (
    _JsonFormatter,  # internal but importable
    configure_root_logging,
)


def _capture_log(record_msg: str, level: int = logging.INFO, **extra) -> dict:
    """Emit a log record and return the parsed JSON payload."""
    logger = logging.getLogger("test.logger")
    # Install a fresh handler with our formatter
    handler = logging.StreamHandler()
    fmt = _JsonFormatter()
    handler.setFormatter(fmt)
    logger.handlers = [handler]
    logger.setLevel(level)

    # Build record manually so we can inject arbitrary extra
    record = logger.makeRecord(
        name=logger.name,
        level=level,
        fn="test_logger",
        lno=123,
        msg=record_msg,
        args=(),
        exc_info=None,
    )
    for k, v in extra.items():
        setattr(record, k, v)
    rendered = fmt.format(record)
    return json.loads(rendered)


def test_configure_root_logging_installs_json_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Root logger should get a JSON formatter and respect LOG_LEVEL."""
    monkeypatch.setenv("LOG_LEVEL", "debug")
    root = logging.getLogger()
    root.handlers.clear()

    configure_root_logging()
    assert root.level == logging.DEBUG
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, _JsonFormatter)


def test_json_formatter_basic_fields() -> None:
    """Formatter should emit ts, level, logger and message."""
    payload = _capture_log("hello-world")
    assert payload["message"] == "hello-world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert "ts" in payload  # timestamp is present


def test_json_formatter_includes_request_id_from_record_and_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Request ID should come from record.request_id or REQUEST_ID env."""
    monkeypatch.delenv("REQUEST_ID", raising=False)

    payload = _capture_log("with-record-id", request_id="abc-123")
    assert payload["request_id"] == "abc-123"

    # Now drop record attribute, rely on env
    os.environ["REQUEST_ID"] = "env-id"
    payload = _capture_log("with-env-id")
    assert payload["request_id"] == "env-id"


def test_json_formatter_includes_exception_info(caplog: pytest.LogCaptureFixture) -> None:
    """Formatter should add exc_type and exc_message for errors with exc_info."""
    logger = logging.getLogger("test.logger.exc")
    handler = logging.StreamHandler()
    fmt = _JsonFormatter()
    handler.setFormatter(fmt)
    logger.handlers = [handler]
    logger.setLevel(logging.ERROR)

    try:
        raise ValueError("boom")
    except Exception:
        logger.exception("failure")

    # Grab last log line and parse JSON
    record = caplog.records[-1]
    line = handler.format(record)
    payload = json.loads(line)
    assert payload["level"] == "ERROR"
    assert payload["exc_type"] == "ValueError"
    assert "boom" in payload["exc_message"]
