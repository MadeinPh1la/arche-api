# src/stacklion_api/application/schemas/dto/fundamentals.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Application DTOs for fundamentals time-series.

Purpose:
    Provide strict Pydantic DTOs used by application-layer use cases and
    adapters for fundamentals-oriented read models. These DTOs are
    transport-agnostic and suitable for mapping into HTTP envelopes
    defined by API_STANDARDS.

Layer:
    application/schemas/dto
"""

from __future__ import annotations

from datetime import date

from pydantic import ConfigDict

from stacklion_api.application.schemas.dto.base import BaseDTO
from stacklion_api.domain.enums.edgar import FiscalPeriod


class FundamentalsTimeSeriesPointDTO(BaseDTO):
    """DTO representing a single fundamentals time-series point.

    This DTO is the application-layer representation of a normalized
    fundamentals data point, suitable for mapping into HTTP contracts
    or other output formats.

    Attributes:
        cik: Company CIK.
        statement_date: Period end date associated with the fundamentals.
        fiscal_year: Fiscal year associated with the statement.
        fiscal_period: Fiscal period (e.g., FY, Q1, Q2).
        frequency: Aggregation frequency for the series (e.g., "annual",
            "quarterly"). Validation of allowed values is handled by the
            application layer and/or HTTP schemas.
        metrics: Mapping from canonical metric identifiers (strings) to
            stringified numeric values or None when a metric is missing
            for the given point.
    """

    model_config = ConfigDict(extra="forbid")

    cik: str
    statement_date: date
    fiscal_year: int
    fiscal_period: FiscalPeriod
    frequency: str
    metrics: dict[str, str | None]


class GetFundamentalsTimeSeriesResultDTO(BaseDTO):
    """Result DTO for fundamentals time-series queries.

    Attributes:
        points: Ordered list of fundamentals time-series points. Application
            and presenter layers SHOULD ensure deterministic ordering, e.g.
            by (cik, statement_date, metric).
    """

    model_config = ConfigDict(extra="forbid")

    points: list[FundamentalsTimeSeriesPointDTO]


__all__ = [
    "FundamentalsTimeSeriesPointDTO",
    "GetFundamentalsTimeSeriesResultDTO",
]
