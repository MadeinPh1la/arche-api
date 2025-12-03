# tests/unit/domain/services/test_fact_dq_engine.py

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from stacklion_api.domain.entities.edgar_dq import (
    EdgarDQRun,
    NormalizedStatementIdentity,
)
from stacklion_api.domain.entities.edgar_normalized_fact import EdgarNormalizedFact
from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType
from stacklion_api.domain.services.fact_dq_engine import (
    FactDQConfig,
    FactDQEngine,
    FactDQResult,
)


def _make_identity() -> NormalizedStatementIdentity:
    return NormalizedStatementIdentity(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=1,
    )


def _make_fact(
    metric_code: str,
    value: Decimal,
    dimension_key: str = "default",
    statement_date: date | None = None,
    version_sequence: int = 1,
) -> EdgarNormalizedFact:
    """Helper to construct a minimal normalized fact."""
    return EdgarNormalizedFact(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard="US_GAAP",
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        statement_date=statement_date or date(2024, 3, 31),
        version_sequence=version_sequence,
        metric_code=metric_code,
        metric_label=None,
        unit="USD",
        period_start=None,
        period_end=statement_date or date(2024, 3, 31),
        value=value,
        dimensions={},
        dimension_key=dimension_key,
        source_line_item=None,
    )


def test_evaluate_missing_key_metric_generates_presence_anomaly() -> None:
    """When key metrics are missing, MISSING_KEY_METRIC anomalies are emitted."""
    identity = _make_identity()

    # Use config with a key metric that is not present.
    config = FactDQConfig(
        key_metrics=("REVENUE", "NET_INCOME"),
        non_negative_metrics=(),
        history_outlier_multiplier=Decimal("10"),
        history_min_observations=2,
    )
    engine = FactDQEngine(config=config)

    # Facts: only NET_INCOME present → REVENUE missing.
    facts = [
        _make_fact("NET_INCOME", Decimal("100")),
    ]

    result = engine.evaluate(statement_identity=identity, facts=facts, history=[])

    assert isinstance(result, FactDQResult)
    # No fact-quality for REVENUE because there is no fact – just anomalies.
    assert any(a.rule_code == "MISSING_KEY_METRIC" for a in result.anomalies)
    missing = [a for a in result.anomalies if a.rule_code == "MISSING_KEY_METRIC"]
    assert {a.metric_code for a in missing} == {"REVENUE"}
    # Run metadata should be consistent.
    assert isinstance(result.run, EdgarDQRun)
    assert result.run.statement_identity == identity
    assert result.run.scope_type == "STATEMENT"
    assert result.run.rule_set_version == config.rule_set_version


def test_evaluate_respects_executed_at_override() -> None:
    """Provided executed_at must be used instead of utcnow()."""
    identity = _make_identity()
    engine = FactDQEngine()

    now = datetime.utcnow() - timedelta(days=1)
    facts = [_make_fact("REVENUE", Decimal("100"))]

    result = engine.evaluate(
        statement_identity=identity,
        facts=facts,
        history=[],
        executed_at=now,
    )

    assert result.run.executed_at == now


def test_build_history_index_orders_by_date_version_dimension_and_metric() -> None:
    """History index must be deterministically ordered and support outlier detection."""
    identity = _make_identity()
    engine = FactDQEngine(
        FactDQConfig(
            key_metrics=(),
            non_negative_metrics=(),  # keep this out of the way for this test
            history_outlier_multiplier=Decimal("2"),
            history_min_observations=2,
        )
    )

    # Jumbled history; engine should sort by (statement_date, version_sequence, dimension_key, metric_code).
    history = [
        _make_fact(
            "REVENUE",
            Decimal("100"),
            dimension_key="b",
            statement_date=date(2023, 12, 31),
            version_sequence=2,
        ),
        _make_fact(
            "REVENUE",
            Decimal("50"),
            dimension_key="a",
            statement_date=date(2023, 9, 30),
            version_sequence=1,
        ),
    ]

    # Big positive jump vs last historical 100 → ratio 3 > 2 → HISTORY_OUTLIER_HIGH.
    current = _make_fact("REVENUE", Decimal("300"))

    result = engine.evaluate(statement_identity=identity, facts=[current], history=history)

    anomalies = [a for a in result.anomalies if a.rule_code == "HISTORY_OUTLIER_HIGH"]
    assert anomalies  # at least one outlier anomaly

    fq = result.fact_quality[0]
    assert fq.metric_code == "REVENUE"
    assert fq.is_present is True
    assert fq.is_consistent_with_history is False
    assert fq.has_known_issue is True


def test_evaluate_negative_value_generates_negative_anomaly() -> None:
    """Negative value in a non_negative metric should emit NEGATIVE_VALUE anomaly."""
    identity = _make_identity()

    config = FactDQConfig(
        key_metrics=(),
        non_negative_metrics=("REVENUE",),
        history_outlier_multiplier=Decimal("10"),
        history_min_observations=2,
    )
    engine = FactDQEngine(config=config)

    current_fact = _make_fact("REVENUE", Decimal("-1000"))
    history: list[EdgarNormalizedFact] = []

    result = engine.evaluate(statement_identity=identity, facts=[current_fact], history=history)

    assert len(result.fact_quality) == 1
    fq = result.fact_quality[0]
    assert fq.metric_code == "REVENUE"
    assert fq.is_present is True
    assert fq.is_non_negative is False
    assert fq.has_known_issue is True

    codes = {a.rule_code for a in result.anomalies}
    assert "NEGATIVE_VALUE" in codes
    # No history provided → is_consistent_with_history should remain None.
    assert fq.is_consistent_with_history is None
