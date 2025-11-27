# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""EDGAR transport client settings.

Purpose:
    Provide Pydantic-based configuration for the EDGAR HTTP client, including
    base URL, user agent, timeouts, and retry policy.

Layer:
    infrastructure

Notes:
    - Values are sourced from environment variables prefixed with ``EDGAR_``.
    - This module is transport-agnostic; it does not depend on FastAPI or
      application-layer concepts.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EdgarSettings(BaseSettings):
    """Configuration for the EDGAR HTTP client.

    Environment variables (with ``model_config.env_prefix``):

    * ``EDGAR_BASE_URL``
    * ``EDGAR_USER_AGENT``
    * ``EDGAR_TIMEOUT_S``
    * ``EDGAR_MAX_RETRIES``
    * ``EDGAR_RATE_LIMIT_RPS``
    """

    base_url: str = Field(
        "https://data.sec.gov",
        description="Base URL for the SEC EDGAR data APIs.",
    )
    user_agent: str = Field(
        "Stacklion/0.1 (+https://stacklion.io; support@stacklion.io)",
        description=(
            "User agent string sent to EDGAR. Must follow SEC guidelines and "
            "include contact details."
        ),
    )
    timeout_s: float = Field(
        8.0,
        description="Per-request timeout in seconds for the transport client.",
    )
    max_retries: int = Field(
        4,
        description="Maximum number of retry attempts for retryable failures.",
    )
    rate_limit_rps: float = Field(
        5.0,
        description=(
            "Logical client-side rate-limit in requests per second. This is a "
            "soft knob; enforcement is performed by higher-level rate-limiters."
        ),
    )

    model_config: SettingsConfigDict = SettingsConfigDict(
        env_prefix="EDGAR_",
        env_nested_delimiter="__",
        extra="ignore",
    )
