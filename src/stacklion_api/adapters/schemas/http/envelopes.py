"""
HTTP Envelopes (Adapters Layer)

Purpose:
    Canonical, transport-facing envelopes required by the public contract:
      - SuccessEnvelope[T]
      - PaginatedEnvelope[T]
      - ErrorEnvelope (wrapping ErrorObject)

Authority:
    * API schema shapes, field names, and examples follow API Standards (§2.1, §3, §17).  # noqa: D401
    * Engineering practices (typing, docstrings, Pydantic config) follow the Engineering Guide.

Layer:
    adapters/schemas

Notes:
    - Only presenters construct these envelopes (application/domain never return HTTP envelopes).
    - Field naming is canonical: `page`, `page_size`, `total`, `items`.
    - Models are strict (`extra='forbid'`) and include examples for OpenAPI consumers.
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


class ErrorObject(BaseModel):
    """Structured error object carried inside ErrorEnvelope.

    Per API Standards §2.1, all error responses must include these fields.

    Attributes:
        code: Stable, machine-readable error code (UPPER_SNAKE_CASE).
        http_status: HTTP status intended for the response.
        message: Human-readable, safe description (no secrets/PII).
        details: Optional structured context helpful to the client.
        trace_id: Echo of the request correlation id (X-Request-ID).
    """

    model_config = ConfigDict(
        title="ErrorObject",
        extra="forbid",
        json_schema_extra={
            "description": "Canonical error payload per API Standards §2.1.",
            "examples": [
                {
                    "code": "VALIDATION_ERROR",
                    "http_status": 400,
                    "message": "from must be <= to",
                    "details": {"from": "2025-09-30", "to": "2025-01-01"},
                    "trace_id": "7e8a5d2e-2f8e-4a7a-8d2b-0e1f9e5c1234",
                }
            ],
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
        description="Human-readable, safe description of the error.",
    )
    details: dict[str, Any] | None = Field(  # Use Any to keep Pydantic schema generation happy
        default=None,
        description="Optional structured context; safe to expose to clients.",
    )
    trace_id: str | None = Field(
        default=None,
        description="Request correlation id echoed back to the client.",
    )


class ErrorEnvelope(BaseHTTPSchema):
    """Canonical error envelope.

    Shape:
        { "error": ErrorObject }

    Contracts:
        * Presenters must embed the request's `trace_id` into `error.trace_id`
          and echo `X-Request-ID` in headers (API Standards §2.1, §11).
    """

    model_config = ConfigDict(
        title="ErrorEnvelope",
        extra="forbid",
        json_schema_extra={
            "description": "Canonical error envelope wrapping ErrorObject.",
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
            ],
        },
    )

    error: ErrorObject = Field(..., description="Structured error details.")


class SuccessEnvelope[T](BaseHTTPSchema):
    """Success envelope for non-paginated responses.

    Shape:
        { "data": T }

    Usage:
        * Used for create/get/update/delete responses that return a single resource or value.
        * The `data` field carries an adapter-facing DTO or primitive.

    Examples:
        Basic object payload:
            {
              "data": { "id": "a3d8...", "ticker": "MSFT" }
            }
    """

    model_config = ConfigDict(
        title="SuccessEnvelope",
        extra="forbid",
        json_schema_extra={
            "description": "Canonical success envelope for single-resource responses.",
            "examples": [
                {
                    "data": {
                        "id": "a3d8b3c8-9d9e-4a64-9b38-7e2b8cfd8c34",
                        "ticker": "MSFT",
                    }
                }
            ],
        },
    )

    data: T = Field(
        ...,
        description="Adapter DTO or primitive value returned by the endpoint.",
    )


class PaginatedEnvelope[T](BaseHTTPSchema):
    """Success envelope for paginated list responses.

    Shape:
        {
          "page": <int>,
          "page_size": <int>,
          "total": <int>,
          "items": [ T, ... ]
        }

    Contracts:
        * Pagination fields and bounds follow API Standards §3 (page ≥ 1; page_size 1..200).
        * Deterministic ordering is required at the endpoint level (documented in route docs).

    Examples:
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
              "revenue": "61800000000"
            }
          ]
        }
    """

    model_config = ConfigDict(
        title="PaginatedEnvelope",
        extra="forbid",
        json_schema_extra={
            "description": "Canonical paginated envelope for list responses.",
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
            ],
        },
    )

    page: int = Field(..., ge=1, description="1-indexed page number.")
    page_size: int = Field(..., ge=1, le=200, description="Items per page (bounded by API policy).")
    total: int = Field(
        ..., ge=0, description="Total number of records matching the current filter."
    )
    items: Sequence[T] = Field(..., description="Page contents (adapter DTOs).")
