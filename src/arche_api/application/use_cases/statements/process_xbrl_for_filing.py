# src/arche_api/application/use_cases/statements/process_xbrl_for_filing.py
# SPDX-License-Identifier: MIT
"""Compatibility shim for XBRL processing use case.

Purpose:
    Historically, statement-related use-cases lived under
    ``application/use_cases/statements``. Phase E10 introduced the
    XBRL-processing pipeline under the external-API oriented namespace:

        arche_api.application.use_cases.external_apis.edgar.process_xbrl_for_filing

    To avoid churn in call sites that may import from the statements namespace,
    this module simply re-exports the canonical implementation.

Layer:
    application/use_cases/statements
"""

from __future__ import annotations

from arche_api.application.use_cases.external_apis.edgar.process_xbrl_for_filing import (
    ProcessXBRLForFilingRequest,
    ProcessXBRLForFilingResult,
    ProcessXBRLForFilingUseCase,
)

__all__ = [
    "ProcessXBRLForFilingRequest",
    "ProcessXBRLForFilingResult",
    "ProcessXBRLForFilingUseCase",
]
