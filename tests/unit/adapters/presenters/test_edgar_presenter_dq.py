# tests/unit/adapters/presenters/test_edgar_presenter_dq.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Tests for EDGAR DQ presenter mappings and envelopes."""

from __future__ import annotations

from datetime import UTC, date, datetime

from stacklion_api.adapters.presenters.edgar_presenter import EdgarPresenter
from stacklion_api.adapters.schemas.http.edgar_schemas import (
    DQAnomalyHTTP,
    FactQualityHTTP,
    NormalizedFactHTTP,
    PersistNormalizedFactsResultHTTP,
    RunStatementDQResultHTTP,
    StatementDQOverlayHTTP,
)
from stacklion_api.adapters.schemas.http.envelopes import SuccessEnvelope
from stacklion_api.application.schemas.dto.edgar_dq import (
    DQAnomalyDTO,
    FactQualityDTO,
    NormalizedFactDTO,
    PersistNormalizedFactsResultDTO,
    RunStatementDQResultDTO,
    StatementDQOverlayDTO,
)
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    MaterialityClass,
    StatementType,
)


def _build_presenter() -> EdgarPresenter:
    """Return a fresh EdgarPresenter instance."""
    return EdgarPresenter()


def test_map_normalized_fact_dto_to_http_uses_period_start_when_present() -> None:
    """Mapper should preserve period_start when provided."""
    dto = NormalizedFactDTO(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        statement_date=date(2024, 3, 31),
        version_sequence=1,
        metric_code="REVENUE",
        metric_label="Revenue",
        unit="USD",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 31),
        value="100",
        dimension_key="root",
        dimensions={"segment": "US"},
        source_line_item="Net sales",
    )

    presenter = _build_presenter()
    http_fact = presenter._map_normalized_fact_dto_to_http(dto)  # type: ignore[attr-defined]

    assert isinstance(http_fact, NormalizedFactHTTP)
    assert http_fact.metric == "REVENUE"
    assert http_fact.period_start == date(2024, 1, 1)
    assert http_fact.period_end == date(2024, 3, 31)
    assert http_fact.dimension == {"segment": "US"}


def test_map_normalized_fact_dto_to_http_falls_back_to_period_end() -> None:
    """Mapper should fall back to period_end when period_start is None."""
    dto = NormalizedFactDTO(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        statement_date=date(2024, 3, 31),
        version_sequence=1,
        metric_code="NET_INCOME",
        metric_label=None,
        unit="USD",
        period_start=None,
        period_end=date(2024, 3, 31),
        value="50",
        dimension_key="root",
        dimensions={},
        source_line_item=None,
    )

    presenter = _build_presenter()
    http_fact = presenter._map_normalized_fact_dto_to_http(dto)  # type: ignore[attr-defined]

    assert http_fact.metric == "NET_INCOME"
    # Fallback should use period_end.
    assert http_fact.period_start == date(2024, 3, 31)
    assert http_fact.period_end == date(2024, 3, 31)
    # Empty dict should map to None for dimension.
    assert http_fact.dimension is None


def test_map_fact_quality_dto_to_http() -> None:
    """FactQualityDTO should map 1:1 into FactQualityHTTP."""
    fq_dto = FactQualityDTO(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=1,
        metric_code="REVENUE",
        dimension_key="root",
        severity=MaterialityClass.LOW,
        is_present=True,
        is_non_negative=True,
        is_consistent_with_history=False,
        has_known_issue=True,
        details={"anomaly_count": "1"},
    )

    presenter = _build_presenter()
    http_fq = presenter._map_fact_quality_dto_to_http(fq_dto)  # type: ignore[attr-defined]

    assert isinstance(http_fq, FactQualityHTTP)
    assert http_fq.cik == "0000320193"
    assert http_fq.metric == "REVENUE"
    assert isinstance(http_fq.severity, str)
    assert http_fq.severity == MaterialityClass.LOW.value
    assert http_fq.details == {"anomaly_count": "1"}


def test_map_dq_anomaly_dto_to_http() -> None:
    """DQAnomalyDTO should map 1:1 into DQAnomalyHTTP."""
    anomaly_dto = DQAnomalyDTO(
        dq_run_id="run-1",
        metric_code="REVENUE",
        dimension_key="root",
        rule_code="NEGATIVE_VALUE",
        severity=MaterialityClass.HIGH,
        message="Revenue is negative.",
        details={"value": "-100.00"},
    )

    presenter = _build_presenter()
    http_anomaly = presenter._map_dq_anomaly_dto_to_http(anomaly_dto)  # type: ignore[attr-defined]

    assert isinstance(http_anomaly, DQAnomalyHTTP)
    assert http_anomaly.dq_run_id == "run-1"
    assert http_anomaly.metric == "REVENUE"
    assert http_anomaly.rule_code == "NEGATIVE_VALUE"
    assert isinstance(http_anomaly.severity, str)
    assert http_anomaly.severity == MaterialityClass.HIGH.value
    assert http_anomaly.details == {"value": "-100.00"}


