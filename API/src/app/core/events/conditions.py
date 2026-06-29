"""Shared predicate AST + evaluator.

Used by:

  * **Workflows track** (Step 6) — trigger-node conditions filter
    inbound events; branch / switch nodes pick edges by predicate.
  * **Module B (future)** — automation triggers will migrate from
    :mod:`core.automation.conditions` (which uses the older
    ``field``/``ne``/``regex``/``not_exists`` shape) onto this shared
    module so both engines share one AST. The migration is a
    follow-up: Module B's seeds are written in the older shape and
    don't break until they're hand-converted.

The AST is JSON-shaped — operators author it via the canvas
node-editor (Step 15) and we never `eval()` user input. Strict JSON
only; unexpected keys at any level raise :class:`InvalidCondition`.

Leaf shape:

.. code-block:: json

    {"op": "eq", "path": "contact.first_name", "value": "Asha"}

  * ``op`` — one of the 14 supported operators (see
    :data:`SUPPORTED_OPS`).
  * ``path`` — dot-path into the context dict. Missing intermediate
    keys resolve to ``None`` without raising; the leaf op then
    decides whether ``None`` matches.
  * ``value`` — the comparison RHS. Optional for ``exists`` /
    ``is_null``.

Compound shape:

.. code-block:: json

    {"all": [<node>, ...]}    // AND — short-circuits on first False
    {"any": [<node>, ...]}    // OR — short-circuits on first True
    {"not": <node>}           // NOT — single child

Empty ``{}`` returns True — the "always match" default for fresh
triggers + the seeded workflows.
"""
from __future__ import annotations

import logging
import re
from typing import Any


logger = logging.getLogger(__name__)


class InvalidCondition(ValueError):
    """Raised when the AST shape is malformed (unknown op, missing
    required key, non-list children, etc.). The Step-2 graph
    validator + the Step-15 node-editor's save handler catch this
    + surface the reason to the operator."""


SUPPORTED_OPS: frozenset[str] = frozenset(
    {
        "eq",
        "neq",
        "gt",
        "gte",
        "lt",
        "lte",
        "in",
        "not_in",
        "contains",
        "starts_with",
        "ends_with",
        "matches",
        "exists",
        "is_null",
    }
)

# ReDoS defence — accept user-supplied regex but cap the source-text
# length. Stricter than necessary for typical operator use; loose
# enough to support common email / phone patterns.
_REGEX_MAX_LEN = 1000

# Sentinel used by the dot-path resolver to distinguish "key missing
# from the context" vs "key present but None".
_MISSING = object()


# --- Dot-path resolution -------------------------------------------------


def _resolve_path(context: Any, path: str) -> Any:
    """Walk a dot-path into the context dict. Returns the literal
    value at the leaf, or :data:`_MISSING` if any intermediate key
    is absent.

    The resolver tolerates non-dict intermediates by returning
    ``_MISSING`` — so ``contact.email`` against
    ``{"contact": None}`` resolves to missing, not a TypeError."""
    current: Any = context
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        return _MISSING
    return current


# --- Leaf evaluation -----------------------------------------------------


def _eval_leaf(node: dict[str, Any], context: Any) -> bool:
    op = node.get("op")
    path = node.get("path")
    if not isinstance(op, str) or not isinstance(path, str) or not path:
        raise InvalidCondition(
            "leaf node missing 'op' or 'path' (both required strings)"
        )
    if op not in SUPPORTED_OPS:
        raise InvalidCondition(f"unsupported op '{op}'")

    value = _resolve_path(context, path)

    # Presence ops — operate on the resolution-result sentinel.
    if op == "exists":
        return value is not _MISSING
    if op == "is_null":
        return value is _MISSING or value is None

    # Every other op fails-False when the path resolved to missing
    # or null. Matches the "fail-closed on missing data" convention
    # the automation engine already uses.
    if value is _MISSING or value is None:
        return False

    target = node.get("value")

    if op == "eq":
        return value == target
    if op == "neq":
        return value != target
    if op == "gt":
        return _safe_compare(value, target, lambda a, b: a > b)
    if op == "gte":
        return _safe_compare(value, target, lambda a, b: a >= b)
    if op == "lt":
        return _safe_compare(value, target, lambda a, b: a < b)
    if op == "lte":
        return _safe_compare(value, target, lambda a, b: a <= b)
    if op == "in":
        if not isinstance(target, (list, tuple, set)):
            raise InvalidCondition("'in' value must be a list")
        return value in target
    if op == "not_in":
        if not isinstance(target, (list, tuple, set)):
            raise InvalidCondition("'not_in' value must be a list")
        return value not in target
    if op == "contains":
        return _safe_contains(value, target)
    if op == "starts_with":
        return isinstance(value, str) and isinstance(target, str) and value.startswith(target)
    if op == "ends_with":
        return isinstance(value, str) and isinstance(target, str) and value.endswith(target)
    if op == "matches":
        return _safe_regex_match(value, target)

    # Unreachable — SUPPORTED_OPS guard above covers all 14 ops.
    raise InvalidCondition(f"unhandled op '{op}'")


def _safe_compare(left: Any, right: Any, fn) -> bool:
    """Numeric / lexicographic comparison with TypeError swallowed —
    e.g. ``gt`` on a string vs a number returns False instead of
    raising."""
    try:
        return bool(fn(left, right))
    except TypeError:
        return False


def _safe_contains(haystack: Any, needle: Any) -> bool:
    """``contains`` is overloaded: substring for strings, membership
    for lists / tuples / sets, key-presence for dicts."""
    try:
        return needle in haystack
    except TypeError:
        return False


