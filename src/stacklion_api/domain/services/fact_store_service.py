# src/stacklion_api/domain/services/fact_store_service.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Fact store service for normalized EDGAR payloads.

Purpose:
    Provide pure domain logic for transforming canonical normalized EDGAR
    statement payloads into atomic facts suitable for persistence in the
    EDGAR fact store and data-quality evaluation.

Layer:
    domain/services

Notes:
    - This module is intentionally infrastructure-agnostic. It does not
      depend on SQLAlchemy, Pydantic, or HTTP schemas.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from stacklion_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from stacklion_api.domain.entities.edgar_normalized_fact import EdgarNormalizedFact
from stacklion_api.domain.enums.edgar import FiscalPeriod


@dataclass(frozen=True, slots=True)
class FactDerivationConfig:
    """Configuration for fact derivation.

    Attributes:
        default_period_start_strategy:
            Strategy for inferring period_start when it is not explicitly
            represented in the payload. Supported values:
                - "none": leave period_start as None.
                - "fiscal_year_start": approximate from fiscal_year and
                  fiscal_period (best-effort).
        include_extra_metrics:
            Whether to derive facts from ``extra_metrics`` in addition to
            ``core_metrics``.
    """

    default_period_start_strategy: str = "none"
    include_extra_metrics: bool = True


def build_dimension_key(dimensions: Mapping[str, str] | None) -> str:
    """Build a deterministic key for a dimensions mapping.

    The key is constructed by sorting the dimension items by key, then
    joining them as "key=value" pairs with a "|" separator. An empty
    mapping produces the constant key "default".

    Args:
        dimensions:
            Mapping of dimension key to value. May be None.

    Returns:
        A deterministic string key representing the dimensional slice.
    """
    if not dimensions:
        return "default"

    items = sorted((str(k), str(v)) for k, v in dimensions.items())
    return "|".join(f"{k}={v}" for k, v in items)


def _infer_period_start(
    statement_date: date,
    fiscal_year: int,
    fiscal_period: FiscalPeriod,
    strategy: str,
) -> date | None:
    """Infer period_start based on a simple strategy.

    This intentionally implements conservative logic. It is better to return
    None than to emit a misleading period boundary.

    Args:
        statement_date:
            Reporting period end date.
        fiscal_year:
            Fiscal year.
        fiscal_period:
            Fiscal period within the year.
        strategy:
            Strategy identifier. Currently supported:
                - "none": always returns None.
                - "fiscal_year_start": approximate period start as:
                    * FY: January 1st of the fiscal_year.
                    * Q1/Q2/Q3/Q4: naive quarter start boundaries.

    Returns:
        The inferred period start date, or None if no inference is performed.
    """
    if strategy == "none":
        return None

    if strategy != "fiscal_year_start":
        # Unknown strategy; fail closed.
        return None

    # NOTE: This is intentionally naive and does not attempt to honor
    # arbitrary fiscal year offsets. It provides rough boundaries for
    # analytics where an approximate period_start is sufficient.
    from datetime import date as _date

    if fiscal_period.name == "FY":
        return _date(fiscal_year, 1, 1)

    quarter_starts = {
        "Q1": _date(fiscal_year, 1, 1),
        "Q2": _date(fiscal_year, 4, 1),
        "Q3": _date(fiscal_year, 7, 1),
        "Q4": _date(fiscal_year, 10, 1),
    }
    return quarter_starts.get(fiscal_period.name, None)


def payload_to_facts(
    payload: CanonicalStatementPayload,
    *,
    version_sequence: int,
    config: FactDerivationConfig | None = None,
) -> list[EdgarNormalizedFact]:
    """Derive normalized facts from a canonical statement payload.

    Args:
        payload:
            Canonical normalized statement payload.
        version_sequence:
            Statement version sequence to attribute to all derived facts.
        config:
            Optional derivation configuration. When omitted, defaults are
            applied (include extra metrics, no period_start inference).

    Returns:
        List of :class:`EdgarNormalizedFact` instances suitable for persistence
        in the fact store.

    Raises:
        ValueError:
            If the payload has incompatible attributes (e.g., negative
            fiscal_year) that should have been caught earlier in the pipeline.
    """
    cfg = config or FactDerivationConfig()

    if payload.fiscal_year <= 0:
        raise ValueError(
            f"fiscal_year must be positive for fact derivation; " f"got {payload.fiscal_year!r}",
        )

    period_start = _infer_period_start(
        statement_date=payload.statement_date,
        fiscal_year=payload.fiscal_year,
        fiscal_period=payload.fiscal_period,
        strategy=cfg.default_period_start_strategy,
    )

    dimensions = dict(payload.dimensions)
    dimension_key = build_dimension_key(dimensions)

    facts: list[EdgarNormalizedFact] = []

    def _iter_metrics() -> Iterable[tuple[str, Decimal]]:
        for metric, amount in payload.core_metrics.items():
            yield metric.value, amount
        if cfg.include_extra_metrics:
            for key, amount in payload.extra_metrics.items():
                yield str(key), amount

    for metric_code, amount in _iter_metrics():
        facts.append(
            EdgarNormalizedFact(
                cik=payload.cik,
                statement_type=payload.statement_type,
                accounting_standard=payload.accounting_standard,
                fiscal_year=payload.fiscal_year,
                fiscal_period=payload.fiscal_period,
                statement_date=payload.statement_date,
                version_sequence=version_sequence,
                metric_code=metric_code,
                metric_label=None,
                unit=payload.currency,
                period_start=period_start,
                period_end=payload.statement_date,
                value=amount,
                dimensions=dimensions,
                dimension_key=dimension_key,
                source_line_item=None,
            ),
        )

    return facts
