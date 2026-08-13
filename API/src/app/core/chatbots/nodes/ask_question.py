"""Ask Question node (``tasks/chatbot-builder`` Step 8).

Config shape::

    {
      "prompt": "What's your first name?",
      "save_to": "contact.first_name",         # save_target_registry key
      "expected_format": "text",                # text|email|phone|number|url|date|choice
      "choices": [                              # required when expected_format=choice
        {"value": "yes", "aliases": ["y", "yep", "sure"]},
        {"value": "no",  "aliases": ["n", "nope"]}
      ],
      "max_retries": 2,
      "retry_message": "Sorry, I didn't catch that. Please try again.",
      "timeout_seconds": 79200                  # 22h default
    }

Three-phase handler:

  * **First execution** — send prompt, park run with
    ``park_key=("reply", conversation_id)``, stamp
    ``run.next_step_at = now() + timeout_seconds`` so the sweeper
    can fire the timeout port.
  * **Resume by inbound** (``context.resumed_by='inbound'``) —
    validate reply via :mod:`core.chatbots.validators`. Valid →
    save via :mod:`save_target_registry`, stamp
    ``answers[node_id] = value``, take ``answered`` port. Invalid
    → increment ``retry_counts[node_id]``; if under cap, re-send
    ``retry_message`` and re-park; else take ``invalid`` port.
  * **Resume by timeout** (``context.resumed_by='timeout'``) —
    take ``timeout`` port.

Output ports (matched by ``edge.label``): ``answered``, ``invalid``,
``timeout``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from src.app.core.chatbots import channel_bridge
from src.app.core.chatbots import save_target_registry as save_targets
from src.app.core.chatbots.engine import (
    NodeExecutionContext,
    NodeResult,
    register_node,
)
from src.app.core.chatbots.exceptions import InvalidSaveTarget
from src.app.core.chatbots.nodes import _shared
from src.app.core.chatbots.validators import resolve_validator, validate_choice

_NODE_TYPE = "ask_question"
_DEFAULT_TIMEOUT_SECONDS = 22 * 3600  # 22h — inside the WA session window
_DEFAULT_MAX_RETRIES = 2


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    if _shared.is_resumed_from_park(ctx):
        return await _handle_resume(ctx)
    return await _handle_first_pass(ctx)


async def _handle_first_pass(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    prompt = str(cfg.get("prompt") or "")
    save_to = str(cfg.get("save_to") or "")

    if not prompt:
        return _shared.errored_result("ask_question.prompt is required")
    if not save_to:
        return _shared.errored_result("ask_question.save_to is required")

    # Save-time gate — the picker already excluded sensitive fields,
    # but a stale graph could still carry a bad target. Fail fast
    # here so the flow ends cleanly instead of after sending the
    # prompt.
    if not save_to.startswith("run_variable."):
        try:
            await save_targets.validate_save_target(
                ctx.session, org_id=ctx.run.org_id, qualified_key=save_to
            )
        except InvalidSaveTarget as exc:
            return _shared.errored_result(f"save_to rejected: {exc}")

    conversation = await _shared.load_conversation(
        ctx.session, conversation_id=ctx.run.conversation_id
    )
    contact_data = await _shared.load_contact_data(
        ctx.session, contact_id=ctx.run.contact_id
    )
    channel = _shared.channel_of(ctx)

    body = channel_bridge.render_variables(
        prompt,
        run_context=ctx.run_context,
        contact_data=contact_data,
        channel=channel,
    )

    if not await _shared.wa_window_open_or_take_session_expired(
        ctx.session, conversation=conversation
    ):
        return NodeResult(
            next_edge_label="session_expired",
            skip_reason="wa_session_window_closed",
        )

    if conversation is None:
        transcript = {"send_kind": "ask_prompt", "prompt": body, "test_mode": True}
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
        output={**transcript, "save_to": save_to, "timeout_at": timeout_at.isoformat()},
    )


async def _handle_resume(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    save_to = str(cfg.get("save_to") or "")
    context_patch = _shared.clear_resume_flag()

    resumed_by = (ctx.run_context or {}).get("resumed_by") or "inbound"
    if resumed_by == "timeout":
        return NodeResult(
            next_edge_label="timeout",
            context_patch=context_patch,
            skip_reason="timeout",
            output={"resumed_by": "timeout"},
        )

    reply_text = str((ctx.run_context or {}).get("last_inbound_text") or "")

    # Validate.
    expected_format = str(cfg.get("expected_format") or "text")
    if expected_format == "choice":
        choices = cfg.get("choices") or []
        valid, normalised = validate_choice(reply_text, choices=choices)
    else:
        validator = resolve_validator(expected_format)
        valid, normalised = validator(reply_text)

    if not valid:
        return await _handle_invalid(ctx, reply_text, context_patch)

    # Persist + record answer.
    answers = dict((ctx.run_context or {}).get("answers") or {})
    answers[ctx.node_id] = normalised
    context_patch["answers"] = answers

    save_result: dict[str, Any] = {}
    if save_to.startswith("run_variable."):
        # Value already lives in answers under the node id; nothing
        # else to persist.
        save_result = {"entity": "run_variable"}
    else:
        try:
            save_result = await save_targets.write_save_target(
                ctx.session,
                org_id=ctx.run.org_id,
                qualified_key=save_to,
                value=normalised,
                contact_id=ctx.run.contact_id,
                lead_id=ctx.run.lead_id,
            )
            await ctx.session.commit()
        except InvalidSaveTarget as exc:
            # Case #6 — target vanished mid-run. Fall back to
            # run_variable persistence so the answer isn't lost.
            save_result = {
                "entity": "run_variable",
                "fallback_from": save_to,
                "reason": str(exc),
            }

    # Reset retry counter now that we accepted a reply.
    retry_counts = dict((ctx.run_context or {}).get("retry_counts") or {})
    retry_counts.pop(ctx.node_id, None)
    context_patch["retry_counts"] = retry_counts

    return NodeResult(
        next_edge_label="answered",
        context_patch=context_patch,
        output={
            "resumed_by": "inbound",
            "reply": reply_text,
            "normalised": normalised,
            "save_result": save_result,
        },
    )


async def _handle_invalid(
    ctx: NodeExecutionContext,
    reply_text: str,
    context_patch: dict[str, Any],
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
            output={"reply": reply_text, "retries": current},
        )

    retry_counts[ctx.node_id] = current + 1
    context_patch["retry_counts"] = retry_counts

    # Send retry message + re-park.
    retry_message = str(cfg.get("retry_message") or "Sorry, I didn't understand — please try again.")
    conversation = await _shared.load_conversation(
        ctx.session, conversation_id=ctx.run.conversation_id
    )
    contact_data = await _shared.load_contact_data(
        ctx.session, contact_id=ctx.run.contact_id
    )
    channel = _shared.channel_of(ctx)
    retry_body = channel_bridge.render_variables(
        retry_message,
        run_context=ctx.run_context,
        contact_data=contact_data,
        channel=channel,
    )

    if conversation is not None:
        await channel_bridge.send_bot_text(
            ctx.session,
            conversation=conversation,
            run_id=ctx.run.id,
            text=retry_body,
            is_test=ctx.is_test,
        )

    conv_id = str(ctx.run.conversation_id) if ctx.run.conversation_id else "test"
    return NodeResult(
        park_key=("reply", conv_id),
        context_patch=context_patch,
        output={
            "resumed_by": "inbound",
            "reply": reply_text,
            "retry_sent": True,
            "retry_number": current + 1,
        },
    )


register_node(_NODE_TYPE, handle)
