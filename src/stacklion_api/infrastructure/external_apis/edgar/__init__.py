# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""EDGAR external API package.

Purpose:
    Group EDGAR-related infrastructure modules:

    * settings: Pydantic settings for the EDGAR client.
    * client: Resilient async HTTP client for SEC EDGAR.
    * types: Typed response fragments for EDGAR endpoints.
"""

from __future__ import annotations
