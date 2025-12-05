# tests/unit/domain/services/test_gaap_taxonomy.py
# Copyright (c)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import date

import pytest

from stacklion_api.domain.entities.xbrl_document import (
    XBRLContext,
    XBRLDimension,
    XBRLFact,
    XBRLPeriod,
    XBRLUnit,
)
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.exceptions.edgar import EdgarMappingError
from stacklion_api.domain.services.gaap_taxonomy import (
    GAAPTaxonomy,
    build_minimal_gaap_taxonomy,
)


def _build_dummy_fact_and_context(
    concept_qname: str,
    *,
    is_instant: bool,
) -> tuple[XBRLFact, XBRLContext, XBRLUnit]:
    period = XBRLPeriod(
        is_instant=is_instant,
        instant_date=date(2024, 12, 31) if is_instant else None,
        start_date=None if is_instant else date(2024, 1, 1),
        end_date=None if is_instant else date(2024, 12, 31),
    )
    ctx = XBRLContext(
        id="C1",
        entity_identifier="0000123456",
        period=period,
        dimensions=(XBRLDimension(dimension_qname="d1", member_qname="m1"),),
    )
    fact = XBRLFact(
        id="f1",
        concept_qname=concept_qname,
        context_ref="C1",
        unit_ref="U1",
        raw_value="100",
        decimals=0,
        precision=None,
        is_nil=False,
        footnote_refs=(),
    )
    unit = XBRLUnit(id="U1", measure="iso4217:USD")
    return fact, ctx, unit


def test_build_minimal_gaap_taxonomy_contains_core_concepts() -> None:
    taxonomy = build_minimal_gaap_taxonomy()

    revenues = taxonomy.get("us-gaap:Revenues")
    assert revenues is not None
    assert revenues.canonical_metric == CanonicalStatementMetric.REVENUE
    assert revenues.period_type == "duration"


def test_validate_fact_allows_unknown_concept() -> None:
    taxonomy = GAAPTaxonomy(concepts={})
    fact, ctx, unit = _build_dummy_fact_and_context("us-gaap:UnknownFooBar", is_instant=False)

    # Should not raise: concept not in taxonomy → no enforcement in E10-A.
    taxonomy.validate_fact(fact=fact, context=ctx, unit=unit)


def test_validate_fact_instant_period_mismatch_raises() -> None:
    taxonomy = build_minimal_gaap_taxonomy()
    # Revenues is duration; we give it an instant context.
    fact, ctx, unit = _build_dummy_fact_and_context("us-gaap:Revenues", is_instant=True)

    with pytest.raises(EdgarMappingError):
        taxonomy.validate_fact(fact=fact, context=ctx, unit=unit)


def test_validate_fact_duration_period_mismatch_raises() -> None:
    # Create a concept that requires instant, then give duration context.
    from stacklion_api.domain.services.gaap_taxonomy import GAAPConcept

    concept = GAAPConcept(
        concept_qname="us-gaap:Assets",
        canonical_metric=CanonicalStatementMetric.TOTAL_ASSETS,
        period_type="instant",
        default_unit_suffix="USD",
        allowed_dimensions=(),
    )
    taxonomy = GAAPTaxonomy(concepts={"us-gaap:Assets": concept})

    fact, ctx, unit = _build_dummy_fact_and_context("us-gaap:Assets", is_instant=False)

    with pytest.raises(EdgarMappingError):
        taxonomy.validate_fact(fact=fact, context=ctx, unit=unit)


def test_validate_fact_unit_suffix_mismatch_raises() -> None:
    taxonomy = build_minimal_gaap_taxonomy()
    fact, ctx, _ = _build_dummy_fact_and_context("us-gaap:Revenues", is_instant=False)
    bad_unit = XBRLUnit(id="U1", measure="shares")

    with pytest.raises(EdgarMappingError):
        taxonomy.validate_fact(fact=fact, context=ctx, unit=bad_unit)
