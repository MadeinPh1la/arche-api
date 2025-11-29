from datetime import date

from stacklion_api.adapters.presenters.edgar_presenter import EdgarPresenter
from stacklion_api.application.schemas.dto.edgar_derived import (
    EdgarDerivedMetricsPointDTO,
)
from stacklion_api.domain.enums.derived_metric import DerivedMetric
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    StatementType,
)


def _make_point(
    *,
    cik: str,
    statement_date: date,
    fiscal_year: int,
    fiscal_period: FiscalPeriod,
    version_seq: int,
    gross_margin: str,
) -> EdgarDerivedMetricsPointDTO:
    """Helper to build a minimal derived metrics DTO for tests."""
    return EdgarDerivedMetricsPointDTO(
        cik=cik,
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=statement_date,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        currency="USD",
        metrics={DerivedMetric.GROSS_MARGIN: gross_margin},
        normalized_payload_version_sequence=version_seq,
    )


def test_present_derived_metrics_timeseries_sorts_and_maps() -> None:
    """Presenter should sort points deterministically and preserve core fields."""
    presenter = EdgarPresenter()

    # Intentionally out of order to test sorting.
    dto_late = _make_point(
        cik="0000000002",
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        version_seq=2,
        gross_margin="0.350000",
    )
    dto_early = _make_point(
        cik="0000000001",
        statement_date=date(2023, 12, 31),
        fiscal_year=2023,
        fiscal_period=FiscalPeriod.FY,
        version_seq=1,
        gross_margin="0.400000",
    )

    result = presenter.present_derived_timeseries(
        dtos=[dto_late, dto_early],
        ciks=["0000000001", "0000000002"],
        statement_type=StatementType.INCOME_STATEMENT,
        frequency="annual",
        from_date=date(2023, 1, 1),
        to_date=date(2024, 12, 31),
        trace_id="trace-123",
    )

    envelope = result.body
    assert envelope is not None

    # CIK universe should be normalized and sorted.
    assert envelope.data.ciks == ["0000000001", "0000000002"]

    # Metadata should be preserved.
    assert envelope.data.statement_type == StatementType.INCOME_STATEMENT
    assert envelope.data.frequency == "annual"
    assert envelope.data.from_date == date(2023, 1, 1)
    assert envelope.data.to_date == date(2024, 12, 31)

    # Points should be sorted deterministically.
    points = envelope.data.points
    assert [p.cik for p in points] == ["0000000001", "0000000002"]
    assert [p.statement_date for p in points] == [
        date(2023, 12, 31),
        date(2024, 12, 31),
    ]

    # Metrics should be exposed as string-keyed mapping.
    assert points[0].metrics == {"GROSS_MARGIN": "0.400000"}
    assert points[1].metrics == {"GROSS_MARGIN": "0.350000"}
