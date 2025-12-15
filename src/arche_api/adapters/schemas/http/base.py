# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Base HTTP Schema (Adapters Layer).

Purpose:
    Canonical Pydantic base for all adapter-layer HTTP schemas.
    Enforces strict config, deterministic JSON encoding, and OpenAPI hygiene.

Layer: adapters/schemas/http

Notes:
    - Transport-facing only. Application DTOs must not import from this module.
    - All HTTP envelopes and resource schemas must subclass BaseHTTPSchema.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class BaseHTTPSchema(BaseModel):
    """Base class for all HTTP-facing schemas.

    Provides:
        • Strict `extra='forbid'` validation.
        • Canonical JSON encoding for UUID, Decimal, datetime, date.
        • Deterministic ISO formatting with zeroed microseconds (contract requirement).
        • Consistent `model_dump_http()` for presenters and routers.

    This forms the root surface for all public HTTP shapes.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
        ser_json_timedelta="iso8601",
        ser_json_inf_nan="null",
        use_enum_values=True,
        arbitrary_types_allowed=True,
        json_schema_extra=None,  # Prevents clutter & enforces envelope-level documentation.
        json_encoders={
            UUID: str,
            Decimal: lambda v: format(v, "f"),
            datetime: lambda v: (
                v.astimezone().replace(microsecond=0).isoformat().replace("+00:00", "Z")
                if v.tzinfo
                else v.replace(microsecond=0).isoformat()
            ),
            date: lambda v: v.isoformat(),
        },
    )

    def model_dump_http(self, **kwargs: Any) -> dict[str, Any]:
        """Return a JSON-serializable dict suitable for HTTP responses.

        Presenters must use this instead of raw model_dump() to ensure
        canonical serialization across all HTTP surfaces.
        """
        return self.model_dump(mode="json", **kwargs)
