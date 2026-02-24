# API Contracts (Run 1 Placeholder)

## Endpoints

- `GET /api/v1/anomalies`
- `GET /api/v1/anomalies/{id}`
- `PATCH /api/v1/anomalies/{id}/status`
- `GET /api/v1/alerts`
- `GET /api/v1/kpis`

## Anomaly Response (draft)

```json
{
  "anomaly_id": "uuid",
  "account_id": "string",
  "timestamp": "2026-01-01T00:00:00Z",
  "final_score": 0.82,
  "severity": "high",
  "score_breakdown": {
    "ts": 0.9,
    "if": 0.7,
    "rule": 0.8
  },
  "explanation": "Cost exceeded expected baseline with rule trigger"
}
```
