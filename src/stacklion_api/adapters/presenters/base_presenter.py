# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Presenter utilities and canonical envelope helpers.

Purpose:
    Thin, framework-aware helpers used by adapter layers (routers/controllers)
    to consistently shape HTTP responses and headers.

Responsibilities:
    * Build SuccessEnvelope, PaginatedEnvelope, and ErrorEnvelope instances.
    * Compute strong, quoted ETags from canonical JSON material.
    * Apply standard headers such as X-Request-ID and optional Cache-Control.

Layer:
    adapters/presenters
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import Response

from stacklion_api.adapters.schemas.http.envelopes import (
    ErrorEnvelope,
    ErrorObject,
    PaginatedEnvelope,
    SuccessEnvelope,
)
from stacklion_api.infrastructure.logging.logger import get_json_logger

_LOGGER = get_json_logger(__name__)


def _json_default(value: Any) -> str:
    """Serialize non-JSON-native types deterministically for hashing.

    This MUST stay in sync with BaseHTTPSchema's JSON encoders so that ETags
    are stable for semantically equivalent payloads across the codebase.
    """
    if isinstance(value, datetime):
        # Preserve full timestamp including microseconds and timezone.
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        # Canonicalize numeric representation:
        #   * Strip insignificant trailing zeros.
        #   * Avoid scientific notation.
        #   * Collapse -0 and 0 to "0".
        v = value.normalize()
        if v == 0:
            return "0"
        if v == v.to_integral():
            return format(v.to_integral(), "f")
        s = format(v, "f")
        return s.rstrip("0").rstrip(".")
    raise TypeError(f"unsupported type for JSON hashing: {type(value)!r}")


def _compute_quoted_etag(payload: Mapping[str, Any]) -> str:
    """Return a quoted strong ETag (SHA-256 of canonical JSON for ``payload``)."""
    material = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    digest = hashlib.sha256(material).hexdigest()
    return f'"{digest}"'


@dataclass(slots=True)
class PresentResult[T]:
    """Presentation result envelope.

    Attributes:
        body: A Pydantic envelope instance, or ``None`` for e.g. 304.
        headers: Extra HTTP headers to apply.
        status_code: Optional HTTP status override.
    """

    body: T | None
    headers: Mapping[str, str]
    status_code: int | None = None


class BasePresenter[T]:
    """Base presenter for HTTP response shaping in adapter layers.

    Provides helpers to assemble standard envelopes and headers, leaving all
    business decisions to the use-case/application layer.
    """

    # ------------------------- Success / Error ------------------------- #

    def present_success(
        self,
        *,
        data: Any,
        trace_id: str | None = None,
    ) -> PresentResult[SuccessEnvelope[Any]]:
        """Build a SuccessEnvelope and attach headers.

        Behavior:
            * Always echoes ``X-Request-ID`` when provided.
            * Computes and sets a **quoted** strong ``ETag`` from the envelope body.
        """
        body = SuccessEnvelope[Any](data=data)
        payload = body.model_dump(mode="python")

        headers: dict[str, str] = {}
        if trace_id:
            headers["X-Request-ID"] = trace_id
        headers["ETag"] = _compute_quoted_etag(payload)
        return PresentResult(body=body, headers=headers)

    def present_error(
        self,
        *,
        code: str,
        http_status: int,
        message: str,
        trace_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> PresentResult[ErrorEnvelope]:
        """Build an ErrorEnvelope and attach ``X-Request-ID`` (no ETag)."""
        err = ErrorObject(
            code=code,
            http_status=http_status,
            message=message,
            details=details or {},
            trace_id=trace_id,
        )
        headers: dict[str, str] = {}
        if trace_id:
            headers["X-Request-ID"] = trace_id
        body = ErrorEnvelope(error=err)
        return PresentResult(body=body, headers=headers, status_code=int(http_status))

    # ------------------------- Paginated ------------------------------- #

    def present_paginated(
        self,
        *,
        items: list[Any],
        page: int,
        page_size: int,
        total: int,
        trace_id: str | None = None,
        etag: str | None = None,
    ) -> PresentResult[PaginatedEnvelope[Any]]:
        """Build a PaginatedEnvelope and attach optional headers.

        Notes:
            * If ``etag`` is supplied (e.g., a precomputed weak validator), it is
              passed through **verbatim** as the ``ETag`` header.
            * If ``etag`` is ``None``, this method does **not** compute one. The
              caller (router/use-case) decides ETag behavior for conditional GETs.
        """
        body = PaginatedEnvelope[Any](page=page, page_size=page_size, total=total, items=items)
        headers: dict[str, str] = {}
        if trace_id:
            headers["X-Request-ID"] = trace_id
        if etag is not None:
            headers["ETag"] = etag
        return PresentResult(body=body, headers=headers)

    # ------------------------- Header application ---------------------- #

    @staticmethod
    def apply_headers(result: PresentResult[Any], response: Response) -> None:
        """Apply headers and optional status code to the outgoing response."""
        try:
            response.headers.update(dict(result.headers))
        except Exception:  # pragma: no cover
            _LOGGER.exception("presenter_apply_headers_failed", extra={"headers": result.headers})

        if result.status_code is not None:
            response.status_code = result.status_code
