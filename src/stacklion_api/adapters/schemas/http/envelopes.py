# src/stacklion_api/adapters/schemas/http/envelopes.py
# Copyright ...
"""HTTP Envelopes (Adapters Layer).

Purpose:
    Canonical transport-facing HTTP envelopes:
      - ErrorEnvelope
      - SuccessEnvelope[T]
      - PaginatedEnvelope[T]

Extended:
    ErrorObject now explicitly documents idempotency error codes:
        - IDEMPOTENCY_KEY_CONFLICT
        - IDEMPOTENCY_KEY_IN_PROGRESS
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from stacklion_api.adapters.schemas.http.base import BaseHTTPSchema

__all__ = [
    "ErrorObject",
    "ErrorEnvelope",
    "SuccessEnvelope",
    "PaginatedEnvelope",
]


# ---------------------------------------------------------------------------
# Error Object
# ---------------------------------------------------------------------------


class ErrorObject(BaseModel):
    """Structured error object inside ErrorEnvelope.

    Error codes follow API Standards:
        - UPPER_SNAKE_CASE
        - Stable across releases
        - Client-visible and testable

    Idempotency-specific codes included:
        - IDEMPOTENCY_KEY_CONFLICT: Key reused with different payload.
        - IDEMPOTENCY_KEY_IN_PROGRESS: Another request with same key is in-flight.
    """

    model_config = ConfigDict(
        title="ErrorObject",
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "code": "IDEMPOTENCY_KEY_CONFLICT",
                    "http_status": 409,
                    "message": "Idempotency-Key reused with a different request payload.",
                    "details": {},
                    "trace_id": "req-123",
                }
            ]
        },
    )

    code: str = Field(
        ...,
        description=(
            "Stable machine-readable error code.\n"
            "\n"
            "**Idempotency codes:**\n"
            "- `IDEMPOTENCY_KEY_CONFLICT`: Key reused with different request payload.\n"
            "- `IDEMPOTENCY_KEY_IN_PROGRESS`: Another request with same key is in progress.\n"
            "\n"
            "Other subsystems define additional codes (e.g. MARKET_DATA_*, VALIDATION_ERROR)."
        ),
    )
    http_status: int = Field(..., description="Associated HTTP status.")
    message: str = Field(..., description="Human-readable error description.")
    details: dict[str, Any] | None = Field(
        default=None,
        description="Optional structured details safe for clients.",
    )
    trace_id: str | None = Field(
        default=None,
        description="Request correlation identifier.",
    )


# ---------------------------------------------------------------------------
# Error Envelope
# ---------------------------------------------------------------------------


class ErrorEnvelope(BaseHTTPSchema):
    r"""Canonical error envelope: {"error": ErrorObject}."""

    model_config = ConfigDict(
        title="ErrorEnvelope",
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "error": {
                        "code": "IDEMPOTENCY_KEY_IN_PROGRESS",
                        "http_status": 409,
                        "message": (
                            "Another request with the same Idempotency-Key is in progress."
                        ),
                        "details": {},
                        "trace_id": "req-456",
                    }
                }
            ]
        },
    )

    error: ErrorObject = Field(..., description="Structured error details.")


# ---------------------------------------------------------------------------
# Success Envelope
# ---------------------------------------------------------------------------


class SuccessEnvelope[T](BaseHTTPSchema):
    r"""Success envelope for non-paginated responses: {"data": T}."""

    model_config = ConfigDict(
        title="SuccessEnvelope",
        extra="forbid",
    )

    data: T = Field(..., description="Returned resource or value.")


# ---------------------------------------------------------------------------
# Paginated Envelope
# ---------------------------------------------------------------------------


class PaginatedEnvelope[T](BaseHTTPSchema):
    """Paginated success envelope."""

    model_config = ConfigDict(
        title="PaginatedEnvelope",
        extra="forbid",
    )

    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=200)
    total: int = Field(..., ge=0)
    items: Sequence[T] = Field(...)
