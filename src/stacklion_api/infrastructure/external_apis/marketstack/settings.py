# Copyright (c)
# SPDX-License-Identifier: MIT
"""Pydantic settings for the Marketstack transport client."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_allowed_intervals() -> list[str]:
    """Default intraday intervals if env is not set."""
    return ["1h", "30min", "15min"]


class MarketstackSettings(BaseSettings):
    """Configuration for the Marketstack V2 client.

    Environment variables (with ``model_config.env_prefix``):

    * ``MARKETSTACK_BASE_URL``
    * ``MARKETSTACK_ACCESS_KEY``
    * ``MARKETSTACK_TIMEOUT_S``
    * ``MARKETSTACK_MAX_RETRIES``
    * ``MARKETSTACK_ALLOWED_INTRADAY_INTERVALS`` (comma-separated list)
    """

    base_url: str = Field(
        "https://api.marketstack.com/v2",
        description="Base URL for the Marketstack V2 API.",
    )
    access_key: SecretStr = Field(
        ...,
        description="Marketstack API access key.",
    )
    timeout_s: float = Field(
        8.0,
        description="Per-request timeout in seconds for the transport client.",
    )
    max_retries: int = Field(
        4,
        description="Maximum number of retry attempts for retryable failures.",
    )
    # Raw env value (comma-separated); we normalize in a property below.
    allowed_intraday_intervals_raw: str | None = Field(
        None,
        description="Comma-separated allowed intraday intervals from env.",
    )

    model_config: SettingsConfigDict = SettingsConfigDict(
        env_prefix="MARKETSTACK_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @property
    def allowed_intraday_intervals(self) -> list[str]:
        """Return normalized intraday intervals (lowercased, stripped)."""
        raw = self.allowed_intraday_intervals_raw
        if not raw:
            return _default_allowed_intervals()
        parts: Iterable[str] = (p.strip().lower() for p in raw.split(","))
        return [p for p in parts if p]
