"""
OPS-03: In-process HTTP request metrics for the dashboards endpoint.

A small thread-safe registry that the metrics middleware writes to and
the ``/metrics`` Prometheus exposition endpoint reads from.  Mirrors the
shape of ``services.detection.metrics`` so both registries can be
serialised by the same Prometheus formatter.

Two metric families are tracked:

  http_requests_total{method,path,status}
        Counter — total HTTP requests handled, broken down by route.

  http_request_duration_seconds_sum{method,path}
  http_request_duration_seconds_count{method,path}
        Counter pair — total observed latency and total observation count
        per route.  Their ratio yields average latency; pairing them on the
        same labels lets Prometheus compute ``rate(...sum) / rate(...count)``
        for time-windowed averages on the dashboard.

We deliberately do not implement histogram buckets — that would require
either a heavier dependency (``prometheus_client``) or bucket-config
plumbing that this codebase does not currently need.  Average latency is
sufficient for the OPS-03 dashboards; switching to histograms is a drop-in
later if percentile graphs become required.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Dict, Tuple

# (method, path, status) tuple keys for counters; (method, path) for latency.
_RequestKey = Tuple[str, str, str]
_LatencyKey = Tuple[str, str]


class HttpMetrics:
    """Thread-safe in-process HTTP request metrics."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._requests_total: Dict[_RequestKey, int] = defaultdict(int)
        self._duration_sum: Dict[_LatencyKey, float] = defaultdict(float)
        self._duration_count: Dict[_LatencyKey, int] = defaultdict(int)

    def record(
        self,
        method: str,
        path: str,
        status: int,
        duration_seconds: float,
    ) -> None:
        """Record one completed request."""
        rkey: _RequestKey = (method, path, str(status))
        lkey: _LatencyKey = (method, path)
        with self._lock:
            self._requests_total[rkey] += 1
            self._duration_sum[lkey] += duration_seconds
            self._duration_count[lkey] += 1

    def reset(self) -> None:
        """Clear all counters (intended for tests)."""
        with self._lock:
            self._requests_total.clear()
            self._duration_sum.clear()
            self._duration_count.clear()

    def snapshot(self) -> Dict[str, Dict[Tuple[str, ...], float]]:
        """Return a deep-copied snapshot of all counters.

        Shape::
            {
              "requests_total":   {(method, path, status): count, ...},
              "duration_sum":     {(method, path): seconds, ...},
              "duration_count":   {(method, path): observations, ...},
            }
        """
        with self._lock:
            return {
                "requests_total": dict(self._requests_total),
                "duration_sum": dict(self._duration_sum),
                "duration_count": dict(self._duration_count),
            }


# Module-level singleton shared between the middleware and the endpoint.
http_metrics: HttpMetrics = HttpMetrics()
