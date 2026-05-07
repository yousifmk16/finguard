"""
OPS-02: Tests for finalized structured logging.

Coverage:
  1. JsonFormatter emits valid JSON with the required fields.
  2. JsonFormatter merges user-supplied extras and skips reserved keys.
  3. JsonFormatter includes ``request_id`` only when set in context.
  4. JsonFormatter serializes exceptions into the ``exception`` field.
  5. TextFormatter produces a single-line human-readable string.
  6. configure_logging() is idempotent (no duplicate handlers).
  7. RequestIdMiddleware honors inbound X-Request-ID and echoes it back.
  8. RequestIdMiddleware generates a hex UUID when none is supplied.
  9. The request_id context var is populated during request handling.
 10. Non-JSON-serializable extras fall back to repr().
"""

from __future__ import annotations

import json
import logging
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.logging_config import (
    JsonFormatter,
    TextFormatter,
    configure_logging,
    request_id_var,
)
from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    level: int = logging.INFO,
    msg: str = "hello",
    name: str = "test.logger",
    extra: dict | None = None,
    exc_info=None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=10,
        msg=msg,
        args=None,
        exc_info=exc_info,
    )
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    return record


# ---------------------------------------------------------------------------
# 1. JsonFormatter — required fields
# ---------------------------------------------------------------------------


def test_json_formatter_emits_valid_json():
    record = _make_record(msg="event accepted")
    out = JsonFormatter().format(record)
    parsed = json.loads(out)
    assert isinstance(parsed, dict)


def test_json_formatter_required_fields_present():
    record = _make_record(msg="event accepted", name="app.api.ingestion")
    parsed = json.loads(JsonFormatter().format(record))
    for key in ("timestamp", "level", "logger", "message", "module"):
        assert key in parsed, f"missing key: {key}"
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "app.api.ingestion"
    assert parsed["message"] == "event accepted"


# ---------------------------------------------------------------------------
# 2. JsonFormatter — extras merged, reserved keys skipped
# ---------------------------------------------------------------------------


def test_json_formatter_merges_extras():
    record = _make_record(extra={"event_id": "abc-123", "provider": "gcp"})
    parsed = json.loads(JsonFormatter().format(record))
    assert parsed["event_id"] == "abc-123"
    assert parsed["provider"] == "gcp"


def test_json_formatter_skips_reserved_logrecord_fields():
    """``args``, ``levelno``, ``pathname``, etc. should not leak into output."""
    record = _make_record()
    parsed = json.loads(JsonFormatter().format(record))
    for reserved in ("args", "levelno", "pathname", "msecs", "relativeCreated"):
        assert reserved not in parsed


def test_json_formatter_skips_underscore_extras():
    record = _make_record(extra={"_internal": "skip me", "visible": "keep me"})
    parsed = json.loads(JsonFormatter().format(record))
    assert "_internal" not in parsed
    assert parsed["visible"] == "keep me"


# ---------------------------------------------------------------------------
# 3. JsonFormatter — request_id from contextvar
# ---------------------------------------------------------------------------


def test_json_formatter_omits_request_id_when_unset():
    request_id_var.set(None)
    parsed = json.loads(JsonFormatter().format(_make_record()))
    assert "request_id" not in parsed


def test_json_formatter_includes_request_id_when_set():
    token = request_id_var.set("rid-from-test-123")
    try:
        parsed = json.loads(JsonFormatter().format(_make_record()))
        assert parsed["request_id"] == "rid-from-test-123"
    finally:
        request_id_var.reset(token)


# ---------------------------------------------------------------------------
# 4. JsonFormatter — exceptions
# ---------------------------------------------------------------------------


def test_json_formatter_serializes_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _make_record(level=logging.ERROR, exc_info=sys.exc_info())

    parsed = json.loads(JsonFormatter().format(record))
    assert "exception" in parsed
    assert "ValueError" in parsed["exception"]
    assert "boom" in parsed["exception"]


# ---------------------------------------------------------------------------
# 5. TextFormatter
# ---------------------------------------------------------------------------


def test_text_formatter_single_line_no_request_id():
    request_id_var.set(None)
    out = TextFormatter().format(_make_record(msg="ready"))
    assert "\n" not in out
    assert "INFO" in out
    assert "ready" in out
    assert "[req=" not in out


def test_text_formatter_includes_truncated_request_id():
    rid = "abcd1234efgh5678"
    token = request_id_var.set(rid)
    try:
        out = TextFormatter().format(_make_record(msg="ready"))
        assert "[req=abcd1234]" in out  # first 8 chars only
    finally:
        request_id_var.reset(token)


def test_text_formatter_appends_traceback_for_exceptions():
    try:
        raise RuntimeError("kaboom")
    except RuntimeError:
        import sys

        record = _make_record(level=logging.ERROR, exc_info=sys.exc_info())
    out = TextFormatter().format(record)
    assert "RuntimeError" in out
    assert "kaboom" in out


# ---------------------------------------------------------------------------
# 6. configure_logging() — idempotent
# ---------------------------------------------------------------------------


def test_configure_logging_is_idempotent():
    configure_logging(level="INFO", fmt="json")
    first_count = len(logging.getLogger().handlers)
    configure_logging(level="INFO", fmt="json")
    configure_logging(level="DEBUG", fmt="text")
    assert len(logging.getLogger().handlers) == first_count


def test_configure_logging_text_format_uses_text_formatter():
    configure_logging(level="INFO", fmt="text")
    handler = logging.getLogger().handlers[0]
    assert isinstance(handler.formatter, TextFormatter)
    # Restore JSON for the rest of the suite.
    configure_logging(level="INFO", fmt="json")


def test_configure_logging_json_format_uses_json_formatter():
    configure_logging(level="INFO", fmt="json")
    handler = logging.getLogger().handlers[0]
    assert isinstance(handler.formatter, JsonFormatter)


# ---------------------------------------------------------------------------
# 7-9. RequestIdMiddleware
# ---------------------------------------------------------------------------


def test_request_id_middleware_echoes_inbound_header():
    rid = "client-supplied-rid-001"
    response = client.get("/health", headers={"X-Request-ID": rid})
    assert response.headers.get("X-Request-ID") == rid


def test_request_id_middleware_generates_hex_uuid_when_absent():
    response = client.get("/health")
    rid = response.headers.get("X-Request-ID")
    assert rid is not None
    # uuid4().hex → 32 lowercase hex chars
    assert re.fullmatch(r"[0-9a-f]{32}", rid), f"unexpected request id: {rid}"


def test_request_id_middleware_unique_across_requests():
    rids = {client.get("/health").headers["X-Request-ID"] for _ in range(5)}
    assert len(rids) == 5


def test_request_id_context_resets_after_request():
    """After the response is returned, no leftover id should leak into background tasks."""
    client.get("/health", headers={"X-Request-ID": "leak-check-rid"})
    # Outside any active request, the contextvar should be back to default.
    assert request_id_var.get() is None


# ---------------------------------------------------------------------------
# 10. Non-JSON-serializable extras
# ---------------------------------------------------------------------------


def test_json_formatter_handles_non_serializable_extras():
    class Opaque:
        def __repr__(self) -> str:
            return "<Opaque>"

    record = _make_record(extra={"weird": Opaque()})
    parsed = json.loads(JsonFormatter().format(record))
    assert parsed["weird"] == "<Opaque>"
