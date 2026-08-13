"""Condition node (``tasks/chatbot-builder`` Step 9).

Reuses :mod:`core.events.conditions` — same AST shape as the
automation-engine condition operator, so operators already familiar
with one syntax get the other for free.

Config shape::

    {
      "condition": {
        "op": "equals",
        "left": {"path": "answers.budget"},
        "right": {"value": "enterprise"}
      }
    }

Supported operators (inherited from ``core.events.conditions``):
``equals``, ``not_equals``, ``contains``, ``starts_with``,
``regex_matches``, ``greater_than``, ``less_than``, ``is_set``,
``is_empty``, plus boolean ``and`` / ``or`` / ``not`` wrappers.

Operands reference ``answers.<node_id>`` / ``contact.<field>`` /
``lead.<field>`` / ``run.<key>`` — resolved from a merged context
built here (same shape as :func:`core.chatbots.channel_bridge.render_variables`
consumes).

Output ports: ``true`` / ``false``.
"""

from __future__ import annotations

from typing import Any

from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.nodes import _shared
from src.app.core.events.conditions import (
    InvalidCondition,
    evaluate_safe,
)

_NODE_TYPE = "condition"


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    condition = cfg.get("condition")

    if not isinstance(condition, dict) or not condition:
        return _shared.errored_result("condition.condition (AST) is required")

    contact_data = await _shared.load_contact_data(
        ctx.session, contact_id=ctx.run.contact_id
    )
    merged_context = _build_condition_context(ctx, contact_data or {})

    try:
        result = evaluate_safe(condition, merged_context)
    except InvalidCondition as exc:
        return _shared.errored_result(f"condition rejected: {exc}")

    edge_label = "true" if result else "false"
    return NodeResult(
        next_edge_label=edge_label,
        output={"condition_result": result, "context_snapshot_keys": sorted(merged_context)},
    )


def _build_condition_context(
    ctx: NodeExecutionContext, contact_data: dict[str, Any]
) -> dict[str, Any]:
    """Merge run + answers + contact + api scopes into the flat
    dict shape that :mod:`core.events.conditions` walks via dotted
    path resolution."""
    run_ctx = ctx.run_context or {}
    return {
        "answers": run_ctx.get("answers") or {},
        "contact": contact_data,
        "run": {
            "conversation_id": run_ctx.get("conversation_id"),
            "contact_id": run_ctx.get("contact_id"),
            "last_inbound_text": run_ctx.get("last_inbound_text") or "",
            "channel": run_ctx.get("channel") or "",
            "is_first_message": bool(run_ctx.get("is_first_message")),
        },
        "api": run_ctx.get("api") or {},
        "variables": run_ctx.get("variables") or {},
    }


register_node(_NODE_TYPE, handle)
