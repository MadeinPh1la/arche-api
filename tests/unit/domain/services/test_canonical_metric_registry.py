# tests/unit/domain/test_canonical_metric_registry.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Tests for the canonical metric registry."""

from __future__ import annotations

from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.enums.edgar import StatementType
from arche_api.domain.services import canonical_metric_registry as reg


def test_all_enum_members_have_registry_entries() -> None:
    """Every CanonicalStatementMetric must be present in the registry.

    If new enum members are added, they must be explicitly registered.
    """
    registered = {m.metric for m in reg.iter_metric_metadata()}
    all_enum = set(CanonicalStatementMetric)

    assert registered == all_enum, (
        f"Registry mismatch: missing={all_enum - registered}, " f"extra={registered - all_enum}"
    )


def test_no_duplicate_metric_codes() -> None:
    """Registry must not contain duplicate metric codes."""
    codes = [m.metric.value for m in reg.iter_metric_metadata()]
    assert len(codes) == len(set(codes)), "Duplicate metric codes detected in registry"


def test_statement_types_are_from_allowed_set() -> None:
    """All registry entries must use a known statement_type."""
    allowed = {"IS", "BS", "CF"}
    for meta in reg.iter_metric_metadata():
        assert meta.statement_type in allowed, (
            f"Unexpected statement_type {meta.statement_type!r} " f"for {meta.metric}"
        )


def test_categories_are_from_allowed_set() -> None:
    """All registry entries must use a known category."""
    allowed = {
        "REVENUE",
        "EXPENSE",
        "PROFITABILITY",
        "ASSETS",
        "LIABILITIES",
        "EQUITY",
        "CASH_FLOW",
        "CAPITAL_STRUCTURE",
        "PER_SHARE",
        "SHARES",
        "OTHER",
    }
    for meta in reg.iter_metric_metadata():
        assert meta.category in allowed, f"Unexpected category {meta.category!r} for {meta.metric}"


def test_tier1_pinned_is_subset_of_registry_and_non_empty() -> None:
    """Tier-1 pinned metrics must be non-empty and subset of registry."""
    tier1 = set(reg.TIER1_METRICS_PINNED)
    registered = {m.metric for m in reg.iter_metric_metadata()}

    assert tier1, "Tier-1 pinned set must not be empty"
    assert tier1 <= registered, "Tier-1 metrics must all exist in the registry"


def test_tier1_matches_primary_flag() -> None:
    """Tier-1 pinning should align with is_primary flags."""
    tier1 = set(reg.TIER1_METRICS_PINNED)
    primary_from_flags = {meta.metric for meta in reg.iter_metric_metadata() if meta.is_primary}

    # We allow primary metrics that are not pinned (future expansion),
    # but pinned Tier-1 metrics must always be primary.
    assert tier1 <= primary_from_flags, "All pinned Tier-1 metrics must be marked is_primary=True"


def test_get_metric_metadata_roundtrip() -> None:
    """get_metric_metadata returns metadata for all registry metrics."""
    for meta in reg.iter_metric_metadata():
        roundtrip = reg.get_metric_metadata(meta.metric)
        assert roundtrip is meta or roundtrip == meta


def test_tier1_for_statement_type_is_subset_of_global_pin() -> None:
    """Per-statement-type Tier-1 helper must return subset of global pinned set."""
    pinned = set(reg.TIER1_METRICS_PINNED)

    for statement_type in StatementType:
        subset = set(reg.get_tier1_metrics_for_statement_type(statement_type))
        assert subset <= pinned
