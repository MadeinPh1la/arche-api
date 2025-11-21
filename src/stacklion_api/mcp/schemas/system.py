# src/stacklion_api/mcp/schemas/system.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""MCP Schemas: System Health & Metadata.

Purpose:
- Define MCP models for `system.health` and `system.metadata`.

Layer: adapters/mcp
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SystemHealthResult(BaseModel):
    """Result payload for `system.health`."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(
        ...,
        description="Overall MCP view of Stacklion health (ok, degraded, down).",
    )
    request_id: str | None = Field(
        default=None,
        description="Underlying Stacklion X-Request-ID, if a health check call was made.",
    )
    source_status: int = Field(
        ...,
        description="HTTP status returned by the underlying /healthz endpoint.",
    )


class SystemMetadataResult(BaseModel):
    """Static metadata and usage limits for MCP clients."""

    model_config = ConfigDict(extra="forbid")

    mcp_version: str = Field(..., description="Stacklion MCP service version.")
    api_version: str = Field(..., description="Underlying Stacklion HTTP API major version.")
    quotes_contract_version: str = Field(
        ...,
        description="Contract version for quotes endpoints bound to this MCP version.",
    )
    supported_intervals: list[str] = Field(
        ...,
        description="Supported bar intervals for historical quotes (e.g., 1d, 1m).",
    )
    max_page_size: int = Field(
        ...,
        description="Recommended maximum page size for MCP clients.",
    )
    max_range_days: int = Field(
        ...,
        description="Recommended maximum date range in days per MCP call.",
    )
    max_tickers_per_request: int = Field(
        ...,
        description="Maximum tickers per MCP request (mirrors stacklion HTTP rules).",
    )
