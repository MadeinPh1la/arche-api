# tests/unit/adapters/presenters/test_edgar_dq_presenter.py

from datetime import date, datetime
from uuid import uuid4

from stacklion_api.adapters.presenters.edgar_dq_presenter import (
    present_run_statement_dq,
    present_statement_dq_overlay,
)
from stacklion_api.adapters.schemas.http.edgar_dq_schemas import (
    DQAnomalyHTTP,
    FactQualityHTTP,
    NormalizedFactHTTP,
    RunStatementDQResultHTTP,
    StatementDQOverlayHTTP,
)
from stacklion_api.application.schemas.dto.edgar_dq import (
    DQAnomalyDTO,
    FactQualityDTO,
    NormalizedFactDTO,
    RunStatementDQResultDTO,
    StatementDQOverlayDTO,
)
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    MaterialityClass,
    StatementType,
)


def _make_normalized_fact(metric_code: str, dimension_key: str) -> NormalizedFactDTO:
    """Helper to build a minimal-but-valid NormalizedFactDTO."""
    return NormalizedFactDTO(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        statement_date=date(2024, 12, 31),
        version_sequence=1,
        metric_code=metric_code,
        metric_label=None,
        unit="USD",
        period_start=None,
        period_end=date(2024, 12, 31),
        value="123.45",
        dimension_key=dimension_key,
        dimensions={},
        source_line_item=None,
    )


def test_present_run_statement_dq_envelope_shape() -> None:
    """Presenter should map RunStatementDQResultDTO → HTTP envelope cleanly."""
    now = datetime(2025, 1, 1, 12, 0, 0)
    dq_run_uuid = uuid4()

    dto = RunStatementDQResultDTO(
        dq_run_id=str(dq_run_uuid),
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        version_sequence=1,
        rule_set_version="v1",
        scope_type="STATEMENT_ONLY",
        history_lookback=4,
        executed_at=now,
        facts_evaluated=10,
        anomaly_count=2,
        max_severity=MaterialityClass.MEDIUM,
    )

    envelope = present_run_statement_dq(dto)
    assert isinstance(envelope.data, RunStatementDQResultHTTP)

    data = envelope.data

    # Identity / metadata
    assert data.cik == "0000123456"
    assert str(data.dq_run_id) == str(dq_run_uuid)

    # Severity + counts
    assert data.max_severity == MaterialityClass.MEDIUM
    assert data.anomaly_count == 2
    assert data.facts_evaluated == 10

    dumped = data.model_dump()
    assert "unknown_field" not in dumped


def test_present_statement_dq_overlay_fact_sorting_and_shape() -> None:
    """Presenter should sort facts deterministically and project all components."""
    fact_b = _make_normalized_fact("EBIT", "seg:2")
    fact_a = _make_normalized_fact("REVENUE", "seg:1")

    dq_run_uuid = uuid4()

    fq = FactQualityDTO(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        version_sequence=1,
        metric_code=fact_a.metric_code,
        dimension_key=fact_a.dimension_key,
        severity=MaterialityClass.LOW,
        is_present=True,
        is_non_negative=True,
        is_consistent_with_history=None,
        has_known_issue=False,
        details={"key": "value"},
    )

    anomaly = DQAnomalyDTO(
        dq_run_id=str(dq_run_uuid),
        metric_code=fact_b.metric_code,
        dimension_key=fact_b.dimension_key,
        rule_code="NON_NEGATIVE",
        severity=MaterialityClass.MEDIUM,
        message="Negative value",
        details={"metric": fact_b.metric_code},
    )

    overlay_dto = StatementDQOverlayDTO(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        version_sequence=1,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 12, 31),
        currency="USD",
        dq_run_id=str(dq_run_uuid),
        dq_rule_set_version="v1",
        dq_executed_at=datetime(2025, 1, 1, 12, 0, 0),
        max_severity=MaterialityClass.MEDIUM,
        facts=[fact_b, fact_a],  # intentionally unsorted
        fact_quality=[fq],
        anomalies=[anomaly],
    )

    envelope = present_statement_dq_overlay(overlay_dto)
    assert isinstance(envelope.data, StatementDQOverlayHTTP)

    data = envelope.data

    assert data.cik == "0000123456"
    assert str(data.dq_run_id) == str(dq_run_uuid)
    assert data.max_severity == MaterialityClass.MEDIUM

    # Facts should be sorted by (metric_code, dimension_key)
    assert [f.metric_code for f in data.facts] == ["EBIT", "REVENUE"]

    assert isinstance(data.facts[0], NormalizedFactHTTP)
    assert isinstance(data.fact_quality[0], FactQualityHTTP)
    assert isinstance(data.anomalies[0], DQAnomalyHTTP)

    dumped = data.model_dump()
    assert "unknown_field" not in dumped