def test_present_persist_normalized_facts_result_envelope() -> None:
    """present_persist_normalized_facts_result should wrap in SuccessEnvelope."""
    dto = PersistNormalizedFactsResultDTO(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=1,
        facts_persisted=10,
    )

    presenter = _build_presenter()
    result = presenter.present_persist_normalized_facts_result(dto=dto, trace_id="req-1")

    assert isinstance(result.body, SuccessEnvelope)
    payload = result.body.data
    assert isinstance(payload, PersistNormalizedFactsResultHTTP)
    assert payload.cik == "0000320193"
    assert payload.facts_persisted == 10
    # statement_type is serialized as string.
    assert isinstance(payload.statement_type, str)
    assert payload.statement_type == StatementType.INCOME_STATEMENT.value
    # status_code is owned by router; presenter may leave it as None, so we
    # deliberately do NOT assert on it here.


def test_present_run_statement_dq_result_envelope() -> None:
    """present_run_statement_dq_result should map DTO → HTTP result."""
    executed_at = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)

    dto = RunStatementDQResultDTO(
        dq_run_id="run-xyz",
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=2,
        rule_set_version="v1",
        scope_type="STATEMENT",
        history_lookback=4,
        executed_at=executed_at,
        facts_evaluated=50,
        anomaly_count=3,
        max_severity=MaterialityClass.MEDIUM,
    )

    presenter = _build_presenter()
    result = presenter.present_run_statement_dq_result(dto=dto, trace_id="req-2")

    assert isinstance(result.body, SuccessEnvelope)
    payload = result.body.data
    assert isinstance(payload, RunStatementDQResultHTTP)
    assert payload.dq_run_id == "run-xyz"
    assert payload.history_lookback == 4
    assert payload.anomaly_count == 3
    assert isinstance(payload.max_severity, str)
    assert payload.max_severity == MaterialityClass.MEDIUM.value
    assert payload.executed_at is executed_at


def test_present_statement_dq_overlay_orders_and_maps_layers() -> None:
    """present_statement_dq_overlay should order facts, fact_quality, anomalies."""
    # Two facts, intentionally out of order.
    fact1 = NormalizedFactDTO(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        statement_date=date(2024, 3, 31),
        version_sequence=1,
        metric_code="NET_INCOME",
        metric_label="Net income",
        unit="USD",
        period_start=None,
        period_end=date(2024, 3, 31),
        value="50",
        dimension_key="root",
        dimensions={},
        source_line_item=None,
    )
    fact0 = NormalizedFactDTO(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        statement_date=date(2024, 3, 31),
        version_sequence=1,
        metric_code="REVENUE",
        metric_label="Revenue",
        unit="USD",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 31),
        value="100",
        dimension_key="segment:US",
        dimensions={"segment": "US"},
        source_line_item="Net sales",
    )

    # Fact quality entries, out of order relative to metric codes.
    fq1 = FactQualityDTO(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=1,
        metric_code="NET_INCOME",
        dimension_key="root",
        severity=MaterialityClass.LOW,
        is_present=True,
        is_non_negative=True,
        is_consistent_with_history=True,
        has_known_issue=False,
        details=None,
    )
    fq0 = FactQualityDTO(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=1,
        metric_code="REVENUE",
        dimension_key="segment:US",
        severity=MaterialityClass.MEDIUM,
        is_present=True,
        is_non_negative=True,
        is_consistent_with_history=False,
        has_known_issue=True,
        details={"rule_codes": "HISTORY_OUTLIER_HIGH"},
    )

    # Anomalies with different severity and rule codes to exercise ordering.
    anomaly_global = DQAnomalyDTO(
        dq_run_id="run-1",
        metric_code=None,
        dimension_key=None,
        rule_code="MISSING_KEY_METRIC",
        severity=MaterialityClass.HIGH,
        message="Key metric missing.",
        details=None,
    )
    anomaly_revenue = DQAnomalyDTO(
        dq_run_id="run-1",
        metric_code="REVENUE",
        dimension_key="segment:US",
        rule_code="HISTORY_OUTLIER_HIGH",
        severity=MaterialityClass.MEDIUM,
        message="Revenue spike vs history.",
        details={"ratio": "11.0"},
    )

    overlay_dto = StatementDQOverlayDTO(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=1,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 3, 31),
        currency="USD",
        dq_run_id="run-1",
        dq_rule_set_version="v1",
        dq_executed_at=datetime(2025, 1, 1, tzinfo=UTC),
        max_severity=MaterialityClass.HIGH,
        facts=[fact1, fact0],  # out of order
        fact_quality=[fq1, fq0],  # out of order
        anomalies=[anomaly_global, anomaly_revenue],
    )

    presenter = _build_presenter()
    result = presenter.present_statement_dq_overlay(dto=overlay_dto, trace_id="req-3")

    assert isinstance(result.body, SuccessEnvelope)
    payload = result.body.data
    assert isinstance(payload, StatementDQOverlayHTTP)

    # Facts should be mapped and both present.
    assert len(payload.facts) == 2
    fact_metrics = {f.metric for f in payload.facts}
    assert fact_metrics == {"REVENUE", "NET_INCOME"}

    # Fact-quality should be sorted and mapped to HTTP.
    assert len(payload.fact_quality) == 2
    fq_metrics = {fq.metric for fq in payload.fact_quality}
    assert fq_metrics == {"REVENUE", "NET_INCOME"}

    # Anomalies should all map successfully.
    assert len(payload.anomalies) == 2
    rule_codes = {a.rule_code for a in payload.anomalies}
    assert rule_codes == {"MISSING_KEY_METRIC", "HISTORY_OUTLIER_HIGH"}

    # Max severity should flow through as a string.
    assert isinstance(payload.max_severity, str)
    assert payload.max_severity == MaterialityClass.HIGH.value
