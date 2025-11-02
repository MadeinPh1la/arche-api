# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Presenter: Latest Quotes → HTTP SuccessEnvelope.

Synopsis:
    Renders application-layer Quote DTOs into the canonical SuccessEnvelope,
    attaching optional caching headers (ETag, Cache-Control) in a controlled,
    deterministic way.

Layer:
    adapters/presenters

Design:
    * Separates presentation concerns from use-cases and routers.
    * Supports deterministic ETag generation (explicit seed) or content-hash.
    * Avoids business logic and external I/O.

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
    """Presenter for `/v1/quotes` success responses (latest quotes)."""

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
        """Build a SuccessEnvelope[QuotesBatch] and optional caching headers.

        Args:
            dto: Application DTO containing latest quotes.
            trace_id: Optional trace identifier to propagate in envelopes/headers.
            enable_caching: Whether to attach ETag (and Cache-Control if ttl provided).
            cache_ttl_s: Max-age in seconds to advertise when caching is enabled.
            etag_seed: Deterministic seed for ETag (preferred); if None, hash body.
            extra_headers: Extra headers to merge into the response.

        Returns:
            PresentResult[SuccessEnvelope[QuotesBatch]]: Body + headers pair.

        Notes:
            * If `etag_seed` is provided, it is used directly to derive the ETag,
              ensuring deterministic tags across equivalent payloads.
            * If not provided, a compact JSON representation of the body is hashed.
        """
        payload = QuotesBatch(
            items=[
                QuoteItem(
                    ticker=i.ticker,
                    price=str(i.price),
                    currency=i.currency,
                    as_of=i.as_of,  # Let the schema handle datetime serialization.
                    volume=i.volume,
                )
                for i in dto.items
            ]
        )
        envelope = SuccessEnvelope[QuotesBatch](data=payload)

        headers: dict[str, str] = {}
        if enable_caching:
            # Deterministic ETag when seed is provided, else compute over body.
            if etag_seed is not None:
                body_bytes = etag_seed.encode("utf-8")
            else:
                body_dict = envelope.model_dump_http()
                body_bytes = json.dumps(
                    body_dict,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")

            etag = f'"{hashlib.sha256(body_bytes).hexdigest()}"'
            headers["ETag"] = etag

            if cache_ttl_s is not None:
                headers["Cache-Control"] = f"public, max-age={int(cache_ttl_s)}"

        if extra_headers:
            headers.update(dict(extra_headers))

        # To propagate trace IDs via headers or envelope meta, this is where
        # to add them (e.g., headers["X-Trace-Id"] = trace_id) depending
        # on BasePresenter conventions.
        return PresentResult(body=envelope, headers=headers)
