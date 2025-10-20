"""
Base HTTP Schema (Adapters Layer)

Purpose:
    Defines the canonical Pydantic base class for all adapter-layer HTTP schemas.
    Provides unified configuration, JSON encoding behavior, validation, and
    OpenAPI hygiene per Stacklion Engineering Guide and API Standards.

Layer: adapters/schemas

Notes:
    - This is the foundation for all HTTP-facing models (requests, responses,
      and envelopes).
    - Enforces ConfigDict(extra="forbid"), ensuring strict schema parity with
      OpenAPI.
    - Inherits default encoders for UUID, Decimal, datetime, and date types.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class BaseHTTPSchema(BaseModel):
    """Canonical base class for all HTTP-facing schemas in the adapters layer.

    This class standardizes Pydantic configuration and serialization rules for
    Stacklion's FastAPI contracts, ensuring deterministic encoding and schema
    compliance across all resources.

    Attributes:
        model_config: Pydantic v2 ConfigDict enforcing strict field validation
            and canonical JSON encoding.
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
            datetime: lambda v: v.isoformat() + "Z" if v.tzinfo else v.isoformat(),
            date: lambda v: v.isoformat(),
        },
    )

    def model_dump_http(self, **kwargs: Any) -> dict[str, Any]:
        """Return a JSON-serializable dict suitable for HTTP responses.

        Args:
            **kwargs: Optional Pydantic dump settings (e.g., exclude_none).

        Returns:
            A fully JSON-serializable dictionary representation.
        """
        return self.model_dump(mode="json", **kwargs)
