"""Pure-function condition evaluator for automation triggers.

A *condition* is a JSONB tree. Two shapes:

  Leaf  — ``{"field": "lead.source", "op": "in", "value": [...]}``
  Branch — ``{"all": [<condition>, ...]}`` (AND) or
           ``{"any": [<condition>, ...]}`` (OR) or
           ``{"not": <condition>}``

Empty ``{}`` is the "always match" default — fresh triggers + the
seeded defaults use it. Malformed conditions evaluate to **False**
(fail-closed); the matcher logs once and moves on, so a single
broken trigger can't poison every event publish.

``field`` is a dot-path into the published payload, e.g.
``contact.email`` reads ``payload["contact"]["email"]``. Missing
intermediate keys resolve to ``None`` without raising — the leaf op
then decides whether ``None`` counts as a match (``is_null``,
``not_exists`` say yes; ``eq``, ``gt`` etc. say no).

Thirteen ops:

* Equality      — ``eq``, ``ne``
* Membership    — ``in``, ``not_in``
* Strings       — ``contains``, ``starts_with``, ``ends_with``
* Numbers       — ``gt``, ``gte``, ``lt``, ``lte``
* Presence      — ``exists``, ``not_exists``
* Pattern       — ``regex`` (cap pattern at 200 chars; compile +
                  match in a try/except to defang ReDoS)

The evaluator is intentionally I/O-free. The recipient resolver
(:mod:`core.automation.recipients`) does its own DB lookups when the
payload doesn't carry the relevant contact/user dict; conditions
operate only on what's in the published envelope.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# Pattern length cap — mirrors the WhatsApp keyword-engine ReDoS
# defenses from ``whatsapp-platform-upgrade`` Step 17.
_REGEX_MAX_LEN = 200

_VALID_OPS: frozenset[str] = frozenset(
    {
        "eq",
        "ne",
        "in",
        "not_in",
        "contains",
        "starts_with",
        "ends_with",
        "gt",
        "gte",
        "lt",
        "lte",
        "exists",
        "not_exists",
        "regex",
    }
)


_MISSING = object()


def evaluate(condition: Any, payload: dict[str, Any]) -> bool:
    """Return True iff ``payload`` matches ``condition``.

    Empty ``{}`` is the always-match default. Malformed conditions
    fail closed (return False + log once).
    """
    if condition is None or condition == {}:
        return True
    if not isinstance(condition, dict):
        logger.warning("automation.conditions malformed_root condition=%r", condition)
        return False
    try:
        return _eval_node(condition, payload)
    except _ConditionError as exc:
        logger.warning(
            "automation.conditions malformed reason=%s condition=%r",
            exc.reason,
            condition,
        )
        return False
    except Exception:
        # Defensive — anything we didn't explicitly type as
        # _ConditionError shouldn't take the publisher down.
        logger.exception("automation.conditions evaluator_crashed")
        return False


def validate(condition: Any) -> None:
    """Raise :class:`InvalidCondition` if the shape is broken.

    Service-layer ``create_trigger`` / ``update_trigger`` call this
    so the operator sees a 422 at save time instead of silently
    fail-closing at every event publish."""
    from src.app.core.automation.exceptions import InvalidCondition

    if condition is None or condition == {}:
        return
    if not isinstance(condition, dict):
        raise InvalidCondition("root must be a JSON object or empty {}")
    try:
        _validate_node(condition)
    except _ConditionError as exc:
        raise InvalidCondition(exc.reason) from exc


# --- internals --------------------------------------------------------


class _ConditionError(Exception):
    """Internal — bubbles up to ``evaluate`` (which logs + returns
    False) or to ``validate`` (which re-raises as
    :class:`InvalidCondition`)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _eval_node(node: dict[str, Any], payload: dict[str, Any]) -> bool:
    if "all" in node:
        children = node["all"]
        if not isinstance(children, list) or not children:
            raise _ConditionError("'all' requires a non-empty list of conditions")
        return all(_eval_node(c, payload) if isinstance(c, dict) else False for c in children)
    if "any" in node:
        children = node["any"]
        if not isinstance(children, list) or not children:
            raise _ConditionError("'any' requires a non-empty list of conditions")
        return any(_eval_node(c, payload) if isinstance(c, dict) else False for c in children)
    if "not" in node:
        inner = node["not"]
        if not isinstance(inner, dict):
            raise _ConditionError("'not' requires a nested condition object")
        return not _eval_node(inner, payload)
    return _eval_leaf(node, payload)


