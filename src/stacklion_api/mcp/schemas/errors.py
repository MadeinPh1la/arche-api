# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""MCP Error Schemas.

Purpose:
- Define MCP-facing error types decoupled from HTTP but informed by the
  canonical Stacklion ErrorEnvelope.

Layer: adapters/mcp

Notes:
- HTTP error information is exposed only as metadata; MCP clients never
  have to speak HTTP directly.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MCPError(BaseModel):
    """Standard MCP error shape for Stacklion MCP methods."""

    model_config = ConfigDict(
        extra="forbid",
        title="MCPError",
    )

    type: str = Field(
        ...,
        description=(
            "Stable error type (e.g. VALIDATION_ERROR, RATE_LIMITED, "
            "PROVIDER_QUOTA_EXCEEDED, INTERNAL_ERROR)."
        ),
    )
    message: str = Field(..., description="Human-readable error message.")
    retryable: bool = Field(
        ...,
        description="Whether clients should treat this error as retryable.",
    )
    http_status: int | None = Field(
        default=None,
        description="HTTP status returned by the underlying Stacklion API, if any.",
    )
    http_code: str | None = Field(
        default=None,
        description="Underlying Stacklion error.code value, if present.",
    )
    trace_id: str | None = Field(
        default=None,
        description="Underlying Stacklion trace identifier (X-Request-ID).",
    )
    retry_after_s: float | None = Field(
        default=None,
        description="Recommended delay in seconds before retrying (from Retry-After header).",
    )
