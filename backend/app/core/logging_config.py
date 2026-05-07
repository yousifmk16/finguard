"""
OPS-02: Finalized structured logging.

Centralizes log configuration for the FinGuard backend. Two output formats
are supported, selected via the ``FINGUARD_LOG_FORMAT`` environment variable:

    json  (default)  One JSON object per line. Required for production where
                     log aggregators (ELK, Loki, CloudWatch) parse fields.
    text             Human-friendly single-line output for local development.

Standard fields emitted on every record (JSON format)::

    {
      "timestamp": "2026-05-08T12:34:56.789012+00:00",
      "level":     "INFO",
      "logger":    "app.api.ingestion",
      "message":   "event accepted",
      "module":    "ingestion",
      "request_id": "8c5b2f0a4e6c4f1b9a8e2d3c5f6a7b8c",   # if set
      // any extras passed via logger.info("...", extra={...}) are merged in
      "exception": "Traceback (most recent call last): ..."  # if exc_info
    }

Request IDs
-----------
``request_id_var`` is a ContextVar populated by ``RequestIdMiddleware``.
The ``JsonFormatter`` and ``TextFormatter`` both pull the current value into
each record automatically, so callers do not need to pass ``trace_id`` in
``extra=`` for it to appear in logs.

Idempotency
-----------
``configure_logging()`` is safe to call multiple times — it replaces handlers
on the root logger rather than appending. This keeps repeated test imports
from doubling output.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# Public — middleware writes to this; formatters read from it.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


# Fields that ``logging.LogRecord`` always sets — we already emit these via
# our own field names, so they should not leak into the JSON output as
# duplicates when extras are merged.
_RESERVED_LOGRECORD_FIELDS = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
}


class JsonFormatter(logging.Formatter):
    """Serialize a LogRecord as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        payload: dict[str, Any] = {
            "timestamp": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
        }

        rid = request_id_var.get()
        if rid is not None:
            payload["request_id"] = rid

        # Merge any user-supplied extras (anything not in the reserved set).
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOGRECORD_FIELDS or key in payload:
                continue
            if key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    """Single-line human-readable formatter for local development.

    Example::
        2026-05-08T12:34:56+00:00 INFO  app.api.ingestion [req=8c5b2f0a] event accepted
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
            timespec="seconds"
        )
        rid = request_id_var.get()
        rid_part = f" [req={rid[:8]}]" if rid else ""
        line = (
            f"{ts} {record.levelname:<5} {record.name}{rid_part} "
            f"{record.getMessage()}"
        )
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def configure_logging(
    level: str | int | None = None,
    fmt: str | None = None,
) -> None:
    """Install the FinGuard log configuration on the root logger.

    Parameters
    ----------
    level
        Logging level. Falls back to ``FINGUARD_LOG_LEVEL`` env var (default INFO).
    fmt
        ``"json"`` or ``"text"``. Falls back to ``FINGUARD_LOG_FORMAT``
        env var (default ``"json"``).

    Idempotent — replaces existing handlers on each call.
    """
    if level is None:
        level = os.getenv("FINGUARD_LOG_LEVEL", "INFO")
    if fmt is None:
        fmt = os.getenv("FINGUARD_LOG_FORMAT", "json")

    formatter: logging.Formatter
    if fmt.lower() == "text":
        formatter = TextFormatter()
    else:
        formatter = JsonFormatter()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # Replace existing handlers so repeated calls don't duplicate output.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn ships its own access logger that writes plain text to stderr.
    # Route it through the same handler so JSON-only log pipelines stay clean.
    for lib_logger in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(lib_logger)
        for existing in list(lg.handlers):
            lg.removeHandler(existing)
        lg.propagate = True
