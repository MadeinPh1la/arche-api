# tests/unit/domain/entities/test_edgar_normalized_fact.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Unit tests for EDGAR normalized fact entity."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from arche_api.domain.entities.edgar_normalized_fact import EdgarNormalizedFact
from arche_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType


def test_edgar_normalized_fact_basic_construction() -> None:
    """EdgarNormalizedFact should round-trip core attributes correctly."""
    dimensions: Mapping[str, str] = {"segment": "US", "currency": "USD"}

    fact = EdgarNormalizedFact(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        statement_date=date(2024, 3, 31),
        version_sequence=2,
        metric_code="REVENUE",
        metric_label="Revenue",
        unit="USD",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 31),
        value=Decimal("123456.78"),
        dimensions=dimensions,
        dimension_key="segment=US|currency=USD",
        source_line_item="Net sales",
    )

    assert fact.cik == "0000123456"
    assert fact.statement_type is StatementType.INCOME_STATEMENT
    assert fact.accounting_standard is AccountingStandard.US_GAAP
    assert fact.fiscal_year == 2024
    assert fact.fiscal_period is FiscalPeriod.Q1
    assert fact.statement_date == date(2024, 3, 31)
    assert fact.version_sequence == 2

    assert fact.metric_code == "REVENUE"
    assert fact.metric_label == "Revenue"
    assert fact.unit == "USD"

    assert fact.period_start == date(2024, 1, 1)
    assert fact.period_end == date(2024, 3, 31)

    assert isinstance(fact.value, Decimal)
    assert fact.value == Decimal("123456.78")

    assert fact.dimensions == dimensions
    assert fact.dimension_key == "segment=US|currency=USD"
    assert fact.source_line_item == "Net sales"


def test_edgar_normalized_fact_allows_missing_period_start_and_label() -> None:
    """EdgarNormalizedFact should allow nullable fields where expected."""
    fact = EdgarNormalizedFact(
        cik="0000123456",
        statement_type=StatementType.BALANCE_SHEET,
        accounting_standard=AccountingStandard.US_GAAP,
        fiscal_year=2023,
        fiscal_period=FiscalPeriod.FY,
        statement_date=date(2023, 12, 31),
        version_sequence=1,
        metric_code="TOTAL_ASSETS",
        metric_label=None,
        unit="USD",
        period_start=None,
        period_end=date(2023, 12, 31),
        value=Decimal("9999999"),
        dimensions={},
        dimension_key="default",
        source_line_item=None,
    )

    assert fact.metric_label is None
    assert fact.period_start is None
    assert fact.source_line_item is None
    assert fact.dimensions == {}
    assert fact.dimension_key == "default"


def test_edgar_normalized_fact_is_frozen() -> None:
    """EdgarNormalizedFact instances should be immutable."""
    fact = EdgarNormalizedFact(
        cik="0000123456",
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
        value=Decimal("42"),
        dimensions={},
        dimension_key="default",
        source_line_item=None,
    )

    with pytest.raises(FrozenInstanceError):
        fact.value = Decimal("0")  # type: ignore[assignment]
