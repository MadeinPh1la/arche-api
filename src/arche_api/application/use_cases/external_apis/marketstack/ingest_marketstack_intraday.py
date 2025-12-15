# src/arche_api/application/use_cases/external_apis/marketstack/ingest_marketstack_intraday.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: Ingest Marketstack intraday bars into partitioned storage.

Idempotent at the (source, endpoint, key) granularity and stores raw payloads
for deterministic replay. Depends on the ingest-oriented MarketDataGateway
(port) and repositories for staging and market-data persistence.

Layer:
    application/use_cases/external_apis
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from arche_api.application.interfaces.market_data_gateway import MarketDataGateway


@dataclass(frozen=True)
class IngestIntradayRequest:
    """Request parameters for intraday ingest.

    Attributes:
        symbol_id: UUID of the internal symbol.
        ticker: External ticker string (case-insensitive).
        window_from: Inclusive start (UTC).
        window_to: Exclusive end (UTC).
        interval: Provider interval label (e.g., "1min", "5min").
    """

    symbol_id: UUID
    ticker: str
    window_from: datetime
    window_to: datetime
    interval: str = "1min"


class IngestMarketstackIntradayBars:
    """Ingest Marketstack intraday bars for a bounded UTC window.

    The use case:

    * Ensures idempotency via the staging ingest key.
    * Persists the raw provider payload into staging for replay/debuggability.
    * Normalizes intraday bars into `IntradayBarRow` records and upserts
      them into partitioned market-data tables.
    """

    def __init__(self, gateway: MarketDataGateway) -> None:
        """Initialize the use case.

        Args:
            gateway: Market data gateway implementation (ingest port).
        """
        self._gateway = gateway

    async def __call__(self, session: AsyncSession, req: IngestIntradayRequest) -> int:
        """Execute the ingest.

        Args:
            session: Database session.
            req: Ingest parameters.

        Returns:
            Number of rows persisted (inserted or updated).
        """
        staging_module = import_module("arche_api.adapters.repositories.staging_repository")
        StagingRepository = staging_module.StagingRepository
        IngestKey = staging_module.IngestKey

        md_module = import_module("arche_api.adapters.repositories.market_data_repository")
        MarketDataRepository = md_module.MarketDataRepository
        IntradayBarRow = md_module.IntradayBarRow

        staging = StagingRepository(session)
        md_repo = MarketDataRepository(session)

        key = IngestKey(
            source="marketstack",
            endpoint="intraday",
            key=(
                f"{req.ticker}:"
                f"{req.window_from.isoformat()}-{req.window_to.isoformat()}:"
                f"{req.interval}"
            ),
        )
        run_id = await staging.start_run(key)

        try:
            bars, meta = await self._gateway.fetch_intraday_bars(
                symbol=req.ticker,
                start=req.window_from,
                end=req.window_to,
                interval=req.interval,
                page_size=1000,
            )

            # Normalize provider bars and metadata into plain dicts.
            bars_normalized: list[dict[str, Any]] = [_bar_to_dict(b) for b in bars]
            meta_normalized: dict[str, Any] = dict(meta)

            # Persist raw payload for deterministic replay/debuggability.
            await staging.save_raw_payload(
                source="marketstack",
                endpoint="intraday",
                symbol_or_cik=req.ticker,
                etag=meta_normalized.get("etag"),
                payload={"data": bars_normalized},
                window_from=req.window_from,
                window_to=req.window_to,
            )

            # Map normalized bars into IntradayBarRow objects.
            rows = [
                IntradayBarRow(
                    symbol_id=req.symbol_id,
                    ts=_normalize_ts(b["ts"]),
                    open=b["open"],
                    high=b["high"],
                    low=b["low"],
                    close=b["close"],
                    volume=b["volume"],
                )
                for b in bars_normalized
            ]

            n = int(await md_repo.upsert_intraday_bars(rows))
            await staging.finish_run(run_id, result="SUCCESS")
            await session.commit()
            return n
        except Exception as exc:  # pragma: no cover
            await staging.finish_run(run_id, result="ERROR", error_reason=type(exc).__name__)
            await session.rollback()
            raise


def _bar_to_dict(bar: Any) -> dict[str, Any]:
    """Normalize a provider bar into a simple dict.

    Supports both dict-like payloads (tests) and record-like objects with
    attributes (real gateway types).
    """
    if isinstance(bar, dict):
        # Copy to avoid mutating provider-owned structures.
        return dict(bar)

    # Fallback: attribute-based record (e.g., dataclass with ts/open/high/low/close/volume).
    return {
        "ts": bar.ts,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
    }


def _normalize_ts(value: Any) -> datetime:
    """Normalize a provider timestamp into an aware UTC datetime."""
    if isinstance(value, datetime):
        return value.astimezone(UTC)

    if isinstance(value, str):
        # Accept both "....Z" and ISO-with-offset formats.
        iso = value.replace("Z", "+00:00")
        return datetime.fromisoformat(iso).astimezone(UTC)

    raise TypeError(f"Unsupported ts type for intraday bar: {type(value)!r}")
