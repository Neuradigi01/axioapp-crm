"""Pin tests for the Step-6 shared condition AST + evaluator.

Covers all 14 leaf ops + AND / OR / NOT compounds + empty
``{}`` always-match + unknown-op rejection + path extraction +
the validate() schema check.
"""

from __future__ import annotations

import pytest

from src.app.core.events.conditions import (
    InvalidCondition,
    evaluate,
    evaluate_safe,
    extract_paths,
    validate,
)

_CONTEXT = {
    "contact": {
        "first_name": "Asha",
        "email": "asha@example.com",
        "phone": "+919876543210",
        "tags": ["vip", "newsletter"],
        "extra": None,
    },
    "lead": {
        "score": 75,
        "source": "google",
    },
}


# ---------------------------------------------------------------------------
# 14 leaf ops
# ---------------------------------------------------------------------------


def test_eq():
    assert evaluate(
        {"op": "eq", "path": "contact.first_name", "value": "Asha"},
        _CONTEXT,
    )
    assert not evaluate(
        {"op": "eq", "path": "contact.first_name", "value": "Other"},
        _CONTEXT,
    )


def test_neq():
    assert evaluate({"op": "neq", "path": "lead.source", "value": "meta"}, _CONTEXT)
    assert not evaluate({"op": "neq", "path": "lead.source", "value": "google"}, _CONTEXT)


def test_gt_gte_lt_lte():
    assert evaluate({"op": "gt", "path": "lead.score", "value": 50}, _CONTEXT)
    assert not evaluate({"op": "gt", "path": "lead.score", "value": 75}, _CONTEXT)
    assert evaluate({"op": "gte", "path": "lead.score", "value": 75}, _CONTEXT)
    assert evaluate({"op": "lt", "path": "lead.score", "value": 80}, _CONTEXT)
    assert evaluate({"op": "lte", "path": "lead.score", "value": 75}, _CONTEXT)


def test_in():
    assert evaluate(
        {"op": "in", "path": "lead.source", "value": ["google", "meta"]},
        _CONTEXT,
    )
    assert not evaluate({"op": "in", "path": "lead.source", "value": ["walk_in"]}, _CONTEXT)


def test_not_in():
    assert evaluate(
        {"op": "not_in", "path": "lead.source", "value": ["walk_in"]},
        _CONTEXT,
    )
    assert not evaluate(
        {"op": "not_in", "path": "lead.source", "value": ["google"]},
        _CONTEXT,
    )


def test_contains_string_and_list():
    # Substring on a string value.
    assert evaluate(
        {"op": "contains", "path": "contact.email", "value": "@example"},
        _CONTEXT,
    )
    # Membership in a list value.
    assert evaluate({"op": "contains", "path": "contact.tags", "value": "vip"}, _CONTEXT)
    assert not evaluate(
        {"op": "contains", "path": "contact.tags", "value": "missing"},
        _CONTEXT,
    )


def test_starts_with_ends_with():
    assert evaluate(
        {"op": "starts_with", "path": "contact.email", "value": "asha"},
        _CONTEXT,
    )
    assert evaluate(
        {"op": "ends_with", "path": "contact.email", "value": ".com"},
        _CONTEXT,
    )


def test_matches_regex():
    assert evaluate(
        {"op": "matches", "path": "contact.email", "value": r"^asha@.+\.com$"},
        _CONTEXT,
    )
    assert not evaluate(
        {"op": "matches", "path": "contact.email", "value": r"^xxx@.+$"},
        _CONTEXT,
    )


def test_exists_and_is_null():
    assert evaluate({"op": "exists", "path": "contact.first_name"}, _CONTEXT)
    assert not evaluate({"op": "exists", "path": "contact.missing"}, _CONTEXT)
    assert evaluate({"op": "is_null", "path": "contact.extra"}, _CONTEXT)
    assert evaluate({"op": "is_null", "path": "contact.missing"}, _CONTEXT)
    assert not evaluate({"op": "is_null", "path": "contact.first_name"}, _CONTEXT)


# ---------------------------------------------------------------------------
# Missing-data fail-closed
# ---------------------------------------------------------------------------


