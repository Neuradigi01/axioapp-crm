"""Ask Media node (``tasks/chatbot-builder`` Step 8).

Prompts for a media upload (image / video / document). On resume,
reads the inbound message's attachments — v1 accepts the WA
media reference and stores its metadata for the operator; actual
download from Meta + persistence via :class:`StorageBackend` is a
Step-8 follow-up (needs a media-download helper on the WA adapter
we don't ship in this step). For v1, the file_id / channel media
handle is what's saved to the target field.

Config shape::

    {
      "prompt": "Please upload the ID document.",
      "save_to": "contact.custom.id_document_media_id",
      "max_size_bytes": 10485760,             # 10 MB default
      "allowed_types": ["image", "document"], # default: any
      "timeout_seconds": 79200,
      "max_retries": 2
    }
"""

from __future__ import annotations

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

_NODE_TYPE = "ask_media"
_DEFAULT_TIMEOUT_SECONDS = 22 * 3600
_DEFAULT_MAX_RETRIES = 2
_DEFAULT_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED_MEDIA_TYPES = frozenset({"image", "video", "audio", "document"})


async def handle(ctx: NodeExecutionContext) -> NodeResult:
    if _shared.is_resumed_from_park(ctx):
        return await _handle_resume(ctx)
    return await _handle_first_pass(ctx)


async def _handle_first_pass(ctx: NodeExecutionContext) -> NodeResult:
    cfg = ctx.node_config or {}
    prompt = str(cfg.get("prompt") or "")
    save_to = str(cfg.get("save_to") or "")

    if not prompt or not save_to:
        return _shared.errored_result("ask_media.prompt + save_to required")

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
        transcript = {"send_kind": "ask_media", "prompt": body, "test_mode": True}
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

    # The matcher stamps last_inbound_attachments on the run context
    # when the inbound message carried media. v1 accepts the first
    # matching attachment. Full StorageBackend download + local
    # persistence is a follow-up (needs adapter.download_media()).
    attachments = (ctx.run_context or {}).get("last_inbound_attachments") or []
    cfg = ctx.node_config or {}
    allowed = set(cfg.get("allowed_types") or _ALLOWED_MEDIA_TYPES)
    max_size = int(cfg.get("max_size_bytes") or _DEFAULT_MAX_SIZE_BYTES)

    accepted = None
    for att in attachments:
        if not isinstance(att, dict):
            continue
        att_type = att.get("type")
        if att_type not in allowed:
            continue
        size = int(att.get("size_bytes") or 0)
        if size and size > max_size:
            continue
        accepted = {
            "type": att_type,
            "media_id": att.get("media_id") or att.get("id"),
            "mime_type": att.get("mime_type"),
            "size_bytes": size,
            "filename": att.get("filename"),
        }
        break

    if accepted is None:
        return await _handle_invalid(ctx, context_patch)

    save_to = str(cfg.get("save_to") or "")
    answers = dict((ctx.run_context or {}).get("answers") or {})
    answers[ctx.node_id] = accepted
    context_patch["answers"] = answers

    save_result: dict = {}
    if save_to.startswith("run_variable."):
        save_result = {"entity": "run_variable"}
    else:
        try:
            # Media targets typically save the media_id string, not
            # the whole descriptor. Callers who want the full dict
            # can save_to a JSONB custom field.
            value_to_save = accepted["media_id"] or accepted
            save_result = await save_targets.write_save_target(
                ctx.session,
                org_id=ctx.run.org_id,
                qualified_key=save_to,
                value=value_to_save,
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
        output={"resumed_by": "inbound", "media": accepted, "save_result": save_result},
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
        or "Please attach the file/image (allowed: image, video, document)."
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
