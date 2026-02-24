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
