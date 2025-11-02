from datetime import UTC, date, datetime, time

from stacklion_api.adapters.routers.historical_quotes_router import _to_utc_end, _to_utc_start


def test_to_utc_start_from_date_and_datetime():
    d = date(2025, 1, 2)
    out = _to_utc_start(d)
    assert out.tzinfo is UTC
    assert out.time() == time.min

    # naive datetime should be treated as UTC
    naive = datetime(2025, 1, 2, 12, 0, 0)
    out2 = _to_utc_start(naive)
    assert out2.tzinfo is UTC
    assert out2.hour == 12


def test_to_utc_end_from_date_and_datetime():
    d = date(2025, 1, 2)
    out = _to_utc_end(d)
    assert out.tzinfo is UTC
    assert out.time() == time.max

    aware = datetime(2025, 1, 2, 7, 30, tzinfo=UTC)
    out2 = _to_utc_end(aware)
    assert out2.tzinfo is UTC
    assert out2.hour == 7 and out2.minute == 30
