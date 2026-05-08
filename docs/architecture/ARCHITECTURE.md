# FinGuard — Finalized Architecture Document

> **Document status:** Final (DOC-01 · Sprint 5).
> Supersedes the Sprint 1 baseline in `sprint-1-architecture-baseline.md`.
> Reflects the system as implemented and verified through Sprint 5 integration testing (TST-05).

---

## Table of contents

1. [Purpose and scope](#1-purpose-and-scope)
2. [Architecture style](#2-architecture-style)
3. [Component inventory](#3-component-inventory)
4. [System data-flow](#4-system-data-flow)
5. [Detection pipeline](#5-detection-pipeline)
6. [Scoring ensemble](#6-scoring-ensemble)
7. [Explanation stack (EXP-01..04)](#7-explanation-stack-exp-0104)
8. [Database schema](#8-database-schema)
9. [REST API surface](#9-rest-api-surface)
10. [Authentication and RBAC](#10-authentication-and-rbac)
11. [Deployment topology](#11-deployment-topology)
12. [ML quality gates (MLQ-01..04)](#12-ml-quality-gates-mlq-0104)
13. [Observability](#13-observability)
14. [Configuration reference](#14-configuration-reference)
15. [Cross-reference index](#15-cross-reference-index)

---

## 1. Purpose and scope

FinGuard is a real-time cloud billing anomaly detection platform.
It ingests raw billing events from GCP (with adapter hooks for AWS and Azure),
scores each minute-aggregate with a weighted ensemble of three complementary signals,
produces human-readable explanations, and surfaces anomalies through a queryable REST API
backed by a React dashboard with role-based access control.

The system is designed for:
- **Low latency** — Redis Streams transport events from ingestion to detection in under a second.
- **Operational simplicity** — every service reads env vars at startup; no hard-coded config.
- **Graceful degradation** — if an ML model is absent, its weight is redistributed to the remaining signals and scoring continues without interruption.
- **Auditability** — every privileged action is audit-logged; every request carries a `X-Request-ID` trace header end-to-end.

---

## 2. Architecture style

**Event-driven microservices** (ARC-01).

The ingest → detect → alert pipeline is fully async (Redis Streams).
The API → frontend path is synchronous REST (FastAPI + React fetch/polling).

| Criterion | Decision |
| --- | --- |
| Transport | Redis Streams (lightweight, persistent, consumer-group semantics) |
| API framework | FastAPI 0.115 (async, OpenAPI auto-docs, Pydantic v2 validation) |
| Frontend | React 18.3 + Vite 5.4 (SPA, no SSR) |
| Persistence | PostgreSQL 14+ (structured storage), Redis 7+ (cache + streams) |
| Auth | JWT (HS256), 60-minute TTL, role claim embedded |
| Deployment unit | Docker Compose (local), containers on managed cloud (cloud profile) |

---

## 3. Component inventory

| # | Component | Location | Role |
| --- | --- | --- | --- |
| 1 | **Synthetic Generator** | `generators/` | Produces labeled billing events for development and ML evaluation |
| 2 | **Ingestion API** | `backend/app/api/ingestion.py` | Validates, deduplicates (ING-03), normalises, and persists billing events; publishes to `billing-events` stream |
| 3 | **Stream Broker** | Redis Streams | Transports events async between ingestion and detection workers |
| 4 | **Stream Consumer** | `services/stream/consumer.py` | Reads from `billing-events`, runs the feature + scoring pipeline per event |
| 5 | **Detection Pipeline** | `services/` + `ml/src/` | Feature extraction (FEA-01/04), ensemble scoring (ENS-01), explanation (EXP-01..04) |
| 6 | **Alert Orchestrator** | `backend/app/alerts/orchestrator.py` | Consumes `anomaly-events`, deduplicates (ALT-02), applies cooldown (ALT-03), dispatches in-app and email alerts |
| 7 | **Backend REST API** | `backend/app/main.py` | Exposes anomalies, alerts, KPIs, auth, audit, health, and metrics over HTTP; caches hot reads in Redis |
| 8 | **Frontend Dashboard** | `frontend/src/` | React SPA — dashboard, anomaly list/detail, alert center, settings; role-gated views |

The **Normalizer** (`services/normalizer/`) runs inside the Stream Consumer and translates raw provider events (GCP schema today; AWS/Azure adapters via provider registry) into the canonical internal format before the feature pipeline.

---

## 4. System data-flow

Full diagram: [`diagrams/system-architecture.mmd`](diagrams/system-architecture.mmd)

```
Synthetic Generator
      │  POST /api/v1/events
      ▼
Ingestion API ──────────────► billing_events_raw (PostgreSQL)
      │
      │  XADD billing-events
      ▼
Redis Streams ──► Stream Consumer ──► Feature Pipeline ──► OnlineScorer
                                                                │
                              ┌─────────────────────────────────┤
                              │                                 │
                              ▼                                 ▼
                       anomalies (PostgreSQL)         anomaly-events (Redis Streams)
                              │                                 │
                              ▼                                 ▼
                        Backend API                    Alert Orchestrator
                              │                                 │
                              ▼                          ┌──────┴──────┐
                       Frontend SPA                      ▼             ▼
                    (REST + polling)            In-App Channel   Email Channel
                                                      │
                                                      ▼
                                               alerts (PostgreSQL)
                                                      │
                                                      ▼
                                               Backend API → Frontend SPA
```

**Async path latency budget:** event publication to anomaly persist target < 60 s end-to-end (TST-07 SLA).

---

## 5. Detection pipeline

Detection runs inside the Stream Consumer on each ingested event group.
The pipeline has four stages:

### 5.1 Normalisation

`services/normalizer/core.py` maps a provider-specific event to the
canonical `BillingEvent` schema (ARC-04). Provider adapters live in
`services/normalizer/providers/`; GCP is the reference implementation.

### 5.2 Feature extraction

`FEA-01` — rolling aggregate features: `total_cost_rollN_mean`,
`total_cost_rollN_std`, `total_cost_rollN_max` for N ∈ {3, 6, 12, 24}.

`FEA-04` — calendar features: `hour_of_day`, `day_of_week`.

Both run per `(account_id, service, region)` group.

### 5.3 Scoring — see [§ 6](#6-scoring-ensemble)

### 5.4 Persistence and emission

After scoring, the detection service:
1. Wraps the result in an `AnomalyExplanationResponse` (EXP-04 schema).
2. Persists an `Anomaly` record to PostgreSQL.
3. Publishes an `anomaly-events` message to Redis Streams for the Alert Orchestrator.

---

## 6. Scoring ensemble

Implementation: `ml/src/inference/scorer.py` (`OnlineScorer`, ENS-01)

### 6.1 Three signals

| Signal | Source | Default weight | Range | Degrades to |
| --- | --- | --- | --- | --- |
| `ts_signal` | TS-03 time-series z-score | **0.35** | [0, 1] | 0 if no baseline |
| `if_score` | ML-01 Isolation Forest | **0.40** | [0, 1] | NaN if no model file |
| `rule_score` | RUL-01/02/03 blended rules | **0.25** | [0, 1] | always available |

### 6.2 Fusion formula

```
anomaly_score = Σ(wᵢ · sᵢ) / Σwᵢ
```

where the sum is taken only over signals whose value is not NaN.
When `if_score = NaN` (model absent), the 0.40 weight is redistributed
across `ts_signal` and `rule_score` proportionally, preserving the ratio
0.35 : 0.25 = 7 : 5.

### 6.3 Rule sub-scores (RUL-01/02/03)

| Rule | Trigger condition | Weight within rule blend |
| --- | --- | --- |
| `threshold_breach` (RUL-01) | `cost > FINGUARD_THRESHOLD_BUDGET_LIMIT` (default 1000) | 0.50 |
| `sudden_jump` (RUL-02) | Δcost > `FINGUARD_THRESHOLD_SUDDEN_JUMP_PCT` of window mean (default 50 %) | 0.30 |
| `sustained_increase` (RUL-03) | ≥ `FINGUARD_THRESHOLD_SUSTAINED_WINDOW` consecutive rising periods each by ≥ `FINGUARD_THRESHOLD_SUSTAINED_GROWTH` (defaults: 3, 5 %) | 0.20 |

Rule weights are validated at import time to sum to 1.0 ± 0.001 and can be
overridden at runtime via `FINGUARD_WEIGHT_*` environment variables.

### 6.4 Threshold calibration

MLQ-01 (`ml/src/tuning/tune_thresholds.py`) tunes the anomaly threshold on a
3 000-row synthetic validation set (seed 42, ~5 % anomaly rate).
The calibrated threshold is written to `ml/artifacts/threshold_calibration.json`.
At threshold **0.30**: precision = 1.000, recall = 0.730 (108 TP, 0 FP, 40 FN, 2 852 TN).

---

## 7. Explanation stack (EXP-01..04)

Full diagram: [`diagrams/detection-flow.mmd`](diagrams/detection-flow.mmd)

| Layer | Module | Output |
| --- | --- | --- |
| EXP-01 | `ml/src/explanation/forecast_explanation.py` | `ForecastExplanation` — residual, direction ("above"/"below"), 95 % CI, narrative summary |
| EXP-02 | `ml/src/explanation/rule_explanation.py` | `RuleExplanation` — per-rule fired flag, observed value, margin, triggered-rules list |
| EXP-03 | `ml/src/explanation/score_breakdown.py` | `ScoreBreakdown` — component table (name, weight, raw score, weighted contribution, active flag) |
| EXP-04 | `backend/app/schemas/explanation.py` | `AnomalyExplanationResponse` — Pydantic API schema, validated via `format_explanation()` |

The EXP-04 schema is the **contract gate** for all quality examples (MLQ-04).
Every curated gallery payload round-trips through `AnomalyExplanationResponse.model_validate()`.

---

## 8. Database schema

Five Alembic-managed migrations (`backend/alembic/versions/0001…0005`).

### `billing_events_raw` (migration 0001)

| Column | Type | Notes |
| --- | --- | --- |
| `event_id` | UUID PK | Idempotency key — unique constraint prevents duplicate ingest |
| `timestamp` | timestamptz | Provider event time |
| `provider` | varchar | `gcp` \| `aws` \| `azure` |
| `account_id` | varchar | Cloud billing account |
| `service` | varchar | Cloud product / service |
| `region` | varchar | Cloud region |
| `cost_amount` | numeric | Cost in account currency |
| `usage_amount` | numeric | Unit usage |
| `usage_unit` | varchar | Unit label |
| `tags` | jsonb | Arbitrary provider tags |
| `source_type` | varchar | `synthetic` \| `live` |
| `ingested_at` | timestamptz | Server-side insert timestamp |

### `anomalies` (migration 0002)

| Column | Type | Notes |
| --- | --- | --- |
| `anomaly_id` | UUID PK | |
| `account_id` | varchar | |
| `service` | varchar | |
| `region` | varchar | |
| `bucket` | timestamptz | 1-minute aggregate bucket |
| `detected_at` | timestamptz | Detection time |
| `anomaly_score` | float | [0, 1] ensemble score |
| `anomaly_threshold` | float | Threshold active at detection time |
| `severity` | varchar | `none` \| `low` \| `medium` \| `high` |
| `anomaly_type` | varchar | `spike` \| `budget_breach` \| `normal` |
| `status` | varchar | `open` \| `acknowledged` \| `resolved` \| `suppressed` |
| `score_breakdown` | jsonb | EXP-04 payload — full explanation |

### `alerts` (migration 0003)

| Column | Type | Notes |
| --- | --- | --- |
| `alert_id` | UUID PK | |
| `anomaly_id` | UUID FK → anomalies | |
| `channel` | varchar | `in_app` \| `email` |
| `status` | varchar | `pending` \| `sent` \| `failed` \| `suppressed` |
| `created_at` | timestamptz | |
| `sent_at` | timestamptz | Null until delivered |
| `error_detail` | text | Set on failure |

### `users` (migration 0004)

| Column | Type | Notes |
| --- | --- | --- |
| `user_id` | UUID PK | |
| `email` | varchar UNIQUE | |
| `hashed_password` | varchar | bcrypt |
| `role` | varchar | `admin` \| `analyst` |
| `is_active` | boolean | |
| `created_at` | timestamptz | |

### `audit_logs` (migration 0005)

| Column | Type | Notes |
| --- | --- | --- |
| `log_id` | UUID PK | |
| `actor_id` | UUID | User who performed the action |
| `actor_email` | varchar | Snapshot at time of action |
| `action` | varchar | e.g. `status_update`, `login` |
| `resource_type` | varchar | |
| `resource_id` | varchar | |
| `detail` | jsonb | Action-specific payload |
| `client_ip` | varchar | From `X-Forwarded-For` |
| `created_at` | timestamptz | |

---

## 9. REST API surface

Base path: `/api/v1`. Full interactive docs at `/docs` (Swagger UI) and `/redoc`.

| Tag | Endpoint | Method | Auth | Role |
| --- | --- | --- | --- | --- |
| **auth** | `/auth/login` | POST | — | — |
| **ingestion** | `/events` | POST | Bearer | analyst+ |
| **anomalies** | `/anomalies` | GET | Bearer | analyst+ |
| **anomalies** | `/anomalies/{id}` | GET | Bearer | analyst+ |
| **anomalies** | `/anomalies/{id}/status` | PATCH | Bearer | analyst+ |
| **alerts** | `/alerts` | GET | Bearer | analyst+ |
| **kpi** | `/kpi/summary` | GET | Bearer | analyst+ |
| **kpi** | `/kpi/trend` | GET | Bearer | analyst+ |
| **detection** | `/detection/health` | GET | Bearer | analyst+ |
| **audit** | `/audit/logs` | GET | Bearer | **admin** |
| **health** | `/health` | GET | — | — |
| **metrics** | `/metrics` | GET | — | — |

All list endpoints support `page` / `page_size` pagination plus dimension
filters (`account_id`, `service`, `region`, `severity`, `status`) and, for
anomalies, sort (`detected_at`, `bucket`, `anomaly_score`, `severity`).

---

## 10. Authentication and RBAC

**JWT** (`HS256`, 60-minute TTL by default).

The `role` claim is embedded in the token at login and verified by FastAPI
dependencies on every protected route.

| Role | Capabilities |
| --- | --- |
| `admin` | All analyst capabilities + manage users, manage policies, read audit logs |
| `analyst` | Ingest events, read and filter anomalies, read alerts, read KPIs, triage anomaly status |

Security events logged to `audit_logs`: login, status transitions, policy changes.
Client IP is captured from `X-Forwarded-For` (honoured by all three cloud LB implementations).

`JWT_SECRET` **must** be overridden in any non-development environment.
The application warns and starts with the dev-only fallback, but the fallback is
deterministic and not secret.

---

## 11. Deployment topology

### 11.1 Local (development)

Six processes, all optional beyond the minimum four required for API traffic:

| # | Process | Port | Required |
| --- | --- | --- | --- |
| 1 | PostgreSQL | 5432 | Yes |
| 2 | Redis | 6379 | Yes (stream path) |
| 3 | Backend API (`uvicorn`) | 8000 | Yes |
| 4 | Frontend (`vite dev`) | 3000 | UI only |
| 5 | Stream consumer | — | Stream path |
| 6 | Alert orchestrator | — | Alert path |

Full walkthrough: [`docs/deployment/local-deployment.md`](../deployment/local-deployment.md)

### 11.2 Cloud profile (GCP reference)

| Component | GCP service | AWS equivalent | Azure equivalent |
| --- | --- | --- | --- |
| Backend API | Cloud Run | ECS Fargate | Container Apps |
| Stream consumer / alert worker | Cloud Run job / GKE Deployment | ECS service | Container Apps |
| Frontend SPA | Cloud Storage + Cloud CDN | S3 + CloudFront | Storage Static Web + Front Door |
| PostgreSQL | Cloud SQL for PostgreSQL | RDS for PostgreSQL | Azure DB for PostgreSQL Flexible |
| Redis Streams | Memorystore for Redis | ElastiCache | Azure Cache for Redis |
| Secrets | Secret Manager | Secrets Manager | Key Vault |
| Logs | Cloud Logging (JSON ingest) | CloudWatch Logs | Log Analytics |
| Metrics | Cloud Monitoring / Managed Prometheus | AMP | Azure Managed Prometheus |

Detailed walkthrough: [`docs/deployment/cloud-deployment.md`](../deployment/cloud-deployment.md)

**Recommended rollout order:**
1. Apply Alembic migrations (one-shot job, pre-deploy).
2. Deploy backend API to 5–10 % canary; watch `finguard_http_requests_total{status=~"5.."}`.
3. Deploy stream consumer and alert orchestrator workers.
4. Promote API to 100 %.
5. Sync frontend build to CDN and invalidate cache.

**Scale-out caveat:** the in-process idempotency store is per-replica.
The `event_id` unique index in `billing_events_raw` provides the true cross-replica dedup
guarantee. Migrate the in-process store to Redis `SET NX` before running multiple API replicas
(ING-03 follow-up).

---

## 12. ML quality gates (MLQ-01..04)

Four frozen quality reports live in `ml/reports/`:

| Gate | Task | Artifact | Key metric |
| --- | --- | --- | --- |
| MLQ-01 | Threshold calibration | `threshold_calibration.json` | threshold = 0.30, F1 = 0.844 |
| MLQ-02 | Model evaluation | `MODEL_EVALUATION_REPORT.md` | precision = 1.000, recall = 0.730 at 0.30 |
| MLQ-03 | False-positive analysis | `FALSE_POSITIVE_ANALYSIS.md` | FP = 0, borderline margin = 0.035 |
| MLQ-04 | Explainability gallery | `EXPLAINABILITY_EXAMPLES.md` | 5 curated cases, all EXP-04 validated |

The evaluation set is a deterministic 3 000-row synthetic dataset (seed 42, ~5 % anomaly rate)
built by `ml/src/tuning/build_validation_set.py`. Re-run MLQ-01..04 whenever the score
recipe or training data changes.

---

## 13. Observability

Three OPS tasks instrument the backend:

| Layer | Endpoint / mechanism | Format |
| --- | --- | --- |
| **Health** (OPS-01) | `GET /health` | JSON — `ok` \| `degraded` \| `unhealthy` per component |
| **Structured logs** (OPS-02) | stdout | JSON (one object per line, `request_id` always set) |
| **Prometheus metrics** (OPS-03) | `GET /metrics` | Text format 0.0.4 |

Grafana dashboard: `infra/dashboards/finguard.json`.
Setup: [`docs/runbooks/metrics-dashboards.md`](../runbooks/metrics-dashboards.md).

Dead-letter queue (OPS-04): events that fail processing are written to
`STREAM_DLQ_PATH` (default `logs/dlq.jsonl`). Inspect with
`python -m services.stream.dlq_tools tail`.

---

## 14. Configuration reference

All runtime behaviour is controlled by environment variables.
No secrets are hard-coded; the dev-only fallbacks are safe only for local development.

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | _(required)_ | SQLAlchemy connection string for PostgreSQL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `JWT_SECRET` | `dev-only-fallback` | HMAC-SHA256 signing key — **must** be overridden in production |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `JWT_EXPIRE_MINUTES` | `60` | Token TTL |
| `FINGUARD_CORS_ORIGINS` | `http://localhost:3000,...` | Comma-separated CORS allow-list |
| `FINGUARD_LOG_LEVEL` | `INFO` | Log level |
| `FINGUARD_LOG_FORMAT` | `json` | `json` (production) or `text` (readable local) |
| `STREAM_NAME` | `billing-events` | Redis Streams key for ingestion events |
| `STREAM_DLQ_PATH` | `logs/dlq.jsonl` | Dead-letter queue file path |
| `STREAM_CONSUMER_GROUP` | `billing-stream-consumers` | Redis Streams consumer group name |
| `STREAM_CONSUMER_NAME` | `<host>-worker` | Redis Streams consumer identity |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | unset | Email channel (skipped when unset) |
| `ALERT_FROM_ADDRESS` / `ALERT_RECIPIENTS` | unset | Email alert addressing |
| `FINGUARD_WEIGHT_THRESHOLD` | `0.50` | Rule weight — threshold_breach |
| `FINGUARD_WEIGHT_SUDDEN_JUMP` | `0.30` | Rule weight — sudden_jump |
| `FINGUARD_WEIGHT_SUSTAINED` | `0.20` | Rule weight — sustained_increase |
| `FINGUARD_THRESHOLD_BUDGET_LIMIT` | `1000.0` | RUL-01 absolute cost ceiling |
| `FINGUARD_THRESHOLD_SUDDEN_JUMP_PCT` | `0.50` | RUL-02 percentage jump threshold |
| `FINGUARD_THRESHOLD_SUSTAINED_WINDOW` | `3` | RUL-03 consecutive-period window |
| `FINGUARD_THRESHOLD_SUSTAINED_GROWTH` | `0.05` | RUL-03 minimum per-period growth |

---

## 15. Cross-reference index

| Code | Task | Section in this document |
| --- | --- | --- |
| ARC-01 | Architecture style selection | § 2 |
| ARC-02 | Component boundaries | § 3 |
| ARC-03 | Communication paths | § 4 |
| ARC-04 | Canonical event schema | § 8 (`billing_events_raw`) |
| ARC-05 | Anomaly output schema | § 8 (`anomalies`) |
| ARC-06 | Storage schema | § 8 |
| ARC-07 | Auth and RBAC | § 10 |
| ARC-08 | Deployment topology | § 11 |
| ENS-01 | Weighted score fusion | § 6 |
| EXP-01..04 | Explanation stack | § 7 |
| FEA-01/04 | Feature pipeline | § 5.2 |
| ING-01/02/03 | Ingestion API | § 3, § 9 |
| MLQ-01..04 | ML quality gates | § 12 |
| OPS-01..04 | Observability | § 13 |
| RUL-01/02/03 | Rule engine | § 6.3 |
| SEC-01 | JWT auth | § 10 |
| SEC-04 | Audit logging | § 8 (`audit_logs`), § 9 |
| TS-03 | Time-series signal | § 6.1 |
| TST-07 | Latency SLA | § 4 |

Related documents:

- [`sprint-1-architecture-baseline.md`](sprint-1-architecture-baseline.md) — Sprint 1 planning baseline
- [`docs/deployment/local-deployment.md`](../deployment/local-deployment.md) — OPS-05
- [`docs/deployment/cloud-deployment.md`](../deployment/cloud-deployment.md) — OPS-06
- [`docs/runbooks/metrics-dashboards.md`](../runbooks/metrics-dashboards.md) — OPS-03
- [`docs/runbooks/retry-and-dlq.md`](../runbooks/retry-and-dlq.md) — OPS-04
- [`docs/api/api-contracts.md`](../api/api-contracts.md) — API-06
- [`ml/reports/MODEL_EVALUATION_REPORT.md`](../../ml/reports/MODEL_EVALUATION_REPORT.md) — MLQ-02
- [`ml/reports/FALSE_POSITIVE_ANALYSIS.md`](../../ml/reports/FALSE_POSITIVE_ANALYSIS.md) — MLQ-03
- [`ml/reports/EXPLAINABILITY_EXAMPLES.md`](../../ml/reports/EXPLAINABILITY_EXAMPLES.md) — MLQ-04
