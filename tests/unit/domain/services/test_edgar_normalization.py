# tests/unit/domain/services/test_edgar_normalization.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Unit tests for the EDGAR canonical statement normalization engine.

Covers:
    - NormalizationContext validation invariants.
    - Happy-path normalization for a minimal income statement.
    - Deterministic selection of facts based on currency and date.
    - Decimal parsing and quantization rules.
    - Missing metrics generating warnings instead of hard failures.
"""

from __future__ import annotations

from datetime import date

import pytest

from stacklion_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from stacklion_api.domain.enums.canonical_statement_metric import (
    CanonicalStatementMetric,
)
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    StatementType,
)
from stacklion_api.domain.exceptions.edgar import EdgarMappingError
from stacklion_api.domain.services.edgar_normalization import (
    NORMALIZED_PAYLOAD_VERSION,
    CanonicalStatementNormalizer,
    EdgarFact,
    EdgarNormalizationError,
    NormalizationContext,
)


def _make_basic_context(facts: list[EdgarFact]) -> NormalizationContext:
    """Construct a minimal valid NormalizationContext for tests."""
    return NormalizationContext(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 9, 28),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        accession_id="0000320193-24-000010",
        taxonomy="US_GAAP_2024",
        version_sequence=1,
        facts=facts,
    )


def test_normalization_context_validation_rejects_invalid_inputs() -> None:
    """Invalid context fields should trigger EdgarNormalizationError."""
    facts: list[EdgarFact] = []
    normalizer = CanonicalStatementNormalizer()

    # Empty CIK.
    context = NormalizationContext(
        cik="  ",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 9, 28),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        accession_id="0000320193-24-000010",
        taxonomy="US_GAAP_2024",
        version_sequence=1,
        facts=facts,
    )
    with pytest.raises(EdgarNormalizationError):
        normalizer.normalize(context)

    # Invalid fiscal year.
    context = NormalizationContext(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 9, 28),
        fiscal_year=0,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        accession_id="0000320193-24-000010",
        taxonomy="US_GAAP_2024",
        version_sequence=1,
        facts=facts,
    )
    with pytest.raises(EdgarNormalizationError):
        normalizer.normalize(context)

    # Empty taxonomy.
    context = NormalizationContext(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 9, 28),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        accession_id="0000320193-24-000010",
        taxonomy=" ",
        version_sequence=1,
        facts=facts,
    )
    with pytest.raises(EdgarNormalizationError):
        normalizer.normalize(context)


def test_normalizer_produces_canonical_payload_for_simple_income_statement() -> None:
    """Happy-path: REVENUE and NET_INCOME map to canonical metrics."""
    facts = [
        EdgarFact(
            fact_id="f1",
            concept="us-gaap:Revenues",
            value="1000",
            unit="USD",
            decimals=0,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 9, 28),
            instant_date=None,
            dimensions={},
        ),
        EdgarFact(
            fact_id="f2",
            concept="us-gaap:NetIncomeLoss",
            value="200",
            unit="USD",
            decimals=0,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 9, 28),
            instant_date=None,
            dimensions={},
        ),
    ]
    context = _make_basic_context(facts=facts)
    normalizer = CanonicalStatementNormalizer()
    result = normalizer.normalize(context)

    assert result.payload_version == NORMALIZED_PAYLOAD_VERSION
    assert isinstance(result.payload, CanonicalStatementPayload)

    payload = result.payload
    assert payload.cik == "0000320193"
    assert payload.statement_type == StatementType.INCOME_STATEMENT
    assert payload.accounting_standard == AccountingStandard.US_GAAP
    assert payload.currency == "USD"
    assert payload.unit_multiplier == 0

    # Core metrics mapped.
    assert payload.core_metrics[CanonicalStatementMetric.REVENUE] == 1000
    assert payload.core_metrics[CanonicalStatementMetric.NET_INCOME] == 200


def test_normalizer_prefers_facts_with_matching_currency_and_latest_date() -> None:
    """When multiple facts exist, the normalizer deterministically picks one."""
    facts = [
        # Older USD revenue.
        EdgarFact(
            fact_id="f1",
            concept="us-gaap:Revenues",
            value="900",
            unit="USD",
            decimals=0,
            period_start=date(2023, 1, 1),
            period_end=date(2023, 12, 31),
            instant_date=None,
            dimensions={},
        ),
        # Newer USD revenue.
        EdgarFact(
            fact_id="f2",
            concept="us-gaap:Revenues",
            value="1100",
            unit="USD",
            decimals=0,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 9, 28),
            instant_date=None,
            dimensions={},
        ),
        # EUR revenue should be ignored in favor of reporting currency USD.
        EdgarFact(
            fact_id="f3",
            concept="us-gaap:Revenues",
            value="9999",
            unit="EUR",
            decimals=0,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 9, 28),
            instant_date=None,
            dimensions={},
        ),
    ]
    context = _make_basic_context(facts=facts)
    normalizer = CanonicalStatementNormalizer()
    result = normalizer.normalize(context)

    payload = result.payload
    revenue = payload.core_metrics[CanonicalStatementMetric.REVENUE]
    assert revenue == 1100  # Newest USD fact wins.

    record = result.metric_records[CanonicalStatementMetric.REVENUE]
    assert record.value == revenue
    assert record.unit == "USD"
    assert record.source_fact_ids == ("f2",)


def test_normalizer_generates_warning_for_missing_metric_in_registry() -> None:
    """If a registry metric has no candidate facts, it is omitted with a warning."""
    facts = [
        EdgarFact(
            fact_id="f1",
            concept="us-gaap:Revenues",
            value="1000",
            unit="USD",
            decimals=0,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 9, 28),
            instant_date=None,
            dimensions={},
        ),
    ]
    context = _make_basic_context(facts=facts)
    normalizer = CanonicalStatementNormalizer()
    result = normalizer.normalize(context)

    payload = result.payload

    # Revenue present; NET_INCOME not mapped because no candidate facts.
    assert CanonicalStatementMetric.REVENUE in payload.core_metrics
    assert CanonicalStatementMetric.NET_INCOME not in payload.core_metrics

    # At least one warning mentioning NET_INCOME.
    joined = " ".join(result.warnings)
    assert "NET_INCOME" in joined


def test_normalizer_raises_on_unparseable_numeric_value() -> None:
    """Unparseable numeric values surface as EdgarNormalizationError."""
    facts = [
        EdgarFact(
            fact_id="bad",
            concept="us-gaap:Revenues",
            value="not-a-number",
            unit="USD",
            decimals=0,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 9, 28),
            instant_date=None,
            dimensions={},
        ),
    ]
    context = _make_basic_context(facts=facts)
    normalizer = CanonicalStatementNormalizer()

    # EdgarNormalizationError is a subclass of EdgarMappingError.
    with pytest.raises(EdgarMappingError):
        normalizer.normalize(context)


def test_decimal_quantization_respects_decimals_hint_when_non_negative() -> None:
    """Decimals >= 0 cause deterministic quantization."""
    facts = [
        EdgarFact(
            fact_id="f1",
            concept="us-gaap:Revenues",
            value="123.456",
            unit="USD",
            decimals=2,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 9, 28),
            instant_date=None,
            dimensions={},
        ),
    ]
    context = _make_basic_context(facts=facts)
    normalizer = CanonicalStatementNormalizer()
    result = normalizer.normalize(context)

    value = result.payload.core_metrics[CanonicalStatementMetric.REVENUE]
    # Quantized to 2 decimal places.
    assert str(value) == "123.46"
