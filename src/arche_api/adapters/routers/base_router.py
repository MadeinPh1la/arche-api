# src/arche_api/adapters/routers/base_router.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Base Router (Adapters Layer).

Purpose:
    Provide a canonical APIRouter wrapper and shared utilities for Arche HTTP endpoints:
        - Versioned routing with stable prefixes (e.g., "/v1/companies").
        - Standard error response mapping using ErrorEnvelope.
        - Pagination query dependency with hard caps and helpers.
        - Helpers to emit presenter results with headers (ETag, X-Request-ID).
        - Default tags, dependencies, and OpenAPI metadata aligned to API Standards.
        - Reusable OpenAPI response object for idempotency conflicts.

Layer:
    adapters/routers
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from fastapi import APIRouter, Query, status

from arche_api.adapters.presenters.base_presenter import PresentResult
from arche_api.adapters.schemas.http.base import BaseHTTPSchema
from arche_api.adapters.schemas.http.envelopes import ErrorEnvelope
from arche_api.infrastructure.logging.logger import get_json_logger
from arche_api.types import JsonValue

_LOGGER = get_json_logger(__name__)

# ---------------------------------------------------------------------------
# Reusable Types
# ---------------------------------------------------------------------------

TagType = str | Enum  # UP007 compliant


@dataclass(frozen=True)
class PageParams:
    """Validated pagination parameters with computed `offset` and `limit`."""

    page: int
    page_size: int

    @property
    def offset(self) -> int:
        """Return the zero-based row offset for this page."""
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        """Return the maximum number of rows to fetch for this page."""
        return self.page_size


@runtime_checkable
class _ResponseLike(Protocol):
    """Duck-typed response that supports mutating headers."""

    headers: MutableMapping[str, str]


# ---------------------------------------------------------------------------
# Idempotency Conflict Response (409)
# ---------------------------------------------------------------------------

IDEMPOTENCY_CONFLICT_RESPONSE: dict[int, dict[str, Any]] = {
    status.HTTP_409_CONFLICT: {
        "model": ErrorEnvelope,
        "description": (
            "Idempotency conflict.\n\n"
            "**Error codes:**\n"
            "- `IDEMPOTENCY_KEY_CONFLICT`: Idempotency-Key reused with different payload.\n"
            "- `IDEMPOTENCY_KEY_IN_PROGRESS`: Another request with the same Idempotency-Key "
            "is currently being processed."
        ),
        "content": {
            "application/json": {
                "examples": {
                    "key_conflict": {
                        "summary": "Payload conflict",
                        "value": {
                            "error": {
                                "code": "IDEMPOTENCY_KEY_CONFLICT",
                                "http_status": 409,
                                "message": (
                                    "Idempotency-Key reused with a different request payload."
                                ),
                                "details": {},
                                "trace_id": "trace-123",
                            }
                        },
                    },
                    "in_progress": {
                        "summary": "In-progress conflict",
                        "value": {
                            "error": {
                                "code": "IDEMPOTENCY_KEY_IN_PROGRESS",
                                "http_status": 409,
                                "message": (
                                    "Another request with the same Idempotency-Key is in progress."
                                ),
                                "details": {},
                                "trace_id": "trace-xyz",
                            }
                        },
                    },
                }
            }
        },
    }
}


# ---------------------------------------------------------------------------
# BaseRouter Implementation
# ---------------------------------------------------------------------------


