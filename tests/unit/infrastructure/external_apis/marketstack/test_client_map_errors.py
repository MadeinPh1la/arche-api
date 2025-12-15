from __future__ import annotations

import pytest

from arche_api.domain.exceptions.market_data import (
    MarketDataBadRequest,
    MarketDataQuotaExceeded,
    MarketDataRateLimited,
    MarketDataUnavailable,
)
from arche_api.infrastructure.external_apis.marketstack.client import (
    MarketstackClient,
)


def test_map_errors_rate_limited() -> None:
    with pytest.raises(MarketDataRateLimited):
        MarketstackClient._map_errors(429)


def test_map_errors_quota() -> None:
    with pytest.raises(MarketDataQuotaExceeded):
        MarketstackClient._map_errors(402)


def test_map_errors_bad_request_400() -> None:
    with pytest.raises(MarketDataBadRequest):
        MarketstackClient._map_errors(400)


def test_map_errors_bad_request_422() -> None:
    with pytest.raises(MarketDataBadRequest):
        MarketstackClient._map_errors(422)


def test_map_errors_unavailable_500() -> None:
    with pytest.raises(MarketDataUnavailable):
        MarketstackClient._map_errors(500)
