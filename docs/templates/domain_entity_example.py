# docs/templates/domain_entity_example.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Example domain entity.

Purpose:
- Demonstrate the canonical pattern for domain entities/value objects.

Layer: domain

Notes:
- No HTTP, DB, or framework imports.
- Enforce invariants in __post_init__.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from stacklion_api.domain.exceptions import ValidationException


@dataclass(frozen=True, slots=True)
class ExampleStatementVersion:
    """Canonical example of a domain entity representing a statement version.

    Args:
        company_id: Stable UUID for the company this version belongs to.
        statement_date: The financial statement date (not filing date).
        version: Monotonic version counter for this (company, statement_date, type).
        is_restated: Whether this version represents a restatement.
        restatement_reason: Optional human-readable reason when restated.

    Raises:
        ValidationException: If invariants are violated (e.g., negative version).
    """

    company_id: str
    statement_date: date
    version: int
    is_restated: bool = False
    restatement_reason: str | None = None

    def __post_init__(self) -> None:
        """Enforce domain invariants after initialization.

        Raises:
            ValidationException: If version is non-positive or restatement flags are inconsistent.
        """
        if self.version <= 0:
            raise ValidationException("version must be a positive integer")

        if self.is_restated and not self.restatement_reason:
            raise ValidationException("restatement_reason is required when is_restated is True")

        if not self.is_restated and self.restatement_reason:
            raise ValidationException("restatement_reason must be None when is_restated is False")
