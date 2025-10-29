# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Base Domain Exceptions.

Summary:
    Canonical base class for domain/application exceptions to ensure deterministic
    mapping to HTTP at the boundary.

Layer:
    domain/exceptions
"""
from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for all domain/application exceptions."""

    code: str = "DOMAIN_ERROR"

    def __init__(self, message: str = "", *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details: dict[str, Any] = details or {}
