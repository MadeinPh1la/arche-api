"""
HTTP Envelopes (Adapters Layer)

Purpose:
    Canonical, transport-facing envelopes required by the public contract:
      - SuccessEnvelope[T]
      - PaginatedEnvelope[T]
      - ErrorEnvelope

Authority:
    • API_STANDARDS.md §§2–3.
    • Engineering Guide typing + Pydantic v2 rules.
    • Deterministic HTTP contract enforced via OpenAPI snapshot tests.

Layer:
    adapters/schemas/http

Notes:
    - Only presenters construct envelopes.
    - Application/domain layers must NEVER import from this module.
    - Field naming is canonical: page, page_size, total, items.
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
    """Structured error object carried inside ErrorEnvelope."""

    model_config = ConfigDict(
        title="ErrorObject",
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "code": "VALIDATION_ERROR",
                    "http_status": 400,
                    "message": "from must be <= to",
                    "details": {"from": "2025-09-30", "to": "2025-01-01"},
                    "trace_id": "7e8a5d2e-2f8e-4a7a-8d2b-0e1f9e5c1234",
                }
            ]
        },
    )

    code: str = Field(
        ...,
        description="Stable machine-readable error code (UPPER_SNAKE_CASE).",
    )
    http_status: int = Field(
        ...,
        description="HTTP status code associated with this error.",
    )
    message: str = Field(
        ...,
        description="Human-readable, safe error description.",
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Optional structured details safe to expose to clients.",
    )
    trace_id: str | None = Field(
        default=None,
        description="Request correlation id echoed back to the client.",
    )


# ---------------------------------------------------------------------------
# Error Envelope
# ---------------------------------------------------------------------------


class ErrorEnvelope(BaseHTTPSchema):
    """Canonical error envelope: `{\"error\": ErrorObject}`."""

    model_config = ConfigDict(
        title="ErrorEnvelope",
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "http_status": 400,
                        "message": "price must be >= 0",
                        "details": {"field": "price", "min_value": 0},
                        "trace_id": "c5a6a0c4-0c8d-4f0f-b6e6-8f1f0c2b7e7a",
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
    """Success envelope for non-paginated responses.

    Shape:
        {"data": T}
    """

    model_config = ConfigDict(
        title="SuccessEnvelope",
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "data": {
                        "id": "a3d8b3c8-9d9e-4a64-9b38-7e2b8cfd8c34",
                        "ticker": "MSFT",
                    }
                }
            ]
        },
    )

    data: T = Field(
        ...,
        description="Single resource or primitive returned by the endpoint.",
    )


# ---------------------------------------------------------------------------
# Paginated Envelope
# ---------------------------------------------------------------------------


class PaginatedEnvelope[T](BaseHTTPSchema):
    """Paginated success envelope.

    Shape:
        {
          "page": int,
          "page_size": int,
          "total": int,
          "items": [T, ...]
        }
    """

    model_config = ConfigDict(
        title="PaginatedEnvelope",
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "page": 1,
                    "page_size": 50,
                    "total": 1234,
                    "items": [
                        {
                            "company_id": "a3d8b3c8-9d9e-4a64-9b38-7e2b8cfd8c34",
                            "ticker": "MSFT",
                            "statement_date": "2024-12-31",
                            "currency": "USD",
                            "revenue": "61800000000",
                        }
                    ],
                }
            ]
        },
    )

    page: int = Field(..., ge=1, description="1-indexed page number.")
    page_size: int = Field(..., ge=1, le=200, description="Items per page (bounded by API policy).")
    total: int = Field(..., ge=0, description="Total number of matching records.")
    items: Sequence[T] = Field(..., description="Page contents.")
