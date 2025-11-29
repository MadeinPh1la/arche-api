# tests/unit/application/schemas/dto/test_edgar_derived_dto.py
# Copyright (c)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import date

from stacklion_api.application.schemas.dto.edgar_derived import (
    EdgarDerivedMetricsPointDTO,
)
from stacklion_api.domain.enums.derived_metric import DerivedMetric
from stacklion_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType


def test_edgar_derived_metrics_point_dto_roundtrip() -> None:
    dto = EdgarDerivedMetricsPointDTO(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        metrics={DerivedMetric.GROSS_MARGIN: "0.4"},
        normalized_payload_version_sequence=1,
    )

    assert dto.cik == "0000320193"
    assert dto.statement_type is StatementType.INCOME_STATEMENT
    assert dto.accounting_standard is AccountingStandard.US_GAAP
    assert dto.fiscal_year == 2024
    assert dto.fiscal_period is FiscalPeriod.FY
    assert dto.currency == "USD"
    assert dto.metrics[DerivedMetric.GROSS_MARGIN] == "0.4"
    assert dto.normalized_payload_version_sequence == 1
