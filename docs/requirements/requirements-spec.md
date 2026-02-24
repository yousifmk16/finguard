# Requirements Specification (Run 1)

## Functional

- FR-1: Secure login and RBAC (Admin, Analyst).
- FR-2: Stream synthetic billing events.
- FR-3: Detect account-level anomalies in under 60s.
- FR-4: Hybrid scoring (time-series + IF + rules).
- FR-5: Explainability payload for each anomaly.
- FR-6: Dashboard list/filter/details.
- FR-7: In-app and email alerts.

## Non-functional

- NFR-1: p95 latency <= 45s; hard limit < 60s.
- NFR-2: Recall/F1 targets on labeled synthetic data.
- NFR-3: Retry + DLQ for failed processing.
- NFR-4: JWT + RBAC security baseline.
- NFR-5: Local Docker and cloud-ready deployment profile.
