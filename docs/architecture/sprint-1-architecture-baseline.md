# Sprint 1 Architecture Baseline (ARC-01 to ARC-08)

## ARC-01 Selected Architecture Style

Selected: event-driven service architecture.

Reason:
- supports low-latency streaming decisions,
- isolates failures by service boundary,
- allows parallel team delivery.

## ARC-02 Component Boundaries

- Synthetic Generator: produces labeled billing events.
- Ingestion Service: validates and accepts incoming events.
- Stream Broker: transports events asynchronously.
- Detection Service: feature extraction + scoring + explanation.
- Alert Service: dedup, cooldown, in-app/email dispatch.
- Backend API: read/write application interfaces.
- Frontend Dashboard: user interaction and monitoring.
- Storage: PostgreSQL for persistence, Redis for cache/state.

## ARC-03 Communication Paths

### Async
- Generator -> Ingestion -> Broker -> Detection -> Alert Service

### Sync
- Dashboard -> Backend API -> PostgreSQL/Redis
- Alert Service -> email provider (SMTP/API)

## ARC-04 Canonical Event Schema v1

```json
{
  "event_id": "uuid",
  "timestamp": "ISO-8601",
  "provider": "aws",
  "account_id": "string",
  "service": "string",
  "region": "string",
  "cost_amount": 0.0,
  "usage_amount": 0.0,
  "usage_unit": "string",
  "tags": {},
  "source_type": "synthetic"
}
```

## ARC-05 Anomaly Output Schema v1

```json
{
  "anomaly_id": "uuid",
  "account_id": "string",
  "timestamp": "ISO-8601",
  "final_score": 0.0,
  "severity": "low|medium|high",
  "score_breakdown": {
    "ts": 0.0,
    "if": 0.0,
    "rule": 0.0
  },
  "explanation": "string",
  "status": "new"
}
```

## ARC-06 Storage Schema v1

| Table | Purpose | Key Fields |
|---|---|---|
| `billing_events_raw` | normalized event history | `event_id`, `timestamp`, `account_id`, `cost_amount` |
| `billing_agg_1m` | account-level minute aggregates | `bucket_ts`, `account_id`, `total_cost` |
| `model_features` | feature vectors for scoring | `feature_ts`, `account_id`, feature columns |
| `anomalies` | anomaly decisions | `anomaly_id`, `timestamp`, `final_score`, `status` |
| `alerts` | alert dispatch and dedup state | `alert_id`, `anomaly_id`, `channel`, `sent_at` |

## ARC-07 Auth and RBAC Strategy

- JWT for authentication.
- Roles:
  - Admin: manage policies/users and all analyst actions.
  - Analyst: investigate and triage anomalies.
- Protected endpoints enforce role checks.
- Security events (login, policy changes, status overrides) are audit logged.

## ARC-08 Deployment Topology

### Local (development)
- Docker Compose stack: backend, frontend, postgres, redis, broker.
- Used for feature integration and sprint demos.

### Cloud profile (target)
- Container services for backend/frontend.
- Managed Postgres and Redis.
- Managed message broker (Kafka-compatible).
- Centralized logs/metrics and secret store.
