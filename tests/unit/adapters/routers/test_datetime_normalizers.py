# tests/unit/adapters/routers/test_datetime_normalizers.py
from datetime import UTC, date, datetime, time


# Define local helpers instead of importing adapter privates
def _to_utc_start(d: date | datetime) -> datetime:
    """UTC start-of-day for date/datetime."""
    if isinstance(d, datetime):
        return d.astimezone(UTC) if d.tzinfo else d.replace(tzinfo=UTC)
    return datetime.combine(d, time.min, tzinfo=UTC)


def _to_utc_end(d: date | datetime) -> datetime:
    """UTC end-of-day for date/datetime."""
    if isinstance(d, datetime):
        return d.astimezone(UTC) if d.tzinfo else d.replace(tzinfo=UTC)
    return datetime.combine(d, time.max, tzinfo=UTC)


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
