# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Market Data presenters.

Overview:
    Presentation helpers specialized for market data endpoints. Adds support for
    cache validators (ETag) and conditional responses (304 Not Modified).

Layer:
    adapters/presenters

Design:
    * Extends BasePresenter and returns Contract Registry envelopes.
    * For list endpoints, prefer `present_paginated` with an optional ETag supplied
      by the use-case. A helper below can compute a canonical strong ETag when
      needed (same hashing rules as `BasePresenter`).
"""

from __future__ import annotations

from typing import Any

from fastapi import Response

from stacklion_api.adapters.presenters.base_presenter import (
    BasePresenter,
    PresentResult,
    _compute_quoted_etag,
)
from stacklion_api.adapters.schemas.http.envelopes import PaginatedEnvelope


def _normalize_if_none_match(value: str | None) -> str | None:
    """Normalize an ``If-None-Match`` value for weak vs strong comparison.

    RFC 7232 allows weak validators (``W/"..."``) for GET/HEAD. We strip a
    leading ``W/`` and surrounding whitespace for a pragmatic equality check.

    Args:
        value: Raw ``If-None-Match`` header value.

    Returns:
        Normalized tag (still quoted) or ``None`` if input was falsy.
    """
    if not value:
        return None
    v = value.strip()
    if v.startswith("W/"):
        v = v[2:].lstrip()
    return v


class MarketDataPresenter(BasePresenter[dict[str, Any]]):
    """Presenter for market data surfaces (quotes, historical bars)."""

    # ---- Simple wrapper some routers/tests expect ----
    def present_list(
        self, *, items: list[Any], page: int, page_size: int, total: int
    ) -> PresentResult[PaginatedEnvelope[Any]]:
        """Create a canonical PaginatedEnvelope (no conditional logic here)."""
        return self.present_paginated(
            items=items, page=page, page_size=page_size, total=total, trace_id=None, etag=None
        )

    def present_list_with_etag(
        self,
        *,
        items: list[dict[str, Any]],
        page: int,
        page_size: int,
        total: int,
        if_none_match: str | None,
    ) -> PresentResult[PaginatedEnvelope[Any] | None]:
        """Create a PaginatedEnvelope and attach an ETag; emit 304 if unchanged.

        Args:
            items: Items for the page.
            page: 1-based page number.
            page_size: Items per page.
            total: Total matching items.
            if_none_match: Incoming value of the ``If-None-Match`` request header.

        Returns:
            PresentResult: Result with body (or ``None`` for 304), headers, and optional status.
        """
        # Build the envelope first (so hashing matches final body shape)
        body = PaginatedEnvelope[Any](page=page, page_size=page_size, total=total, items=items)
        etag = _compute_quoted_etag(body.model_dump(mode="python"))
        provided = _normalize_if_none_match(if_none_match)

        if provided and provided == etag:
            # 304 Not Modified, body suppressed but headers carry the ETag.
            return PresentResult(body=None, headers={"ETag": etag}, status_code=304)

        # Normal 200 with body + ETag header
        return PresentResult(body=body, headers={"ETag": etag})

    def finalize(self, result: PresentResult[Any], response: Response) -> Any | None:
        """Apply headers/status then return the envelope body (or None for 304).

        Args:
            result: Presentation result from any method above.
            response: Outgoing response instance to mutate.

        Returns:
            The envelope body to be sent (or ``None`` for 304).
        """
        self.apply_headers(result, response)
        return result.body
