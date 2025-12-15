# tests/unit/domain/services/test_edgar_normalization_overrides.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Override-aware normalization tests for CanonicalStatementNormalizer.

Covers:
    - Remapping a base-mapped metric via a GLOBAL override rule.
    - Suppressing a base-mapped metric via a COMPANY override rule.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from arche_api.domain.entities.edgar_statement_version import (
    AccountingStandard,
)
from arche_api.domain.enums.canonical_statement_metric import (
    CanonicalStatementMetric,
)
from arche_api.domain.enums.edgar import FiscalPeriod, StatementType
from arche_api.domain.services.edgar_normalization import (
    CanonicalStatementNormalizer,
    EdgarFact,
    NormalizationContext,
)
from arche_api.domain.services.xbrl_mapping_overrides import (
    MappingOverrideRule,
    OverrideScope,
)


def _make_fact(value: Decimal = Decimal("100.0")) -> EdgarFact:
    """Return a simple EdgarFact for us-gaap:Revenues."""
    return EdgarFact(
        fact_id="f1",
        concept="us-gaap:Revenues",
        value=value,
        unit="USD",
        decimals=None,
        period_start=None,
        period_end=date(2024, 12, 31),
        instant_date=None,
        dimensions={},
    )


def _make_context(
    *,
    facts: list[EdgarFact],
    override_rules: tuple[MappingOverrideRule, ...],
) -> NormalizationContext:
    """Build a minimal NormalizationContext for testing overrides."""
    return NormalizationContext(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        accession_id="0000123456-24-000001",
        taxonomy="US_GAAP_MIN_E10A",
        version_sequence=1,
        facts=tuple(facts),
        override_rules=override_rules,
        enable_override_trace=False,
    )


def _make_global_remap_rule() -> MappingOverrideRule:
    """GLOBAL rule: Revenues → NET_INCOME."""
    return MappingOverrideRule(
        rule_id="rule-global-remap",
        scope=OverrideScope.GLOBAL,
        source_concept="us-gaap:Revenues",
        source_taxonomy="US_GAAP_MIN_E10A",
        match_cik=None,
        match_industry_code=None,
        match_analyst_id=None,
        match_dimensions={},
        target_metric=CanonicalStatementMetric.NET_INCOME,
        is_suppression=False,
        priority=10,
    )


def _make_company_suppression_rule() -> MappingOverrideRule:
    """COMPANY rule: suppress Revenues for specific CIK."""
    return MappingOverrideRule(
        rule_id="rule-company-suppress",
        scope=OverrideScope.COMPANY,
        source_concept="us-gaap:Revenues",
        source_taxonomy="US_GAAP_MIN_E10A",
        match_cik="0000123456",
        match_industry_code=None,
        match_analyst_id=None,
        match_dimensions={},
        target_metric=None,
        is_suppression=True,
        priority=10,
    )


def test_global_override_remaps_metric_in_payload() -> None:
    """GLOBAL override rules should remap the base metric in the payload."""
    normalizer = CanonicalStatementNormalizer()
    fact = _make_fact()

    # No overrides: baseline behavior.
    ctx_no_override = _make_context(facts=[fact], override_rules=())
    result_no_override = normalizer.normalize(ctx_no_override)
    payload_no_override = result_no_override.payload

    # Sanity: base mapping should produce REVENUE.
    assert CanonicalStatementMetric.REVENUE in payload_no_override.core_metrics

    # Now apply a GLOBAL override that remaps Revenues → NET_INCOME.
    remap_rule = _make_global_remap_rule()
    ctx_with_override = _make_context(facts=[fact], override_rules=(remap_rule,))
    result_with_override = normalizer.normalize(ctx_with_override)
    payload_with_override = result_with_override.payload

    # REVENUE should no longer appear; metric should be NET_INCOME instead.
    assert CanonicalStatementMetric.REVENUE not in payload_with_override.core_metrics
    assert CanonicalStatementMetric.NET_INCOME in payload_with_override.core_metrics

    # The numeric value should have been preserved under the new metric key.
    assert (
        payload_with_override.core_metrics[CanonicalStatementMetric.NET_INCOME]
        == payload_no_override.core_metrics[CanonicalStatementMetric.REVENUE]
    )


def test_company_suppression_rule_drops_fact_from_payload() -> None:
    """COMPANY suppression rules should prevent facts from entering the payload."""
    normalizer = CanonicalStatementNormalizer()
    fact = _make_fact()

    # Baseline: fact contributes to payload as REVENUE.
    ctx_no_override = _make_context(facts=[fact], override_rules=())
    result_no_override = normalizer.normalize(ctx_no_override)
    payload_no_override = result_no_override.payload
    assert CanonicalStatementMetric.REVENUE in payload_no_override.core_metrics

    # Apply COMPANY suppression rule for this CIK.
    suppression_rule = _make_company_suppression_rule()
    ctx_with_suppression = _make_context(
        facts=[fact],
        override_rules=(suppression_rule,),
    )
    result_with_suppression = normalizer.normalize(ctx_with_suppression)
    payload_with_suppression = result_with_suppression.payload

    # REVENUE should be completely absent.
    assert CanonicalStatementMetric.REVENUE not in payload_with_suppression.core_metrics
    # No other metric should have appeared spuriously; for this test the
    # payload should be empty.
    assert payload_with_suppression.core_metrics == {}
    assert payload_with_suppression.extra_metrics == {}
