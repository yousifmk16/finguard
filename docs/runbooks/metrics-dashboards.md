# OPS-03 — Metrics dashboards

This runbook documents the metrics surface and the Grafana dashboard
shipped with FinGuard.

## Endpoints

| Path | Format | Use |
| --- | --- | --- |
| `GET /metrics` | Prometheus text exposition (v0.0.4) | Scrape target for Prometheus / Grafana Agent / Datadog OpenMetrics. |
| `GET /api/v1/detection/metrics` | JSON snapshot | Read by ops staff and the existing detection health endpoint. |
| `GET /api/v1/detection/health` | JSON | Per-component status (DB, scorer, emitter). |
| `GET /health` | JSON | Aggregate service health for load balancers (OPS-01). |

`/metrics` is unauthenticated by design — Prometheus scrapers do not authenticate
by default. Restrict it at the network layer (e.g. only the metrics namespace
in your cluster can reach the pod).

## Metric families

### Detection pipeline (counters)

| Metric | Source |
| --- | --- |
| `finguard_batches_processed_total` | scoring batches completed |
| `finguard_rows_scored_total` | rows passed through the scorer |
| `finguard_anomalies_detected_total` | rows where `is_anomaly == 1` |
| `finguard_anomalies_persisted_total` | rows successfully written to DB |
| `finguard_events_emitted_total` | events published to the stream |
| `finguard_errors_scoring_total` | exceptions in the OnlineScorer |
| `finguard_errors_persist_total` | exceptions in the AnomalyRepository |
| `finguard_errors_emit_total` | exceptions in the AnomalyEventEmitter |

### Detection pipeline (gauges)

| Metric | Meaning |
| --- | --- |
| `finguard_last_batch_rows` | row count of the most recent batch |
| `finguard_last_batch_anomalies` | anomaly count of the most recent batch |

### HTTP layer (counters, recorded by the middleware)

| Metric | Labels |
| --- | --- |
| `finguard_http_requests_total` | `method`, `path`, `status` |
| `finguard_http_request_duration_seconds_sum` | `method`, `path` |
| `finguard_http_request_duration_seconds_count` | `method`, `path` |

`path` is the matched **route template** (e.g. `/api/v1/anomalies/{anomaly_id}`),
not the raw URL — this prevents path-parameter cardinality from blowing up
the time-series database.

Average request latency for a route window is

```promql
rate(finguard_http_request_duration_seconds_sum[5m])
/
rate(finguard_http_request_duration_seconds_count[5m])
```

## Wiring up Prometheus

Add a scrape job pointing at the FinGuard backend:

```yaml
scrape_configs:
  - job_name: finguard
    metrics_path: /metrics
    scrape_interval: 15s
    static_configs:
      - targets: ["finguard-backend:8000"]
```

## Importing the Grafana dashboard

The dashboard JSON lives at `infra/dashboards/finguard.json`.

1. Grafana → Dashboards → New → Import.
2. Upload `finguard.json` or paste its contents.
3. Pick the Prometheus datasource that scrapes `/metrics`.

The dashboard includes:

- Top-line stat panels (batches, anomalies, errors).
- Pipeline rate panels (rows/sec, anomalies/sec).
- Pipeline error rates split by component.
- HTTP request rate by route.
- HTTP average latency by route.
- HTTP 5xx error rate.
- Last-batch row & anomaly counts.

## Verifying locally

```bash
curl -s http://localhost:8000/metrics | head -40
```

You should see the `# HELP` / `# TYPE` blocks followed by metric lines. If
`finguard_http_requests_total` is empty the middleware has not yet observed
a request — hit any endpoint (e.g. `GET /health`) and re-scrape.
