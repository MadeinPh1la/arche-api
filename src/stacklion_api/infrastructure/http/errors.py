# stacklion_api/infrastructure/http/errors.py
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.responses import Response  # <-- add this


def _trace_id(request: Request) -> str | None:
    return getattr(getattr(request, "state", None), "trace_id", None)


def error_envelope(
    *,
    code: str,
    http_status: int,
    message: str,
    details: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:  # <-- add return type
    err: dict[str, Any] = {
        "code": code,
        "http_status": http_status,
        "message": message,
    }
    if details is not None:
        err["details"] = details
    if trace_id is not None:
        err["trace_id"] = trace_id
    return {"error": err}


async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> Response:  # <-- add
    payload = error_envelope(
        code="VALIDATION_ERROR",
        http_status=422,
        message="Request validation failed",
        details={"errors": exc.errors()},
        trace_id=_trace_id(request),
    )
    return JSONResponse(status_code=422, content=payload)


async def handle_http_exception(request: Request, exc: HTTPException) -> Response:  # <-- add
    payload = error_envelope(
        code="HTTP_ERROR",
        http_status=exc.status_code,
        message=exc.detail if isinstance(exc.detail, str) else "HTTP error",
        details=None if isinstance(exc.detail, str) else {"detail": exc.detail},
        trace_id=_trace_id(request),
    )
    return JSONResponse(status_code=exc.status_code, content=payload)


async def handle_unhandled_exception(request: Request, exc: Exception) -> Response:  # <-- add
    payload = error_envelope(
        code="INTERNAL_ERROR",
        http_status=500,
        message="Internal server error",
        details=None,
        trace_id=_trace_id(request),
    )
    return JSONResponse(status_code=500, content=payload)
