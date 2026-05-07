"""
OPS-03: Prometheus exposition endpoint.

GET /metrics
    Returns the FinGuard service metrics in Prometheus 0.0.4 text exposition
    format.  Scraped by Prometheus / Grafana Agent / Datadog OpenMetrics
    integrations.  Excluded from auth and from the OpenAPI schema by design
    — Prometheus scrapers do not authenticate and do not consume OpenAPI.

The endpoint reuses the in-process registries:

  * ``services.detection.metrics.detection_metrics`` — pipeline counters
    (filled in by the detection service after each batch).
  * ``app.core.http_metrics.http_metrics`` — request counters and latency
    accumulators (filled in by ``MetricsMiddleware``).

Content-Type
------------
``text/plain; version=0.0.4; charset=utf-8`` — required by Prometheus.
A wrong content type causes the scraper to silently drop the payload.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.core.http_metrics import http_metrics
from app.core.prometheus_text import render
from services.detection.metrics import detection_metrics

router = APIRouter(tags=["metrics"])

_PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@router.get(
    "/metrics",
    summary="Prometheus metrics exposition",
    response_class=PlainTextResponse,
    include_in_schema=False,  # Prometheus scrapers do not consume OpenAPI.
)
def metrics() -> PlainTextResponse:
    body = render(detection_metrics, http_metrics)
    return PlainTextResponse(content=body, media_type=_PROMETHEUS_CONTENT_TYPE)
