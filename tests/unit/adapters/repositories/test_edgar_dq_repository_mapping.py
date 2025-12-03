# tests/unit/adapters/repositories/test_edgar_dq_repository_mapping.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Mapping tests for :mod:`edgar_dq_repository`.

Scope:
    - Validate that low-level mapping helpers on :class:`EdgarDQRepository`
      correctly translate between DB-ish row structures and domain entities.
    - Exercise both "happy path" and edge cases (missing identity, None
      details, optional flags).

Design:
    - Use lightweight dummy row dataclasses instead of real ORM models.
    - Keep tests focused on mapping semantics, not persistence behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from stacklion_api.adapters.repositories.edgar_dq_repository import EdgarDQRepository
from stacklion_api.domain.entities.edgar_dq import (
    EdgarDQAnomaly,
    EdgarDQRun,
    EdgarFactQuality,
    NormalizedStatementIdentity,
)
from stacklion_api.domain.enums.edgar import FiscalPeriod, MaterialityClass, StatementType

# ---------------------------------------------------------------------------
# Dummy row types to simulate ORM results
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _DummyRunRow:
    dq_run_id: UUID
    statement_version_id: UUID | None
    cik: str | None
    statement_type: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    version_sequence: int | None
    rule_set_version: str
    scope_type: str
    executed_at: datetime


@dataclass(slots=True)
class _DummyFactQualityRow:
    fact_quality_id: UUID
    dq_run_id: UUID
    statement_version_id: UUID | None
    cik: str | None
    statement_type: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    version_sequence: int | None
    metric_code: str
    dimension_key: str
    severity: str
    is_present: bool
    is_non_negative: bool | None
    is_consistent_with_history: bool | None
    has_known_issue: bool
    details: dict | None


@dataclass(slots=True)
class _DummyAnomalyRow:
    anomaly_id: UUID
    dq_run_id: UUID
    statement_version_id: UUID | None
    metric_code: str | None
    dimension_key: str | None
    rule_code: str
    severity: str
    message: str
    details: dict | None


# ---------------------------------------------------------------------------
# _map_run_to_domain
# ---------------------------------------------------------------------------


def test_map_run_to_domain_with_full_identity() -> None:
    """_map_run_to_domain should construct a domain run with statement identity."""
    dq_run_id = uuid4()
    sv_id = uuid4()
    executed_at = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)

    row = _DummyRunRow(
        dq_run_id=dq_run_id,
        statement_version_id=sv_id,
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT.value,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1.value,
        version_sequence=2,
        rule_set_version="v1",
        scope_type="STATEMENT",
        executed_at=executed_at,
    )

    result = EdgarDQRepository._map_run_to_domain(row)  # type: ignore[arg-type]

    assert isinstance(result, EdgarDQRun)
    assert result.dq_run_id == str(dq_run_id)
    assert result.rule_set_version == "v1"
    assert result.scope_type == "STATEMENT"
    # We expect the exact datetime object to be preserved, not re-parsed.
    assert result.executed_at is executed_at

    assert result.statement_identity is not None
    identity = result.statement_identity
    assert isinstance(identity, NormalizedStatementIdentity)
    assert identity.cik == "0000123456"
    assert identity.statement_type == StatementType.INCOME_STATEMENT
    assert identity.fiscal_year == 2024
    assert identity.fiscal_period == FiscalPeriod.Q1
    assert identity.version_sequence == 2


def test_map_run_to_domain_without_identity() -> None:
    """_map_run_to_domain should set statement_identity=None when no SV fields."""
    dq_run_id = uuid4()
    executed_at = datetime(2024, 5, 6, 7, 8, 9, tzinfo=UTC)

    row = _DummyRunRow(
        dq_run_id=dq_run_id,
        statement_version_id=None,
        cik=None,
        statement_type=None,
        fiscal_year=None,
        fiscal_period=None,
        version_sequence=None,
        rule_set_version="v2",
        scope_type="COMPANY",
        executed_at=executed_at,
    )

    result = EdgarDQRepository._map_run_to_domain(row)  # type: ignore[arg-type]

    assert isinstance(result, EdgarDQRun)
    assert result.dq_run_id == str(dq_run_id)
    assert result.rule_set_version == "v2"
    assert result.scope_type == "COMPANY"
    assert result.executed_at is executed_at
    assert result.statement_identity is None


# ---------------------------------------------------------------------------
# _fact_quality_to_row / _map_fact_quality_to_domain
# ---------------------------------------------------------------------------


def _build_identity() -> NormalizedStatementIdentity:
    return NormalizedStatementIdentity(
        cik="0000123456",
        statement_type=StatementType.BALANCE_SHEET,
        fiscal_year=2023,
        fiscal_period=FiscalPeriod.FY,
        version_sequence=1,
    )


