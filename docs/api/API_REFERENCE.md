# FinGuard API Reference

**Version:** 0.1.0 · **Spec:** OpenAPI 3.1.0 · **Base URL:** `http://localhost:8000`

FinGuard ingests billing events from GCP, AWS, and Azure, scores them with a weighted ensemble of time-series forecasting, Isolation Forest, and deterministic rules, and surfaces anomalies through a queryable REST API with lifecycle management.

The machine-readable spec is at [`openapi.json`](openapi.json). This document is a human-readable companion organized by functional area.

---

## Authentication

All endpoints except `/health`, `GET /api/v1/detection/health`, and `GET /api/v1/detection/metrics` require a bearer token in the `Authorization` header:

```
Authorization: Bearer <token>
```

Tokens are issued by `POST /api/v1/auth/login`. They are signed HS256 JWTs with a 60-minute TTL. The `role` claim (`admin` or `analyst`) is embedded in the token and controls endpoint access.

| Role | Access |
|------|--------|
| `admin` | All endpoints including `POST /api/v1/events` and `GET /api/v1/audit/logs` |
| `analyst` | Anomalies, Alerts, KPI, Health |
| Public | `/health`, `GET /api/v1/detection/health`, `GET /api/v1/detection/metrics` |

---

## Endpoints

### Auth

#### `POST /api/v1/auth/login`

Authenticate with email and password; receive a signed JWT.

