# src/stacklion_api/domain/interfaces/repositories/edgar_statement_alignment_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""EDGAR statement alignment repository interface.

Purpose:
    Define persistence and query operations for statement-level alignment and
    calendar metadata produced by the stitching engine.

Layer:
    domain/interfaces/repositories

Notes:
    Implementations live in the adapters/infrastructure layers and must:
    - Provide deterministic ordering guarantees for alignment timelines.
    - Translate low-level DB/driver errors into domain exceptions.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from stacklion_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from stacklion_api.domain.enums.edgar import StatementType


class StatementAlignmentRecord(Protocol):
    """Lightweight view of a statement alignment record.

    This protocol exists to decouple the repository interface from any
    particular concrete entity implementation.
    """

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: str
    statement_date: date
    version_sequence: int


class EdgarStatementAlignmentRepository(Protocol):
    """Protocol for repositories managing EDGAR statement alignment records."""

    async def upsert_alignment(self, alignment: StatementAlignmentRecord) -> None:
        """Insert or update a single alignment record.

        Implementations must use deterministic identity semantics, typically
        keyed by statement_version_id.
        """

    async def upsert_alignments(
        self,
        alignments: Sequence[StatementAlignmentRecord],
    ) -> None:
        """Insert or update a batch of alignment records."""

    async def get_alignment_for_statement(
        self,
        identity: NormalizedStatementIdentity,
        statement_type: StatementType,
    ) -> StatementAlignmentRecord | None:
        """Return the alignment record for a given normalized statement identity.

        Resolution should be based on fiscal year, fiscal period, CIK, and
        statement type, using the latest version_sequence where multiple
        versions exist.
        """

    async def list_alignment_timeline_for_company(
        self,
        *,
        cik: str,
        statement_type: StatementType | None = None,
    ) -> Sequence[StatementAlignmentRecord]:
        """List alignment records for a company in deterministic timeline order.

        Ordering:
            (fiscal_year ASC, fiscal_period ASC, version_sequence ASC).
        """