def test_eq_on_missing_path_fails_closed():
    """Leaf ops other than exists / is_null return False when the
    path doesn't resolve."""
    assert not evaluate({"op": "eq", "path": "contact.missing", "value": "x"}, _CONTEXT)


def test_gt_on_missing_path_fails_closed():
    assert not evaluate({"op": "gt", "path": "lead.missing_score", "value": 0}, _CONTEXT)


# ---------------------------------------------------------------------------
# Compound nodes
# ---------------------------------------------------------------------------


def test_all_short_circuits_on_first_false():
    cond = {
        "all": [
            {"op": "eq", "path": "lead.source", "value": "google"},
            {"op": "gt", "path": "lead.score", "value": 100},  # False
        ]
    }
    assert not evaluate(cond, _CONTEXT)


def test_any_short_circuits_on_first_true():
    cond = {
        "any": [
            {"op": "eq", "path": "lead.source", "value": "meta"},  # False
            {"op": "gt", "path": "lead.score", "value": 50},  # True
        ]
    }
    assert evaluate(cond, _CONTEXT)


def test_not_negates():
    cond = {"not": {"op": "eq", "path": "lead.source", "value": "meta"}}
    assert evaluate(cond, _CONTEXT)
    cond_negate_true = {"not": {"op": "eq", "path": "lead.source", "value": "google"}}
    assert not evaluate(cond_negate_true, _CONTEXT)


def test_empty_condition_is_always_match():
    assert evaluate({}, _CONTEXT)
    assert evaluate(None, _CONTEXT)


def test_unknown_op_raises():
    with pytest.raises(InvalidCondition):
        evaluate({"op": "wat", "path": "lead.score", "value": 1}, _CONTEXT)


def test_evaluate_safe_swallows_malformed():
    """evaluate_safe should return False for malformed AST instead
    of raising — used by the trigger handler so one bad workflow
    can't poison every event publish."""
    assert evaluate_safe({"op": "wat", "path": "x", "value": 1}, _CONTEXT) is False


# ---------------------------------------------------------------------------
# Path extraction (Step-19 diagnostics)
# ---------------------------------------------------------------------------


def test_extract_paths_walks_compound():
    cond = {
        "all": [
            {"op": "eq", "path": "contact.first_name", "value": "Asha"},
            {
                "any": [
                    {"op": "gt", "path": "lead.score", "value": 50},
                    {"op": "in", "path": "lead.source", "value": ["google"]},
                ]
            },
            {"not": {"op": "eq", "path": "contact.email", "value": "x"}},
        ]
    }
    paths = extract_paths(cond)
    assert paths == {
        "contact.first_name",
        "lead.score",
        "lead.source",
        "contact.email",
    }


# ---------------------------------------------------------------------------
# validate() schema check
# ---------------------------------------------------------------------------


def test_validate_accepts_well_formed():
    validate({"op": "eq", "path": "x", "value": 1})
    validate({})
    validate({"all": [{"op": "eq", "path": "x", "value": 1}]})


def test_validate_rejects_unknown_op():
    with pytest.raises(InvalidCondition):
        validate({"op": "wat", "path": "x", "value": 1})


def test_validate_rejects_missing_value():
    with pytest.raises(InvalidCondition):
        validate({"op": "eq", "path": "x"})


def test_validate_rejects_empty_all():
    with pytest.raises(InvalidCondition):
        validate({"all": []})


def test_validate_rejects_unknown_leaf_keys():
    with pytest.raises(InvalidCondition):
        validate({"op": "eq", "path": "x", "value": 1, "typo": "field"})


def test_validate_rejects_oversized_regex():
    big_pattern = "a" * 1500
    with pytest.raises(InvalidCondition):
        validate({"op": "matches", "path": "x", "value": big_pattern})


def test_validate_rejects_compound_with_leaf_keys():
    with pytest.raises(InvalidCondition):
        validate(
            {
                "all": [{"op": "eq", "path": "x", "value": 1}],
                "op": "eq",
                "path": "y",
                "value": 2,
            }
        )
