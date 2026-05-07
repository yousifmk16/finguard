"""
OPS-03: HTTP metrics middleware.

Records method, *route template* (not raw URL), status, and duration into
``app.core.http_metrics.http_metrics``.  We use the matched route template
(e.g. ``/api/v1/anomalies/{anomaly_id}``) instead of the raw path so that
each path parameter does not explode into its own time-series — a common
cardinality footgun on Prometheus dashboards.

The ``/metrics`` endpoint itself is excluded from the registry.  Including
it would create self-referencing noise: every Prometheus scrape would bump
its own counter, swamping the actual application traffic.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from app.core.http_metrics import http_metrics

# Endpoints we exclude from the registry to prevent self-referencing noise.
_EXCLUDED_PATHS = {"/metrics"}


def _route_template(request: Request) -> str:
    """Return the matched route template for a request.

    Falls back to the raw URL path when no route is matched (e.g. 404).
    Routes that match a wildcard are reported as ``/<unmatched>`` so high-
    cardinality 404 attacks cannot blow up the registry.
    """
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path  # template form, e.g. "/api/v1/anomalies/{anomaly_id}"
    return "/<unmatched>"


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record ``http_requests_total`` and ``http_request_duration_seconds`` per request."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            # Record a 500 for unhandled exceptions so dashboards reflect them,
            # then re-raise so FastAPI's error handlers run normally.
            duration = time.perf_counter() - start
            path = _route_template(request)
            if path not in _EXCLUDED_PATHS:
                http_metrics.record(request.method, path, 500, duration)
            raise

        duration = time.perf_counter() - start
        path = _route_template(request)
        if path not in _EXCLUDED_PATHS:
            http_metrics.record(request.method, path, status, duration)
        return response
