# tests/unit/domain/services/test_edgar_normalization_overrides_integration.py
# SPDX-License-Identifier: MIT
"""Integration tests for EDGAR normalization with XBRL mapping overrides.

These tests verify that:
    * Override rules influence the canonical payload produced by
      CanonicalStatementNormalizer.
    * Remapping and suppression semantics are reflected in core_metrics.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from arche_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType
from arche_api.domain.services.edgar_normalization import (
    CanonicalStatementNormalizer,
    EdgarFact,
    NormalizationContext,
)
from arche_api.domain.services.xbrl_mapping_overrides import (
    MappingOverrideRule,
    OverrideScope,
)


def _make_fact(concept: str, value: str, currency: str = "USD") -> EdgarFact:
    """Build a minimal EdgarFact for tests."""
    return EdgarFact(
        fact_id=f"{concept}-ctx1",
        concept=concept,
        value=value,
        unit=currency,
        decimals=0,
        period_start=None,
        period_end=date(2024, 12, 31),
        instant_date=None,
        dimensions={"consolidation": "CONSOLIDATED"},
    )


def _base_context(
    *,
    facts: list[EdgarFact],
    override_rules: list[MappingOverrideRule] | None = None,
) -> NormalizationContext:
    """Construct a minimal NormalizationContext for overrides tests."""
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
        facts=facts,
        industry_code="4510",
        analyst_profile_id="profile-1",
        override_rules=tuple(override_rules or ()),
        enable_override_trace=False,
    )


def test_override_remaps_metric_in_canonical_payload() -> None:
    """A COMPANY-scope override remaps REVENUE to NET_INCOME in the payload."""
    # Registry maps REVENUE from "us-gaap:Revenues".
    fact = _make_fact("us-gaap:Revenues", "1000")

    rule = MappingOverrideRule(
        rule_id="r-remap",
        scope=OverrideScope.COMPANY,
        source_concept="us-gaap:Revenues",
        source_taxonomy="US_GAAP_MIN_E10A",
        match_cik="0000123456",
        match_industry_code=None,
        match_analyst_id=None,
        match_dimensions={"consolidation": "CONSOLIDATED"},
        target_metric=CanonicalStatementMetric.NET_INCOME,
        is_suppression=False,
        priority=10,
    )

    context = _base_context(facts=[fact], override_rules=[rule])
    normalizer = CanonicalStatementNormalizer()
    result = normalizer.normalize(context)

    payload: CanonicalStatementPayload = result.payload

    # REVENUE should not appear; NET_INCOME should hold the 1000 value.
    assert CanonicalStatementMetric.REVENUE not in payload.core_metrics
    assert payload.core_metrics[CanonicalStatementMetric.NET_INCOME] == Decimal("1000")


def test_override_suppresses_metric_from_canonical_payload() -> None:
    """A suppression rule removes the metric entirely from core_metrics."""
    fact = _make_fact("us-gaap:Revenues", "500")

    suppression_rule = MappingOverrideRule(
        rule_id="r-suppress",
        scope=OverrideScope.GLOBAL,
        source_concept="us-gaap:Revenues",
        source_taxonomy="US_GAAP_MIN_E10A",
        match_cik=None,
        match_industry_code=None,
        match_analyst_id=None,
        match_dimensions={"consolidation": "CONSOLIDATED"},
        target_metric=None,
        is_suppression=True,
        priority=0,
    )

    context = _base_context(facts=[fact], override_rules=[suppression_rule])
    normalizer = CanonicalStatementNormalizer()
    result = normalizer.normalize(context)

    payload: CanonicalStatementPayload = result.payload

    # Revenue metric is fully suppressed.
    assert CanonicalStatementMetric.REVENUE not in payload.core_metrics
    # Sanity: no other metrics should be present for this simple context.
    assert payload.core_metrics == {}
