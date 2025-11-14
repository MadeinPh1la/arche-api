# Copyright (c)
# SPDX-License-Identifier: MIT
"""Stacklion CLI: operational commands (ingest, partitions, replay).

Commands:
    ingest intraday        Ingest intraday bars using Marketstack (real client).
    partitions create      Pre-create forward monthly partitions.
    replay staging-to-md   Reprocess raw payloads from staging into md.

Environment:
    DATABASE_URL                           Async SQLAlchemy URL.
    MARKETSTACK_BASE_URL                   e.g., https://api.marketstack.com/v2
    MARKETSTACK_ACCESS_KEY                 Your API key.
    MARKETSTACK_ALLOWED_INTRADAY_INTERVALS e.g., "1h,30min,15min"
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

import typer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from stacklion_api.application.use_cases.external_apis.ingest_marketstack_intraday import (
    IngestIntradayRequest,
    IngestMarketstackIntradayBars,
)
from stacklion_api.application.use_cases.maintenance.replay_staging_to_md import (
    ReplayRequest,
    ReplayStagingToMd,
)
from stacklion_api.domain.exceptions.market_data import MarketDataBadRequest
from stacklion_api.infrastructure.database.maintenance.partitions import (
    create_forward_partitions,
)
from stacklion_api.infrastructure.external_apis.marketstack.client import MarketstackClient
from stacklion_api.infrastructure.external_apis.marketstack.settings import MarketstackSettings
from stacklion_api.infrastructure.logging.logger import configure_root_logging, get_json_logger
from stacklion_api.infrastructure.resilience.retry import RetryPolicy

configure_root_logging()
log = get_json_logger(__name__)

app = typer.Typer(add_completion=False, no_args_is_help=True)
ingest_app = typer.Typer(no_args_is_help=True)
partitions_app = typer.Typer(no_args_is_help=True)
replay_app = typer.Typer(no_args_is_help=True)
app.add_typer(ingest_app, name="ingest")
app.add_typer(partitions_app, name="partitions")
app.add_typer(replay_app, name="replay")


def _sessionmaker(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to the given database URL.

    Args:
        database_url: Async SQLAlchemy URL.

    Returns:
        A configured ``async_sessionmaker`` for ``AsyncSession`` instances.
    """
    engine = create_async_engine(database_url, future=True)
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _ms_settings_from_env() -> MarketstackSettings:
    """Build Marketstack settings from environment variables.

    Returns:
        MarketstackSettings: Settings object populated from env vars.

    Notes:
        We do NOT rely on pydantic BaseSettings here; this explicitly reads
        env vars to avoid surprises. Expected envs:
          - MARKETSTACK_BASE_URL (defaults to v2)
          - MARKETSTACK_ACCESS_KEY (required)
          - MARKETSTACK_ALLOWED_INTRADAY_INTERVALS (comma-separated, optional)
          - MARKETSTACK_TIMEOUT_S (optional)
          - MARKETSTACK_MAX_RETRIES (optional)
    """
    from pydantic import SecretStr

    base_url = os.getenv("MARKETSTACK_BASE_URL", "https://api.marketstack.com/v2")

    access_key = os.getenv("MARKETSTACK_ACCESS_KEY")
    if not access_key:
        raise RuntimeError("MARKETSTACK_ACCESS_KEY is not set")

    # Comma-separated allow-list (robust to spaces & case)
    raw_allowed = os.getenv("MARKETSTACK_ALLOWED_INTRADAY_INTERVALS", "1h")
    allowed_list = [s.strip().lower() for s in raw_allowed.split(",") if s.strip()]

    # Optional overrides
    timeout_s = float(os.getenv("MARKETSTACK_TIMEOUT_S", "8.0"))
    max_retries = int(os.getenv("MARKETSTACK_MAX_RETRIES", "4"))

    return MarketstackSettings(
        base_url=base_url,
        access_key=SecretStr(access_key),
        timeout_s=timeout_s,
        max_retries=max_retries,
        allowed_intraday_intervals=allowed_list,
    )


