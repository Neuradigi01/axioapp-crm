"""Ask Location node (``tasks/chatbot-builder`` Step 8).

Prompts for a geo-location. On WhatsApp, the customer can share a
location message natively (a pin) → ``{lat, lng, name?, address?}``.
On email or plain text, a ``lat, lng`` pair is parsed via regex;
non-parseable → retry / invalid path.

Config shape::

    {
      "prompt": "Where should we deliver?",
      "save_to": "contact.custom.location",
      "timeout_seconds": 79200,
      "max_retries": 2
    }
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from src.app.core.chatbots import channel_bridge
from src.app.core.chatbots import save_target_registry as save_targets
from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.exceptions import InvalidSaveTarget
from src.app.core.chatbots.nodes import _shared

_NODE_TYPE = "ask_location"
_DEFAULT_TIMEOUT_SECONDS = 22 * 3600
_DEFAULT_MAX_RETRIES = 2

# "12.9716, 77.5946" or "12.9716,77.5946" or "lat=12.97 lng=77.59"
_LAT_LNG_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)"
)


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    if _shared.is_resumed_from_park(ctx):
        return await _handle_resume(ctx)
    return await _handle_first_pass(ctx)


async def _handle_first_pass(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    prompt = str(cfg.get("prompt") or "")
    save_to = str(cfg.get("save_to") or "")

    if not prompt or not save_to:
        return _shared.errored_result("ask_location.prompt + save_to required")

    conversation = await _shared.load_conversation(
        ctx.session, conversation_id=ctx.run.conversation_id
    )
    contact_data = await _shared.load_contact_data(
        ctx.session, contact_id=ctx.run.contact_id
    )
    channel = _shared.channel_of(ctx)
    body = channel_bridge.render_variables(
        prompt, run_context=ctx.run_context, contact_data=contact_data, channel=channel
    )

    if not await _shared.wa_window_open_or_take_session_expired(
        ctx.session, conversation=conversation
    ):
        return NodeResult(
            next_edge_label="session_expired",
            skip_reason="wa_session_window_closed",
        )

    if conversation is None:
        transcript = {"send_kind": "ask_location", "prompt": body, "test_mode": True}
    else:
        transcript = await channel_bridge.send_bot_text(
            ctx.session,
            conversation=conversation,
            run_id=ctx.run.id,
            text=body,
            is_test=ctx.is_test,
        )

    timeout_seconds = int(cfg.get("timeout_seconds") or _DEFAULT_TIMEOUT_SECONDS)
    timeout_at = datetime.now(UTC) + timedelta(seconds=timeout_seconds)
    ctx.run.next_step_at = timeout_at

    conv_id = str(ctx.run.conversation_id) if ctx.run.conversation_id else "test"
    return NodeResult(
        park_key=("reply", conv_id),
        context_patch={"timeout_at": timeout_at.isoformat()},
        output={**transcript, "save_to": save_to},
    )


async def _handle_resume(ctx: NodeExecutionContext) -> NodeResult:
    context_patch = _shared.clear_resume_flag()
    resumed_by = (ctx.run_context or {}).get("resumed_by") or "inbound"
    if resumed_by == "timeout":
        return NodeResult(
            next_edge_label="timeout",
            context_patch=context_patch,
            skip_reason="timeout",
        )

    # Prefer a WA-native location payload if present in the run
    # context (matcher / receive_webhook can stamp it). Fall back to
    # regex parse of the text reply.
    ctx_loc = (ctx.run_context or {}).get("last_inbound_location") or {}
    parsed: dict | None = None
    if isinstance(ctx_loc, dict) and "lat" in ctx_loc and "lng" in ctx_loc:
        parsed = {
            "lat": float(ctx_loc["lat"]),
            "lng": float(ctx_loc["lng"]),
            "name": ctx_loc.get("name"),
            "address": ctx_loc.get("address"),
        }
    else:
        reply = str((ctx.run_context or {}).get("last_inbound_text") or "")
        match = _LAT_LNG_RE.search(reply)
        if match:
            try:
                lat = float(match.group(1))
                lng = float(match.group(2))
                if -90 <= lat <= 90 and -180 <= lng <= 180:
                    parsed = {"lat": lat, "lng": lng}
            except ValueError:
                pass

    if parsed is None:
        return await _handle_invalid(ctx, context_patch)

    cfg = ctx.node_config or {}
    save_to = str(cfg.get("save_to") or "")
    answers = dict((ctx.run_context or {}).get("answers") or {})
    answers[ctx.node_id] = parsed
    context_patch["answers"] = answers

    save_result: dict = {}
    if save_to.startswith("run_variable."):
        save_result = {"entity": "run_variable"}
    else:
        try:
            save_result = await save_targets.write_save_target(
                ctx.session,
                org_id=ctx.run.org_id,
                qualified_key=save_to,
                value=parsed,
                contact_id=ctx.run.contact_id,
                lead_id=ctx.run.lead_id,
            )
            await ctx.session.commit()
        except InvalidSaveTarget as exc:
            save_result = {
                "entity": "run_variable",
                "fallback_from": save_to,
                "reason": str(exc),
            }

    return NodeResult(
        next_edge_label="answered",
        context_patch=context_patch,
        output={
            "resumed_by": "inbound",
            "parsed": parsed,
            "save_result": save_result,
        },
    )


async def _handle_invalid(
    ctx: NodeExecutionContext, context_patch: dict
) -> NodeResult:
    cfg = ctx.node_config or {}
    max_retries = int(cfg.get("max_retries") or _DEFAULT_MAX_RETRIES)
    retry_counts = dict((ctx.run_context or {}).get("retry_counts") or {})
    current = int(retry_counts.get(ctx.node_id) or 0)

    if current >= max_retries:
        retry_counts.pop(ctx.node_id, None)
        context_patch["retry_counts"] = retry_counts
        return NodeResult(
            next_edge_label="invalid",
            context_patch=context_patch,
            skip_reason="max_retries_exceeded",
        )

    retry_counts[ctx.node_id] = current + 1
    context_patch["retry_counts"] = retry_counts

    retry_message = str(
        cfg.get("retry_message")
        or "Please share your location as a WhatsApp location message or type as 'lat, lng'."
    )
    conversation = await _shared.load_conversation(
        ctx.session, conversation_id=ctx.run.conversation_id
    )
    if conversation is not None:
        await channel_bridge.send_bot_text(
            ctx.session,
            conversation=conversation,
            run_id=ctx.run.id,
            text=retry_message,
            is_test=ctx.is_test,
        )

    conv_id = str(ctx.run.conversation_id) if ctx.run.conversation_id else "test"
    return NodeResult(
        park_key=("reply", conv_id),
        context_patch=context_patch,
        output={"retry_number": current + 1},
    )


register_node(_NODE_TYPE, handle)
