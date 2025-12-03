# tests/unit/domain/entities/test_edgar_dq.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Unit tests for EDGAR data-quality domain entities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import Any

import pytest

from stacklion_api.domain.entities.edgar_dq import (
    EdgarDQAnomaly,
    EdgarDQRun,
    EdgarFactQuality,
    NormalizedStatementIdentity,
)
from stacklion_api.domain.enums.edgar import FiscalPeriod, MaterialityClass, StatementType


def test_normalized_statement_identity_basic_equality_and_hash() -> None:
    """NormalizedStatementIdentity should be value-equal and hashable."""
    identity1 = NormalizedStatementIdentity(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=2,
    )
    identity2 = NormalizedStatementIdentity(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=2,
    )

    assert identity1 == identity2
    assert hash(identity1) == hash(identity2)

    # Can be used as a dictionary key
    d = {identity1: "ok"}
    assert d[identity2] == "ok"


def test_normalized_statement_identity_is_frozen() -> None:
    """NormalizedStatementIdentity instances should be immutable."""
    identity = NormalizedStatementIdentity(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=1,
    )

    with pytest.raises(FrozenInstanceError):
        identity.cik = "0000000000"  # type: ignore[assignment]


def test_edgar_dq_run_basic_construction() -> None:
    """EdgarDQRun should accept basic metadata and preserve it."""
    identity = NormalizedStatementIdentity(
        cik="0000123456",
        statement_type=StatementType.BALANCE_SHEET,
        fiscal_year=2023,
        fiscal_period=FiscalPeriod.FY,
        version_sequence=3,
    )
    executed_at = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)

    run = EdgarDQRun(
        dq_run_id="dq-123",
        statement_identity=identity,
        rule_set_version="v1",
        scope_type="STATEMENT",
        executed_at=executed_at,
    )

    assert run.dq_run_id == "dq-123"
    assert run.statement_identity == identity
    assert run.rule_set_version == "v1"
    assert run.scope_type == "STATEMENT"
    assert run.executed_at is executed_at


def test_edgar_fact_quality_flags_and_details() -> None:
    """EdgarFactQuality should preserve flags and optional details mapping."""
    identity = NormalizedStatementIdentity(
        cik="0000123456",
        statement_type=StatementType.CASH_FLOW_STATEMENT,
        fiscal_year=2022,
        fiscal_period=FiscalPeriod.Q2,
        version_sequence=1,
    )

    details: Mapping[str, Any] = {"rule": "PRESENCE", "score": "0.9"}

    fq = EdgarFactQuality(
        dq_run_id="dq-xyz",
        statement_identity=identity,
        metric_code="REVENUE",
        dimension_key="default",
        severity=MaterialityClass.LOW,
        is_present=True,
        is_non_negative=True,
        is_consistent_with_history=None,
        has_known_issue=False,
        details=details,
    )

    assert fq.dq_run_id == "dq-xyz"
    assert fq.statement_identity == identity
    assert fq.metric_code == "REVENUE"
    assert fq.dimension_key == "default"
    assert fq.severity is MaterialityClass.LOW
    assert fq.is_present is True
    assert fq.is_non_negative is True
    assert fq.is_consistent_with_history is None
    assert fq.has_known_issue is False
    assert fq.details is details
    assert fq.details["rule"] == "PRESENCE"


def test_edgar_dq_anomaly_optional_fields() -> None:
    """EdgarDQAnomaly should allow optional metric and dimension context."""
    anomaly = EdgarDQAnomaly(
        dq_run_id="dq-1",
        statement_identity=None,
        metric_code=None,
        dimension_key=None,
        rule_code="NEGATIVE_REVENUE",
        severity=MaterialityClass.MEDIUM,
        message="Revenue is negative for multiple periods.",
        details={"observed": "-100", "threshold": "0"},
    )

    assert anomaly.dq_run_id == "dq-1"
    assert anomaly.statement_identity is None
    assert anomaly.metric_code is None
    assert anomaly.dimension_key is None
    assert anomaly.rule_code == "NEGATIVE_REVENUE"
    assert anomaly.severity is MaterialityClass.MEDIUM
    assert "negative" in anomaly.message.lower()
    assert anomaly.details is not None
    assert anomaly.details["observed"] == "-100"


def test_edgar_dq_anomaly_is_frozen() -> None:
    """EdgarDQAnomaly should be immutable."""
    anomaly = EdgarDQAnomaly(
        dq_run_id="dq-1",
        statement_identity=None,
        metric_code="REVENUE",
        dimension_key="default",
        rule_code="NEGATIVE_REVENUE",
        severity=MaterialityClass.HIGH,
        message="Severely negative revenue.",
        details=None,
    )

    with pytest.raises(FrozenInstanceError):
        anomaly.message = "patched"  # type: ignore[assignment]