@ingest_app.command("intraday")
def ingest_intraday(
    database_url: str = typer.Option(
        ..., envvar="DATABASE_URL", help="Async SQLAlchemy URL."
    ),  # noqa: B008
    symbol_id: UUID = typer.Option(..., help="Symbol UUID."),  # noqa: B008
    ticker: str = typer.Option(..., help="Ticker (e.g., MSFT)."),  # noqa: B008
    minutes: int = typer.Option(
        5, min=1, help="Lookback window in minutes ending now."
    ),  # noqa: B008
    interval: str = typer.Option(
        "1m", help='Provider interval label (e.g., "1m", "5m", "15min", "1hour").'
    ),  # noqa: B008
) -> None:
    """Ingest a small intraday window for a single ticker using the V2 transport.

    The gateway enforces a configurable allow-list of plan-permitted intervals
    (e.g., ``MARKETSTACK_ALLOWED_INTRADAY_INTERVALS="1h,30min,15min"``). When an
    interval outside the plan is requested, the command fails fast with a
    deterministic, operator-friendly message (no wasted retries).
    """
    Session = _sessionmaker(database_url)
    window_to = datetime.now(UTC)
    window_from = window_to - timedelta(minutes=minutes)
    settings = _ms_settings_from_env()

    async def _run() -> None:
        client = MarketstackClient(
            settings,
            timeout_s=settings.timeout_s,
            retry_policy=RetryPolicy(
                total=settings.max_retries,  # number of retries beyond first attempt
                base=0.25,
                cap=2.5,
                jitter=True,
            ),
        )
        async with Session() as session:
            try:
                from stacklion_api.adapters.gateways.marketstack_gateway import (
                    MarketstackGateway,
                )

                gateway = MarketstackGateway(client=client, settings=settings)
                uc = IngestMarketstackIntradayBars(gateway)
                try:
                    n = await uc(
                        session,
                        IngestIntradayRequest(
                            symbol_id=symbol_id,
                            ticker=ticker,
                            window_from=window_from,
                            window_to=window_to,
                            interval=interval,
                        ),
                    )
                except MarketDataBadRequest as exc:
                    # Provide a deterministic operator UX for plan gates.
                    details = getattr(exc, "details", {}) or {}
                    code = details.get("code")
                    if details.get("status") == 403 or code in {
                        "function_access_restricted",
                        "interval_not_allowed_on_plan",
                    }:
                        log.error(
                            "ingest_intraday.forbidden",
                            extra={
                                "extra": {
                                    "ticker": ticker,
                                    "interval": interval,
                                    "details": details,
                                }
                            },
                        )
                        print(
                            "Intraday request not permitted on the current plan. "
                            "Set MARKETSTACK_ALLOWED_INTRADAY_INTERVALS to your allowed set "
                            "(e.g., '1h,30min,15min') or use a less granular interval."
                        )
                        return
                    raise

                log.info(
                    "ingest_intraday.done",
                    extra={
                        "extra": {
                            "ticker": ticker,
                            "rows": n,
                            "interval": interval,
                            "from": window_from.isoformat(),
                            "to": window_to.isoformat(),
                        }
                    },
                )
            finally:
                await client.aclose()

    asyncio.run(_run())


@partitions_app.command("create")
def partitions_create(
    database_url: str = typer.Option(..., envvar="DATABASE_URL"),  # noqa: B008
    months: int = typer.Option(3, min=1, help="How many months ahead to create."),  # noqa: B008
) -> None:
    """Create forward monthly partitions for intraday and EOD parent tables.

    Args:
        database_url: Async SQLAlchemy URL.
        months: Number of future months for which to create partitions.
    """
    Session = _sessionmaker(database_url)

    async def _run() -> None:
        async with Session() as session:
            created = await create_forward_partitions(session, months=months)
            log.info(
                "partitions.created",
                extra={"extra": {"months": months, "tables_created": created}},
            )

    asyncio.run(_run())


@replay_app.command("staging-to-md")
def replay_staging_to_md(
    database_url: str = typer.Option(..., envvar="DATABASE_URL"),  # noqa: B008
    source: str = typer.Option("marketstack"),  # noqa: B008
    endpoint: str = typer.Option("intraday"),  # noqa: B008
    symbol_id: UUID = typer.Option(...),  # noqa: B008
    ticker: str = typer.Option(...),  # noqa: B008
    window_from: datetime | None = typer.Option(None),  # noqa: B008
    window_to: datetime | None = typer.Option(None),  # noqa: B008
) -> None:
    """Replay raw staging payloads into the market data store deterministically.

    Args:
        database_url: Async SQLAlchemy URL.
        source: Staging source key (e.g., "marketstack").
        endpoint: Endpoint key (e.g., "intraday" or "eod").
        symbol_id: Internal symbol UUID.
        ticker: Symbol ticker.
        window_from: Optional start bound for replay.
        window_to: Optional end bound for replay.
    """
    Session = _sessionmaker(database_url)

    async def _run() -> None:
        async with Session() as session:
            uc = ReplayStagingToMd()
            n = await uc(
                session,
                ReplayRequest(
                    source=source,
                    endpoint=endpoint,
                    symbol_id=symbol_id,
                    ticker=ticker,
                    window_from=window_from,
                    window_to=window_to,
                ),
            )
            log.info(
                "replay.done",
                extra={
                    "extra": {
                        "source": source,
                        "endpoint": endpoint,
                        "ticker": ticker,
                        "rows": n,
                    }
                },
            )

    asyncio.run(_run())


# Colon alias for convenience.
@app.command("ingest:intraday")
def ingest_intraday_alias(
    database_url: str = typer.Option(..., envvar="DATABASE_URL"),  # noqa: B008
    symbol_id: UUID = typer.Option(...),  # noqa: B008
    ticker: str = typer.Option(...),  # noqa: B008
    minutes: int = typer.Option(5, min=1),  # noqa: B008
    interval: str = typer.Option("1m"),  # noqa: B008
) -> None:
    """Alias of ``ingest intraday``."""
    ingest_intraday(database_url, symbol_id, ticker, minutes, interval)


if __name__ == "__main__":
    app()
