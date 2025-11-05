# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Unit tests for HistoricalQuotesController."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stacklion_api.adapters.controllers.historical_quotes_controller import (
    HistoricalQuotesController,
)
from stacklion_api.application.schemas.dto.quotes import HistoricalBarDTO, HistoricalQueryDTO
from stacklion_api.domain.entities.historical_bar import BarInterval


class _FakeUC:
    """Async UC double that records the last call and returns a valid DTO list."""

    def __init__(self) -> None:
        self.last_query: HistoricalQueryDTO | None = None
        self.last_if_none_match: str | None = None

    async def execute(
        self, query: HistoricalQueryDTO, *, if_none_match: str | None
    ) -> tuple[list[HistoricalBarDTO], int, str]:
        self.last_query = query
        self.last_if_none_match = if_none_match

        # Your HistoricalBarDTO expects a single 'timestamp' (not starts_at/ends_at).
        items = [
            HistoricalBarDTO(
                ticker="MSFT",
                open="100.00",
                high="110.00",
                low="99.50",
                close="108.00",
                volume=12345,
                timestamp=datetime(2025, 1, 1, 14, 30, tzinfo=UTC),
                interval=query.interval,  # echo the requested interval
            )
        ]
        total = 1
        etag = '"abc123"'
        return items, total, etag


@pytest.mark.anyio
async def test_controller_list_builds_dto_and_delegates() -> None:
    uc = _FakeUC()
    controller = HistoricalQuotesController(uc)

    # Don’t guess enum member names; pick any available one.
    any_interval = next(iter(BarInterval))

    items, total, etag = await controller.list(
        tickers=("msft", "aapl"),
        from_=datetime(2025, 1, 1, tzinfo=UTC),
        to=datetime(2025, 1, 2, tzinfo=UTC),
        interval=any_interval,
        page=2,
        page_size=50,
        if_none_match='"pre-etag"',
    )

    # Passthrough from UC
    assert isinstance(items, list) and isinstance(items[0], HistoricalBarDTO)
    assert total == 1
    assert etag == '"abc123"'
    assert items[0].timestamp == datetime(2025, 1, 1, 14, 30, tzinfo=UTC)
    assert items[0].interval == any_interval

    # UC call captured correctly
    assert isinstance(uc.last_query, HistoricalQueryDTO)
    assert uc.last_if_none_match == '"pre-etag"'

    # DTO constructed correctly by controller
    assert uc.last_query.tickers == ["msft", "aapl"]
    assert uc.last_query.from_ == datetime(2025, 1, 1, tzinfo=UTC)
    assert uc.last_query.to == datetime(2025, 1, 2, tzinfo=UTC)
    assert uc.last_query.interval == any_interval
    assert uc.last_query.page == 2
    assert uc.last_query.page_size == 50
