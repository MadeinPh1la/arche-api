# tests/unit/adapters/schemas/http/test_edgar_dq_http_schemas.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Tests for EDGAR DQ HTTP schemas.

These tests are intentionally lightweight: the goal is to ensure that the
Pydantic models for fact-level DQ and statement overlays can be instantiated,
validate types correctly, and perform basic serialization.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from arche_api.adapters.schemas.http.edgar_schemas import (
    DQAnomalyHTTP,
    FactQualityHTTP,
    NormalizedFactHTTP,
    PersistNormalizedFactsResultHTTP,
    RunStatementDQResultHTTP,
    StatementDQOverlayHTTP,
)
from arche_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    MaterialityClass,
    StatementType,
)


def test_normalized_fact_http_basic_instantiation() -> None:
    """NormalizedFactHTTP should accept a minimal, valid payload."""
    fact = NormalizedFactHTTP(
        metric="REVENUE",
        label="Revenue",
        unit="USD",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 31),
        value="123.45",
        dimension={"segment": "US"},
        source_line_item="Net sales",
    )

    assert fact.metric == "REVENUE"
    assert fact.unit == "USD"
    assert fact.period_start == date(2024, 1, 1)
    assert fact.period_end == date(2024, 3, 31)
    assert fact.dimension == {"segment": "US"}


def test_fact_quality_http_roundtrip() -> None:
    """FactQualityHTTP should preserve core fields and details."""
    fq = FactQualityHTTP(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=1,
        metric="REVENUE",
        dimension_key="segment:US",
        severity=MaterialityClass.MEDIUM,
        is_present=True,
        is_non_negative=True,
        is_consistent_with_history=False,
        has_known_issue=True,
        details={"rule_codes": "NEGATIVE_VALUE"},
    )

    assert fq.cik == "0000320193"
    assert fq.metric == "REVENUE"
    # HTTP schema uses string values for enums on the wire.
    assert isinstance(fq.severity, str)
    assert fq.severity == MaterialityClass.MEDIUM.value
    assert fq.details == {"rule_codes": "NEGATIVE_VALUE"}


def test_dq_anomaly_http_roundtrip() -> None:
    """DQAnomalyHTTP should capture anomaly metadata and details."""
    anomaly = DQAnomalyHTTP(
        dq_run_id="run-1",
        metric="REVENUE",
        dimension_key="segment:US",
        rule_code="NEGATIVE_VALUE",
        severity=MaterialityClass.HIGH,
        message="Revenue is unexpectedly negative.",
        details={"value": "-100.00"},
    )

    assert anomaly.dq_run_id == "run-1"
    assert anomaly.metric == "REVENUE"
    assert anomaly.rule_code == "NEGATIVE_VALUE"
    assert isinstance(anomaly.severity, str)
    assert anomaly.severity == MaterialityClass.HIGH.value
    assert anomaly.details == {"value": "-100.00"}


def test_persist_normalized_facts_result_http() -> None:
    """PersistNormalizedFactsResultHTTP should expose persisted count."""
    result = PersistNormalizedFactsResultHTTP(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=2,
        facts_persisted=42,
    )

    assert result.facts_persisted == 42
    # statement_type is serialized as a string on the wire.
    assert isinstance(result.statement_type, str)
    assert result.statement_type == StatementType.INCOME_STATEMENT.value


def test_run_statement_dq_result_http() -> None:
    """RunStatementDQResultHTTP should capture run metadata and summary."""
    now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)

    result = RunStatementDQResultHTTP(
        dq_run_id="run-123",
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=3,
        rule_set_version="v1",
        scope_type="STATEMENT",
        history_lookback=4,
        executed_at=now,
        facts_evaluated=100,
        anomaly_count=5,
        max_severity=MaterialityClass.MEDIUM,
    )

    assert result.dq_run_id == "run-123"
    assert result.history_lookback == 4
    assert result.anomaly_count == 5
    assert isinstance(result.max_severity, str)
    assert result.max_severity == MaterialityClass.MEDIUM.value


def test_statement_dq_overlay_http_basic_shape() -> None:
    """StatementDQOverlayHTTP should compose statement metadata + DQ layers."""
    fact = NormalizedFactHTTP(
        metric="REVENUE",
        label="Revenue",
        unit="USD",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 31),
        value="100",
        dimension=None,
        source_line_item=None,
    )
    fq = FactQualityHTTP(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=1,
        metric="REVENUE",
        dimension_key="root",
        severity=MaterialityClass.LOW,
        is_present=True,
        is_non_negative=True,
        is_consistent_with_history=True,
        has_known_issue=False,
        details=None,
    )
    anomaly = DQAnomalyHTTP(
        dq_run_id="run-1",
        metric="REVENUE",
        dimension_key="root",
        rule_code="NEGATIVE_VALUE",
        severity=MaterialityClass.LOW,
        message="Test anomaly.",
        details=None,
    )

    overlay = StatementDQOverlayHTTP(
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
        max_severity=MaterialityClass.LOW,
        facts=[fact],
        fact_quality=[fq],
        anomalies=[anomaly],
    )

    assert overlay.cik == "0000320193"
    assert overlay.currency == "USD"
    assert overlay.dq_run_id == "run-1"
    assert isinstance(overlay.max_severity, str)
    assert overlay.max_severity == MaterialityClass.LOW.value
    assert len(overlay.facts) == 1
    assert len(overlay.fact_quality) == 1
    assert len(overlay.anomalies) == 1
