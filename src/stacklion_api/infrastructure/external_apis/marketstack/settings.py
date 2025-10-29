# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Marketstack Settings.

Summary:
    Pydantic settings for the Marketstack gateway.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class MarketstackSettings(BaseModel):
    """Configuration for Marketstack gateway."""

    model_config = ConfigDict(extra="forbid")

    # Use str for mypy friendliness; pydantic will still validate when loaded
    base_url: str = Field(default="https://api.marketstack.com/v2")
    access_key: SecretStr
    timeout_s: float = Field(default=5.0, ge=0.1, le=30.0)
    max_retries: int = Field(default=2, ge=0, le=5)
