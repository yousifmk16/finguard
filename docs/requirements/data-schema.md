# Data Schema (v1)

## Canonical Billing Event (v1)

```json
{
  "event_id": "uuid",
  "timestamp": "2026-01-01T00:00:00Z",
  "provider": "gcp",
  "account_id": "string",
  "service": "Compute Engine",
  "region": "us-central1",
  "cost_amount": 12.34,
  "usage_amount": 10.0,
  "usage_unit": "Hrs",
  "tags": {
    "env": "prod"
  },
  "source_type": "synthetic"
}
```

## Anomaly Record (v1)

```json
{
  "anomaly_id": "uuid",
  "account_id": "string",
  "timestamp": "2026-01-01T00:01:00Z",
  "final_score": 0.82,
  "severity": "high",
  "score_breakdown": {
    "ts": 0.9,
    "if": 0.7,
    "rule": 0.8
  },
  "explanation": "cost exceeded expected baseline",
  "status": "new"
}
```

## Notes

- Canonical schema is provider-agnostic with GCP-priority example values.
- This file is the source reference for ARC-04 and ARC-05.
