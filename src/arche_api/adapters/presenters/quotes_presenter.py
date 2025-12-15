# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Presenter: Latest Quotes → HTTP SuccessEnvelope.

Synopsis:
    Renders application-layer Quote DTOs into the canonical SuccessEnvelope,
    attaching optional strong ETags and optional Cache-Control headers.
    All serialization flows through BaseHTTPSchema → canonical JSON contracts.

Layer:
    adapters/presenters
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from arche_api.adapters.presenters.base_presenter import PresentResult
from arche_api.adapters.schemas.http.envelopes import SuccessEnvelope
from arche_api.adapters.schemas.http.quotes import QuoteItem, QuotesBatch
from arche_api.application.schemas.dto.quotes import QuotesBatchDTO


class QuotesPresenter:
    """Presenter for `/v1/quotes` (latest quotes)."""

    def _compute_etag(self, body: Mapping[str, Any]) -> str:
        """Strong ETag from canonical JSON (sorted, compact, safe)."""
        material = json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f'"{hashlib.sha256(material).hexdigest()}"'

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
        """Build a SuccessEnvelope[QuotesBatch] with optional caching headers.

        Args:
            dto: Application DTO.
            trace_id: Correlation id for envelope + X-Request-ID header.
            enable_caching: Whether to emit ETag (and max-age).
            cache_ttl_s: Cache-Control TTL in seconds.
            etag_seed: Stable seed for deterministic ETags; fallback is body hash.
            extra_headers: Additional headers to attach.

        Returns:
            PresentResult containing envelope + headers.
        """
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
        if trace_id:
            headers["X-Request-ID"] = trace_id

        if enable_caching:
            if etag_seed is not None:
                material = etag_seed.encode()
            else:
                material = json.dumps(
                    envelope.model_dump_http(),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()

            headers["ETag"] = f'"{hashlib.sha256(material).hexdigest()}"'

            if cache_ttl_s is not None:
                headers["Cache-Control"] = f"public, max-age={int(cache_ttl_s)}"

        if extra_headers:
            headers.update(dict(extra_headers))

        return PresentResult(body=envelope, headers=headers)
