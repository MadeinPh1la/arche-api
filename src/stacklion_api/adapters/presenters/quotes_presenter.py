# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Quotes Presenter.

Summary:
    Render application-layer Quote DTOs as the canonical SuccessEnvelope and
    attach optional caching headers (ETag, Cache-Control).

Layer:
    adapters/presenters
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from stacklion_api.adapters.presenters.base_presenter import PresentResult
from stacklion_api.adapters.schemas.http.envelopes import SuccessEnvelope
from stacklion_api.adapters.schemas.http.quotes import QuoteItem, QuotesBatch
from stacklion_api.application.schemas.dto.quotes import QuotesBatchDTO


class QuotesPresenter:
    """Presenter for `/v1/quotes` success responses."""

    def present_success(
        self,
        dto: QuotesBatchDTO,
        *,
        trace_id: str | None = None,
        enable_caching: bool = False,
        cache_ttl_s: int | None = None,
        etag_seed: str | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> PresentResult[SuccessEnvelope[QuotesBatch]]:
        """Build a SuccessEnvelope[QuotesBatch] and optional ETag headers."""
        payload = QuotesBatch(
            items=[
                QuoteItem(
                    ticker=i.ticker,
                    price=str(i.price),
                    currency=i.currency,
                    as_of=i.as_of,
                    volume=i.volume,
                )
                for i in dto.items
            ]
        )
        envelope = SuccessEnvelope[QuotesBatch](data=payload)

        headers: dict[str, str] = {}
        if enable_caching:
            # Use deterministic seed when provided; otherwise hash the body.
            if etag_seed is not None:
                body_bytes = etag_seed.encode("utf-8")
            else:
                body_dict = envelope.model_dump_http()
                body_bytes = json.dumps(body_dict, separators=(",", ":"), sort_keys=True).encode(
                    "utf-8"
                )
            etag = f'"{hashlib.sha256(body_bytes).hexdigest()}"'
            headers["ETag"] = etag
            if cache_ttl_s is not None:
                headers["Cache-Control"] = f"public, max-age={int(cache_ttl_s)}"

        if extra_headers:
            headers.update(dict(extra_headers))

        return PresentResult(body=envelope, headers=headers)
