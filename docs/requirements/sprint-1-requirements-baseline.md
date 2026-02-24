# Sprint 1 Requirements Baseline (REQ-01 to REQ-10)

## REQ-01 Problem Statement

Cloud billing anomalies (misconfiguration spikes, accidental over-provisioning, unusual workload bursts, or abusive usage) are often detected late. Late detection increases cost impact and weakens budget control. The project solves this by detecting account-level billing anomalies in near real time with explainable alerts.

## REQ-02 Scope Boundaries

### In Scope
- AWS-first canonical billing event pipeline with multi-cloud-ready schema.
- Synthetic data generation with labeled anomaly scenarios.
- Near-real-time anomaly detection and explainable scoring.
- Web dashboard + in-app/email alerts.
- Local Docker runtime and cloud deployment profile documentation.

### Out of Scope
- Direct paid cloud billing API integrations in this phase.
- Automated remediation actions (shutdown/rollback).
- Fine-grained resource-level anomaly detection.

## REQ-03 User Personas and Roles

| Persona | Primary Goal | Required Permissions |
|---|---|---|
| Admin | configure thresholds, policies, users | full admin + analyst actions |
| Analyst | monitor anomalies and triage alerts | view, filter, acknowledge, classify |
| Project Owner (read-only future role) | monitor risk and trends | read-only dashboards/reports |

## REQ-04 Functional Requirements

- FR-01: secure login and role-based access.
- FR-02: ingest synthetic billing events continuously.
- FR-03: normalize events to canonical schema.
- FR-04: compute account-level anomaly scores in near real time.
- FR-05: combine time-series, unsupervised, and rules-based scores.
- FR-06: store anomaly decision with score breakdown.
- FR-07: provide anomaly list/detail/filter APIs.
- FR-08: provide anomaly lifecycle actions (acknowledge/dismiss/classify).
- FR-09: trigger in-app and email alerts with dedup/cooldown.
- FR-10: expose health/metrics for operations.

## REQ-05 Non-Functional Requirements

- NFR-01 Latency: decision under 60 seconds.
- NFR-02 Accuracy: prioritize recall/F1 on labeled synthetic data.
- NFR-03 Reliability: retries and dead-letter path for failures.
- NFR-04 Security: JWT auth + RBAC + audit trail for privileged actions.
- NFR-05 Maintainability: linted, tested, documented services.
- NFR-06 Portability: local Docker + cloud-ready topology.

## REQ-06 Measurable Acceptance Criteria

| Requirement | Acceptance Criteria |
|---|---|
| FR-04/NFR-01 | p95 detection latency <= 45s, hard cap < 60s |
| FR-05/NFR-02 | documented hybrid score formula + evaluation report generated |
| FR-07 | anomaly list/detail APIs return valid schema with pagination/filter |
| FR-08 | lifecycle status updates persisted and queryable |
| FR-09 | medium/high anomalies create in-app alert and email attempt |
| NFR-03 | failed processing paths log and route to DLQ |

## REQ-07 Success Metrics

- Detection latency p95 <= 45s and max < 60s.
- Recall >= 0.90 on synthetic validation sets.
- F1 >= 0.85 on synthetic validation sets.
- 100% anomaly records include explanation payload.
- CI checks pass for required lint and test jobs.

## REQ-08 Alert Severity Policy

| Final Score Range | Severity | Notification Policy |
|---|---|---|
| 0.50 - 0.69 | low | in-app only |
| 0.70 - 0.84 | medium | in-app + email |
| >= 0.85 | high | in-app + email + highlighted priority |

Policy notes:
- deduplicate by `(account_id, anomaly_type, time_bucket)`.
- apply cooldown to avoid alert floods.

## REQ-09 Anomaly Lifecycle States

States:
- `new` -> `notified` -> (`acknowledged` | `dismissed`) -> `resolved` -> `closed`

Rules:
- only analyst/admin can acknowledge or dismiss.
- only admin can force-close unresolved anomalies.

## REQ-10 Threat and Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| false positives | alert fatigue | threshold tuning + cooldown + rule calibration |
| false negatives | missed overspend | hybrid scoring + recall-focused tuning |
| latency breaches | delayed response | async pipeline + perf tests + caching |
| secret leakage | security incident | `.env` policy + no secrets in git + review checks |
| integration drift | unstable releases | CI checks + contract docs + sprint reviews |
