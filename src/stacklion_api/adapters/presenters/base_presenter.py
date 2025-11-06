# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Presenter utilities and canonical envelope helpers.

This module contains a small, framework-oriented façade used by adapter layers
(routers/controllers) to consistently shape HTTP responses and headers.

It builds Contract Registry envelopes (SuccessEnvelope, PaginatedEnvelope,
ErrorEnvelope) and applies standard headers (e.g. ``X-Request-ID``, ``ETag``).

Design:
  * Pure presentation: no I/O or business logic.
  * PEP-695 generics for type-safe envelopes.
  * Strong, **quoted** ETag for success responses is computed from a canonical
    JSON rendering that safely handles ``Decimal``/``datetime`` values.
  * For paginated responses, the caller decides whether to include an ETag
    (e.g., pass a precomputed weak validator from the use case). If no ETag is
    supplied, we do not invent one so that routers can implement conditional GET.
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

from stacklion_api.infrastructure.logging.logger import get_json_logger

from ..schemas.http.envelopes import (
    ErrorEnvelope,
    ErrorObject,
    PaginatedEnvelope,
    SuccessEnvelope,
)
from . import __name__ as _pkg_name  # for diagnostics

_LOGGER = get_json_logger(__name__)


def _json_default(value: Any) -> str:
    """Serialize non-JSON-native types deterministically for hashing."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        # Canonicalize: remove insignificant zeros, avoid scientific notation,
        # collapse -0 to 0, and use integer form when exact.
        v = value.normalize()  # strips trailing zeros in the coefficient
        if v == 0:
            return "0"  # collapse -0 and 0 to the same string
        # If value is an exact integer, render as integer (no trailing .0)
        if v == v.to_integral():
            return format(v.to_integral(), "f")
        s = format(v, "f")  # fixed-point, no scientific notation
        s = s.rstrip("0").rstrip(".")  # strip any remaining insignificant zeros/dot
        return s
    raise TypeError(f"{_pkg_name}: unsupported JSON default for type {type(value)!r}")


def _compute_quoted_etag(payload: Mapping[str, Any]) -> str:
    """Return a **quoted** strong ETag (SHA-256 of canonical JSON for ``payload``).

    Args:
        payload: A Pydantic ``model_dump`` (or other mapping) to hash.

    Returns:
        str: A double-quoted hex digest, e.g. ``"d41d8cd98f00b204e9800998ecf8427e"``.
    """
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
    """Structured result produced by presenter methods.

    Attributes:
        body: A Pydantic envelope instance, or ``None`` when returning 304.
        headers: Extra HTTP headers to apply to the response.
        status_code: Optional HTTP status override (e.g., 304, 400, 429).
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
        self, *, data: Any, trace_id: str | None = None
    ) -> PresentResult[SuccessEnvelope[Any]]:
        """Build a :class:`SuccessEnvelope` and attach headers.

        Behavior:
            * Always echoes ``X-Request-ID`` when provided.
            * Computes and sets a **quoted** strong ``ETag`` from the envelope body.

        Args:
            data: Domain/adaptor DTO or primitive to embed under ``data``.
            trace_id: Optional correlation id to echo as ``X-Request-ID``.

        Returns:
            PresentResult: Wrapper containing the `SuccessEnvelope` and headers.
        """
        body = SuccessEnvelope[Any](data=data)
        payload = body.model_dump(mode="python")
        headers: dict[str, str] = {}
        if trace_id:
            headers["X-Request-ID"] = str(trace_id)
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
        """Build an :class:`ErrorEnvelope` and attach ``X-Request-ID`` (no ETag).

        Args:
            code: Stable machine-readable error code (e.g., ``"VALIDATION_ERROR"``).
            http_status: HTTP status code to emit (e.g., 400/403/404/429/500/503).
            message: Human-readable error description.
            trace_id: Optional correlation id to echo as ``X-Request-ID``.
            details: Optional structured diagnostics for clients.

        Returns:
            PresentResult: With error body and the provided status code.
        """
        err = ErrorObject(
            code=code,
            http_status=http_status,
            message=message,
            details=details or {},
            trace_id=trace_id,
        )
        headers: dict[str, str] = {}
        if trace_id:
            headers["X-Request-ID"] = str(trace_id)
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
        """Build a :class:`PaginatedEnvelope` and attach optional headers.

        Notes:
            * If ``etag`` is supplied (e.g., a precomputed weak validator), it is
              passed through **verbatim** as the ``ETag`` header.
            * If ``etag`` is ``None``, this method does **not** compute one. The
              caller (router/use-case) decides ETag behavior for conditional GETs.

        Args:
            items: Page of mapped DTOs.
            page: 1-based page number.
            page_size: Items per page.
            total: Total number of matching rows.
            trace_id: Optional correlation id to echo as ``X-Request-ID``.
            etag: Optional precomputed ETag (e.g., ``W/"..."`` or quoted hex).

        Returns:
            PresentResult: With a `PaginatedEnvelope` and headers.
        """
        body = PaginatedEnvelope[Any](page=page, page_size=page_size, total=total, items=items)
        headers: dict[str, str] = {}
        if trace_id:
            headers["X-Request-ID"] = str(trace_id)
        if etag is not None:
            headers["ETag"] = str(etag)
        return PresentResult(body=body, headers=headers)

    # ------------------------- Header application ---------------------- #

    @staticmethod
    def apply_headers(result: PresentResult[Any], response: Response) -> None:
        """Apply headers and optional status code to the outgoing response.

        Args:
            result: The previously built presentation result.
            response: The active :class:`fastapi.Response` to mutate.
        """
        # apply presenter headers to the framework response safely
        try:
            response.headers.update(dict(result.headers))
        except Exception:  # pragma: no cover
            _LOGGER.exception("presenter_apply_headers_failed", extra={"headers": result.headers})

        # status code (if presenter set one)
        if result.status_code is not None:
            response.status_code = result.status_code