def test_fact_quality_to_row_and_back_roundtrip() -> None:
    """_fact_quality_to_row + _map_fact_quality_to_domain should be consistent."""
    identity = _build_identity()

    fq = EdgarFactQuality(
        dq_run_id="dq-1",
        statement_identity=identity,
        metric_code="TOTAL_ASSETS",
        dimension_key="default",
        severity=MaterialityClass.LOW,
        is_present=True,
        is_non_negative=None,
        is_consistent_with_history=True,
        has_known_issue=False,
        details={"rule": "HISTORY", "score": "0.95"},
    )

    dq_run_uuid = uuid4()
    statement_version_id = uuid4()

    row_dict = EdgarDQRepository._fact_quality_to_row(
        fq=fq,
        dq_run_uuid=dq_run_uuid,
        statement_version_id=statement_version_id,
        cik=identity.cik,
        statement_type=identity.statement_type.value,
        fiscal_year=identity.fiscal_year,
        fiscal_period=identity.fiscal_period.value,
        version_sequence=identity.version_sequence,
    )

    # Sanity checks on row_dict shape
    assert row_dict["dq_run_id"] == dq_run_uuid
    assert row_dict["statement_version_id"] == statement_version_id
    assert row_dict["cik"] == "0000123456"
    assert row_dict["statement_type"] == StatementType.BALANCE_SHEET.value
    assert row_dict["fiscal_year"] == 2023
    assert row_dict["fiscal_period"] == FiscalPeriod.FY.value
    assert row_dict["version_sequence"] == 1
    assert row_dict["metric_code"] == "TOTAL_ASSETS"
    assert row_dict["dimension_key"] == "default"
    assert row_dict["severity"] == MaterialityClass.LOW.value
    assert row_dict["details"] == {"rule": "HISTORY", "score": "0.95"}

    row = _DummyFactQualityRow(
        fact_quality_id=row_dict["fact_quality_id"],
        dq_run_id=row_dict["dq_run_id"],
        statement_version_id=row_dict["statement_version_id"],
        cik=row_dict["cik"],
        statement_type=row_dict["statement_type"],
        fiscal_year=row_dict["fiscal_year"],
        fiscal_period=row_dict["fiscal_period"],
        version_sequence=row_dict["version_sequence"],
        metric_code=row_dict["metric_code"],
        dimension_key=row_dict["dimension_key"],
        severity=row_dict["severity"],
        is_present=row_dict["is_present"],
        is_non_negative=row_dict["is_non_negative"],
        is_consistent_with_history=row_dict["is_consistent_with_history"],
        has_known_issue=row_dict["has_known_issue"],
        details=row_dict["details"],
    )

    fq_domain = EdgarDQRepository._map_fact_quality_to_domain(row)  # type: ignore[arg-type]

    assert isinstance(fq_domain, EdgarFactQuality)
    # dq_run_id becomes the string form of the UUID we passed into the row
    assert fq_domain.dq_run_id == str(dq_run_uuid)
    assert fq_domain.metric_code == "TOTAL_ASSETS"
    assert fq_domain.dimension_key == "default"
    assert fq_domain.severity == MaterialityClass.LOW
    assert fq_domain.is_present is True
    assert fq_domain.is_non_negative is None
    assert fq_domain.is_consistent_with_history is True
    assert fq_domain.has_known_issue is False
    assert fq_domain.details == {"rule": "HISTORY", "score": "0.95"}

    identity_mapped = fq_domain.statement_identity
    assert isinstance(identity_mapped, NormalizedStatementIdentity)
    assert identity_mapped.cik == "0000123456"
    assert identity_mapped.statement_type == StatementType.BALANCE_SHEET
    assert identity_mapped.fiscal_year == 2023
    assert identity_mapped.fiscal_period == FiscalPeriod.FY
    assert identity_mapped.version_sequence == 1


def test_map_fact_quality_to_domain_with_nulls() -> None:
    """_map_fact_quality_to_domain should handle None flags and details.

    We still expect a full statement identity when the identity columns are
    populated, but some of the quality flags and details may be NULL.
    """
    dq_run_uuid = uuid4()

    row = _DummyFactQualityRow(
        fact_quality_id=uuid4(),
        dq_run_id=dq_run_uuid,
        # Identity columns are present – this is what the real repo emits.
        statement_version_id=uuid4(),
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT.value,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1.value,
        version_sequence=1,
        # Fact-level fields
        metric_code="EPS_DILUTED",
        dimension_key="segment:US",
        severity=MaterialityClass.HIGH.value,
        is_present=False,
        # Nullable flags + details
        is_non_negative=None,
        is_consistent_with_history=None,
        has_known_issue=True,
        details=None,
    )

    fq_domain = EdgarDQRepository._map_fact_quality_to_domain(row)  # type: ignore[arg-type]

    assert isinstance(fq_domain, EdgarFactQuality)
    assert fq_domain.dq_run_id == str(dq_run_uuid)
    assert fq_domain.metric_code == "EPS_DILUTED"
    assert fq_domain.dimension_key == "segment:US"
    assert fq_domain.severity == MaterialityClass.HIGH
    assert fq_domain.is_present is False
    # These are the nullable bits we care about in this test:
    assert fq_domain.is_non_negative is None
    assert fq_domain.is_consistent_with_history is None
    assert fq_domain.has_known_issue is True
    assert fq_domain.details is None

    # Identity should be fully reconstructed from the non-null identity columns.
    identity = fq_domain.statement_identity
    assert isinstance(identity, NormalizedStatementIdentity)
    assert identity.cik == "0000123456"
    # Use equality, not identity, to avoid enum reload edge cases.
    assert identity.statement_type == StatementType.INCOME_STATEMENT
    assert identity.fiscal_year == 2024
    assert identity.fiscal_period == FiscalPeriod.Q1
    assert identity.version_sequence == 1


