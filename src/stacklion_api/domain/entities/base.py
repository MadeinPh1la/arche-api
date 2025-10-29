# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Base Entity (Domain Layer)

Purpose:
    Mixin for immutable domain entities. Provides frozen dataclass semantics
    and a small validation hook for invariants.

Layer: domain/entities
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BaseEntity:
    """Base mixin for domain entities.

    Notes:
        - Pure Python dataclass. No framework/HTTP imports allowed (EQS).
        - Subclasses may implement `__post_init__` to enforce invariants.
    """

    # Intentionally empty; serves as a marker + dataclass config.
    ...
