# src/arche_api/domain/services/fact_dq_engine.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""EDGAR fact-level data-quality engine (phase 1).

Purpose:
    Provide a rule-based data-quality engine for normalized EDGAR facts.
    The engine evaluates a set of simple, explainable rules and produces
    DQ runs, fact-level quality flags, and rule-level anomalies.

Layer:
    domain/services

Notes:
    - This is a phase-1 engine. It is intentionally conservative and focused
      on a small number of high-signal rules:
        * Presence of key metrics.
        * Non-negativity for selected metrics.
        * Simple history-based outlier detection.
    - Rules are designed to be deterministic and reproducible.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from arche_api.domain.entities.edgar_dq import (
    EdgarDQAnomaly,
    EdgarDQRun,
    EdgarFactQuality,
    NormalizedStatementIdentity,
)
from arche_api.domain.entities.edgar_normalized_fact import EdgarNormalizedFact
from arche_api.domain.enums.edgar import MaterialityClass


@dataclass(frozen=True, slots=True)
class FactDQConfig:
    """Configuration for the fact-level DQ engine.

    Attributes:
        rule_set_version:
            Identifier for the set of rules being applied (e.g., "v1").
        key_metrics:
            Metric codes that should normally be present in a normalized
            statement (e.g., ["REVENUE", "NET_INCOME"]).
        non_negative_metrics:
            Metric codes that should not be negative under normal
            circumstances (e.g., ["REVENUE"]).
        history_outlier_multiplier:
            Threshold multiplier for simple history-based outlier detection.
            For example, a value of 10.0 will flag values that exceed 10x
            the most recent historical value.
        history_min_observations:
            Minimum number of historical observations required before
            applying history-based rules.
    """

    rule_set_version: str = "v1"
    key_metrics: Sequence[str] = ("REVENUE", "NET_INCOME")
    non_negative_metrics: Sequence[str] = ("REVENUE",)
    history_outlier_multiplier: Decimal = Decimal("10")
    history_min_observations: int = 2


@dataclass(frozen=True, slots=True)
class FactDQResult:
    """Result of a fact-level DQ evaluation.

    Attributes:
        run:
            DQ run metadata.
        fact_quality:
            Fact-level quality records.
        anomalies:
            Rule-level anomalies generated during evaluation.
    """

    run: EdgarDQRun
    fact_quality: list[EdgarFactQuality]
    anomalies: list[EdgarDQAnomaly]


