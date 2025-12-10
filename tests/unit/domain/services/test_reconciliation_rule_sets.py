from stacklion_api.domain.entities.edgar_reconciliation import (
    CalendarReconciliationRule,
    IdentityReconciliationRule,
    ReconciliationRule,
)
from stacklion_api.domain.enums.edgar_reconciliation import ReconciliationRuleCategory
from stacklion_api.domain.services.reconciliation_rule_sets import (
    DEFAULT_E11_RULE_SET_ID,
    get_default_e11_rules,
)


def test_default_e11_ruleset_contains_expected_rules() -> None:
    rules = get_default_e11_rules()
    assert isinstance(rules, tuple)
    assert rules  # non-empty

    rule_ids = {r.rule_id for r in rules}
    assert "E11_IDENTITY_NET_CHANGE_CASH" in rule_ids
    assert "E11_IDENTITY_BALANCE_SHEET" in rule_ids
    assert "E11_CALENDAR_FYE_MONTH" in rule_ids

    # Sanity: categories
    by_id: dict[str, ReconciliationRule] = {r.rule_id: r for r in rules}
    assert isinstance(by_id["E11_IDENTITY_NET_CHANGE_CASH"], IdentityReconciliationRule)
    assert by_id["E11_IDENTITY_NET_CHANGE_CASH"].category is ReconciliationRuleCategory.IDENTITY

    assert isinstance(by_id["E11_IDENTITY_BALANCE_SHEET"], IdentityReconciliationRule)
    assert by_id["E11_IDENTITY_BALANCE_SHEET"].category is ReconciliationRuleCategory.IDENTITY

    assert isinstance(by_id["E11_CALENDAR_FYE_MONTH"], CalendarReconciliationRule)
    assert by_id["E11_CALENDAR_FYE_MONTH"].category is ReconciliationRuleCategory.CALENDAR


def test_default_ruleset_id_is_stable() -> None:
    assert DEFAULT_E11_RULE_SET_ID == "E11_RULESET_V1"
