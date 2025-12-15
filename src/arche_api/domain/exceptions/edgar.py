# src/arche_api/domain/exceptions/edgar.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""EDGAR domain exceptions.

Purpose:
    Provide EDGAR-specific domain-level error types for ingestion, mapping, and
    lookup failures.

Layer:
    domain

Notes:
    - These exceptions are raised by EDGAR entities and domain interfaces.
    - Adapters and infrastructure are responsible for translating transport or
      persistence errors into these types.
    - For now, these derive directly from Exception to avoid tight coupling to
      any particular base exception implementation.
"""

from __future__ import annotations

from typing import Any


class EdgarError(Exception):
    """Base class for EDGAR-related domain errors.

    Attributes:
        message:
            Human-readable error message (safe for clients).
        details:
            Optional machine-readable diagnostic payload for logs and callers.
    """

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        """Initialize an EDGAR error instance.

        Args:
            message:
                Human-readable error message describing the failure.
            details:
                Optional structured diagnostic payload; should be safe to log
                and, when appropriate, surface to API clients.

        """
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}

    def __str__(self) -> str:
        """Return the human-readable message for this error."""
        # Details are intentionally not injected into the string representation
        # to avoid leaking internal structure by accident.
        return self.message


class EdgarIngestionError(EdgarError):
    """Raised when EDGAR ingestion fails or yields unusable data."""


class EdgarMappingError(EdgarError):
    """Raised when raw EDGAR data cannot be mapped into domain entities safely."""


class EdgarNotFound(EdgarError):
    """Raised when an EDGAR filing, statement version, or company cannot be found."""
