# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Base HTTP Schema (Adapters Layer)

Purpose:
    Canonical Pydantic base for all adapter-layer HTTP schemas.
    Enforces strict config, deterministic JSON encoding, and OpenAPI hygiene.

Layer: adapters/schemas/http

Notes:
    - Transport-facing only. Application DTOs must not import from this module.
    - Contract Registry envelopes import and subclass this base.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class BaseHTTPSchema(BaseModel):
    """Base class for all HTTP-facing schemas.

    This standardizes Pydantic configuration and serialization rules for
    Stacklion's FastAPI contracts, ensuring deterministic encoding and
    schema compliance across all resources.

    Attributes:
        model_config: Pydantic v2 `ConfigDict` with strict validation and
            canonical JSON encoders for core types.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        json_schema_extra={"example": {"trace_id": "c1e2d3f4-5678-90ab-cdef-1234567890ab"}},
        ser_json_timedelta="iso8601",
        ser_json_inf_nan="null",
        use_enum_values=True,
        arbitrary_types_allowed=True,
        json_encoders={
            UUID: str,
            Decimal: lambda v: format(v, "f"),
            datetime: lambda v: (
                v.astimezone().replace(microsecond=0).isoformat().replace("+00:00", "Z")
                if v.tzinfo
                else v.isoformat()
            ),
            date: lambda v: v.isoformat(),
        },
    )

    def model_dump_http(self, **kwargs: Any) -> dict[str, Any]:
        """Return a JSON-serializable dict suitable for HTTP responses.

        Args:
            **kwargs: Optional Pydantic dump settings (e.g., ``exclude_none=True``).

        Returns:
            dict[str, Any]: Fully JSON-serializable representation.
        """
        return self.model_dump(mode="json", **kwargs)
