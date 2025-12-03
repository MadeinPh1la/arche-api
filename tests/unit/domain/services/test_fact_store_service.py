# tests/unit/domain/services/test_fact_store_service.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Unit tests for fact_store_service."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from stacklion_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from stacklion_api.domain.entities.edgar_normalized_fact import EdgarNormalizedFact
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType
from stacklion_api.domain.services.fact_store_service import (
    FactDerivationConfig,
    _infer_period_start,
    build_dimension_key,
    payload_to_facts,
)


def _make_payload(
    *,
    statement_type: StatementType = StatementType.INCOME_STATEMENT,
    fiscal_year: int = 2024,
    fiscal_period: FiscalPeriod = FiscalPeriod.Q1,
    core_metrics: dict[CanonicalStatementMetric, Decimal] | None = None,
    extra_metrics: dict[str, Decimal] | None = None,
) -> CanonicalStatementPayload:
    """Helper to construct a minimal canonical payload that matches the service expectations."""
    return CanonicalStatementPayload(
        cik="0000123456",
        statement_type=statement_type,
        accounting_standard="US_GAAP",
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        statement_date=date(2024, 3, 31),
        currency="USD",
        unit_multiplier=Decimal("1"),
        source_accession_id="0000123456-24-000001",
        source_taxonomy="us-gaap-2024",
        source_version_sequence=1,
        dimensions={},
        core_metrics=core_metrics
        or {
            CanonicalStatementMetric.REVENUE: Decimal("100"),
        },
        extra_metrics=extra_metrics or {},
    )


# --------------------------------------------------------------------------- #
# build_dimension_key                                                        #
# --------------------------------------------------------------------------- #


def test_build_dimension_key_default_and_sorted() -> None:
    """build_dimension_key should normalize None/empty and sort keys."""
    assert build_dimension_key(None) == "default"
    assert build_dimension_key({}) == "default"

    key = build_dimension_key({"b": "2", "a": "1"})
    # Sorted by key, joined with |
    assert key == "a=1|b=2"


def test_build_dimension_key_coerces_non_string_values() -> None:
    """build_dimension_key should stringify non-string keys/values deterministically."""
    key = build_dimension_key({"year": 2024, "segment": 1})
    # Sorted by key
    assert key == "segment=1|year=2024"


# --------------------------------------------------------------------------- #
# _infer_period_start                                                        #
# --------------------------------------------------------------------------- #


def test_infer_period_start_none_strategy_returns_none() -> None:
    """_infer_period_start('none') must be a no-op."""
    ps = _infer_period_start(
        statement_date=date(2024, 3, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        strategy="none",
    )
    assert ps is None


def test_infer_period_start_fiscal_year_start_for_fy_and_quarters() -> None:
    """_infer_period_start('fiscal_year_start') should map FY and quarters to naive boundaries."""
    fy_start = _infer_period_start(
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        strategy="fiscal_year_start",
    )
    assert fy_start == date(2024, 1, 1)

    q1_start = _infer_period_start(
        statement_date=date(2024, 3, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        strategy="fiscal_year_start",
    )
    assert q1_start == date(2024, 1, 1)

    q4_start = _infer_period_start(
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q4,
        strategy="fiscal_year_start",
    )
    assert q4_start == date(2024, 10, 1)


def test_infer_period_start_unknown_strategy_fails_closed() -> None:
    """Unknown strategy should return None and not guess."""
    ps = _infer_period_start(
        statement_date=date(2024, 3, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        strategy="totally_unknown",
    )
    assert ps is None


# --------------------------------------------------------------------------- #
# payload_to_facts                                                           #
# --------------------------------------------------------------------------- #


def test_payload_to_facts_basic_core_only_default_config() -> None:
    """payload_to_facts should emit facts for core metrics, no extras, no period_start."""
    payload = _make_payload(extra_metrics={})
    facts = payload_to_facts(payload, version_sequence=1)

    assert len(facts) == 1
    fact = facts[0]
    assert isinstance(fact, EdgarNormalizedFact)
    assert fact.metric_code == CanonicalStatementMetric.REVENUE.value
    assert fact.value == Decimal("100")
    assert fact.period_start is None
    assert fact.period_end == payload.statement_date
    assert fact.dimension_key == "default"


def test_payload_to_facts_includes_extra_metrics_and_period_start() -> None:
    """Custom config should include extra_metrics and infer period_start."""
    payload = _make_payload(
        fiscal_period=FiscalPeriod.Q2,
        core_metrics={CanonicalStatementMetric.REVENUE: Decimal("200")},
        extra_metrics={"CUSTOM_METRIC": Decimal("300")},
    )
    cfg = FactDerivationConfig(
        default_period_start_strategy="fiscal_year_start",
        include_extra_metrics=True,
    )

    facts = payload_to_facts(payload, version_sequence=2, config=cfg)

    # One core + one extra
    codes = {f.metric_code for f in facts}
    assert codes == {CanonicalStatementMetric.REVENUE.value, "CUSTOM_METRIC"}

    for f in facts:
        assert f.period_start == date(payload.fiscal_year, 4, 1)  # Q2 start
        assert f.period_end == payload.statement_date
        assert f.unit == payload.currency
        assert f.version_sequence == 2


def test_payload_to_facts_respects_include_extra_metrics_false() -> None:
    """When include_extra_metrics is False, only core metrics should produce facts."""
    payload = _make_payload(
        core_metrics={CanonicalStatementMetric.REVENUE: Decimal("200")},
        extra_metrics={"CUSTOM_METRIC": Decimal("300")},
    )
    cfg = FactDerivationConfig(
        default_period_start_strategy="none",
        include_extra_metrics=False,
    )

    facts = payload_to_facts(payload, version_sequence=3, config=cfg)

    assert {f.metric_code for f in facts} == {CanonicalStatementMetric.REVENUE.value}


def test_payload_to_facts_negative_fiscal_year_raises() -> None:
    """Negative fiscal_year should cause a ValueError before fact derivation."""
    with pytest.raises(ValueError):
        payload = _make_payload(fiscal_year=-1)
        payload_to_facts(payload, version_sequence=1)