**Request body** (`application/json`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string (email) | yes | Registered user email |
| `password` | string | yes | Plaintext password |

**Responses:**

| Status | Description |
|--------|-------------|
| `200` | Token issued — see `TokenResponse` |
| `401` | Invalid credentials |
| `503` | Database not configured |

**Response body** (`TokenResponse`):

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600,
  "role": "analyst"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `access_token` | string | Signed JWT bearer token |
| `token_type` | `"bearer"` | Always `"bearer"` |
| `expires_in` | integer | Token lifetime in seconds |
| `role` | `"admin"` \| `"analyst"` | Role granted to the authenticated user |

---

### Ingestion

#### `POST /api/v1/events`

**Auth:** bearer (admin only)

Ingest a canonical billing event (ARC-04). Duplicate `event_id` values are handled idempotently — the original receipt is returned with `duplicate=true` and HTTP 200 instead of 202. Each accepted ingest is recorded in `audit_logs` (SEC-04).

**Request body** (`application/json`) — `BillingEvent`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | string (uuid) | no | Auto-generated if omitted. Include client-side for idempotent re-submission. |
| `timestamp` | string (date-time) | yes | ISO-8601 event time |
| `provider` | `"gcp"` \| `"aws"` \| `"azure"` | yes | Cloud provider |
| `account_id` | string | yes | Cloud account / project identifier |
| `service` | string | yes | Cloud service name (e.g. `"BigQuery"`) |
| `region` | string | yes | Cloud region (e.g. `"us-central1"`) |
| `cost_amount` | number ≥ 0 | yes | Cost in USD |
| `usage_amount` | number ≥ 0 | yes | Usage quantity |
| `usage_unit` | string | yes | Usage unit (e.g. `"GiB"`) |
| `tags` | object (string values) | no | Arbitrary key-value metadata |
| `source_type` | `"synthetic"` \| `"live"` | no | Default `"synthetic"` |

**Responses:**

| Status | Description |
|--------|-------------|
| `202` | Event accepted — see `IngestionReceipt` |
| `200` | Event already accepted (duplicate `event_id`) — see `IngestionReceipt` |
| `401` | Missing or invalid bearer token |
| `403` | Authenticated user lacks the admin role |
| `422` | Validation error |

**Response body** (`IngestionReceipt`):

```json
{
  "event_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "accepted",
  "duplicate": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | string (uuid) | Assigned event ID |
| `status` | `"accepted"` | Always `"accepted"` |
| `duplicate` | boolean | `true` if this `event_id` was already ingested |

---

### Anomalies

#### `GET /api/v1/anomalies`

**Auth:** bearer (analyst or admin)

Paginated list of detected anomalies. Returns an empty list when DATABASE_URL is not configured.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `account_id` | string | — | Filter by account ID |
| `service` | string | — | Filter by service name |
| `region` | string | — | Filter by region |
| `severity` | `none` \| `low` \| `medium` \| `high` | — | Filter by severity level |
| `status` | `open` \| `acknowledged` \| `resolved` \| `suppressed` | — | Filter by lifecycle status |
| `from_bucket` | string (date-time) | — | Include buckets at or after this datetime (ISO-8601) |
| `to_bucket` | string (date-time) | — | Include buckets at or before this datetime (ISO-8601) |
| `sort` | `detected_at` \| `bucket` \| `anomaly_score` \| `severity` | `detected_at` | Column to sort by |
| `order` | `asc` \| `desc` | `desc` | Sort direction |
| `page` | integer ≥ 1 | `1` | Page number (1-indexed) |
| `page_size` | integer 1–200 | `50` | Results per page |

**Response** `200` — `AnomalyListResponse`:

```json
{
  "items": [ ... ],
  "total": 148,
  "page": 1,
  "page_size": 50,
  "pages": 3
}
```

Each item in `items` is an `AnomalyResponse` (see schema below).

---

#### `GET /api/v1/anomalies/{anomaly_id}`

**Auth:** bearer (analyst or admin)

Return a single anomaly record by UUID.

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `anomaly_id` | string (uuid) | Anomaly identifier |

**Responses:**

| Status | Description |
|--------|-------------|
| `200` | `AnomalyResponse` |
| `401` | Missing or invalid bearer token |
| `403` | Insufficient role |
| `404` | Anomaly not found |

**Response body** (`AnomalyResponse`):

```json
{
  "anomaly_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "account_id": "gcp-project-42",
  "service": "BigQuery",
  "region": "us-central1",
  "bucket": "2026-04-15T14:00:00Z",
  "anomaly_score": 0.87,
  "severity": "high",
  "status": "open",
  "detected_at": "2026-04-15T14:01:03Z",
  "score_breakdown": {
    "ts_signal": 0.91,
    "if_score": 0.85,
    "rule_score": 0.80
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `anomaly_id` | string (uuid) | yes | Unique anomaly identifier |
| `account_id` | string | yes | Cloud account / project |
| `service` | string | yes | Cloud service name |
| `region` | string | yes | Cloud region |
| `bucket` | string (date-time) | yes | 1-minute time bucket the event belongs to |
| `anomaly_score` | number | yes | Composite score ∈ [0, 1] — see scoring ensemble |
| `severity` | string | yes | `none` / `low` / `medium` / `high` |
| `status` | string | yes | Lifecycle status (`open` / `acknowledged` / `resolved` / `suppressed`) |
| `detected_at` | string (date-time) | yes | When the anomaly was first persisted |
| `score_breakdown` | object \| null | no | Per-signal scores: `ts_signal`, `if_score`, `rule_score` |

---

#### `PATCH /api/v1/anomalies/{anomaly_id}/status`

**Auth:** bearer (analyst or admin)

Transition an anomaly to a new lifecycle status.

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `anomaly_id` | string (uuid) | Anomaly identifier |

**Request body** (`AnomalyStatusUpdate`):

```json
{ "status": "acknowledged" }
```

| Field | Type | Allowed values |
|-------|------|----------------|
| `status` | string | `open` \| `acknowledged` \| `resolved` \| `suppressed` |

**Responses:**

| Status | Description |
|--------|-------------|
| `200` | Updated `AnomalyResponse` |
| `401` | Missing or invalid bearer token |
| `403` | Insufficient role |
| `404` | Anomaly not found |

---

### Alerts

#### `GET /api/v1/alerts`

**Auth:** bearer (analyst or admin)

Paginated list of alert delivery records.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `account_id` | string | — | Filter by account ID |
| `service` | string | — | Filter by service name |
| `region` | string | — | Filter by region |
| `severity` | `none` \| `low` \| `medium` \| `high` | — | Filter by severity |
| `status` | `pending` \| `sent` \| `failed` \| `suppressed` | — | Filter by delivery status |
| `channel` | `in_app` \| `email` | — | Filter by delivery channel |
| `page` | integer ≥ 1 | `1` | Page number (1-indexed) |
| `page_size` | integer 1–200 | `50` | Results per page |

**Response** `200` — `AlertListResponse`:

```json
{
  "items": [ ... ],
  "total": 23,
  "page": 1,
  "page_size": 50,
  "pages": 1
}
```

Each item in `items` is an `AlertResponse`:

```json
{
  "alert_id": "uuid",
  "anomaly_id": "uuid",
  "account_id": "gcp-project-42",
  "service": "BigQuery",
  "region": "us-central1",
  "severity": "high",
  "channel": "email",
  "status": "sent",
  "dedup_key": "gcp-project-42::BigQuery::us-central1::2026-04-15T14:00:00",
  "created_at": "2026-04-15T14:01:05Z",
  "sent_at": "2026-04-15T14:01:08Z",
  "error_detail": null
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `alert_id` | string (uuid) | yes | Alert record ID |
| `anomaly_id` | string (uuid) | yes | Associated anomaly |
| `account_id` | string | yes | Cloud account |
| `service` | string | yes | Cloud service |
| `region` | string | yes | Cloud region |
| `severity` | string | yes | Severity of the source anomaly |
| `channel` | string | yes | `in_app` or `email` |
| `status` | string | yes | `pending` / `sent` / `failed` / `suppressed` |
| `dedup_key` | string | yes | Deduplication key used by the orchestrator |
| `created_at` | string (date-time) | yes | When the alert record was created |
| `sent_at` | string (date-time) \| null | no | When the alert was successfully delivered |
| `error_detail` | string \| null | no | Error message when `status=failed` |

---

### KPI

#### `GET /api/v1/kpi/summary`

**Auth:** bearer (analyst or admin)

Aggregated anomaly statistics for dashboard KPI cards.

**Response** `200` — `KpiSummaryResponse`:

```json
{
  "total_anomalies": 312,
  "open_count": 14,
  "acknowledged_count": 5,
  "resolved_count": 290,
  "suppressed_count": 3,
  "high_severity_count": 42,
  "medium_severity_count": 117,
  "low_severity_count": 153,
  "anomalies_last_24h": 7,
  "top_services": [
    { "service": "BigQuery", "count": 88 },
    { "service": "GCS", "count": 45 }
  ],
  "top_accounts": [
    { "account_id": "gcp-project-42", "count": 120 }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `total_anomalies` | integer | All-time anomaly count |
| `open_count` | integer | Anomalies with status `open` |
| `acknowledged_count` | integer | Anomalies with status `acknowledged` |
| `resolved_count` | integer | Anomalies with status `resolved` |
| `suppressed_count` | integer | Anomalies with status `suppressed` |
| `high_severity_count` | integer | Anomalies with severity `high` |
| `medium_severity_count` | integer | Anomalies with severity `medium` |
| `low_severity_count` | integer | Anomalies with severity `low` |
| `anomalies_last_24h` | integer | Anomalies detected in the last 24 hours |
| `top_services` | `ServiceCount[]` | Top services by anomaly count (`service`, `count`) |
| `top_accounts` | `AccountCount[]` | Top accounts by anomaly count (`account_id`, `count`) |

---

#### `GET /api/v1/kpi/trend`

**Auth:** bearer (analyst or admin)

Daily anomaly counts for the dashboard sparkline.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `days` | integer 1–90 | `14` | Number of trailing days to include |

**Response** `200` — `KpiTrendResponse`:

```json
{
  "days": 14,
  "points": [
    { "day": "2026-05-01", "count": 3 },
    { "day": "2026-05-02", "count": 7 }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `days` | integer | Number of days included |
| `points` | `TrendPoint[]` | One entry per calendar day (`day` as ISO date, `count` as integer) |

---

### Health

#### `GET /health`

**Auth:** public

Aggregate service health check (OPS-01). Used by load balancers and container orchestrators.

Returns `200` for `ok` and `degraded` (service is operational). Returns `503` for `unhealthy` so orchestrators can restart the pod.

**Response** `200`:

```json
{
  "status": "ok",
  "components": {
    "database": { "status": "ok" },
    "redis": { "status": "ok" }
  }
}
```

---

### Detection

#### `GET /api/v1/detection/health`

**Auth:** public

Component health check for the real-time detection pipeline (DET-03). Returns status for DB, scorer, and emitter sub-components.

**Response** `200`:

```json
{
  "status": "ok",
  "components": {
    "db":      { "status": "ok", "anomaly_count": 42 },
    "scorer":  { "status": "ok", "baseline_loaded": true },
    "emitter": { "status": "configured", "stream_name": "anomaly-events" }
  },
  "metrics": { ... }
}
```

`status` at the top level is `"ok"` when the DB is reachable, `"degraded"` otherwise.

---

#### `GET /api/v1/detection/metrics`

**Auth:** public

In-process counter/gauge snapshot from the detection pipeline.

**Response** `200`:

```json
{
  "batches_processed": 150,
  "rows_scored": 7500,
  "anomalies_detected": 12,
  "anomalies_persisted": 12,
  "events_emitted": 12,
  "errors_scoring": 0,
  "errors_persist": 0,
  "errors_emit": 0,
  "last_batch_at": "2026-04-16T12:00:00+00:00",
  "last_batch_rows": 50,
  "last_batch_anomalies": 1
}
```

---

### Audit

#### `GET /api/v1/audit/logs`

**Auth:** bearer (admin only)

Paginated audit log query (SEC-04). Records auth events and all privileged actions.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `event_type` | string | — | Filter by event type |
| `action` | string | — | Filter by action |
| `outcome` | `success` \| `failure` | — | Filter by outcome |
| `user_id` | string (uuid) | — | Filter by actor user ID |
| `from_time` | string (date-time) | — | Include rows with `created_at >= from_time` (ISO-8601) |
| `to_time` | string (date-time) | — | Include rows with `created_at <= to_time` (ISO-8601) |
| `page` | integer ≥ 1 | `1` | Page number (1-indexed) |
| `page_size` | integer 1–200 | `50` | Results per page |

**Response** `200` — `AuditLogListResponse`:

```json
{
  "items": [ ... ],
  "total": 512,
  "page": 1,
  "page_size": 50,
  "pages": 11
}
```

Each item in `items` is an `AuditLogResponse`:

```json
{
  "audit_id": "uuid",
  "event_type": "ingest",
  "action": "create",
  "outcome": "success",
  "user_id": "uuid",
  "actor_email": "admin@example.com",
  "actor_role": "admin",
  "target_type": "billing_event",
  "target_id": "uuid",
  "ip_address": "10.0.0.1",
  "user_agent": "Mozilla/5.0 ...",
  "meta": { "event_id": "uuid" },
  "created_at": "2026-04-15T14:01:05Z"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `audit_id` | string (uuid) | yes | Audit log entry ID |
| `event_type` | string | yes | Category of event (e.g. `ingest`, `auth`) |
| `action` | string | yes | Action performed (e.g. `create`, `login`) |
| `outcome` | string | yes | `success` or `failure` |
| `user_id` | string (uuid) \| null | no | UUID of the authenticated actor |
| `actor_email` | string \| null | no | Email of the actor |
| `actor_role` | string \| null | no | Role of the actor at the time of the action |
| `target_type` | string \| null | no | Resource type affected |
| `target_id` | string \| null | no | Resource identifier |
| `ip_address` | string \| null | no | Client IP address |
| `user_agent` | string \| null | no | Client user-agent string |
| `meta` | object \| null | no | Arbitrary action-specific metadata |
| `created_at` | string (date-time) | yes | When the log entry was recorded |

---

## Error Responses

All endpoints return RFC-standard HTTP status codes. Validation errors use the `HTTPValidationError` shape:

```json
{
  "detail": [
    {
      "loc": ["body", "provider"],
      "msg": "Input should be 'gcp', 'aws' or 'azure'",
      "type": "literal_error"
    }
  ]
}
```

| Status | Meaning |
|--------|---------|
| `400` | Bad request |
| `401` | Missing or invalid bearer token |
| `403` | Authenticated but insufficient role |
| `404` | Resource not found |
| `422` | Request body / query parameter validation failure |
| `503` | Service unavailable (database not configured) |

---

## Scoring Ensemble Reference

The `anomaly_score` field is computed by the weighted fusion ensemble (ENS-01):

```
anomaly_score = Σ(wᵢ · sᵢ) / Σwᵢ
```

| Signal | Weight | Source |
|--------|--------|--------|
| `ts_signal` | 0.35 | TS-03 — per-account Z-score of rolling µ/σ, clipped at Z_CAP=5, normalized to [0, 1] |
| `if_score` | 0.40 | ML-01 — IsolationForest trained on clean baseline |
| `rule_score` | 0.25 | RUL-01/02/03 — blended: threshold_breach (w=0.50), sudden_jump (w=0.30), sustained_increase (w=0.20) |

Weights renormalize automatically when a signal is `NaN` (e.g. no trained model). Severity thresholds: `high` ≥ 0.75, `medium` ≥ 0.50, `low` ≥ 0.25, `none` < 0.25.

---

## Pagination

All list endpoints return the same pagination envelope:

| Field | Type | Description |
|-------|------|-------------|
| `items` | array | Current page of results |
| `total` | integer | Total matching records across all pages |
| `page` | integer | Current page (1-indexed) |
| `page_size` | integer | Requested page size |
| `pages` | integer | Total number of pages |