def _safe_regex_match(value: Any, pattern: Any) -> bool:
    if not isinstance(value, str) or not isinstance(pattern, str):
        return False
    if len(pattern) > _REGEX_MAX_LEN:
        return False
    try:
        return re.search(pattern, value) is not None
    except re.error:
        return False


# --- Compound + entry point ---------------------------------------------


def evaluate(node: Any, context: Any) -> bool:
    """Recursive walker over the AST. Returns True/False. Raises
    :class:`InvalidCondition` for malformed shapes — callers
    that want fail-closed semantics catch the exception + treat
    it as False."""
    if node is None:
        return True
    if not isinstance(node, dict):
        raise InvalidCondition(
            "condition must be a dict (got " f"{type(node).__name__})"
        )
    if not node:
        # Empty {} is the always-match default.
        return True

    if "all" in node:
        children = node["all"]
        if not isinstance(children, list):
            raise InvalidCondition("'all' must be a list")
        return all(evaluate(child, context) for child in children)
    if "any" in node:
        children = node["any"]
        if not isinstance(children, list):
            raise InvalidCondition("'any' must be a list")
        return any(evaluate(child, context) for child in children)
    if "not" in node:
        return not evaluate(node["not"], context)

    return _eval_leaf(node, context)


def evaluate_safe(node: Any, context: Any) -> bool:
    """Wrapper that swallows :class:`InvalidCondition` and returns
    False. The Step-5 trigger handler calls this — a single broken
    workflow can't poison every event publish."""
    try:
        return evaluate(node, context)
    except InvalidCondition as exc:
        logger.warning(
            "events.conditions.evaluate_safe rejected_condition: %s", exc
        )
        return False


# --- Validation ---------------------------------------------------------


def validate(node: Any) -> None:
    """Schema-shape check for the AST. Used by the Step-2 graph
    validator + the Step-15 node-editor's save handler so the
    operator gets a 422 with a friendly reason BEFORE the workflow
    publishes."""
    if node is None or node == {}:
        return
    if not isinstance(node, dict):
        raise InvalidCondition(
            "condition must be a dict (got " f"{type(node).__name__})"
        )

    compound_keys = {"all", "any", "not"} & set(node.keys())
    if compound_keys:
        if len(compound_keys) > 1:
            raise InvalidCondition(
                "condition must use exactly one of all/any/not, "
                f"got {sorted(compound_keys)}"
            )
        key = next(iter(compound_keys))
        if key in ("all", "any"):
            children = node[key]
            if not isinstance(children, list) or not children:
                raise InvalidCondition(
                    f"'{key}' must be a non-empty list of conditions"
                )
            for child in children:
                validate(child)
        else:  # not
            validate(node["not"])
        # Compound nodes cannot carry leaf fields.
        leaf_fields = {"op", "path", "value"} & set(node.keys())
        if leaf_fields:
            raise InvalidCondition(
                f"compound condition cannot also carry leaf fields "
                f"{sorted(leaf_fields)}"
            )
        return

    # Leaf shape.
    op = node.get("op")
    path = node.get("path")
    if not isinstance(op, str) or op not in SUPPORTED_OPS:
        raise InvalidCondition(
            f"leaf condition has invalid 'op': {op!r}"
        )
    if not isinstance(path, str) or not path:
        raise InvalidCondition(
            "leaf condition missing non-empty 'path'"
        )
    # `exists` and `is_null` don't need `value`; everything else does.
    if op not in ("exists", "is_null") and "value" not in node:
        raise InvalidCondition(
            f"leaf condition '{op}' requires a 'value'"
        )
    # Cap regex pattern length at validate time so the editor
    # surfaces the rejection instead of silently fail-False'ing at
    # runtime.
    if op == "matches":
        pattern = node.get("value")
        if not isinstance(pattern, str):
            raise InvalidCondition("'matches' value must be a string regex")
        if len(pattern) > _REGEX_MAX_LEN:
            raise InvalidCondition(
                f"'matches' regex exceeds {_REGEX_MAX_LEN}-char cap"
            )
        try:
            re.compile(pattern)
        except re.error as exc:
            raise InvalidCondition(f"invalid regex: {exc}") from exc

    # Reject any unexpected keys so typos surface as 422 at the
    # editor instead of silently becoming dead config.
    allowed = {"op", "path", "value"}
    extra = set(node.keys()) - allowed
    if extra:
        raise InvalidCondition(
            f"leaf condition has unknown keys: {sorted(extra)}"
        )


# --- Path extraction (Step-19 diagnostics) -----------------------------


def extract_paths(node: Any) -> set[str]:
    """Return every context dot-path referenced by the condition.
    Step 19's "why didn't this fire?" diagnostics surface uses this
    to show "the condition looked at: contact.email, lead.score" so
    operators can spot misnamed paths."""
    if not isinstance(node, dict) or not node:
        return set()
    if "all" in node and isinstance(node["all"], list):
        out: set[str] = set()
        for child in node["all"]:
            out |= extract_paths(child)
        return out
    if "any" in node and isinstance(node["any"], list):
        out = set()
        for child in node["any"]:
            out |= extract_paths(child)
        return out
    if "not" in node:
        return extract_paths(node["not"])
    path = node.get("path")
    return {path} if isinstance(path, str) and path else set()


__all__ = [
    "InvalidCondition",
    "SUPPORTED_OPS",
    "evaluate",
    "evaluate_safe",
    "extract_paths",
    "validate",
]
