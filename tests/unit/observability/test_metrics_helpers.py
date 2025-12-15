import pytest

from arche_api.infrastructure.observability import metrics_market_data as m


def test_inc_market_data_error_labels():
    # ensure label path registers
    m.inc_market_data_error("validation", "/v1/quotes/historical")
    # scrape happens in other tests; just ensure no exception on label use


def test_observe_upstream_request_success_and_error():
    # success
    with m.observe_upstream_request(provider="marketstack", endpoint="eod", interval="1d") as obs:
        obs.status = "success"
    # error path auto-sets status="error"
    with (
        m.observe_upstream_request(provider="marketstack", endpoint="intraday", interval="1m"),
        pytest.raises(RuntimeError),
    ):
        raise RuntimeError("boom")