class BaseRouter(APIRouter):
    """Canonical router wrapper for Arche HTTP endpoints."""

    MIN_PAGE: int = 1
    MIN_PAGE_SIZE: int = 1
    MAX_PAGE_SIZE: int = 200
    DEFAULT_PAGE_SIZE: int = 50

    def __init__(
        self,
        *,
        version: str,
        resource: str,
        prefix: str | None = None,
        tags: Sequence[TagType] | None = None,
        dependencies: Sequence[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the router with a versioned prefix and common settings.

        Args:
            version: API version segment (e.g., "v1").
            resource: Resource segment (e.g., "companies").
            prefix: Optional explicit prefix; defaults to f"/{version}/{resource}".
            tags: Optional default tags for the router's endpoints.
            dependencies: Optional dependencies applied to all routes.
            **kwargs: Additional keyword arguments forwarded to APIRouter.
        """
        computed_prefix = prefix or f"/{version}/{resource}"

        super().__init__(
            prefix=computed_prefix,
            tags=list(tags) if tags is not None else None,
            dependencies=list(dependencies) if dependencies is not None else None,
            **kwargs,
        )

        _LOGGER.info(
            "router_initialized",
            extra={"service": "arche_api", "prefix": computed_prefix, "tags": list(tags or [])},
        )

    # ----------------------------------------------------------------------
    # Response helpers
    # ----------------------------------------------------------------------

    @staticmethod
    def send_success(
        response: _ResponseLike | None,
        result: PresentResult[Any],
    ) -> BaseHTTPSchema | dict[str, JsonValue]:
        """Apply presenter headers and return a plain body for FastAPI.

        Args:
            response: Optional HTTP response-like object to mutate with headers.
            result: Presenter result containing headers and a structured body.

        Returns:
            A mapping suitable for FastAPI's response_model handling. If the
            presenter body is None, an empty dict is returned.
        """
        if response is not None:
            try:
                response.headers.update(dict(result.headers))
            except Exception as exc:  # pragma: no cover
                _LOGGER.exception(
                    "router_send_success_headers_failed",
                    extra={"headers": result.headers, "reason": str(exc)},
                )

        body = result.body
        if body is None:
            return {}
        if isinstance(body, Mapping):
            return dict(body)
        return body

    # ----------------------------------------------------------------------
    # Pagination dependency
    # ----------------------------------------------------------------------

    @classmethod
    def page_params(
        cls,
        page: int | None = Query(default=None, description="1-indexed page number.", ge=1),
        page_size: int | None = Query(default=None, description="Items per page (bounded).", ge=1),
        per_page: int | None = Query(default=None, description="Deprecated alias.", ge=1),
    ) -> PageParams:
        """Normalize and validate pagination query parameters.

        Args:
            page: 1-indexed page number; defaults to MIN_PAGE when omitted.
            page_size: Desired page size; defaults to DEFAULT_PAGE_SIZE.
            per_page: Deprecated alias for page_size, used only when page_size
                is not explicitly provided.

        Returns:
            PageParams with resolved page, page_size, offset, and limit.
        """
        p = page if page is not None else cls.MIN_PAGE
        ps = page_size if page_size is not None else cls.DEFAULT_PAGE_SIZE

        if per_page is not None and page_size is None:
            ps = per_page

        p = max(p, cls.MIN_PAGE)
        ps = max(min(ps, cls.MAX_PAGE_SIZE), cls.MIN_PAGE_SIZE)

        return PageParams(page=p, page_size=ps)

    # ----------------------------------------------------------------------
    # OpenAPI Error Responses
    # ----------------------------------------------------------------------

    @staticmethod
    def std_error_responses() -> dict[int, dict[str, Any]]:
        """Return canonical error responses including idempotency 409 conflicts."""
        responses = {
            400: {"model": ErrorEnvelope, "description": "Bad request."},
            401: {"model": ErrorEnvelope, "description": "Unauthorized."},
            403: {"model": ErrorEnvelope, "description": "Forbidden."},
            404: {"model": ErrorEnvelope, "description": "Not found."},
            409: {"model": ErrorEnvelope, "description": "Conflict."},
            422: {"model": ErrorEnvelope, "description": "Unprocessable content."},
            429: {"model": ErrorEnvelope, "description": "Rate limit exceeded."},
            500: {"model": ErrorEnvelope, "description": "Internal server error."},
            503: {"model": ErrorEnvelope, "description": "Service unavailable."},
        }

        # Replace the generic 409 with the richer idempotency-aware block
        responses[409] = IDEMPOTENCY_CONFLICT_RESPONSE[409]

        return responses