def _validate_node(node: dict[str, Any]) -> None:
    if "all" in node or "any" in node:
        key = "all" if "all" in node else "any"
        children = node[key]
        if not isinstance(children, list) or not children:
            raise _ConditionError(f"'{key}' requires a non-empty list of conditions")
        for child in children:
            if not isinstance(child, dict):
                raise _ConditionError(f"'{key}' children must be condition objects")
            _validate_node(child)
        return
    if "not" in node:
        inner = node["not"]
        if not isinstance(inner, dict):
            raise _ConditionError("'not' requires a nested condition object")
        _validate_node(inner)
        return
    _validate_leaf(node)


def _validate_leaf(node: dict[str, Any]) -> None:
    op = node.get("op")
    if op not in _VALID_OPS:
        raise _ConditionError(f"unknown op {op!r}; expected one of {sorted(_VALID_OPS)}")
    field = node.get("field")
    if not isinstance(field, str) or not field:
        raise _ConditionError("leaf condition requires a non-empty 'field' string")
    if op in ("exists", "not_exists"):
        return
    if "value" not in node:
        raise _ConditionError(f"leaf condition with op {op!r} requires 'value'")
    if op == "regex":
        pattern = node["value"]
        if not isinstance(pattern, str):
            raise _ConditionError("'regex' op requires a string pattern")
        if len(pattern) > _REGEX_MAX_LEN:
            raise _ConditionError(f"'regex' pattern exceeds {_REGEX_MAX_LEN}-char cap")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise _ConditionError(f"'regex' pattern does not compile: {exc}")


def _eval_leaf(node: dict[str, Any], payload: dict[str, Any]) -> bool:
    op = node.get("op")
    if op not in _VALID_OPS:
        raise _ConditionError(f"unknown op {op!r}")
    field = node.get("field")
    if not isinstance(field, str) or not field:
        raise _ConditionError("leaf condition requires a 'field' string")
    actual = _read_path(payload, field)

    if op == "exists":
        return actual is not _MISSING and actual is not None
    if op == "not_exists":
        return actual is _MISSING or actual is None

    if actual is _MISSING:
        # Every other op needs a real value; missing fields never match.
        return False

    if "value" not in node:
        raise _ConditionError(f"leaf condition with op {op!r} requires 'value'")
    expected = node["value"]

    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "in":
        return isinstance(expected, (list, tuple, set)) and actual in expected
    if op == "not_in":
        return isinstance(expected, (list, tuple, set)) and actual not in expected
    if op == "contains":
        if isinstance(actual, str) and isinstance(expected, str):
            return expected in actual
        if isinstance(actual, (list, tuple, set)):
            return expected in actual
        return False
    if op == "starts_with":
        return isinstance(actual, str) and isinstance(expected, str) and actual.startswith(expected)
    if op == "ends_with":
        return isinstance(actual, str) and isinstance(expected, str) and actual.endswith(expected)
    if op in ("gt", "gte", "lt", "lte"):
        try:
            if op == "gt":
                return actual > expected
            if op == "gte":
                return actual >= expected
            if op == "lt":
                return actual < expected
            return actual <= expected
        except TypeError:
            return False
    if op == "regex":
        if not isinstance(actual, str) or not isinstance(expected, str):
            return False
        if len(expected) > _REGEX_MAX_LEN:
            return False
        try:
            return bool(re.search(expected, actual))
        except re.error:
            return False

    # Shouldn't reach here — every op above is exhaustively handled.
    raise _ConditionError(f"unsupported op {op!r}")


def _read_path(payload: dict[str, Any], dotted: str) -> Any:
    """Walk ``dotted`` against ``payload`` and return the value or
    :data:`_MISSING` for any missing intermediate. Never raises."""
    cursor: Any = payload
    for segment in dotted.split("."):
        if cursor is None:
            return _MISSING
        if isinstance(cursor, dict):
            if segment not in cursor:
                return _MISSING
            cursor = cursor[segment]
            continue
        return _MISSING
    return cursor


__all__ = ["evaluate", "validate"]
