# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Base Router (Adapters Layer)

Purpose:
    Provide a canonical APIRouter wrapper and shared utilities for Stacklion HTTP endpoints:
      - Versioned routing with stable prefixes (e.g., "/v1/companies").
      - Standard error response mapping using ErrorEnvelope.
      - Pagination query dependency with hard caps and helpers.
      - Helpers to emit presenter results with headers (ETag, X-Request-ID).
      - Default tags, dependencies, and OpenAPI metadata aligned to API Standards.

Layer:
    adapters/routers
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from fastapi import APIRouter, Query

from stacklion_api.adapters.presenters.base_presenter import PresentResult
from stacklion_api.adapters.schemas.http.base import BaseHTTPSchema
from stacklion_api.adapters.schemas.http.envelopes import ErrorEnvelope
from stacklion_api.infrastructure.logging.logger import get_json_logger
from stacklion_api.types import JsonValue

_LOGGER = get_json_logger(__name__)

# Tag type accepted by FastAPI for APIRouter.tags
TagType = str | Enum  # UP007 compliant


@dataclass(frozen=True)
class PageParams:
    """Validated pagination parameters with computed `offset` and `limit`.

    Attributes:
        page: 1-indexed page number.
        page_size: Items per page.
        offset: Calculated zero-based offset for repositories/DAOs.
        limit: Calculated limit (equals `page_size`).
    """

    page: int
    page_size: int

    @property
    def offset(self) -> int:
        """Return zero-based row offset."""
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        """Return limit equal to `page_size`."""
        return self.page_size


@runtime_checkable
class _ResponseLike(Protocol):
    """Duck-typed response that supports header updates (e.g., FastAPI Response)."""

    headers: MutableMapping[str, str]


class BaseRouter(APIRouter):
    """Canonical router wrapper for Stacklion HTTP endpoints.

    This class centralizes:

        • Versioned prefixes (e.g., `/v2/quotes`).
        • Default error responses using ErrorEnvelope.
        • Pagination dependency with policy caps.
        • A helper to apply presenter headers and return envelope bodies.

    Args:
        version: API version segment (e.g., "v2").
        resource: Plural resource segment (e.g., "quotes").
        prefix: Optional explicit prefix (overrides version/resource).
        tags: Default tags applied to all routes mounted on this router.
        dependencies: Optional global dependencies for all routes.
        **kwargs: Additional APIRouter kwargs.
    """

    # Canonical caps per API Standards (tune as needed)
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
        computed_prefix = prefix or f"/{version}/{resource}"
        super().__init__(
            prefix=computed_prefix,
            tags=list(tags) if tags is not None else None,
            dependencies=list(dependencies) if dependencies is not None else None,
            **kwargs,
        )
        _LOGGER.info(
            "router_initialized",
            extra={
                "service": "stacklion-api",
                "prefix": computed_prefix,
                "tags": list(tags or []),
            },
        )

    # -------------------------------------------------------------------------
    # Response helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def send_success(
        response: _ResponseLike | None,
        result: PresentResult[Any],
    ) -> BaseHTTPSchema | dict[str, JsonValue]:
        """Apply presenter headers to the Response (if provided) and return the body.

        This is primarily for legacy call sites; newer routers should prefer
        returning the envelope instance directly from the presenter.

        Args:
            response: Framework Response object or None.
            result: Presenter output (envelope + headers).

        Returns:
            The envelope body (SuccessEnvelope / PaginatedEnvelope) or an empty
            object when body is None (defensive).
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
            # Defensive: avoid returning null as top-level JSON when contract
            # expects an object. Routers should avoid using send_success for
            # 304 paths and similar.
            return {}

        if isinstance(body, Mapping):
            return dict(body)

        return body

    # -------------------------------------------------------------------------
    # Pagination dependency
    # -------------------------------------------------------------------------

    @classmethod
    def page_params(
        cls,
        page: int | None = Query(
            default=None,
            description="1-indexed page number.",
            examples=[1],
            ge=1,
        ),
        page_size: int | None = Query(
            default=None,
            description="Items per page (bounded by MAX_PAGE_SIZE).",
            examples=[50],
            ge=1,
        ),
        # Back-compat INPUT ONLY; never emitted in responses
        per_page: int | None = Query(
            default=None,
            description="Deprecated: use page_size (input only).",
            deprecated=True,
            ge=1,
        ),
    ) -> PageParams:
        """Return validated pagination parameters with computed offset/limit.

        Behavior:
            • Defaults: page=1, page_size=DEFAULT_PAGE_SIZE when omitted.
            • `per_page` is accepted for backward compatibility; used only if
              page_size is not explicitly set.
            • Values are clamped to [MIN_PAGE, ...] and [MIN_PAGE_SIZE..MAX_PAGE_SIZE].

        Args:
            page: 1-indexed page number (>= 1).
            page_size: Items per page (1..MAX_PAGE_SIZE).
            per_page: Deprecated synonym for page_size (input-only).

        Returns:
            PageParams with computed offset and limit.
        """
        p = page if page is not None else cls.MIN_PAGE
        ps = page_size if page_size is not None else cls.DEFAULT_PAGE_SIZE

        if per_page is not None and page_size is None:
            ps = per_page

        # Clamp to bounds
        if p < cls.MIN_PAGE:
            p = cls.MIN_PAGE
        if ps < cls.MIN_PAGE_SIZE:
            ps = cls.MIN_PAGE_SIZE
        if ps > cls.MAX_PAGE_SIZE:
            ps = cls.MAX_PAGE_SIZE

        return PageParams(page=p, page_size=ps)

    # -------------------------------------------------------------------------
    # OpenAPI Error Responses
    # -------------------------------------------------------------------------

    @staticmethod
    def std_error_responses() -> dict[int, dict[str, Any]]:
        """Return the canonical error response mapping for endpoints.

        Use in routes via:

            responses=BaseRouter.std_error_responses()

        Returns:
            Mapping from HTTP status code → OpenAPI response object with
            ErrorEnvelope as the model.
        """
        return {
            400: {"model": ErrorEnvelope, "description": "Bad request (validation or parameter)."},
            401: {"model": ErrorEnvelope, "description": "Unauthorized (missing/invalid auth)."},
            403: {"model": ErrorEnvelope, "description": "Forbidden (insufficient permissions)."},
            404: {"model": ErrorEnvelope, "description": "Not found."},
            409: {"model": ErrorEnvelope, "description": "Conflict."},
            422: {"model": ErrorEnvelope, "description": "Unprocessable content."},
            429: {"model": ErrorEnvelope, "description": "Rate limit exceeded."},
            500: {"model": ErrorEnvelope, "description": "Internal server error."},
            503: {"model": ErrorEnvelope, "description": "Service unavailable."},
        }