# ---------------------------------------------------------------------------
# _anomaly_to_row / _map_anomaly_to_domain
# ---------------------------------------------------------------------------


def test_anomaly_to_row_and_back_roundtrip() -> None:
    """_anomaly_to_row + _map_anomaly_to_domain should be consistent.

    Note: the anomaly mapper does not reconstruct the full statement identity;
    that is handled by higher-level queries that join the anomaly to the
    statement-version table. Here we only assert the fields that the mapper
    actually controls.
    """
    identity = NormalizedStatementIdentity(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=2,
    )

    anomaly = EdgarDQAnomaly(
        dq_run_id="dq-99",
        statement_identity=identity,
        metric_code="REVENUE",
        dimension_key="default",
        rule_code="NEGATIVE_REVENUE",
        severity=MaterialityClass.MEDIUM,
        message="Revenue is negative in the latest period.",
        details={"observed": "-100", "threshold": "0"},
    )

    dq_run_uuid = uuid4()
    statement_version_id = uuid4()

    row_dict = EdgarDQRepository._anomaly_to_row(
        anomaly=anomaly,
        dq_run_uuid=dq_run_uuid,
        statement_version_id=statement_version_id,
    )

    # Sanity checks on the row dict shape
    assert row_dict["dq_run_id"] == dq_run_uuid
    assert row_dict["statement_version_id"] == statement_version_id
    assert row_dict["metric_code"] == "REVENUE"
    assert row_dict["dimension_key"] == "default"
    assert row_dict["rule_code"] == "NEGATIVE_REVENUE"
    assert row_dict["severity"] == MaterialityClass.MEDIUM.value
    assert row_dict["message"].startswith("Revenue is negative")
    assert row_dict["details"] == {"observed": "-100", "threshold": "0"}

    # Reconstruct a dummy row to map back to domain
    row = _DummyAnomalyRow(
        anomaly_id=row_dict["anomaly_id"],
        dq_run_id=row_dict["dq_run_id"],
        statement_version_id=row_dict["statement_version_id"],
        metric_code=row_dict["metric_code"],
        dimension_key=row_dict["dimension_key"],
        rule_code=row_dict["rule_code"],
        severity=row_dict["severity"],
        message=row_dict["message"],
        details=row_dict["details"],
    )

    anomaly_domain = EdgarDQRepository._map_anomaly_to_domain(row)  # type: ignore[arg-type]

    assert isinstance(anomaly_domain, EdgarDQAnomaly)
    # dq_run_id should be stringified UUID
    assert anomaly_domain.dq_run_id == str(dq_run_uuid)
    assert anomaly_domain.metric_code == "REVENUE"
    assert anomaly_domain.dimension_key == "default"
    assert anomaly_domain.rule_code == "NEGATIVE_REVENUE"
    assert anomaly_domain.severity == MaterialityClass.MEDIUM
    assert anomaly_domain.message.startswith("Revenue is negative")
    assert anomaly_domain.details == {"observed": "-100", "threshold": "0"}

    # Mapper does not reconstruct identity here; that is done in higher layers.
    assert anomaly_domain.statement_identity is None


def test_map_anomaly_to_domain_without_identity_or_details() -> None:
    """_map_anomaly_to_domain should handle missing identity and details.

    In this case, the anomaly row has no statement_version_id and no details.
    The mapper should still construct a valid EdgarDQAnomaly with the severity
    and rule code populated, and statement_identity left as None.
    """
    dq_run_uuid = uuid4()
    row = _DummyAnomalyRow(
        anomaly_id=uuid4(),
        dq_run_id=dq_run_uuid,
        statement_version_id=None,
        metric_code=None,
        dimension_key=None,
        rule_code="CROSS_STATEMENT_IMBALANCE",
        severity=MaterialityClass.HIGH.value,
        message="Balance sheet does not balance.",
        details=None,
    )

    anomaly_domain = EdgarDQRepository._map_anomaly_to_domain(row)  # type: ignore[arg-type]

    assert isinstance(anomaly_domain, EdgarDQAnomaly)
    assert anomaly_domain.dq_run_id == str(dq_run_uuid)
    assert anomaly_domain.metric_code is None
    assert anomaly_domain.dimension_key is None
    assert anomaly_domain.rule_code == "CROSS_STATEMENT_IMBALANCE"
    assert anomaly_domain.severity == MaterialityClass.HIGH
    assert anomaly_domain.message == "Balance sheet does not balance."
    assert anomaly_domain.details is None
    # No identity columns present → no statement identity reconstructed.
    assert anomaly_domain.statement_identity is None
