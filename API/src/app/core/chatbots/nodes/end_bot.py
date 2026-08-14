"""End Bot node — the explicit "we're done" terminator.

Purpose:
  1. Optionally send a final courtesy message ("Thanks, we'll get
     back to you.").
  2. Optionally set ``Conversation.bot_muted_until`` so the trigger
     matcher refuses to fire any bot on this conversation for the
     configured window — prevents the loop where a customer sends
     "hi" again after a completed flow and the same welcome bot
     re-fires from scratch.
  3. Return ``end_run=True`` so the engine marks the run
     ``status='completed'`` with the correct reason.

Config shape::

    {
      "final_bot_message": "Thanks, we'll get back to you.",   # optional
      "mute_hours": 0                                          # 0 = no mute; max 720 (30 days)
    }

Output port: single default edge (unused — ``end_run=True`` short-
circuits the engine's find-next, so any wired downstream is dead
code). We keep the port slot so the visual builder doesn't complain
about a dangling terminal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.app.core.chatbots import channel_bridge
from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "end_bot"
_MAX_MUTE_HOURS = 720  # 30 days — anything longer belongs in a permanent-block flow


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    final_message = cfg.get("final_bot_message")
    mute_hours_raw = cfg.get("mute_hours") or 0

    try:
        mute_hours = int(mute_hours_raw)
    except (TypeError, ValueError):
        return _shared.errored_result(
            f"end_bot.mute_hours must be an integer, got {mute_hours_raw!r}"
        )
    if mute_hours < 0 or mute_hours > _MAX_MUTE_HOURS:
        return _shared.errored_result(
            f"end_bot.mute_hours must be 0..{_MAX_MUTE_HOURS} (got {mute_hours})"
        )

    conversation = await _shared.load_conversation(
        ctx.session, conversation_id=ctx.run.conversation_id
    )

    # Optional final line — plain text send.
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

    # Optional mute window on the conversation. Test-mode runs never
    # write to a real conversation.
    muted_until: datetime | None = None
    if mute_hours > 0 and conversation is not None and not ctx.is_test:
        muted_until = datetime.now(UTC) + timedelta(hours=mute_hours)
        conversation.bot_muted_until = muted_until
        await ctx.session.commit()

    return NodeResult(
        end_run=True,
        output={
            "sent_final_message": bool(final_message),
            "mute_hours": mute_hours,
            "muted_until": muted_until.isoformat() if muted_until else None,
            "test_mode": ctx.is_test,
        },
    )


register_node(_NODE_TYPE, handle)
