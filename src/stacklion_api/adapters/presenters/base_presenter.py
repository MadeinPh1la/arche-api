"""
Base Presenter (Adapters Layer)

Purpose:
    Construct canonical HTTP envelopes and headers for the adapters boundary:
      - SuccessEnvelope[T] for single payloads
      - PaginatedEnvelope[T] for lists with total count
      - ErrorEnvelope for failures, embedding ErrorObject
    and emit deterministic, cache-friendly headers (ETag) plus trace echo (X-Request-ID).

Design:
    * Transport-only: presenters know nothing about domain/services/DB.
    * PEP-695 generics (Py3.12) for envelope type safety.
    * Deterministic ETag: SHA-256 over canonical JSON (sorted keys).
    * Logging: structured JSON via infrastructure logger.
    * No hard dependency on FastAPI; response typing is optional/duck-typed.

Contracts (API Standards):
    * Presenters are the only layer allowed to shape HTTP envelopes.
    * X-Request-ID is echoed when provided.
    * Error responses include a structured ErrorObject with a trace_id.
    * Pagination fields: page (>=1), page_size (1..200), total (>=0).

Layer:
    adapters/presenters
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from stacklion_api.adapters.schemas.base import BaseHTTPSchema
from stacklion_api.adapters.schemas.envelopes import (
    ErrorEnvelope,
    ErrorObject,
    PaginatedEnvelope,
    SuccessEnvelope,
)
from stacklion_api.infrastructure.logging.logger import get_json_logger

_logger = get_json_logger(__name__)


# ------------------------------------------------------------------------------
# Result wrapper
# ------------------------------------------------------------------------------


@dataclass(frozen=True)
class PresentResult[BodyT]:
    """Value object carrying an envelope body and headers.

    Attributes:
        body: The envelope instance (SuccessEnvelope / PaginatedEnvelope / ErrorEnvelope).
        headers: HTTP headers to apply at the router boundary.
    """

    body: BodyT
    headers: Mapping[str, str]


# Minimal protocol so we can update headers without type: ignore
class _ResponseLike(Protocol):
    headers: MutableMapping[str, str]


# ------------------------------------------------------------------------------
# Presenter
# ------------------------------------------------------------------------------


class BasePresenter[T]:
    """Canonical presenter that constructs contract-compliant HTTP envelopes.

    Responsibilities:
        * Build Success, Paginated, and Error envelopes from adapter DTOs.
        * Compute deterministic ETags and emit standard headers.
        * Remain transport-only and framework-agnostic.

    Notes:
        * Returned `PresentResult.headers` is a mapping of strings.
        * Routers/controllers apply headers and serialize `body`.
    """

    # ------------------------------------------------------------------ #
    # Success                                                            #
    # ------------------------------------------------------------------ #
    def present_success(
        self,
        data: T,
        *,
        trace_id: str | None = None,
        etag: str | None = None,
    ) -> PresentResult[SuccessEnvelope[T]]:
        """Create a SuccessEnvelope[T] with standard headers.

        Args:
            data: Adapter DTO or primitive to place under `data`.
            trace_id: Correlation id to echo as `X-Request-ID` and embed in logs.
            etag: Precomputed ETag. When omitted, it is computed deterministically.

        Returns:
            PresentResult[SuccessEnvelope[T]]: Envelope and headers.
        """
        envelope = SuccessEnvelope[T](data=data)
        etag_value = etag or self._compute_etag(envelope)
        headers = self._standard_headers(trace_id=trace_id, etag=etag_value)
        _logger.debug(
            "present_success",
            extra={"trace_id": trace_id, "computed_etag": etag_value},
        )
        return PresentResult(body=envelope, headers=headers)

    # ------------------------------------------------------------------ #
    # Paginated                                                          #
    # ------------------------------------------------------------------ #
    def present_paginated(
        self,
        *,
        items: Sequence[T],
        page: int,
        page_size: int,
        total: int,
        trace_id: str | None = None,
        etag: str | None = None,
    ) -> PresentResult[PaginatedEnvelope[T]]:
        """Create a PaginatedEnvelope[T] with standard headers.

        Args:
            items: Page contents (adapter DTOs).
            page: 1-indexed page number (>= 1).
            page_size: Items per page (1..200).
            total: Total number of matching records (>= 0).
            trace_id: Correlation id to echo in headers and logs.
            etag: Optional precomputed ETag for cache coordination.

        Returns:
            PresentResult[PaginatedEnvelope[T]]: Envelope and headers.
        """
        envelope = PaginatedEnvelope[T](page=page, page_size=page_size, total=total, items=items)
        etag_value = etag or self._compute_etag(envelope)
        headers = self._standard_headers(trace_id=trace_id, etag=etag_value)
        _logger.debug(
            "present_paginated",
            extra={
                "trace_id": trace_id,
                "page": page,
                "page_size": page_size,
                "total": total,
                "computed_etag": etag_value,
            },
        )
        return PresentResult(body=envelope, headers=headers)

    # ------------------------------------------------------------------ #
    # Error                                                              #
    # ------------------------------------------------------------------ #
    def present_error(
        self,
        *,
        code: str,
        http_status: int,
        message: str,
        details: Mapping[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> PresentResult[ErrorEnvelope]:
        """Create an ErrorEnvelope with standard headers.

        Args:
            code: Stable machine-readable error code (UPPER_SNAKE_CASE).
            http_status: HTTP status that routers should set on the response.
            message: Human-readable, safe error message (no secrets).
            details: Optional structured error context (client-safe).
            trace_id: Correlation id to embed in `error.trace_id` and echo as header.

        Returns:
            PresentResult[ErrorEnvelope]: Envelope and headers.
        """
        err = ErrorObject(
            code=code,
            http_status=http_status,
            message=message,
            details=dict(details) if details else None,
            trace_id=trace_id,
        )
        envelope = ErrorEnvelope(error=err)
        headers = self._standard_headers(trace_id=trace_id, etag=None)
        _logger.debug(
            "present_error",
            extra={"trace_id": trace_id, "code": code, "http_status": http_status},
        )
        return PresentResult(body=envelope, headers=headers)

    # ------------------------------------------------------------------ #
    # Header helpers                                                     #
    # ------------------------------------------------------------------ #
    @staticmethod
    def rate_limit_headers(
        limit: int, remaining: int, reset_epoch_seconds: int
    ) -> Mapping[str, str]:
        """Return canonical rate-limit headers.

        Args:
            limit: Allowed requests in this window.
            remaining: Remaining requests in this window.
            reset_epoch_seconds: Unix epoch seconds when the window resets.

        Returns:
            Mapping[str, str]: X-RateLimit-* headers.
        """
        return {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_epoch_seconds),
        }

    # ------------------------------------------------------------------ #
    # Response integration (duck-typed; framework-agnostic)              #
    # ------------------------------------------------------------------ #
    def apply_headers(self, result: PresentResult[object], response: _ResponseLike | None) -> None:
        """Apply prepared headers onto a response-like object (optional).

        The provided `response` must expose a `headers` mapping with an `.update(dict)` method.
        If `response` is None, this is a no-op.

        Args:
            result: PresentResult from `present_*`.
            response: A framework response object (e.g., FastAPI Response) or None.
        """
        if response is None:
            return
        try:
            response.headers.update(dict(result.headers))
        except Exception as exc:  # pragma: no cover
            _logger.exception(
                "apply_headers_failed",
                extra={"headers": result.headers, "reason": str(exc)},
            )

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _standard_headers(*, trace_id: str | None, etag: str | None) -> dict[str, str]:
        """Compose standard headers (X-Request-ID and optional ETag).

        Args:
            trace_id: Request correlation id to echo as `X-Request-ID`.
            etag: Strong ETag value to include, if present.

        Returns:
            dict[str, str]: Headers ready for application by the router/controller.
        """
        headers: dict[str, str] = {}
        if trace_id:
            headers["X-Request-ID"] = trace_id
        if etag:
            headers["ETag"] = etag
        return headers

    @staticmethod
    def _compute_etag(payload: BaseHTTPSchema | Mapping[str, Any]) -> str:
        """Compute a deterministic strong ETag over the JSON body.

        The digest is the hex SHA-256 of `json.dumps(body, sort_keys=True, separators=(",", ":"))`.

        Args:
            payload: Envelope instance or plain mapping representing the body.

        Returns:
            str: Quoted hex digest suitable for the `ETag` header.
        """
        if isinstance(payload, BaseHTTPSchema):
            data = payload.model_dump(mode="json")
        else:
            data = dict(payload)
        blob = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(blob).hexdigest()
        return f'"{digest}"'
