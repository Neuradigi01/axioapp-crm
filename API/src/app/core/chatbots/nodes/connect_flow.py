"""Connect Flow node (``tasks/chatbot-builder`` Step 10).

Chains the current bot into a second bot in the same org. The
current run ends with reason ``connect_flow_transferred``; the
target bot's :func:`engine.start_run` fires immediately with the
current ``answers`` context + ``chain_depth+1`` so the runtime
depth guard (max 5, Case #33) can enforce the ceiling.

Config shape::

    {
      "target_bot_id": "<uuid>"
    }

Save-time graph validator (Step 2) also refuses connect chains
longer than 5 or self-referential; this runtime guard catches
chains built across bots edited independently.
"""

from __future__ import annotations

import uuid

from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
    start_run as _engine_start_run,
)
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "connect_flow"
_MAX_CHAIN_DEPTH = 5


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    target_raw = cfg.get("target_bot_id")
    if not target_raw:
        return _shared.errored_result("connect_flow.target_bot_id is required")

    try:
        target_bot_id = uuid.UUID(str(target_raw))
    except (TypeError, ValueError) as exc:
        return _shared.errored_result(f"invalid target_bot_id: {exc}")

    # Self-reference guard.
    if target_bot_id == ctx.run.chatbot_id:
        return NodeResult(
            next_edge_label="error",
            skip_reason="self_reference",
            output={"target_bot_id": str(target_bot_id)},
        )

    # Chain-depth guard (Case #33).
    current_depth = int((ctx.run_context or {}).get("chain_depth") or 0)
    if current_depth >= _MAX_CHAIN_DEPTH:
        return NodeResult(
            next_edge_label="error",
            skip_reason="chain_depth_exceeded",
            output={"chain_depth": current_depth, "cap": _MAX_CHAIN_DEPTH},
        )

    # Load target bot — same org only. Cross-org rejects here.
    from src.app.core.chatbots import data_access as _dal

    target_bot = await _dal.get_chatbot(
        ctx.session,
        org_id=ctx.run.org_id,
        chatbot_id=target_bot_id,
    )
    if target_bot is None:
        return NodeResult(
            next_edge_label="error",
            skip_reason="target_bot_missing",
            output={"target_bot_id": str(target_bot_id)},
        )
    if target_bot.status != "live":
        return NodeResult(
            next_edge_label="error",
            skip_reason="target_bot_not_live",
            output={"status": target_bot.status},
        )

    if ctx.is_test:
        return NodeResult(
            end_run=True,
            output={
                "chain_target_bot_id": str(target_bot_id),
                "new_chain_depth": current_depth + 1,
                "test_mode": True,
            },
        )

    # Build a synthetic event that mirrors the shape start_run
    # expects, seeded with the carried answers + incremented depth.
    synthetic_event: dict = {
        "org_id": str(ctx.run.org_id),
        "conversation_id": (
            str(ctx.run.conversation_id) if ctx.run.conversation_id else None
        ),
        "contact_id": str(ctx.run.contact_id) if ctx.run.contact_id else None,
        "message_id": None,
        "text": (ctx.run_context or {}).get("last_inbound_text"),
        "channel": (ctx.run_context or {}).get("channel"),
        "is_first_message": False,
        "direction": "in",
        # Non-standard keys that start_run copies into the target
        # run's context via its normal seeding path — handlers on
        # the target bot pick up carried answers seamlessly.
        "_carried_answers": (ctx.run_context or {}).get("answers") or {},
        "_chain_depth": current_depth + 1,
    }

    try:
        new_run = await _engine_start_run(
            ctx.session,
            bot=target_bot,
            event=synthetic_event,
            is_test=False,
        )
        # Seed the target run's context with the carried answers +
        # chain_depth so downstream nodes see them. Refresh so the
        # in-memory row matches DB after the patch.
        target_ctx = dict(new_run.context or {})
        target_ctx["answers"] = dict(synthetic_event["_carried_answers"] or {})
        target_ctx["chain_depth"] = current_depth + 1
        new_run.context = target_ctx
        await ctx.session.commit()
    except Exception as exc:  # noqa: BLE001
        return NodeResult(
            next_edge_label="error",
            skip_reason="target_start_failed",
            output={"error": str(exc)},
        )

    return NodeResult(
        end_run=True,
        output={
            "chain_target_bot_id": str(target_bot_id),
            "chain_target_run_id": str(new_run.id),
            "new_chain_depth": current_depth + 1,
        },
    )


register_node(_NODE_TYPE, handle)
