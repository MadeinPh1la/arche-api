from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from arche_api.application.use_cases.quotes.get_quotes import GetQuotes
from arche_api.domain.entities.quote import Quote
from arche_api.domain.interfaces.gateways.market_data_gateway import MarketDataGatewayProtocol


class FakeGateway(MarketDataGatewayProtocol):
    async def get_latest_quotes(self, tickers: Sequence[str]) -> list[Quote]:
        now = datetime.now(tz=UTC)
        return [
            Quote(ticker=t, price=Decimal("123.45"), currency="USD", as_of=now) for t in tickers
        ]


@pytest.mark.asyncio
async def test_maps_entities_to_dtos() -> None:
    uc = GetQuotes(gateway=FakeGateway())
    dto = await uc.execute(["AAPL", "MSFT"])
    assert [i.ticker for i in dto.items] == ["AAPL", "MSFT"]
    assert all(str(i.price) == "123.45" for i in dto.items)
