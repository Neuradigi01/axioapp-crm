"""Pin tests for the Step-2 condition evaluator.

The evaluator is the most-touched piece of automation — every event
publish hits it once per matching trigger. Test coverage skews
heavy on the truth table + edge cases (missing fields, malformed
input, ReDoS defense).
"""

from __future__ import annotations

import pytest

from src.app.core.automation import conditions
from src.app.core.automation.exceptions import InvalidCondition

# --- ops ----------------------------------------------------------


def test_empty_condition_evaluates_true():
    assert conditions.evaluate({}, {"lead": {"source": "website"}}) is True


def test_eq_op():
    cond = {"field": "lead.source", "op": "eq", "value": "website"}
    assert conditions.evaluate(cond, {"lead": {"source": "website"}}) is True
    assert conditions.evaluate(cond, {"lead": {"source": "ads"}}) is False


def test_ne_op():
    cond = {"field": "lead.source", "op": "ne", "value": "website"}
    assert conditions.evaluate(cond, {"lead": {"source": "ads"}}) is True
    assert conditions.evaluate(cond, {"lead": {"source": "website"}}) is False


def test_in_op():
    cond = {
        "field": "lead.source",
        "op": "in",
        "value": ["website", "meta_ads"],
    }
    assert conditions.evaluate(cond, {"lead": {"source": "website"}}) is True
    assert conditions.evaluate(cond, {"lead": {"source": "google_ads"}}) is False


def test_not_in_op():
    cond = {
        "field": "lead.source",
        "op": "not_in",
        "value": ["spam", "test"],
    }
    assert conditions.evaluate(cond, {"lead": {"source": "website"}}) is True
    assert conditions.evaluate(cond, {"lead": {"source": "spam"}}) is False


def test_contains_op_string():
    cond = {"field": "lead.notes", "op": "contains", "value": "urgent"}
    assert conditions.evaluate(cond, {"lead": {"notes": "this is urgent"}}) is True
    assert conditions.evaluate(cond, {"lead": {"notes": "no rush"}}) is False


def test_contains_op_list():
    cond = {"field": "contact.tags", "op": "contains", "value": "vip"}
    assert conditions.evaluate(cond, {"contact": {"tags": ["vip", "new"]}}) is True


def test_starts_with_op():
    cond = {"field": "contact.email", "op": "starts_with", "value": "asha"}
    assert conditions.evaluate(cond, {"contact": {"email": "asha@x.com"}}) is True
    assert conditions.evaluate(cond, {"contact": {"email": "rahul@x.com"}}) is False


def test_ends_with_op():
    cond = {"field": "contact.email", "op": "ends_with", "value": "@org.com"}
    assert conditions.evaluate(cond, {"contact": {"email": "a@org.com"}}) is True
    assert conditions.evaluate(cond, {"contact": {"email": "a@other.com"}}) is False


def test_gt_gte_lt_lte_ops():
    payload = {"lead": {"score": 75}}
    assert conditions.evaluate({"field": "lead.score", "op": "gt", "value": 50}, payload) is True
    assert conditions.evaluate({"field": "lead.score", "op": "gte", "value": 75}, payload) is True
    assert conditions.evaluate({"field": "lead.score", "op": "lt", "value": 80}, payload) is True
    assert conditions.evaluate({"field": "lead.score", "op": "lte", "value": 75}, payload) is True
    assert conditions.evaluate({"field": "lead.score", "op": "gt", "value": 80}, payload) is False


def test_exists_and_not_exists_ops():
    payload = {"contact": {"email": "a@x.com"}}
    assert conditions.evaluate({"field": "contact.email", "op": "exists"}, payload) is True
    assert conditions.evaluate({"field": "contact.phone", "op": "exists"}, payload) is False
    assert conditions.evaluate({"field": "contact.phone", "op": "not_exists"}, payload) is True
    assert conditions.evaluate({"field": "contact.email", "op": "not_exists"}, payload) is False


def test_regex_op_matches():
    cond = {
        "field": "contact.email",
        "op": "regex",
        "value": r"^[^@]+@example\.com$",
    }
    assert conditions.evaluate(cond, {"contact": {"email": "a@example.com"}}) is True
    assert conditions.evaluate(cond, {"contact": {"email": "a@other.com"}}) is False


