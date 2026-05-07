"""
OPS-04: Dead-letter queue inspection and replay tooling.

The stream consumer (``StreamConsumerService``) writes one JSON object per
line to ``logs/dlq.jsonl`` (or whatever ``STREAM_DLQ_PATH`` is set to) for
every event it cannot decode, validate, or normalize.  This module gives
operators a small, scriptable surface for triaging that file:

  count(path)             # total record count
  read(path, limit=None)  # iterate records (newest first when limit given)
  replay(path, broker)    # re-publish raw_payload back to the original stream

Each DLQ record has the shape::

    {
      "failed_at":    "2026-05-08T12:34:56+00:00",
      "stream":       "billing-events",
      "message_id":   "1715168096000-0",
      "error":        "Expecting value: line 1 column 1 (char 0)",
      "raw_payload":  "<base-64-or-utf8 string>"
    }

Replay safety
-------------
``replay`` uses the *same* stream name the message originally came from.
The downstream pipeline already deduplicates events by ``event_id`` (the
ingestion idempotency store + the ``billing_events_raw`` unique index), so
re-publishing a fixed payload that still has its original event id is safe.
Replay is intended for cases where the *consumer* was buggy and the
underlying messages were always valid; if the message itself is corrupt,
fix the upstream producer instead.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import deque
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol


LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


_REQUIRED_FIELDS = ("failed_at", "stream", "message_id", "error", "raw_payload")


def _iter_lines(path: Path) -> Iterator[str]:
    """Yield non-empty lines from ``path``. Returns nothing if path is missing."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                yield stripped


def count(path: str | Path) -> int:
    """Return the number of records in the DLQ file at ``path``.

    Counts non-empty lines — silently skips trailing whitespace.  Returns 0
    when the file is missing.
    """
    return sum(1 for _ in _iter_lines(Path(path)))


def read(path: str | Path, limit: int | None = None) -> list[dict[str, Any]]:
    """Return DLQ records as parsed dicts.

    Parameters
    ----------
    path:
        Path to the DLQ JSONL file.
    limit:
        When set, returns only the *most recent* ``limit`` records (file order
        is append-only, so the tail is the newest).  ``None`` returns all.

    Malformed JSON lines are skipped with a warning — the caller should not
    have to defend against a corrupted DLQ to triage other valid entries.
    """
    p = Path(path)
    raw_iter = _iter_lines(p)

    if limit is None:
        lines: list[str] = list(raw_iter)
    else:
        # ``deque(iterable, maxlen=N)`` keeps only the last N items in O(N) memory.
        lines = list(deque(raw_iter, maxlen=limit))

    out: list[dict[str, Any]] = []
    for raw in lines:
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            LOGGER.warning("DLQ record ignored — invalid JSON: %s", exc)
            continue
        if not isinstance(record, dict):
            LOGGER.warning("DLQ record ignored — not an object: %r", record)
            continue
        out.append(record)
    return out


def validate_record(record: dict[str, Any]) -> list[str]:
    """Return a list of missing required fields, empty if the record is well-formed."""
    return [f for f in _REQUIRED_FIELDS if f not in record]


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


class _Publisher(Protocol):
    def publish(self, stream_name: str, payload: str) -> str: ...


def replay(
    path: str | Path,
    broker: _Publisher,
    *,
    limit: int | None = None,
    stream_override: str | None = None,
) -> int:
    """Re-publish DLQ records via ``broker.publish`` and return the count published.

    Parameters
    ----------
    path:
        DLQ JSONL file.
    broker:
        Anything with a ``publish(stream_name, payload) -> message_id`` method
        (the ``EventBroker`` protocol).
    limit:
        Optional cap on the number of newest records to replay.
    stream_override:
        If supplied, all records are re-published to this stream instead of
        the original ``stream`` field.  Useful when migrating to a new stream
        name during a fix-forward.

    Records missing required fields are skipped with a warning — replaying a
    half-formed record would just bounce it back to the DLQ on the next pass.
    """
    records = read(path, limit=limit)
    published = 0
    for record in records:
        missing = validate_record(record)
        if missing:
            LOGGER.warning(
                "DLQ replay skipping record (missing %s): %s",
                ",".join(missing),
                record.get("message_id", "<no-id>"),
            )
            continue
        target_stream = stream_override or record["stream"]
        broker.publish(target_stream, record["raw_payload"])
        published += 1
    return published


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dlq_tools",
        description="OPS-04: inspect and replay DLQ records",
    )
    parser.add_argument(
        "--path",
        default="logs/dlq.jsonl",
        help="Path to the DLQ JSONL file (default: logs/dlq.jsonl)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("count", help="Print the number of records in the DLQ.")

    tail = sub.add_parser("tail", help="Print the most recent N DLQ records as JSON lines.")
    tail.add_argument("-n", "--limit", type=int, default=20)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entrypoint for ``python -m services.stream.dlq_tools``."""
    args = _build_parser().parse_args(argv)
    path = Path(args.path)

    if args.cmd == "count":
        print(count(path))
        return 0
    if args.cmd == "tail":
        for record in read(path, limit=args.limit):
            print(json.dumps(record))
        return 0
    return 2  # unreachable — argparse enforces required=True


if __name__ == "__main__":
    sys.exit(main())
