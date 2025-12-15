# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Market Data presenters.

Provides canonical envelopes for paginated market data pages,
and conditional responses via strong ETags.

Layer:
    adapters/presenters
"""

from __future__ import annotations

from typing import Any

from fastapi import Response

from arche_api.adapters.presenters.base_presenter import (
    BasePresenter,
    PresentResult,
    _compute_quoted_etag,
)
from arche_api.adapters.schemas.http.envelopes import PaginatedEnvelope


def _normalize_if_none_match(value: str | None) -> str | None:
    """Normalize `If-None-Match` for strong ETag comparison (strip W/ prefix)."""
    if not value:
        return None
    v = value.strip()
    return v[2:].lstrip() if v.startswith("W/") else v


class MarketDataPresenter(BasePresenter[dict[str, Any]]):
    """Presenter for all historical/intraday paginated data surfaces."""

    # --- Simple facade used in smaller routers/tests ---
    def present_list(
        self, *, items: list[Any], page: int, page_size: int, total: int
    ) -> PresentResult[PaginatedEnvelope[Any]]:
        """Simple paginated envelope, no conditional logic."""
        return self.present_paginated(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            trace_id=None,
            etag=None,
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
        """Paginated envelope with strong ETag and 304 handling.

        Returns:
            • 200 + envelope + ETag when changed.
            • 304 + ETag (body=None) when unchanged.
        """
        body = PaginatedEnvelope[Any](page=page, page_size=page_size, total=total, items=items)

        etag = _compute_quoted_etag(body.model_dump_http())
        provided = _normalize_if_none_match(if_none_match)

        if provided and provided == etag:
            # 304 Not Modified — ETag must still be emitted
            return PresentResult(body=None, headers={"ETag": etag}, status_code=304)

        return PresentResult(body=body, headers={"ETag": etag})

    def finalize(self, result: PresentResult[Any], response: Response) -> Any | None:
        """Apply presenter-controlled headers and optional status."""
        self.apply_headers(result, response)
        return result.body
