# API Contracts

Finalized in Sprint 5 (DOC-02). The authoritative machine-readable spec is [`openapi.json`](openapi.json). The human-readable reference is [`API_REFERENCE.md`](API_REFERENCE.md).

---

## Endpoint Inventory

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | public | Aggregate service health check (OPS-01) |
| `POST` | `/api/v1/auth/login` | public | Authenticate and issue JWT (SEC-01) |
| `POST` | `/api/v1/events` | admin | Ingest billing event (ING-01/02/03) |
| `GET` | `/api/v1/anomalies` | analyst+ | List anomalies with pagination and filters (API-01) |
| `GET` | `/api/v1/anomalies/{anomaly_id}` | analyst+ | Get anomaly detail (API-02) |
| `PATCH` | `/api/v1/anomalies/{anomaly_id}/status` | analyst+ | Update anomaly lifecycle status (API-03) |
| `GET` | `/api/v1/alerts` | analyst+ | List alert delivery records (API-04) |
| `GET` | `/api/v1/kpi/summary` | analyst+ | Dashboard KPI aggregates (API-05) |
| `GET` | `/api/v1/kpi/trend` | analyst+ | Daily anomaly trend for sparkline (UI-06) |
| `GET` | `/api/v1/detection/health` | public | Detection pipeline health (DET-03) |
| `GET` | `/api/v1/detection/metrics` | public | Detection pipeline metrics (DET-03) |
| `GET` | `/api/v1/audit/logs` | admin | Paginated audit log (SEC-04) |

---

## Key Contracts

### `BillingEvent` — `POST /api/v1/events` request

```json
{
  "event_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "timestamp": "2026-04-15T14:00:00Z",
  "provider": "gcp",
  "account_id": "gcp-project-42",
  "service": "BigQuery",
  "region": "us-central1",
  "cost_amount": 1250.00,
  "usage_amount": 500.0,
  "usage_unit": "GiB",
  "tags": { "env": "prod" },
  "source_type": "live"
}
```

Required: `timestamp`, `provider`, `account_id`, `service`, `region`, `cost_amount`, `usage_amount`, `usage_unit`. `event_id` is auto-generated if omitted. Duplicate `event_id` returns `200` with `duplicate: true`.

### `IngestionReceipt` — `POST /api/v1/events` response

```json
{
  "event_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "accepted",
  "duplicate": false
}
```

### `TokenResponse` — `POST /api/v1/auth/login` response

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600,
  "role": "analyst"
}
```

### `AnomalyResponse` — anomaly endpoints

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

Status enum: `open` | `acknowledged` | `resolved` | `suppressed`.
Severity enum: `none` | `low` | `medium` | `high`.

### `AnomalyStatusUpdate` — `PATCH /api/v1/anomalies/{id}/status` request

```json
{ "status": "acknowledged" }
```

### `AlertResponse` — alert list

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

Channel enum: `in_app` | `email`. Status enum: `pending` | `sent` | `failed` | `suppressed`.

### `KpiSummaryResponse` — KPI dashboard

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
  "top_services": [{ "service": "BigQuery", "count": 88 }],
  "top_accounts": [{ "account_id": "gcp-project-42", "count": 120 }]
}
```

---

## Pagination Envelope

All list endpoints (`/anomalies`, `/alerts`, `/audit/logs`) return:

```json
{
  "items": [ ... ],
  "total": 148,
  "page": 1,
  "page_size": 50,
  "pages": 3
}
```

Default page size: `50`. Maximum: `200`.

---

## Error Shape

Validation errors (HTTP 422):

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
