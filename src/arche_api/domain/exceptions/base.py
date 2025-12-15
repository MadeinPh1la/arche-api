# src/arche_api/domain/exceptions/base.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Base Domain Exceptions.

Summary:
    Canonical base class for domain/application exceptions to ensure deterministic
    mapping to HTTP at the boundary.

Layer:
    domain/exceptions
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for all domain/application exceptions.

    Attributes:
        code:
            Stable error code suitable for mapping to HTTP and metrics.
        details:
            Optional machine-readable diagnostic payload used by adapters and
            logging/observability code.
    """

    code: str = "DOMAIN_ERROR"

    def __init__(self, message: str = "", *, details: dict[str, Any] | None = None) -> None:
        """Initialize a DomainError instance.

        Args:
            message:
                Human-readable error message, safe to surface to API clients.
            details:
                Optional structured diagnostic payload for logs or adapters.

        """
        super().__init__(message)
        self.details: dict[str, Any] = details or {}
