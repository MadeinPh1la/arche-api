# src/arche_api/domain/services/reconciliation_calendar.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Fiscal calendar helpers for EDGAR reconciliation.

Purpose:
    Provide domain-level helpers for inferring statement periods, classifying
    fiscal calendars (including 53-week years), and aligning periods across
    statements for reconciliation.

Layer:
    domain/services

Notes:
    - Pure domain logic:
        * No logging.
        * No HTTP or transport concerns.
        * No persistence or gateways.
    - This module is intentionally conservative: when in doubt, it prefers
        to return None or mark a period as irregular instead of inferring
        aggressive calendar behavior.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from arche_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from arche_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from arche_api.domain.enums.edgar import FiscalPeriod, StatementType


@dataclass(frozen=True, slots=True)
class StatementPeriod:
    """Inferred period information for a single statement.

    Attributes:
        identity:
            Normalized statement identity.
        statement_date:
            Reporting period end date.
        period_start:
            Inferred period start date, when available.
        period_end:
            Reporting period end date (same as statement_date).
        fiscal_year:
            Fiscal year associated with the statement.
        fiscal_period:
            Fiscal period (e.g., FY, Q1, Q2, Q3, Q4).
        statement_type:
            Statement type (income statement, balance sheet, etc.).
        currency:
            ISO currency code for the statement.
        payload:
            Canonical normalized statement payload backing this period.
    """

    identity: NormalizedStatementIdentity
    statement_date: date
    period_start: date | None
    period_end: date
    fiscal_year: int
    fiscal_period: FiscalPeriod
    statement_type: StatementType
    currency: str
    payload: CanonicalStatementPayload


@dataclass(frozen=True, slots=True)
class FiscalCalendarClassification:
    """Classification for a company's fiscal calendar.

    Attributes:
        fye_month:
            Inferred fiscal year-end month (1–12).
        is_53_week_year:
            Whether the observed periods indicate a 53-week year.
        is_irregular:
            Whether the calendar appears irregular (e.g., large gaps,
            inconsistent year-end months).
        inferred_period_length_days:
            Optional typical period length in days for the supplied
            statements (e.g., ~365 for annual, ~90 for quarterly).
    """

    fye_month: int
    is_53_week_year: bool
    is_irregular: bool
    inferred_period_length_days: int | None = None


def infer_statement_period(
    payload: CanonicalStatementPayload,
) -> StatementPeriod:
    """Infer a statement period from a canonical payload.

    This helper creates a StatementPeriod using a conservative period-start
    inference rule based on fiscal_year and fiscal_period.

    Args:
        payload:
            Canonical normalized statement payload.

    Returns:
        Inferred StatementPeriod for the payload.
    """
    from datetime import date as _date

    fiscal_period = payload.fiscal_period
    fiscal_year = payload.fiscal_year

    if fiscal_period.name == "FY" or fiscal_period.name == "Q1":
        period_start = _date(fiscal_year, 1, 1)
    elif fiscal_period.name == "Q2":
        period_start = _date(fiscal_year, 4, 1)
    elif fiscal_period.name == "Q3":
        period_start = _date(fiscal_year, 7, 1)
    elif fiscal_period.name == "Q4":
        period_start = _date(fiscal_year, 10, 1)
    else:
        period_start = None

    identity = NormalizedStatementIdentity(
        cik=payload.cik,
        statement_type=payload.statement_type,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        version_sequence=payload.source_version_sequence,
    )

    return StatementPeriod(
        identity=identity,
        statement_date=payload.statement_date,
        period_start=period_start,
        period_end=payload.statement_date,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        statement_type=payload.statement_type,
        currency=payload.currency,
        payload=payload,
    )


def classify_fiscal_calendar(
    periods: Sequence[StatementPeriod],
) -> FiscalCalendarClassification | None:
    """Classify a fiscal calendar based on observed statement periods.

    Args:
        periods:
            Sequence of statement periods for a single company. The caller
            is responsible for ensuring that all periods relate to the same
            company.

    Returns:
        A FiscalCalendarClassification instance, or None when no periods
        are provided.
    """
    if not periods:
        return None

    sorted_periods = sorted(periods, key=lambda p: p.statement_date)
    fye_months = {p.statement_date.month for p in sorted_periods if p.fiscal_period.name == "FY"}

    if fye_months:
        # Take the most common FY month; ties do not matter materially here.
        fye_month = max(fye_months, key=lambda m: list(fye_months).count(m))
    else:
        fye_month = sorted_periods[-1].statement_date.month

    deltas: list[int] = []
    for prev, curr in zip(sorted_periods, sorted_periods[1:], strict=False):
        delta_days = (curr.statement_date - prev.statement_date).days
        if delta_days > 0:
            deltas.append(delta_days)

    inferred_length: int | None = None
    is_53_week = False
    is_irregular = False

    if deltas:
        deltas_sorted = sorted(deltas)
        inferred_length = deltas_sorted[len(deltas_sorted) // 2]
        is_53_week = inferred_length >= 370

        if deltas_sorted[0] == 0 or deltas_sorted[-1] - deltas_sorted[0] > 40:
            is_irregular = True

    return FiscalCalendarClassification(
        fye_month=fye_month,
        is_53_week_year=is_53_week,
        is_irregular=is_irregular,
        inferred_period_length_days=inferred_length,
    )


def detect_off_cycle_periods(
    periods: Sequence[StatementPeriod],
    *,
    expected_gap_days: int,
    max_gap_days: int,
) -> tuple[StatementPeriod, ...]:
    """Detect off-cycle periods based on gaps between statement dates.

    Args:
        periods:
            Sequence of statement periods for a single company and
            statement type.
        expected_gap_days:
            Expected gap between successive statements (e.g., ~365 for
            annual, ~90 for quarterly).
        max_gap_days:
            Maximum allowed gap before a period is considered off-cycle.

    Returns:
        Tuple of StatementPeriod instances that appear off-cycle.
    """
    if not periods:
        return ()

    sorted_periods = sorted(periods, key=lambda p: p.statement_date)
    off_cycle: list[StatementPeriod] = []

    for prev, curr in zip(sorted_periods, sorted_periods[1:], strict=False):
        gap = (curr.statement_date - prev.statement_date).days
        if gap > max_gap_days or abs(gap - expected_gap_days) > max_gap_days:
            off_cycle.append(curr)

    return tuple(off_cycle)


def align_statements_across_types(
    periods: Sequence[StatementPeriod],
) -> Mapping[tuple[str, int, FiscalPeriod], Mapping[StatementType, StatementPeriod]]:
    """Align statements across statement types by (cik, fiscal_year, period).

    Args:
        periods:
            Sequence of statement periods across statement types.

    Returns:
        Mapping from (cik, fiscal_year, fiscal_period) to a mapping of
        StatementType → StatementPeriod for that identity.
    """
    alignment: dict[tuple[str, int, FiscalPeriod], dict[StatementType, StatementPeriod]] = {}

    for p in periods:
        key = (p.identity.cik, p.fiscal_year, p.fiscal_period)
        bucket = alignment.setdefault(key, {})
        bucket[p.statement_type] = p

    return alignment
