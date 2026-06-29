"""Flow-control action handlers — ``branch.if`` + ``branch.switch``.

Branch handler (:func:`_branch_handler`) walks the node's
``config.branches`` list in order, evaluates each branch's
``conditions`` against the engine's context, and returns the first
matching ``label`` as the :class:`ActionResult.next_edge_label`.
When no branch matches, returns ``"else"`` — every branch node
MUST have an outbound edge with ``label='else'`` (Step 2's graph
validator enforces this).

Switch handler (:func:`_switch_handler`) reads a single value at
``config.path``, then walks ``config.branches`` matching by
equality on ``branch.value``. When nothing matches, returns
``"default"`` — every switch node MUST have an outbound edge with
``label='default'``.

Both handlers are I/O-free — they read from the engine's
``context`` dict (the same shape Step 4 builds: ``contact`` /
``trigger_payload`` / ``run_state``). The Step-2 graph validator
will reject any branch / switch node that doesn't carry the
required ``else`` / ``default`` outbound edge so the operator
gets a clear 422 at publish time instead of a runtime miss.

The remaining flow nodes (``flow.wait``, ``flow.wait_for_event``,
``flow.end``, ``flow.goal``, ``flow.ab_split``) ship in Step 11.
Step 6 only registers the two branch handlers because they're the
minimum needed to validate the condition AST end-to-end.
"""
from __future__ import annotations

import logging
from typing import Any

from src.app.core.events.conditions import evaluate_safe
from src.app.core.workflows.actions import register_action


logger = logging.getLogger(__name__)


_BRANCH_DEFAULT_LABEL = "else"
_SWITCH_DEFAULT_LABEL = "default"


async def _branch_handler(
    session,
    *,
    run,
    step_run,
    node: dict[str, Any],
    context: dict[str, Any],
):
    """Walk ``config.branches`` in order; return the first matching
    label. Empty branches list → ``"else"`` immediately."""
    from src.app.core.workflows.engine import ActionResult

    branches = (node.get("config") or {}).get("branches") or []
    for branch in branches:
        if not isinstance(branch, dict):
            continue
        label = branch.get("label")
        conditions = branch.get("conditions") or {}
        if not isinstance(label, str) or not label:
            continue
        if evaluate_safe(conditions, context):
            return ActionResult(next_edge_label=label)

    return ActionResult(next_edge_label=_BRANCH_DEFAULT_LABEL)


async def _switch_handler(
    session,
    *,
    run,
    step_run,
    node: dict[str, Any],
    context: dict[str, Any],
):
    """Read one value off the context + match by equality against
    every ``branches[].value``. Missing path / no match falls
    through to ``"default"``."""
    from src.app.core.events.conditions import _resolve_path, _MISSING
    from src.app.core.workflows.engine import ActionResult

    cfg = node.get("config") or {}
    path = cfg.get("path")
    branches = cfg.get("branches") or []

    if not isinstance(path, str) or not path:
        return ActionResult(next_edge_label=_SWITCH_DEFAULT_LABEL)

    resolved = _resolve_path(context, path)
    if resolved is _MISSING:
        return ActionResult(next_edge_label=_SWITCH_DEFAULT_LABEL)

    for branch in branches:
        if not isinstance(branch, dict):
            continue
        label = branch.get("label")
        target = branch.get("value")
        if isinstance(label, str) and label and resolved == target:
            return ActionResult(next_edge_label=label)

    return ActionResult(next_edge_label=_SWITCH_DEFAULT_LABEL)


def register() -> None:
    """Register the two Step-6 branch handlers. Imported at
    workflows package init so the registry knows about them before
    any engine dispatch."""
    register_action("branch.if", lambda: _branch_handler)
    register_action("branch.switch", lambda: _switch_handler)


# Side-effect registration on import so the engine resolves
# branch.* nodes without any extra wiring.
register()


__all__ = ["register"]
