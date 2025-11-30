# tests/unit/domain/services/test_statement_ledger_delta_engine.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Tests for the statement ledger delta engine.

Scope:
    - Verify that a restatement ledger is built correctly from a sequence
      of statement versions.
    - Verify selection semantics for computing a single restatement delta
      between versions.
    - Ensure error conditions are surfaced via domain exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from stacklion_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError
from stacklion_api.domain.services.statement_ledger_delta_engine import (
    build_restatement_ledger,
    compute_restatement_delta_between_versions,
)


@dataclass
class _FakeStatementVersion:
    """Minimal fake for EdgarStatementVersion used in tests.

    Only the attributes required by the ledger engine are modeled here:
        * version_sequence
        * normalized_payload
    """

    version_sequence: int
    normalized_payload: CanonicalStatementPayload | None


def _make_payload(
    *,
    cik: str = "0000320193",
    statement_type: StatementType = StatementType.INCOME_STATEMENT,
    accounting_standard: AccountingStandard = AccountingStandard.US_GAAP,
    statement_date: date = date(2024, 12, 31),
    fiscal_year: int = 2024,
    fiscal_period: FiscalPeriod = FiscalPeriod.FY,
    currency: str = "USD",
    unit_multiplier: int = 1,
    revenue: Decimal | None = None,
    net_income: Decimal | None = None,
    source_accession_id: str = "0000320193-24-000012",
    source_taxonomy: str = "us-gaap-2024",
    source_version_sequence: int = 1,
) -> CanonicalStatementPayload:
    core_metrics: dict[CanonicalStatementMetric, Decimal] = {}
    if revenue is not None:
        core_metrics[CanonicalStatementMetric.REVENUE] = revenue
    if net_income is not None:
        core_metrics[CanonicalStatementMetric.NET_INCOME] = net_income

    return CanonicalStatementPayload(
        cik=cik,
        statement_type=statement_type,
        accounting_standard=accounting_standard,
        statement_date=statement_date,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        currency=currency,
        unit_multiplier=unit_multiplier,
        core_metrics=core_metrics,
        extra_metrics={},
        dimensions={},
        source_accession_id=source_accession_id,
        source_taxonomy=source_taxonomy,
        source_version_sequence=source_version_sequence,
    )


def test_build_restatement_ledger_happy_path_adjacent_pairs() -> None:
    """Ledger should compute deltas between each adjacent normalized version."""
    v1 = _FakeStatementVersion(
        version_sequence=1,
        normalized_payload=_make_payload(
            revenue=Decimal("100"),
            source_version_sequence=1,
        ),
    )
    v2 = _FakeStatementVersion(
        version_sequence=2,
        normalized_payload=_make_payload(
            revenue=Decimal("120"),
            source_version_sequence=2,
        ),
    )
    v3 = _FakeStatementVersion(
        version_sequence=3,
        normalized_payload=_make_payload(
            revenue=Decimal("150"),
            source_version_sequence=3,
        ),
    )

    ledger = build_restatement_ledger(versions=[v1, v2, v3])

    assert len(ledger) == 2

    first = ledger[0]
    assert first.from_version_sequence == 1
    assert first.to_version_sequence == 2
    # Only REVENUE should be present and changed by +20.
    assert list(first.metrics.keys()) == [CanonicalStatementMetric.REVENUE]
    delta_first = first.metrics[CanonicalStatementMetric.REVENUE]
    assert delta_first.old == Decimal("100")
    assert delta_first.new == Decimal("120")
    assert delta_first.diff == Decimal("20")

    second = ledger[1]
    assert second.from_version_sequence == 2
    assert second.to_version_sequence == 3
    delta_second = second.metrics[CanonicalStatementMetric.REVENUE]
    assert delta_second.old == Decimal("120")
    assert delta_second.new == Decimal("150")
    assert delta_second.diff == Decimal("30")


def test_build_restatement_ledger_ignores_versions_without_payload() -> None:
    """Versions lacking normalized payloads should be ignored when building the ledger."""
    v1 = _FakeStatementVersion(
        version_sequence=1,
        normalized_payload=None,
    )
    v2 = _FakeStatementVersion(
        version_sequence=2,
        normalized_payload=_make_payload(
            revenue=Decimal("100"),
            source_version_sequence=2,
        ),
    )
    v3 = _FakeStatementVersion(
        version_sequence=3,
        normalized_payload=None,
    )
    v4 = _FakeStatementVersion(
        version_sequence=4,
        normalized_payload=_make_payload(
            revenue=Decimal("130"),
            source_version_sequence=4,
        ),
    )

    ledger = build_restatement_ledger(versions=[v1, v2, v3, v4])

    # Only v2 and v4 participate, yielding a single delta.
    assert len(ledger) == 1
    delta = ledger[0]
    assert delta.from_version_sequence == 2
    assert delta.to_version_sequence == 4
    rev_delta = delta.metrics[CanonicalStatementMetric.REVENUE]
    assert rev_delta.old == Decimal("100")
    assert rev_delta.new == Decimal("130")
    assert rev_delta.diff == Decimal("30")


def test_build_restatement_ledger_returns_empty_when_insufficient_versions() -> None:
    """Ledger should be empty when fewer than two normalized versions exist."""
    v1 = _FakeStatementVersion(
        version_sequence=1,
        normalized_payload=None,
    )
    v2 = _FakeStatementVersion(
        version_sequence=2,
        normalized_payload=_make_payload(
            revenue=Decimal("100"),
            source_version_sequence=2,
        ),
    )

    assert build_restatement_ledger(versions=[]) == []
    assert build_restatement_ledger(versions=[v1]) == []
    assert build_restatement_ledger(versions=[v2]) == []


