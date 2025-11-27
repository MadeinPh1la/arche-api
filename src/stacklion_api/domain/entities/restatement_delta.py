# src/stacklion_api/domain/entities/restatement_delta.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Restatement delta entity.

Purpose:
    Represent the differences between two normalized financial statement
    versions (original → restated) at the canonical metric level. This is used
    by the Normalized Statement Payload Engine to provide restatement lineage
    and quantitative deltas for advanced modeling.

Layer:
    domain

Notes:
    - Deltas are expressed in the same currency and units as the underlying
      canonical payloads (full units, Decimal).
    - Missing metrics in either side should be treated as zero by the engine
      when computing deltas; this entity assumes deltas are already computed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from stacklion_api.domain.enums.canonical_statement_metric import (
    CanonicalStatementMetric,
)
from stacklion_api.domain.enums.edgar import StatementType


@dataclass(frozen=True)
class RestatementDelta:
    """Canonical restatement delta between two statement versions.

    Attributes:
        from_accession_id:
            Accession ID of the original (pre-restatement) filing.
        to_accession_id:
            Accession ID of the restated (or more recent) filing.
        statement_type:
            Statement type this delta applies to.
        statement_date:
            Reporting period end date. Both versions MUST share this date.
        currency:
            ISO currency code for reported values (e.g., "USD").
        deltas:
            Mapping from canonical metrics to the difference:
                value_in_to_version - value_in_from_version
            Metrics absent in one of the versions SHOULD have been treated as
            zero by the engine when computing this mapping.
    """

    from_accession_id: str
    to_accession_id: str
    statement_type: StatementType
    statement_date: date
    currency: str
    deltas: Mapping[CanonicalStatementMetric, Decimal]

    def __post_init__(self) -> None:
        """Enforce basic invariants for canonical restatement deltas."""
        if not isinstance(self.from_accession_id, str) or not self.from_accession_id.strip():
            raise ValueError(
                "RestatementDelta.from_accession_id must be a non-empty string.",
            )
        if not isinstance(self.to_accession_id, str) or not self.to_accession_id.strip():
            raise ValueError(
                "RestatementDelta.to_accession_id must be a non-empty string.",
            )

        if not isinstance(self.currency, str) or not self.currency.strip():
            raise ValueError("RestatementDelta.currency must be a non-empty ISO code.")

        # Shape checks for the deltas mapping.
        for metric, delta in self.deltas.items():
            if not isinstance(metric, CanonicalStatementMetric):
                raise TypeError(
                    "RestatementDelta.deltas keys must be CanonicalStatementMetric instances; "
                    f"got {type(metric)!r}.",
                )
            if not isinstance(delta, Decimal):
                raise TypeError(
                    "RestatementDelta.deltas values must be Decimal instances; "
                    f"got {type(delta)!r}.",
                )


__all__ = ["RestatementDelta"]