def test_regex_op_caps_pattern_length():
    """A 300-char pattern fails closed (returns False) — defends
    against operator-supplied ReDoS patterns."""
    cond = {
        "field": "contact.email",
        "op": "regex",
        "value": "a" * 300,
    }
    assert conditions.evaluate(cond, {"contact": {"email": "aaa"}}) is False


def test_regex_op_invalid_pattern_returns_false():
    cond = {"field": "x", "op": "regex", "value": "[unclosed"}
    assert conditions.evaluate(cond, {"x": "anything"}) is False


# --- nesting ------------------------------------------------------


def test_all_and_branch():
    cond = {
        "all": [
            {"field": "lead.source", "op": "eq", "value": "website"},
            {"field": "lead.score", "op": "gte", "value": 50},
        ]
    }
    assert conditions.evaluate(cond, {"lead": {"source": "website", "score": 75}}) is True
    assert conditions.evaluate(cond, {"lead": {"source": "website", "score": 20}}) is False
    assert conditions.evaluate(cond, {"lead": {"source": "ads", "score": 75}}) is False


def test_any_or_branch():
    cond = {
        "any": [
            {"field": "lead.source", "op": "eq", "value": "website"},
            {"field": "lead.source", "op": "eq", "value": "meta_ads"},
        ]
    }
    assert conditions.evaluate(cond, {"lead": {"source": "website"}}) is True
    assert conditions.evaluate(cond, {"lead": {"source": "meta_ads"}}) is True
    assert conditions.evaluate(cond, {"lead": {"source": "google_ads"}}) is False


def test_not_branch():
    cond = {"not": {"field": "contact.tags", "op": "contains", "value": "spam"}}
    assert conditions.evaluate(cond, {"contact": {"tags": ["new"]}}) is True
    assert conditions.evaluate(cond, {"contact": {"tags": ["spam"]}}) is False


def test_nested_and_or_combination():
    cond = {
        "all": [
            {"field": "lead.score", "op": "gte", "value": 50},
            {
                "any": [
                    {"field": "lead.source", "op": "eq", "value": "website"},
                    {"field": "lead.source", "op": "eq", "value": "referral"},
                ]
            },
        ]
    }
    assert conditions.evaluate(cond, {"lead": {"score": 80, "source": "website"}}) is True
    assert conditions.evaluate(cond, {"lead": {"score": 80, "source": "referral"}}) is True
    assert conditions.evaluate(cond, {"lead": {"score": 80, "source": "ads"}}) is False
    assert conditions.evaluate(cond, {"lead": {"score": 30, "source": "website"}}) is False


# --- safety -------------------------------------------------------


def test_missing_field_returns_false_without_raising():
    cond = {"field": "lead.estimated_value", "op": "gt", "value": 1000}
    # No 'lead' key in payload — must return False, not raise.
    assert conditions.evaluate(cond, {}) is False
    assert conditions.evaluate(cond, {"lead": None}) is False


def test_malformed_condition_returns_false():
    """Unknown op + missing field at the root both fail-closed."""
    assert conditions.evaluate({"op": "weird"}, {}) is False
    assert conditions.evaluate({"field": "x"}, {}) is False  # no op


def test_malformed_condition_does_not_raise():
    """One bad trigger condition shouldn't take down the publisher."""
    # The evaluator catches every exception and returns False.
    assert conditions.evaluate("not a dict", {}) is False
    assert conditions.evaluate(["a", "b"], {}) is False


# --- validate() -------------------------------------------------


def test_validate_accepts_empty_dict():
    conditions.validate({})  # no raise


def test_validate_rejects_unknown_op():
    with pytest.raises(InvalidCondition):
        conditions.validate({"field": "x", "op": "weird", "value": 1})


def test_validate_rejects_missing_field():
    with pytest.raises(InvalidCondition):
        conditions.validate({"op": "eq", "value": 1})


def test_validate_rejects_oversized_regex():
    with pytest.raises(InvalidCondition):
        conditions.validate({"field": "x", "op": "regex", "value": "a" * 300})


def test_validate_walks_nested_branches():
    with pytest.raises(InvalidCondition):
        conditions.validate({"all": [{"field": "x", "op": "weird", "value": 1}]})
