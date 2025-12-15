# src/arche_api/adapters/presenters/edgar_overrides_presenter.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Presenter: XBRL mapping override observability → HTTP envelopes.

Purpose:
    Map application-layer override observability DTOs into canonical HTTP
    schemas and envelopes.

Layer:
    adapters/presenters
"""

from __future__ import annotations

from collections.abc import Iterable

from arche_api.adapters.schemas.http.edgar_overrides_schemas import (
    OverrideRuleApplicationHTTP,
    StatementOverrideTraceHTTP,
)
from arche_api.adapters.schemas.http.envelopes import SuccessEnvelope
from arche_api.application.schemas.dto.xbrl_overrides import (
    OverrideRuleApplicationDTO,
    StatementOverrideTraceDTO,
)
from arche_api.domain.services.xbrl_mapping_overrides import OverrideScope
from arche_api.infrastructure.logging.logger import get_json_logger

_LOGGER = get_json_logger(__name__)


def _scope_to_wire(scope_code: int) -> str:
    """Convert an OverrideScope integer code to a string for the wire.

    Falls back to ``str(scope_code)`` if the code is unknown, to preserve
    forward-compatibility instead of raising.
    """
    try:
        return OverrideScope(scope_code).name
    except ValueError:  # pragma: no cover - defensive
        return str(scope_code)


def _map_override_rule_dto_to_http(
    dto: OverrideRuleApplicationDTO,
) -> OverrideRuleApplicationHTTP:
    """Map an OverrideRuleApplicationDTO to its HTTP schema."""
    scope_str = _scope_to_wire(dto.scope)

    return OverrideRuleApplicationHTTP(
        rule_id=dto.rule_id,
        scope=scope_str,
        priority=dto.priority,
        action=dto.action,
        source_concept=dto.source_concept,
        target_metric_code=dto.target_metric_code,
        target_dimension_key=dto.target_dimension_key,
        is_effective=dto.is_effective,
        reason=dto.reason,
        contributes_to_metrics=dto.contributes_to_metrics,
    )


def _sort_rules_for_wire(
    rules: Iterable[OverrideRuleApplicationDTO],
) -> list[OverrideRuleApplicationDTO]:
    """Deterministically sort override rule applications for wire stability.

    Ordering:
        * scope (ascending numeric code)
        * priority (descending business priority, so higher wins)
        * rule_id (ascending lexicographic)
    """
    return sorted(
        rules,
        key=lambda r: (
            r.scope,
            -r.priority,
            r.rule_id,
        ),
    )


def present_statement_override_trace(
    dto: StatementOverrideTraceDTO,
) -> SuccessEnvelope[StatementOverrideTraceHTTP]:
    """Present a statement-level override trace as a SuccessEnvelope.

    The rules collection is sorted deterministically by:

        * scope (ascending)
        * priority (descending; higher values win)
        * rule_id (ascending)
    """
    sorted_rules = _sort_rules_for_wire(dto.rules)
    rules_http = [_map_override_rule_dto_to_http(r) for r in sorted_rules]

    payload = StatementOverrideTraceHTTP(
        cik=dto.cik,
        statement_type=dto.statement_type.value,
        fiscal_year=dto.fiscal_year,
        fiscal_period=dto.fiscal_period.value,
        version_sequence=dto.version_sequence,
        gaap_concept=dto.gaap_concept,
        canonical_metric_code=dto.canonical_metric_code,
        dimension_key=dto.dimension_key,
        total_facts_evaluated=dto.total_facts_evaluated,
        total_facts_remapped=dto.total_facts_remapped,
        total_facts_suppressed=dto.total_facts_suppressed,
        rules=rules_http,
    )

    _LOGGER.info(
        "edgar_presenter_statement_override_trace",
        extra={
            "cik": dto.cik,
            "statement_type": dto.statement_type.value,
            "fiscal_year": dto.fiscal_year,
            "fiscal_period": dto.fiscal_period.value,
            "version_sequence": dto.version_sequence,
            "gaap_concept": dto.gaap_concept,
            "canonical_metric_code": dto.canonical_metric_code,
            "dimension_key": dto.dimension_key,
            "total_facts_evaluated": dto.total_facts_evaluated,
            "total_facts_remapped": dto.total_facts_remapped,
            "total_facts_suppressed": dto.total_facts_suppressed,
            "rules": len(rules_http),
        },
    )

    return SuccessEnvelope(data=payload)
