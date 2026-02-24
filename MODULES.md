# MODULES

## Proposed Modules (Exact Structure)

- `gcp-adapter` (priority) + `aws-adapter` + `azure-adapter`
- `synthetic-data-generator`
- `ingestion-api`
- `stream-consumer-normalizer`
- `feature-engineering-pipeline`
- `timeseries-anomaly-model`
- `isolation-forest-anomaly-model`
- `rule-engine`
- `hybrid-score-fusion`
- `explainability-engine`
- `anomaly-store-service`
- `alert-orchestrator` (in-app + email, dedup/cooldown)
- `auth-rbac-service`
- `backend-query-api` (anomalies, alerts, KPIs, status)
- `web-dashboard`
- `observability-reliability` (metrics, logs, retries, DLQ)
- `ci-cd-quality-gates`
- `deployment-profiles` (local docker + cloud profile)

## Detailed Module Explanations

| Module | Purpose | Main Inputs | Main Outputs |
|---|---|---|---|
| `gcp-adapter` | GCP-priority provider adapter that converts billing exports/events to canonical schema. | GCP billing records, usage metadata | Canonical billing events |
| `aws-adapter` | AWS adapter for future extension using the same canonical contract. | AWS billing records | Canonical billing events |
| `azure-adapter` | Azure adapter for future extension using the same canonical contract. | Azure billing records | Canonical billing events |
| `synthetic-data-generator` | Produces realistic synthetic spend streams and injected anomaly scenarios for training/testing. | Config (seasonality, trend, anomalies) | Labeled synthetic events |
| `ingestion-api` | Entry point that validates incoming events and publishes accepted events to stream transport. | Canonical/raw events | Validated events to broker, ingestion logs |
| `stream-consumer-normalizer` | Consumes broker messages, normalizes/cleans fields, and enforces schema consistency. | Broker events | Normalized canonical events |
| `feature-engineering-pipeline` | Builds rolling time-window features used by models and rules. | Normalized events/history | Feature vectors per account/time window |
| `timeseries-anomaly-model` | Forecast-based detector that scores deviation from expected spend. | Historical spend windows | Time-series anomaly score |
| `isolation-forest-anomaly-model` | Unsupervised detector for unusual multivariate behavior. | Feature vectors | IF anomaly score |
| `rule-engine` | Deterministic checks for policy and threshold violations. | Features + thresholds/policies | Rule score + rule hits |
| `hybrid-score-fusion` | Combines model/rule scores into a final risk score and severity. | TS score, IF score, rule score | Final score + severity |
| `explainability-engine` | Generates analyst-friendly reasons for each anomaly decision. | Score breakdown, context, rule hits | Explanation payload |
| `anomaly-store-service` | Persists anomalies, scores, explanations, and lifecycle state transitions. | Final anomaly records | Queryable anomaly history |
| `alert-orchestrator` | Sends alerts via in-app/email and applies dedup/cooldown/retry behavior. | New anomaly events + policies | Alert records + notifications |
| `auth-rbac-service` | Handles identity and permission enforcement (Admin/Analyst). | Login credentials, access tokens | JWT tokens, role checks |
| `backend-query-api` | Unified API for anomalies, alerts, KPIs, and lifecycle actions. | Dashboard/API client requests | JSON responses for UI and operations |
| `web-dashboard` | User interface for monitoring, filtering, triage, and status updates. | API responses, auth token | Visual analytics, user actions |
| `observability-reliability` | Cross-cutting telemetry and resilience controls (metrics, logs, retries, DLQ). | Service logs/events | Dashboards, alerts, recovery signals |
| `ci-cd-quality-gates` | Automates lint/tests/checks to protect branch quality before merge/deploy. | PRs/commits | Pass/fail quality checks |
| `deployment-profiles` | Defines reproducible local and cloud deployment configurations. | Infra definitions, env vars | Runnable local stack + cloud profile |

## Cross-Module Flow (High-Level)

1. Adapters/generator produce canonical events.
2. Ingestion validates and publishes events.
3. Consumer normalizes and forwards to feature pipeline.
4. Detection modules compute scores and fuse results.
5. Explainability and persistence capture final anomaly records.
6. Alert orchestrator notifies users.
7. API and dashboard expose monitoring and triage workflows.

## Owner Per Module + Sprint Mapping

| Module | Owner | Sprint Mapping |
|---|---|---|
| `gcp-adapter` | M3 | Sprint 2 (v1), Sprint 4 (hardening) |
| `aws-adapter` | M3 | Sprint 4 (v1), Sprint 5 (optional extension) |
| `azure-adapter` | M3 | Sprint 5 (optional extension) |
| `synthetic-data-generator` | M3 | Sprint 2 |
| `ingestion-api` | M1 | Sprint 2 |
| `stream-consumer-normalizer` | M3 | Sprint 2 |
| `feature-engineering-pipeline` | M2 | Sprint 3 |
| `timeseries-anomaly-model` | M2 | Sprint 3 |
| `isolation-forest-anomaly-model` | M2 | Sprint 3 |
| `rule-engine` | M2 | Sprint 3 |
| `hybrid-score-fusion` | M2 | Sprint 3 |
| `explainability-engine` | M2 | Sprint 3-4 |
| `anomaly-store-service` | M1 | Sprint 3-4 |
| `alert-orchestrator` | M1 | Sprint 4 |
| `auth-rbac-service` | M1 | Sprint 4 |
| `backend-query-api` | M1 | Sprint 4 |
| `web-dashboard` | M4 | Sprint 2 (shell), Sprint 4 (full) |
| `observability-reliability` | M5 | Sprint 4-5 |
| `ci-cd-quality-gates` | M5 | Sprint 0-1 (baseline), Sprint 5 (final gates) |
| `deployment-profiles` | M5 | Sprint 1 (local baseline), Sprint 5 (cloud profile) |

## Owner Legend

- `M1`: Project Manager + Development Engineer
- `M2`: System Architect + ML Lead
- `M3`: Requirement Analyst + Data-Streaming Lead
- `M4`: System Designer + Frontend Lead
- `M5`: Test Engineer + DevOps-QA Lead
