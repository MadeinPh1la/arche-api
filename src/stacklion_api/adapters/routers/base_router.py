"""
Base Router (Adapters Layer)

Purpose:
    Provide a canonical APIRouter wrapper and shared utilities for Stacklion HTTP endpoints:
      - Versioned routing with stable prefixes (e.g., "/v1/companies").
      - Standard error response mapping using ErrorEnvelope.
      - Pagination query dependency with hard caps and helpers.
      - Helpers to emit presenter results with headers (ETag, X-Request-ID).
      - Default tags, dependencies, and OpenAPI meta aligned to API Standards.

Layer:
    adapters/routers

Usage:
    from fastapi import Depends, Response, status
    from stacklion_api.adapters.routers.base_router import BaseRouter, PageParams
    from stacklion_api.adapters.presenters.base_presenter import BasePresenter
    from stacklion_api.adapters.schemas.envelopes import SuccessEnvelope
    from .dto import CompanyResponse  # your adapter schema

    router = BaseRouter(version="v1", resource="companies", tags=["Companies"])
    presenter = BasePresenter[CompanyResponse]()

    @router.get(
        "/{company_id}",
        response_model=SuccessEnvelope[CompanyResponse],
        status_code=status.HTTP_200_OK,
        responses=BaseRouter.std_error_responses(),
        summary="Get company by ID",
    )
    async def get_company(company_id: str, response: Response) -> SuccessEnvelope[CompanyResponse]:
        dto = await service.get_company(company_id)  # your app/service call
        result = presenter.present_success(dto, trace_id=response.headers.get("X-Request-ID"))
        return router.send_success(response, result)

    @router.get(
        "",
        response_model=SuccessEnvelope[list[CompanyResponse]],
        status_code=status.HTTP_200_OK,
        responses=BaseRouter.std_error_responses(),
        summary="List companies (non-paginated example)",
    )
    async def list_companies(response: Response) -> SuccessEnvelope[list[CompanyResponse]]:
        items = await service.list_companies()
        result = presenter.present_success(items, trace_id=response.headers.get("X-Request-ID"))
        return router.send_success(response, result)

    @router.get(
        "/search",
        response_model=SuccessEnvelope[list[CompanyResponse]],
        status_code=status.HTTP_200_OK,
        responses=BaseRouter.std_error_responses(),
        summary="Search companies (with pagination parameters available)",
    )
    async def search_companies(
        q: str,
        page: PageParams = Depends(BaseRouter.page_params),
        response: Response | None = None,  # FastAPI injects this
    ) -> SuccessEnvelope[list[CompanyResponse]]:
        items, total = await service.search_companies(q, offset=page.offset, limit=page.limit)
        # If you want strict paginated envelope instead, use presenter.present_paginated(...)
        result = presenter.present_success(items, trace_id=response.headers.get("X-Request-ID") if response else None)
        return router.send_success(response, result)
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

# -------------------------------------------------------------------------------------
# Module logger
# -------------------------------------------------------------------------------------
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

    This class centralizes versioned prefixes, default error responses, shared
    dependencies (e.g., pagination), and a helper to emit presenter results
    with headers applied.

    Args:
        version: API version segment (e.g., "v1").
        resource: Plural resource segment (e.g., "companies").
        prefix: Optional explicit prefix. If omitted, computed as f"/{version}/{resource}".
        tags: Default tags applied to all routes mounted on this router.
        dependencies: Optional sequence of global dependencies for all routes.
        **kwargs: Additional APIRouter kwargs forwarded to super().__init__.

    Example:
        router = BaseRouter(version="v1", resource="companies", tags=["Companies"])
    """

    # ---- Canonical caps per API Standards (tune as needed) ----
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
        # Convert Sequence -> list for FastAPI while keeping typesafe signature.
        super().__init__(
            prefix=computed_prefix,
            tags=list(tags) if tags is not None else None,
            dependencies=list(dependencies) if dependencies is not None else None,
            **kwargs,
        )
        _LOGGER.info(
            "router_initialized",
            extra={"service": "stacklion-api", "prefix": computed_prefix, "tags": list(tags or [])},
        )

    # -------------------------------------------------------------------------
    # Response helpers
    # -------------------------------------------------------------------------
    @staticmethod
    def send_success(
        response: _ResponseLike | None,
        result: PresentResult[BaseHTTPSchema | Mapping[str, JsonValue]],
    ) -> BaseHTTPSchema | dict[str, JsonValue]:
        """Apply presenter headers on the Response (if provided) and return the body.

        Args:
            response: Framework Response object (e.g., FastAPI Response) or None.
            result: Presenter output containing `body` (Pydantic model or mapping)
                and `headers`.

        Returns:
            The envelope body (`SuccessEnvelope` or `PaginatedEnvelope`) to return.
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
        if isinstance(body, Mapping):
            # Normalize to a concrete dict for JSON rendering.
            return dict(body)
        return body

    # -------------------------------------------------------------------------
    # Dependencies
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
            - Defaults are applied when params are omitted (page=1, page_size=DEFAULT_PAGE_SIZE).
            - `per_page` is accepted for backward compatibility; if supplied and the caller did
              not set `page_size`, its value is used for `page_size`.
            - Values are clamped to [MIN_PAGE, ...] and [MIN_PAGE_SIZE..MAX_PAGE_SIZE].

        Args:
            page: 1-indexed page number (>= 1).
            page_size: Items per page (1..MAX_PAGE_SIZE).
            per_page: Deprecated input-only synonym for page_size.

        Returns:
            PageParams: Immutable struct with `offset` and `limit` helpers.
        """
        # Fill defaults
        p = page if page is not None else cls.MIN_PAGE
        ps = page_size if page_size is not None else cls.DEFAULT_PAGE_SIZE

        # Honor deprecated per_page only if page_size wasn't explicitly provided
        if per_page is not None and page_size is None:
            ps = per_page

        # Clamp to policy bounds
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

        This mapping instructs FastAPI/OpenAPI to document the standard
        ErrorEnvelope for common failure codes. Use it in each route via:

            responses=BaseRouter.std_error_responses()

        Returns:
            Mapping of HTTP status codes to OpenAPI response objects.
        """
        # Keep descriptions brief and actionable for API consumers.
        return {
            400: {"model": ErrorEnvelope, "description": "Bad request (validation or parameter)"},
            401: {"model": ErrorEnvelope, "description": "Unauthorized (missing/invalid auth)"},
            403: {"model": ErrorEnvelope, "description": "Forbidden (insufficient permissions)"},
            404: {"model": ErrorEnvelope, "description": "Not found"},
            409: {"model": ErrorEnvelope, "description": "Conflict"},
            422: {"model": ErrorEnvelope, "description": "Unprocessable content"},
            429: {"model": ErrorEnvelope, "description": "Rate limit exceeded"},
            500: {"model": ErrorEnvelope, "description": "Internal server error"},
            503: {"model": ErrorEnvelope, "description": "Service unavailable"},
        }
