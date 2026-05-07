"""
OPS-02: HTTP middleware for request-scoped tracing.

``RequestIdMiddleware`` assigns every incoming request a stable identifier
that is:

  * pulled from the inbound ``X-Request-ID`` header when present (so the
    caller's correlation ID is preserved through the system), or
  * generated server-side as a 32-char hex UUID when absent.

The id is published to ``app.core.logging_config.request_id_var`` so every
log line emitted *during* the request automatically carries it. The same id
is echoed on the response as ``X-Request-ID`` so clients can quote it in
bug reports and tail it in their own logs.
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.logging_config import request_id_var

_HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Stamp every request with a stable trace ID."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get(_HEADER) or uuid.uuid4().hex
        token = request_id_var.set(rid)
        try:
            response: Response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[_HEADER] = rid
        return response
