"""Handoff to Human node (``tasks/chatbot-builder`` Step 10).

Ends the current bot run by:
  1. Setting ``Conversation.assigned_to_id`` to the resolved user.
  2. Sending an optional ``final_bot_message`` line.
  3. Returning ``end_run=True`` so the engine marks the run
     completed with the correct reason.

Config shape::

    {
      "assign_mode": "specific" | "round_robin",
      "user_id": "<uuid>",              # required for specific mode
      "team_ids": ["<uuid>", "<uuid>"], # optional round_robin pool
      "final_bot_message": "A team member will jump in shortly."
    }

v1 supports ``specific`` + ``round_robin`` across a team_ids list.
``least_loaded`` / ``territory`` are deferred to a follow-up — the
config accepts the fields so future upgrades don't require a schema
change.

Output port: ``handed_off`` (default edge if unlabelled).
"""

from __future__ import annotations

import random

from src.app.core.chatbots import channel_bridge
from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "handoff_to_human"


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    assign_mode = str(cfg.get("assign_mode") or "specific")
    user_id_raw = cfg.get("user_id")
    team_ids = cfg.get("team_ids") or []
    final_message = cfg.get("final_bot_message")

    if assign_mode == "specific":
        if not user_id_raw:
            return _shared.errored_result(
                "handoff.user_id required when assign_mode='specific'"
            )
        assignee_id = user_id_raw
    elif assign_mode == "round_robin":
        if not team_ids or not isinstance(team_ids, list):
            return _shared.errored_result(
                "handoff.team_ids required when assign_mode='round_robin'"
            )
        # v1: pick at random from the pool. A future step swaps in a
        # per-org round-robin counter (mirrors core/leads/routing.py).
        assignee_id = random.choice(team_ids)
    else:
        return _shared.errored_result(
            f"handoff.assign_mode {assign_mode!r} not supported "
            f"(v1: specific | round_robin)"
        )

    conversation = await _shared.load_conversation(
        ctx.session, conversation_id=ctx.run.conversation_id
    )

    if not ctx.is_test and conversation is not None:
        # Assign directly on the Conversation row. The Inbox UI reads
        # this on the next refresh; the assignee_engine (WA-side)
        # respects an existing assignment.
        import uuid as _uuid

        try:
            conversation.assigned_to_id = _uuid.UUID(str(assignee_id))
            await ctx.session.commit()
        except (TypeError, ValueError) as exc:
            return _shared.errored_result(f"invalid user_id {assignee_id!r}: {exc}")

    # Optional courtesy line — a plain text send, not interactive.
    if final_message and conversation is not None and not ctx.is_test:
        contact_data = await _shared.load_contact_data(
            ctx.session, contact_id=ctx.run.contact_id
        )
        rendered = channel_bridge.render_variables(
            str(final_message),
            run_context=ctx.run_context,
            contact_data=contact_data,
            channel=_shared.channel_of(ctx),
        )
        await channel_bridge.send_bot_text(
            ctx.session,
            conversation=conversation,
            run_id=ctx.run.id,
            text=rendered,
            is_test=False,
        )

    return NodeResult(
        end_run=True,
        output={
            "assign_mode": assign_mode,
            "assigned_to_id": str(assignee_id),
            "sent_final_message": bool(final_message),
            "test_mode": ctx.is_test,
        },
    )


register_node(_NODE_TYPE, handle)