class FactDQEngine:
    """Rule-based data-quality engine for normalized EDGAR facts."""

    def __init__(self, config: FactDQConfig | None = None) -> None:
        """Initialize the engine.

        Args:
            config:
                Optional configuration. When omitted, defaults are used.
        """
        self._config = config or FactDQConfig()

    def evaluate(
        self,
        *,
        statement_identity: NormalizedStatementIdentity,
        facts: Sequence[EdgarNormalizedFact],
        history: Sequence[EdgarNormalizedFact] | None = None,
        executed_at: datetime | None = None,
    ) -> FactDQResult:
        """Evaluate data-quality rules for a set of normalized facts.

        Args:
            statement_identity:
                Identity of the statement version being evaluated.
            facts:
                Facts derived from the normalized payload for this statement.
            history:
                Optional historical facts for the same company + statement
                type. These are used for simple outlier detection.
            executed_at:
                Optional evaluation timestamp. When omitted, the current time
                is used.

        Returns:
            A :class:`FactDQResult` containing the DQ run metadata, fact-level
            quality records, and anomalies.
        """
        dq_run_id = str(uuid4())
        run = EdgarDQRun(
            dq_run_id=dq_run_id,
            statement_identity=statement_identity,
            rule_set_version=self._config.rule_set_version,
            scope_type="STATEMENT",
            executed_at=executed_at or datetime.utcnow(),
        )

        anomalies: list[EdgarDQAnomaly] = []
        fact_quality: list[EdgarFactQuality] = []

        # Index facts by (metric_code, dimension_key) for presence checks and
        # to facilitate rule evaluation.
        facts_by_key: dict[tuple[str, str], EdgarNormalizedFact] = {
            (f.metric_code, f.dimension_key): f for f in facts
        }

        # Presence rule: ensure key metrics exist for at least one dimension.
        self._apply_presence_rules(
            dq_run_id=dq_run_id,
            identity=statement_identity,
            facts_by_key=facts_by_key,
            anomalies=anomalies,
        )

        # Non-negativity and history-based rules are evaluated per fact.
        history_index = self._build_history_index(history or [])
        for fact in facts:
            fact_anomalies = self._evaluate_fact_rules(
                dq_run_id=dq_run_id,
                identity=statement_identity,
                fact=fact,
                history_index=history_index,
            )
            anomalies.extend(fact_anomalies)

        # Aggregate anomalies by fact to compute fact-level severity and flags.
        fact_quality.extend(
            self._build_fact_quality(
                dq_run_id=dq_run_id,
                identity=statement_identity,
                facts=facts,
                anomalies=anomalies,
            )
        )

        return FactDQResult(run=run, fact_quality=fact_quality, anomalies=anomalies)

    # --------------------------------------------------------------------- #
    # Rule helpers                                                          #
    # --------------------------------------------------------------------- #

    def _apply_presence_rules(
        self,
        *,
        dq_run_id: str,
        identity: NormalizedStatementIdentity,
        facts_by_key: Mapping[tuple[str, str], EdgarNormalizedFact],
        anomalies: list[EdgarDQAnomaly],
    ) -> None:
        """Apply presence rules for key metrics."""
        present_metrics = {metric for metric, _ in facts_by_key}
        for required in self._config.key_metrics:
            if required not in present_metrics:
                anomalies.append(
                    EdgarDQAnomaly(
                        dq_run_id=dq_run_id,
                        statement_identity=identity,
                        metric_code=required,
                        dimension_key=None,
                        rule_code="MISSING_KEY_METRIC",
                        severity=MaterialityClass.HIGH,
                        message=f"Required metric {required} is missing from normalized facts.",
                        details={
                            "metric_code": required,
                            "statement_identity": {
                                "cik": identity.cik,
                                "statement_type": identity.statement_type.value,
                                "fiscal_year": identity.fiscal_year,
                                "fiscal_period": identity.fiscal_period.value,
                                "version_sequence": identity.version_sequence,
                            },
                        },
                    )
                )

    def _build_history_index(
        self,
        history: Sequence[EdgarNormalizedFact],
    ) -> Mapping[str, list[EdgarNormalizedFact]]:
        """Index historical facts by metric code for outlier checks."""
        by_metric: dict[str, list[EdgarNormalizedFact]] = defaultdict(list)
        for fact in history:
            by_metric[fact.metric_code].append(fact)

        # Ensure deterministic ordering within each metric history.
        for metric_code, facts in by_metric.items():
            facts.sort(
                key=lambda f: (
                    f.statement_date,
                    f.version_sequence,
                    f.dimension_key,
                    f.metric_code,
                )
            )
            by_metric[metric_code] = facts
        return by_metric

    def _evaluate_fact_rules(
        self,
        *,
        dq_run_id: str,
        identity: NormalizedStatementIdentity,
        fact: EdgarNormalizedFact,
        history_index: Mapping[str, Sequence[EdgarNormalizedFact]],
    ) -> list[EdgarDQAnomaly]:
        """Evaluate non-negativity and history-based rules for a single fact."""
        anomalies: list[EdgarDQAnomaly] = []

        # Non-negativity rule.
        if fact.metric_code in self._config.non_negative_metrics and fact.value < 0:
            anomalies.append(
                EdgarDQAnomaly(
                    dq_run_id=dq_run_id,
                    statement_identity=identity,
                    metric_code=fact.metric_code,
                    dimension_key=fact.dimension_key,
                    rule_code="NEGATIVE_VALUE",
                    severity=MaterialityClass.HIGH,
                    message=(
                        f"Metric {fact.metric_code} is expected to be non-negative "
                        f"but has value {fact.value}."
                    ),
                    details={
                        "metric_code": fact.metric_code,
                        "value": str(fact.value),
                    },
                )
            )

        # History-based outlier rule.
        hist_facts = list(history_index.get(fact.metric_code, []))
        if len(hist_facts) >= self._config.history_min_observations:
            last = hist_facts[-1]
            try:
                ratio = fact.value / last.value if last.value != 0 else None
            except (InvalidOperation, ZeroDivisionError):
                ratio = None

            if ratio is not None and ratio > self._config.history_outlier_multiplier:
                anomalies.append(
                    EdgarDQAnomaly(
                        dq_run_id=dq_run_id,
                        statement_identity=identity,
                        metric_code=fact.metric_code,
                        dimension_key=fact.dimension_key,
                        rule_code="HISTORY_OUTLIER_HIGH",
                        severity=MaterialityClass.MEDIUM,
                        message=(
                            f"Metric {fact.metric_code} increased by a factor of "
                            f"{ratio} compared to the most recent historical value."
                        ),
                        details={
                            "metric_code": fact.metric_code,
                            "current_value": str(fact.value),
                            "previous_value": str(last.value),
                            "ratio": str(ratio),
                        },
                    )
                )

        return anomalies

    def _build_fact_quality(
        self,
        *,
        dq_run_id: str,
        identity: NormalizedStatementIdentity,
        facts: Sequence[EdgarNormalizedFact],
        anomalies: Sequence[EdgarDQAnomaly],
    ) -> list[EdgarFactQuality]:
        """Aggregate anomalies into fact-level quality records."""
        # Group anomalies by (metric_code, dimension_key).
        anomaly_map: dict[tuple[str, str], list[EdgarDQAnomaly]] = defaultdict(list)
        for anomaly in anomalies:
            if anomaly.metric_code is None or anomaly.dimension_key is None:
                # Global anomalies (e.g., missing key metric) do not attach to
                # a single fact-level record.
                continue
            key = (anomaly.metric_code, anomaly.dimension_key)
            anomaly_map[key].append(anomaly)

        fact_quality: list[EdgarFactQuality] = []
        for fact in facts:
            key = (fact.metric_code, fact.dimension_key)
            fact_anomalies = anomaly_map.get(key, [])

            severity = MaterialityClass.NONE
            for anomaly in fact_anomalies:
                if anomaly.severity.value > severity.value:
                    severity = anomaly.severity

            is_non_negative = None
            is_consistent_with_history = None
            has_known_issue = bool(fact_anomalies)

            for anomaly in fact_anomalies:
                if anomaly.rule_code == "NEGATIVE_VALUE":
                    is_non_negative = False
                if anomaly.rule_code.startswith("HISTORY_OUTLIER_"):
                    is_consistent_with_history = False

            fact_quality.append(
                EdgarFactQuality(
                    dq_run_id=dq_run_id,
                    statement_identity=identity,
                    metric_code=fact.metric_code,
                    dimension_key=fact.dimension_key,
                    severity=severity,
                    is_present=True,
                    is_non_negative=is_non_negative,
                    is_consistent_with_history=is_consistent_with_history,
                    has_known_issue=has_known_issue,
                    details=(
                        {
                            "anomaly_count": len(fact_anomalies),
                            "rule_codes": [a.rule_code for a in fact_anomalies],
                        }
                        if fact_anomalies
                        else None
                    ),
                )
            )

        return fact_quality
