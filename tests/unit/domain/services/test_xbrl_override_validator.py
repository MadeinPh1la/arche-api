from __future__ import annotations

from dataclasses import replace

import pytest

from arche_api.domain.entities.xbrl_override_admin import (
    OverrideRuleDraft,
    OverrideRuleVersion,
)
from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.exceptions.edgar import EdgarMappingError
from arche_api.domain.services.xbrl_mapping_overrides import OverrideScope
from arche_api.domain.services.xbrl_override_validator import OverrideRuleValidator


def _base_draft(scope: OverrideScope) -> OverrideRuleDraft:
    return OverrideRuleDraft(
        scope=scope,
        source_concept="us-gaap:Revenues",
        source_taxonomy="US_GAAP_2024",
        match_cik=None,
        match_industry_code=None,
        match_analyst_id=None,
        match_dimensions={},
        target_metric=CanonicalStatementMetric.REVENUE,
        is_suppression=False,
        priority=0,
    )


def test_validate_global_ok() -> None:
    validator = OverrideRuleValidator()
    draft = _base_draft(OverrideScope.GLOBAL)

    # Should not raise
    validator.validate_for_create(draft)


def test_validate_global_rejects_match_fields() -> None:
    validator = OverrideRuleValidator()
    draft = _base_draft(OverrideScope.GLOBAL)
    draft_with_cik = replace(draft, match_cik="0000123456")

    with pytest.raises(EdgarMappingError):
        validator.validate_for_create(draft_with_cik)


def test_validate_industry_requires_industry_code_and_no_cik() -> None:
    validator = OverrideRuleValidator()

    # Missing industry code
    draft_missing = _base_draft(OverrideScope.INDUSTRY)
    with pytest.raises(EdgarMappingError):
        validator.validate_for_create(draft_missing)

    # With industry code but illegal CIK
    draft_bad = replace(
        draft_missing,
        match_industry_code="45102010",
        match_cik="0000123456",
    )
    with pytest.raises(EdgarMappingError):
        validator.validate_for_create(draft_bad)


def test_validate_company_requires_cik() -> None:
    validator = OverrideRuleValidator()
    draft = _base_draft(OverrideScope.COMPANY)

    with pytest.raises(EdgarMappingError):
        validator.validate_for_create(draft)

    draft_ok = replace(draft, match_cik="0000123456")
    validator.validate_for_create(draft_ok)


def test_validate_analyst_requires_analyst_id() -> None:
    validator = OverrideRuleValidator()
    draft = _base_draft(OverrideScope.ANALYST)

    with pytest.raises(EdgarMappingError):
        validator.validate_for_create(draft)

    draft_ok = replace(draft, match_analyst_id="analyst-1")
    validator.validate_for_create(draft_ok)


def test_validate_suppression_cannot_have_target_metric() -> None:
    validator = OverrideRuleValidator()
    draft = _base_draft(OverrideScope.GLOBAL)
    draft_suppression = replace(draft, is_suppression=True)

    with pytest.raises(EdgarMappingError):
        validator.validate_for_create(draft_suppression)


def test_validate_priority_non_negative() -> None:
    validator = OverrideRuleValidator()
    draft = _base_draft(OverrideScope.GLOBAL)
    draft_bad = replace(draft, priority=-1)

    with pytest.raises(EdgarMappingError):
        validator.validate_for_create(draft_bad)


def test_validate_for_update_and_deprecate_noop() -> None:
    validator = OverrideRuleValidator()
    draft = _base_draft(OverrideScope.GLOBAL)
    version = OverrideRuleVersion(
        rule_id="rule-1",
        version_sequence=1,
        is_active=True,
        deprecation_reason=None,
        draft=draft,
    )

    # Should not raise for a valid update.
    validator.validate_for_update(existing=version, draft=draft)

    # Deprecation hook is currently a no-op.
    validator.validate_for_deprecate(existing=version)
