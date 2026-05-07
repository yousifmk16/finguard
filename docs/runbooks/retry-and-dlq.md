# OPS-04 — Retry & dead-letter workflow

This runbook documents the two failure-handling paths in FinGuard, how to
diagnose them, and how to recover.

| Path | What it handles | Where failures land |
| --- | --- | --- |
| **Retry** (alert delivery) | Transient channel failures (SMTP timeout, in-app DB hiccup) | `alerts` table with `status='failed'`, `error_detail` populated |
| **Dead letter** (ingestion stream) | Unparseable / invalid billing events from the broker | JSONL file at `STREAM_DLQ_PATH` (default `logs/dlq.jsonl`) |

## 1. Alert retry

**Source:** [`backend/app/alerts/retry.py`](../../backend/app/alerts/retry.py) → `RetryPolicy`
**Caller:** [`backend/app/alerts/orchestrator.py`](../../backend/app/alerts/orchestrator.py) → `AlertOrchestrator._dispatch`

### Behavior

`RetryPolicy.execute(fn)` calls `fn` up to `max_attempts` times with
exponential backoff: `base * 2^(k-1)` seconds before attempt _k_. The default
is 3 attempts with `backoff_base=1.0`, so the worst-case sleep budget is
`1 + 2 = 3 seconds` before the third attempt.

After all retries fail, the orchestrator persists the alert with:

  - `status='failed'`
  - `error_detail = str(last_exception)[:512]` (truncated to fit the column)
  - `sent_at = NULL`

The broker message is **always acked** — even on retry exhaustion — so a
poison anomaly cannot block the queue.

### Diagnosing failed alerts

Run from a Postgres client connected to the FinGuard DB:

```sql
SELECT
  alert_id,
  anomaly_id,
  channel,
  severity,
  created_at,
  error_detail
FROM alerts
WHERE status = 'failed'
ORDER BY created_at DESC
LIMIT 50;
```

The `finguard_errors_emit_total` and `finguard_errors_persist_total`
Prometheus counters (see [metrics-dashboards.md](metrics-dashboards.md))
spike when this is happening at scale. Trace the spike against the
deploy log to find the regression.

### Replaying a failed alert

Alerts are not designed to be replayed in place — by the time a row is
`failed`, the underlying anomaly has already been persisted. To re-send
an alert manually:

1. Inspect the failure (`error_detail` will tell you what blew up).
2. Fix the underlying issue (SMTP creds, channel config).
3. Re-run dispatch by deleting the row (or using a fresh `dedup_key`)
   and replaying the original anomaly event onto `anomaly-events` —
   the orchestrator's dedup check is per `(anomaly_id, channel)`.

Most cases are better resolved by leaving the row as historical evidence
and notifying the user out-of-band.

## 2. Ingestion dead-letter queue

**Source:** [`services/stream/consumer.py`](../../services/stream/consumer.py) → `StreamConsumerService._write_dlq`
**Tools:** [`services/stream/dlq_tools.py`](../../services/stream/dlq_tools.py)

### When messages dead-letter

`StreamConsumerService._handle_message` writes a record to the DLQ when
any of the following raise:

  - `UnicodeDecodeError`  — payload is not UTF-8.
  - `json.JSONDecodeError` — payload is not valid JSON.
  - `TypeError` / `ValueError` — JSON parses but isn't a JSON object.
  - `NormalizationError` — required canonical fields are missing /
    `cost_amount` is negative / `timestamp` is unparseable / etc.

The original broker message is acked after the DLQ write so it won't
re-deliver.

### DLQ record shape

Every DLQ entry is one JSON object on one line:

```json
{
  "failed_at":   "2026-05-08T12:34:56.789012+00:00",
  "stream":      "billing-events",
  "message_id":  "1715168096000-0",
  "error":       "Expecting value: line 1 column 1 (char 0)",
  "raw_payload": "<the original bytes, decoded with errors=replace>"
}
```

`failed_at` is UTC ISO-8601. `raw_payload` preserves the original bytes
as best as possible — non-UTF-8 bytes become Unicode replacement chars.

### Triage commands

The DLQ tools live in [`services.stream.dlq_tools`](../../services/stream/dlq_tools.py).

```bash
# Count records
python -m services.stream.dlq_tools count

# Tail the most recent 20 records (default)
python -m services.stream.dlq_tools tail

# Tail the most recent 5 records
python -m services.stream.dlq_tools tail -n 5

# Custom path
python -m services.stream.dlq_tools --path /var/lib/finguard/dlq.jsonl count
```

### Programmatic replay

For ops scripts and one-off remediation:

```python
from services.stream.dlq_tools import read, replay
from services.stream.broker_interface import RedisStreamBroker

# 1. Inspect what's there.
records = read("logs/dlq.jsonl", limit=10)
for r in records:
    print(r["error"], "→", r["message_id"])

# 2. Replay everything (downstream idempotency catches duplicates).
broker = RedisStreamBroker.from_env()
published = replay("logs/dlq.jsonl", broker)
print(f"Re-published {published} records")

# 3. Replay onto a different stream during a fix-forward migration.
replay("logs/dlq.jsonl", broker, stream_override="billing-events-v2")
```

`replay()` is safe by default: the ingestion API is idempotent on
`event_id`, and the `billing_events_raw.event_id` column has a unique
index. Re-publishing the same payload twice will not double-write.

### When NOT to replay

Replay is intended for cases where the consumer was buggy and the
*messages themselves were valid*. If the message payload is genuinely
corrupt — bad JSON, missing required fields — replaying will just bounce
it back to the DLQ on the next consume. **Fix the upstream producer**
instead, then optionally drop the corrupt entries from `logs/dlq.jsonl`
once the replacement events have been published.

## 3. Deployment notes

  - Mount a persistent volume at the parent of `STREAM_DLQ_PATH` so DLQ
    records survive pod restarts. The default `logs/dlq.jsonl` is
    relative to the consumer's working directory — set
    `STREAM_DLQ_PATH=/var/lib/finguard/dlq.jsonl` (or similar) in
    production.
  - Alert on file size: a DLQ that grows past ~1 MB / day should page
    the on-call. See the `finguard_dlq_size_bytes` metric (TODO if added).
  - Rotate the file periodically (`logrotate` or equivalent) so the JSONL
    doesn't grow unbounded. After rotation, `dlq_tools` will only see the
    *current* file unless you point `--path` at the rotated copy.
