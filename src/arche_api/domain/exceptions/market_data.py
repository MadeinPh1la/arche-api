# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Market Data Domain Exceptions.

Synopsis:
    Domain-level exceptions representing error conditions when interacting with
    external market data providers. These are raised in domain/application and
    mapped to canonical HTTP envelopes by adapters/presenters.

Design:
    * Inherit from :class:`DomainError` for consistent `.code` and safety.
    * Keep HTTP concerns out of the domain; map in presenters/controllers.

Layer:
    domain/exceptions
"""

from __future__ import annotations

from arche_api.domain.exceptions.base import DomainError


class MarketDataUnavailable(DomainError):
    """Third-party market data dependency is unavailable or timed out.

    Typical causes:
        * Network errors / timeouts
        * Upstream 5xx
        * Provider outages

    Attributes:
        code: Stable, machine-readable error code.
    """

    code = "MARKET_DATA_UNAVAILABLE"


class SymbolNotFound(DomainError):
    """Requested symbol(s) could not be found at the provider.

    Use when the upstream responds successfully but indicates an empty result
    or an explicit "symbol not found" condition.

    Attributes:
        code: Stable, machine-readable error code.
    """

    code = "SYMBOL_NOT_FOUND"


class MarketDataValidationError(DomainError):
    """Upstream returned an unexpected or invalid payload shape.

    Indicates schema drift, missing required fields, or invariant violations.

    Attributes:
        code: Stable, machine-readable error code.
    """

    code = "UPSTREAM_SCHEMA_ERROR"


class MarketDataRateLimited(DomainError):
    """Upstream rate limit was hit; retry after cool-down.

    Attributes:
        code: Stable, machine-readable error code.
    """

    code = "MARKET_DATA_RATE_LIMITED"


class MarketDataQuotaExceeded(DomainError):
    """Account plan quota exhausted; non-transient until reset or plan change.

    Attributes:
        code: Stable, machine-readable error code.
    """

    code = "MARKET_DATA_QUOTA_EXCEEDED"


class MarketDataBadRequest(DomainError):
    """Invalid parameters were sent upstream (our bug or user input).

    Attributes:
        code: Stable, machine-readable error code.
    """

    code = "MARKET_DATA_BAD_REQUEST"


class UnsupportedInterval(DomainError):
    """Requested interval is not supported by the current provider.

    Attributes:
        code: Stable, machine-readable error code.
    """

    code = "UNSUPPORTED_INTERVAL"