def test_compute_restatement_delta_between_versions_default_latest_pair() -> None:
    """When no sequences are provided, use the two latest normalized versions."""
    v1 = _FakeStatementVersion(
        version_sequence=1,
        normalized_payload=_make_payload(
            revenue=Decimal("100"),
            source_version_sequence=1,
        ),
    )
    v2 = _FakeStatementVersion(
        version_sequence=2,
        normalized_payload=_make_payload(
            revenue=Decimal("120"),
            source_version_sequence=2,
        ),
    )
    v3 = _FakeStatementVersion(
        version_sequence=3,
        normalized_payload=_make_payload(
            revenue=Decimal("150"),
            source_version_sequence=3,
        ),
    )

    delta = compute_restatement_delta_between_versions(versions=[v1, v2, v3])

    assert delta.from_version_sequence == 2
    assert delta.to_version_sequence == 3
    rev_delta = delta.metrics[CanonicalStatementMetric.REVENUE]
    assert rev_delta.old == Decimal("120")
    assert rev_delta.new == Decimal("150")
    assert rev_delta.diff == Decimal("30")


def test_compute_restatement_delta_between_versions_with_explicit_bounds() -> None:
    """Explicit from/to sequences should select the requested versions."""
    v1 = _FakeStatementVersion(
        version_sequence=10,
        normalized_payload=_make_payload(
            revenue=Decimal("100"),
            source_version_sequence=10,
        ),
    )
    v2 = _FakeStatementVersion(
        version_sequence=20,
        normalized_payload=_make_payload(
            revenue=Decimal("160"),
            source_version_sequence=20,
        ),
    )
    v3 = _FakeStatementVersion(
        version_sequence=30,
        normalized_payload=_make_payload(
            revenue=Decimal("190"),
            source_version_sequence=30,
        ),
    )

    delta = compute_restatement_delta_between_versions(
        versions=[v1, v2, v3],
        from_version_sequence=10,
        to_version_sequence=30,
    )

    assert delta.from_version_sequence == 10
    assert delta.to_version_sequence == 30
    rev_delta = delta.metrics[CanonicalStatementMetric.REVENUE]
    assert rev_delta.old == Decimal("100")
    assert rev_delta.new == Decimal("190")
    assert rev_delta.diff == Decimal("90")


def test_compute_restatement_delta_between_versions_with_only_to_sequence() -> None:
    """When only to_version_sequence is provided, from is the previous normalized version."""
    v1 = _FakeStatementVersion(
        version_sequence=1,
        normalized_payload=_make_payload(
            revenue=Decimal("100"),
            source_version_sequence=1,
        ),
    )
    v2 = _FakeStatementVersion(
        version_sequence=2,
        normalized_payload=_make_payload(
            revenue=Decimal("130"),
            source_version_sequence=2,
        ),
    )

    delta = compute_restatement_delta_between_versions(
        versions=[v1, v2],
        to_version_sequence=2,
    )

    assert delta.from_version_sequence == 1
    assert delta.to_version_sequence == 2
    rev_delta = delta.metrics[CanonicalStatementMetric.REVENUE]
    assert rev_delta.old == Decimal("100")
    assert rev_delta.new == Decimal("130")
    assert rev_delta.diff == Decimal("30")


def test_compute_restatement_delta_between_versions_with_only_from_sequence() -> None:
    """When only from_version_sequence is provided, to is the next normalized version."""
    v1 = _FakeStatementVersion(
        version_sequence=1,
        normalized_payload=_make_payload(
            revenue=Decimal("80"),
            source_version_sequence=1,
        ),
    )
    v2 = _FakeStatementVersion(
        version_sequence=2,
        normalized_payload=_make_payload(
            revenue=Decimal("100"),
            source_version_sequence=2,
        ),
    )

    delta = compute_restatement_delta_between_versions(
        versions=[v1, v2],
        from_version_sequence=1,
    )

    assert delta.from_version_sequence == 1
    assert delta.to_version_sequence == 2
    rev_delta = delta.metrics[CanonicalStatementMetric.REVENUE]
    assert rev_delta.old == Decimal("80")
    assert rev_delta.new == Decimal("100")
    assert rev_delta.diff == Decimal("20")


def test_compute_restatement_delta_between_versions_raises_when_insufficient_versions() -> None:
    """At least two normalized versions are required to compute a delta."""
    v1 = _FakeStatementVersion(
        version_sequence=1,
        normalized_payload=None,
    )
    v2 = _FakeStatementVersion(
        version_sequence=2,
        normalized_payload=_make_payload(
            revenue=Decimal("100"),
            source_version_sequence=2,
        ),
    )

    with pytest.raises(EdgarIngestionError):
        compute_restatement_delta_between_versions(versions=[v1])

    with pytest.raises(EdgarIngestionError):
        compute_restatement_delta_between_versions(versions=[v2])


def test_compute_restatement_delta_between_versions_unknown_sequence_raises_mapping_error() -> None:
    """Unknown version sequences should surface an EdgarMappingError."""
    v1 = _FakeStatementVersion(
        version_sequence=1,
        normalized_payload=_make_payload(
            revenue=Decimal("100"),
            source_version_sequence=1,
        ),
    )
    v2 = _FakeStatementVersion(
        version_sequence=2,
        normalized_payload=_make_payload(
            revenue=Decimal("120"),
            source_version_sequence=2,
        ),
    )

    with pytest.raises(EdgarMappingError):
        compute_restatement_delta_between_versions(
            versions=[v1, v2],
            from_version_sequence=999,
            to_version_sequence=2,
        )

    with pytest.raises(EdgarMappingError):
        compute_restatement_delta_between_versions(
            versions=[v1, v2],
            to_version_sequence=999,
        )
