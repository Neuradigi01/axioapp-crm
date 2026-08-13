"""Template node (``tasks/chatbot-builder`` Step 7).

Reuses :mod:`core.templates` — pick an approved template by id + fill
its variables from ``answers.*`` and ``contact.*``. For WhatsApp,
this is the recommended path when the 24h session window is closed
(Meta's rule: only approved templates outside the window).

Config shape::

    {
      "template_id": "<uuid>",
      "variables": {"1": "{{contact.first_name}}", "2": "{{answers.q_name}}"}
    }

Save-time validation (Step 2's graph validator, extended in a
follow-up): reject if ``template_id`` doesn't resolve to an
approved template in the org.
"""

from __future__ import annotations

import uuid

from src.app.core.chatbots import channel_bridge
from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "template"


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    template_id_raw = cfg.get("template_id")

    if not template_id_raw:
        return _shared.errored_result("template.template_id is required")
    try:
        template_id = uuid.UUID(str(template_id_raw))
    except (TypeError, ValueError):
        return _shared.errored_result(
            f"template.template_id must be a UUID; got {template_id_raw!r}"
        )

    conversation = await _shared.load_conversation(
        ctx.session, conversation_id=ctx.run.conversation_id
    )
    contact_data = await _shared.load_contact_data(
        ctx.session, contact_id=ctx.run.contact_id
    )
    channel = _shared.channel_of(ctx)

    # Resolve variable expressions ({{contact.first_name}} etc) in
    # each mapped value before sending.
    variables_raw: dict[str, str] = cfg.get("variables") or {}
    resolved_variables: dict[str, str] = {}
    for key, value in variables_raw.items():
        resolved_variables[str(key)] = channel_bridge.render_variables(
            str(value),
            run_context=ctx.run_context,
            contact_data=contact_data,
            channel=channel,
        )

    if ctx.is_test or conversation is None:
        return NodeResult(
            output={
                "send_kind": "template",
                "template_id": str(template_id),
                "variables": resolved_variables,
                "test_mode": True,
            }
        )

    # v1 dispatch: reuse `conversations.service.send_template_message`
    # which handles WA-side approval checking + Meta send +
    # persisting the outbound Message. That path sets
    # `sender_user_id` — bot-authored templates need it NULL, so we
    # patch after send. Future polish: a bot-authored template send
    # helper on channel_bridge that mirrors send_bot_interactive_*.
    from src.app.core.conversations.service import send_template_message

    try:
        msg = await send_template_message(
            ctx.session,
            conversation_id=conversation.id,
            user_id=uuid.UUID(int=0),  # placeholder — patched below
            template_id=template_id,
            variables=resolved_variables,
        )
    except ValueError as exc:
        return _shared.errored_result(f"template send rejected: {exc}")
    except Exception as exc:  # noqa: BLE001
        return _shared.errored_result(f"template send failed: {exc}")

    # Retag the outbound row as bot-authored so human-takeover
    # detection (Case #10) sees it as a bot message + not a stray
    # human send.
    msg.chatbot_run_id = ctx.run.id
    msg.sender_user_id = None
    await ctx.session.commit()

    return NodeResult(
        output={
            "send_kind": "template",
            "template_id": str(template_id),
            "variables": resolved_variables,
            "message_id": str(msg.id),
        }
    )


register_node(_NODE_TYPE, handle)
