"""Ask Address node (``tasks/chatbot-builder`` Step 8).

Prompts for a postal address, then parses the reply into
``{street, city, state, postal_code, country, raw}`` using a
best-effort heuristic. On unparseable input, the ``raw`` field
still carries the full string so operators never lose the answer.

Config shape::

    {
      "prompt": "What's your shipping address?",
      "save_to": "contact.custom.address",   # JSONB custom field target
      "timeout_seconds": 79200,
      "retry_message": "..."                 # unused for address — always accepts
    }

Same three-phase pattern as :mod:`ask_question`.
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

_NODE_TYPE = "ask_address"
_DEFAULT_TIMEOUT_SECONDS = 22 * 3600


# US ZIP: 5 digits or 5+4. IN PIN: 6 digits. UK postcode: complex
# but a simple pattern catches most.
_US_ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")
_IN_PIN_RE = re.compile(r"\b\d{6}\b")
_UK_POSTCODE_RE = re.compile(
    r"\b[A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2}\b", re.IGNORECASE
)


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    if _shared.is_resumed_from_park(ctx):
        return await _handle_resume(ctx)
    return await _handle_first_pass(ctx)


async def _handle_first_pass(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    prompt = str(cfg.get("prompt") or "")
    save_to = str(cfg.get("save_to") or "")

    if not prompt:
        return _shared.errored_result("ask_address.prompt is required")
    if not save_to:
        return _shared.errored_result("ask_address.save_to is required")

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
        transcript = {"send_kind": "ask_address", "prompt": body, "test_mode": True}
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

    reply = str((ctx.run_context or {}).get("last_inbound_text") or "").strip()
    parsed = _parse_address(reply)

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
            "reply": reply,
            "parsed": parsed,
            "save_result": save_result,
        },
    )


def _parse_address(raw: str) -> dict[str, str]:
    """Heuristic address parse. Always returns a dict with ``raw``
    populated; other fields are best-effort."""
    result: dict[str, str] = {"raw": raw}
    if not raw:
        return result

    lowered = raw.upper()
    if _US_ZIP_RE.search(lowered):
        m = _US_ZIP_RE.search(lowered)
        result["postal_code"] = m.group(0)  # type: ignore[union-attr]
        result["country"] = "US"
    elif _UK_POSTCODE_RE.search(lowered):
        m = _UK_POSTCODE_RE.search(lowered)
        result["postal_code"] = m.group(0).upper()  # type: ignore[union-attr]
        result["country"] = "GB"
    elif _IN_PIN_RE.search(raw):
        m = _IN_PIN_RE.search(raw)
        result["postal_code"] = m.group(0)  # type: ignore[union-attr]
        result["country"] = "IN"

    # First comma-separated part is usually the street.
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if parts:
        result["street"] = parts[0]
    if len(parts) >= 2:
        result["city"] = parts[1]
    if len(parts) >= 3:
        result["state"] = parts[2]

    return result


register_node(_NODE_TYPE, handle)
