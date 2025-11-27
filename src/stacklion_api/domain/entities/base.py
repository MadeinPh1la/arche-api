# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Base Entity (Domain Layer).

Purpose:
    Mixin for immutable domain entities. Provides frozen dataclass semantics
    and a small validation hook for invariants.

Layer:
    domain/entities
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BaseEntity:
    """Base mixin for domain entities.

    Attributes:
        None:
            ``BaseEntity`` does not define concrete fields itself; it exists to
            provide common dataclass configuration (frozen + slots) and a
            standard invariant hook via :meth:`__post_init__`. Concrete domain
            entities should subclass this mixin and declare their own fields
            and invariants.
    """

    def __post_init__(self) -> None:  # noqa: D401
        """Hook for subclasses to extend with invariant checks.

        The base implementation does not enforce additional invariants. Domain
        entities that need validation logic should override ``__post_init__``
        and may call ``super().__post_init__()`` as a no-op.
        """
        # Intentionally empty; serves as a common extension point.
        return
