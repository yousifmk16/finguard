from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return a flat list of field/message pairs instead of FastAPI's default nested format."""
    errors = []
    for error in exc.errors():
        loc = error.get("loc", ())
        # Drop the leading "body" segment; join the rest into a dotted field path.
        field_parts = [str(p) for p in loc if p != "body"]
        errors.append(
            {
                "field": ".".join(field_parts) if field_parts else "request",
                "message": error.get("msg", "invalid value"),
            }
        )
    return JSONResponse(status_code=422, content={"errors": errors})
