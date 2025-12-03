# tests/unit/adapters/repositories/test_edgar_facts_repository_mapping.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Unit tests for EDGAR normalized facts repository mapping helpers.

Scope:
    - Exercise the static helpers on EdgarFactsRepository:
        * _to_row_dict
        * _map_to_domain

Notes:
    - These tests avoid any real DB or AsyncSession and instead operate purely
      on the mapping logic to drive adapter coverage.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from stacklion_api.adapters.repositories.edgar_facts_repository import EdgarFactsRepository
from stacklion_api.domain.entities.edgar_normalized_fact import EdgarNormalizedFact
from stacklion_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType


@dataclass
class _DummyFactRow:
    fact_id: UUID
    statement_version_id: UUID
    company_id: UUID
    cik: str
    statement_type: str
    accounting_standard: str
    fiscal_year: int
    fiscal_period: str
    statement_date: date
    version_sequence: int
    metric_code: str
    metric_label: str | None
    unit: str
    period_start: date | None
    period_end: date
    value: Any
    dimension_key: str
    dimension: Mapping[str, Any] | None
    source_line_item: str | None


def test_to_row_dict_roundtrip_core_fields() -> None:
    """_to_row_dict should serialize a domain fact into a row dict correctly."""
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

    statement_version_id = uuid4()
    company_id = uuid4()

    row_dict = EdgarFactsRepository._to_row_dict(
        fact=fact,
        statement_version_id=statement_version_id,
        company_id=company_id,
    )

    # Basic shape and identity fields
    assert row_dict["statement_version_id"] == statement_version_id
    assert row_dict["company_id"] == company_id
    assert row_dict["cik"] == "0000123456"
    assert row_dict["statement_type"] == StatementType.INCOME_STATEMENT.value
    assert row_dict["accounting_standard"] == AccountingStandard.US_GAAP.value
    assert row_dict["fiscal_year"] == 2024
    assert row_dict["fiscal_period"] == FiscalPeriod.Q1.value
    assert row_dict["statement_date"] == date(2024, 3, 31)
    assert row_dict["version_sequence"] == 2

    # Metric + value fields
    assert row_dict["metric_code"] == "REVENUE"
    assert row_dict["metric_label"] == "Revenue"
    assert row_dict["unit"] == "USD"
    assert row_dict["period_start"] == date(2024, 1, 1)
    assert row_dict["period_end"] == date(2024, 3, 31)
    assert row_dict["value"] == Decimal("123456.78")
    assert row_dict["dimension_key"] == "segment=US|currency=USD"
    assert row_dict["dimension"] == {"segment": "US", "currency": "USD"}
    assert row_dict["source_line_item"] == "Net sales"


def test_map_to_domain_roundtrip_with_dimensions() -> None:
    """_map_to_domain should reconstruct a domain fact from a row-like object."""
    dimensions_raw: Mapping[str, Any] = {"segment": "EMEA", "currency": "EUR"}

    row = _DummyFactRow(
        fact_id=uuid4(),
        statement_version_id=uuid4(),
        company_id=uuid4(),
        cik="0000987654",
        statement_type=StatementType.BALANCE_SHEET.value,
        accounting_standard=AccountingStandard.US_GAAP.value,
        fiscal_year=2022,
        fiscal_period=FiscalPeriod.FY.value,
        statement_date=date(2022, 12, 31),
        version_sequence=1,
        metric_code="TOTAL_ASSETS",
        metric_label="Total assets",
        unit="USD",
        period_start=None,
        period_end=date(2022, 12, 31),
        value=Decimal("9999999.01"),
        dimension_key="segment=EMEA|currency=EUR",
        dimension=dimensions_raw,
        source_line_item="Total assets",
    )

    fact = EdgarFactsRepository._map_to_domain(row=row, cik="0000987654")

    assert isinstance(fact, EdgarNormalizedFact)
    assert fact.cik == "0000987654"
    assert fact.statement_type is StatementType.BALANCE_SHEET
    assert fact.accounting_standard is AccountingStandard.US_GAAP
    assert fact.fiscal_year == 2022
    assert fact.fiscal_period is FiscalPeriod.FY
    assert fact.statement_date == date(2022, 12, 31)
    assert fact.version_sequence == 1

    assert fact.metric_code == "TOTAL_ASSETS"
    assert fact.metric_label == "Total assets"
    assert fact.unit == "USD"
    assert fact.period_start is None
    assert fact.period_end == date(2022, 12, 31)

    # value should be coerced to Decimal, even if the row stored a different numeric type
    assert isinstance(fact.value, Decimal)
    assert fact.value == Decimal("9999999.01")

    # dimensions should be normalized to str -> str
    assert fact.dimensions == {"segment": "EMEA", "currency": "EUR"}
    assert fact.dimension_key == "segment=EMEA|currency=EUR"
    assert fact.source_line_item == "Total assets"


def test_map_to_domain_handles_missing_dimensions() -> None:
    """_map_to_domain should treat null dimension JSON as an empty mapping."""
    row = _DummyFactRow(
        fact_id=uuid4(),
        statement_version_id=uuid4(),
        company_id=uuid4(),
        cik="0000123456",
        statement_type=StatementType.CASH_FLOW_STATEMENT.value,
        accounting_standard=AccountingStandard.US_GAAP.value,
        fiscal_year=2021,
        fiscal_period=FiscalPeriod.Q3.value,
        statement_date=date(2021, 9, 30),
        version_sequence=3,
        metric_code="OPERATING_CASH_FLOW",
        metric_label=None,
        unit="USD",
        period_start=date(2021, 7, 1),
        period_end=date(2021, 9, 30),
        value=Decimal("123.45"),
        dimension_key="default",
        dimension=None,
        source_line_item=None,
    )

    fact = EdgarFactsRepository._map_to_domain(row=row, cik="0000123456")

    assert isinstance(fact, EdgarNormalizedFact)
    assert fact.metric_code == "OPERATING_CASH_FLOW"
    assert fact.metric_label is None
    assert fact.dimensions == {}
    assert fact.dimension_key == "default"
    assert fact.source_line_item is None
