"""Defense-in-depth pin: the condition evaluator returns no-match
for a field path the runtime payload doesn't carry.

The evaluator's core behaviour is exercised by the
``tasks/automation-engine`` test suite; this pin re-asserts it from
the ``tasks/automation-conditions/`` Step-4 perspective — legacy
triggers whose stored ``conditions`` reference retired field names
must not crash the dispatcher OR spuriously match every event.
"""

from __future__ import annotations

from src.app.core.automation.conditions import evaluate


def test_evaluator_returns_no_match_for_unknown_path():
    """Legacy trigger scenario: a stored condition references a
    field the current publisher no longer emits. The dot-path walk
    hits ``_MISSING`` on the leaf, which every operator treats as
    non-match — so the dispatcher writes the run row as skipped
    without ever raising."""
    condition = {"field": "lead.retired_widget_id", "op": "eq", "value": "banner_v2"}
    # Payload is a realistic `lead.created` envelope that does NOT
    # carry the retired path.
    payload = {
        "lead": {"id": "abc", "source": "widget", "pipeline_stage": "new"},
        "contact": {"email": "asha@example.com"},
    }
    assert evaluate(condition, payload) is False


def test_evaluator_returns_no_match_for_unknown_nested_path():
    """Path with an intermediate segment that doesn't exist either.
    Guards the same behaviour when the missing key is in the middle
    of the dot-chain (not just the leaf)."""
    condition = {"field": "lead.missing.deeply.nested", "op": "eq", "value": "x"}
    payload = {"lead": {"id": "abc"}}
    assert evaluate(condition, payload) is False


def test_evaluator_does_not_raise_when_intermediate_is_not_a_dict():
    """A path that expects to descend through a dict but hits a
    scalar mid-chain must return False, not raise."""
    condition = {"field": "lead.source.subfield", "op": "eq", "value": "x"}
    # `lead.source` is a string, so `.subfield` can't resolve.
    payload = {"lead": {"source": "widget"}}
    assert evaluate(condition, payload) is False
