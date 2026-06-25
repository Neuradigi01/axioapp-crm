"""Service layer for the conversations engine.

Five concerns:

1. `list_conversations` — paginated + filter-aware inbox query
   (`channel`, `status`, `assigned_to_id`, `q` ILIKE on `external_id`).
   Ordered by `last_message_at desc nulls last`.
2. `get_conversation_detail` — one conversation + its messages,
   newest first per the inbox UX.
3. `send_outbound` — resolve the channel adapter, call `send()`,
   persist a `direction='out'` row, bump `last_message_at`. On the
   *first* outbound for a conversation tied to a contact, log a
   `whatsapp` activity (the only chat-style ActivityType today) so the
   contact timeline picks it up.
4. `receive_webhook` — channel-agnostic intake. Calls the adapter's
   `parse_webhook`, finds/creates the matching `Conversation`,
   persists a `direction='in'` row, bumps `unread_count` +
   `last_message_at`, fans out a notification to the assignee (if any)
   via the 2.15 service.
5. `patch_conversation` — narrow PATCH for the three triage fields.

All writes route through the caller's `AsyncSession` so the request
transaction stays in charge. Activity / notification fan-outs use
their respective `log` / `notify` helpers, both of which are
non-raising.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.contacts import data_access
from src.app.core.activities.models import ActivityType
from src.app.core.activities.service import log as activities_log
from src.app.core.contacts.models import Contact
from src.app.core.conversations import data_access as _da
from src.app.core.conversations.adapters import InboundMessage
from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
    ConversationStatus,
    Message,
    MessageDirection,
)
from src.app.core.conversations.adapters.whatsapp import (
    resolve_whatsapp_adapter,
)
from src.app.core.conversations.registry import resolve
from src.app.core.conversations.schemas import ConversationPatch
from src.app.core.notifications.service import notify
from src.app.shared.db.queries import ensure_found


# Channels whose `external_id` is a phone number; the webhook intake
# tries to resolve / auto-create a contact for these so the inbox can
# show a name instead of the raw phone string.
_PHONE_CHANNELS = {ConversationChannel.whatsapp, ConversationChannel.sms}


# --- reads -----------------------------------------------------------------


async def list_conversations(
    session: AsyncSession,
    *,
    channel: Optional[ConversationChannel] = None,
    status_filter: Optional[ConversationStatus] = None,
    assigned_to: Optional[str] = None,
    q: Optional[str] = None,
    tag_ids: Optional[list[uuid.UUID]] = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Conversation], int]:
    # `assigned_to` may be a UUID string (filter to that owner),
    # the sentinel `'unassigned'` (rows with `assigned_to_id IS NULL`),
    # or absent (no filter). Anything else raises 422.
    assigned_to_id: Optional[uuid.UUID] = None
    assigned_to_unassigned = False
    if assigned_to is not None:
        if assigned_to == "unassigned":
            assigned_to_unassigned = True
        else:
            try:
                assigned_to_id = uuid.UUID(assigned_to)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="assigned_to must be a UUID or 'unassigned'",
                ) from exc

    return await _da.list_conversations_query(
        session,
        channel=channel,
        status_filter=status_filter,
        assigned_to_id=assigned_to_id,
        assigned_to_unassigned=assigned_to_unassigned,
        q=q,
        tag_ids=tag_ids,
        page=page,
        size=size,
    )


async def get_conversation(
    session: AsyncSession, conversation_id: uuid.UUID
) -> Conversation:
    return ensure_found(
        await _da.get_conversation_by_id(session, conversation_id),
        entity="conversation",
    )


async def list_messages(
    session: AsyncSession, conversation_id: uuid.UUID
) -> list[Message]:
    return await _da.list_messages_for_conversation(session, conversation_id)


# --- writes ----------------------------------------------------------------


async def send_outbound(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    text_body: str,
    attachments: list[dict[str, Any]],
    interactive: dict[str, Any] | None = None,
    reply_to_message_id: uuid.UUID | None = None,
    send_from_phone_id: str | None = None,
) -> Message:
    conv = await get_conversation(session, conversation_id)
    # whatsapp-platform-upgrade Step 23 — block-list pre-flight on
    # WhatsApp manual outbound. Refuse cleanly with ValueError →
    # 400 so the SPA surfaces the reason in the composer.
    if conv.channel == ConversationChannel.whatsapp:
        from src.app.core.integrations.whatsapp.block_list import (
            is_blocked,
        )

        block_hit = await is_blocked(
            session, org_id=conv.org_id, phone=conv.external_id
        )
        if block_hit is not None:
            raise ValueError(
                f"This number is on the block list "
                f"(reason: {block_hit.reason}). Unblock it from "
                f"Settings → WhatsApp → Block List to send again."
            )

    # WhatsApp goes through the per-org resolver. Step 27a:
    # ``send_from_phone_id`` picks a specific phone for multi-number
    # orgs; explicit > implicit > received_via_phone_id > default.
    # The fallback chain keeps single-number orgs unchanged (they
    # never pass ``send_from_phone_id`` and have one config to
    # resolve anyway).
    if conv.channel == ConversationChannel.whatsapp:
        resolved_phone_id = (
            send_from_phone_id
            or getattr(conv, "received_via_phone_id", None)
        )
        adapter = await resolve_whatsapp_adapter(
            session, phone_id=resolved_phone_id
        )
    else:
        adapter = resolve(conv.channel)

    if interactive is not None and conv.channel != ConversationChannel.whatsapp:
        # Interactive messages are a WhatsApp-only surface today.
        # Surface as a 400 via the router (ValueError → HTTPException).
        raise ValueError(
            "Interactive messages are only supported on WhatsApp "
            "conversations."
        )

    # Step 7: resolve the reply target to a channel-side wamid the
    # adapter can put inside `context.message_id`. Mismatches (wrong
    # conversation, target has no `channel_message_id` yet because it's
    # still in flight) raise ValueError → 400.
    reply_to_wamid: str | None = None
    if reply_to_message_id is not None:
        target = await _da.get_message_by_id(session, reply_to_message_id)
        if target is None or target.conversation_id != conv.id:
            raise ValueError(
                "reply_to_message_id does not belong to this conversation."
            )
        if not target.channel_message_id:
            raise ValueError(
                "Cannot reply to a message that has not been delivered yet."
            )
        reply_to_wamid = target.channel_message_id

    is_first_outbound = (
        await _da.count_outbound_messages_for_conversation(
            session, conversation_id
        )
        == 0
    )

    # Pass `interactive` only when supplied so the registry-based
    # adapters (which haven't opted into the kwarg) don't break.
    send_kwargs: dict[str, Any] = {
        "org_id": conv.org_id,
        "external_id": conv.external_id,
        "text": text_body,
        "attachments": attachments,
    }
    if interactive is not None:
        send_kwargs["interactive"] = interactive
    if reply_to_wamid is not None:
        send_kwargs["reply_to_channel_message_id"] = reply_to_wamid
    ref = await adapter.send(**send_kwargs)
    now = datetime.now(timezone.utc)
    sent_at = ref.sent_at or now

    msg = Message(
        org_id=conv.org_id,
        conversation_id=conv.id,
        direction=MessageDirection.out,
        sender_user_id=user_id,
        text=text_body,
        attachments=attachments,
        interactive_payload=interactive,
        reply_to_message_id=reply_to_message_id,
        channel_message_id=ref.channel_message_id,
        payload={"adapter_ref": ref.channel_message_id},
        sent_at=sent_at,
    )
    _da.insert_message(session, msg)
    conv.last_message_at = sent_at
    await session.commit()
    await session.refresh(msg)
    await session.refresh(conv)

    await audit.log(
        "conversations.message_sent",
        entity_type="conversation",
        entity_id=conv.id,
        after={
            "channel": conv.channel.value,
            "external_id": conv.external_id,
            "message_id": str(msg.id),
        },
    )
    if is_first_outbound and conv.contact_id is not None:
        await activities_log(
            entity_type="contact",
            entity_id=conv.contact_id,
            type=ActivityType.whatsapp
            if conv.channel == ConversationChannel.whatsapp
            else ActivityType.note,
            payload={
                "channel": conv.channel.value,
                "preview": text_body[:120],
                "conversation_id": str(conv.id),
            },
            user_id=user_id,
            org_id=conv.org_id,
        )
    return msg


async def receive_webhook(
    session: AsyncSession,
    *,
    channel: ConversationChannel,
    payload: dict[str, Any],
    received_via_phone_id: str | None = None,
) -> Message | None:
    """Process an inbound webhook event.

    Returns the persisted `Message` row for text/media inbound events.
    Returns `None` when the event was a reaction (Step 7) — those don't
    create a new row, they patch the target message's `reactions` JSONB
    in-place. The router still responds 202 in both cases."""
    adapter = resolve(channel)
    parsed: InboundMessage = adapter.parse_webhook(payload)

    conv = await _find_or_create_conversation(
        session,
        channel=channel,
        external_id=parsed.external_id,
        received_via_phone_id=received_via_phone_id,
    )
    sent_at = parsed.sent_at or datetime.now(timezone.utc)

    # whatsapp-platform-upgrade Step 24 — click-to-WhatsApp ad
    # attribution. Single-touch: capture only when the conversation
    # has never recorded an acquisition source. Subsequent inbounds
    # (even from a different ad) don't overwrite the original
    # attribution — multi-touch is a future spec. Best-effort:
    # the ad-id → campaign-name lookup talks to Meta and may fail
    # (token expired, ad deleted, network); we still persist the
    # raw referral payload so the operator gets *some* attribution
    # even on a degraded lookup.
    if (
        parsed.referral
        and channel == ConversationChannel.whatsapp
        and not conv.acquisition_source
    ):
        try:
            from src.app.core.integrations.meta.ads_lookup import (
                resolve_ad,
            )

            source_type = str(
                parsed.referral.get("source_type") or ""
            ).lower()
            ad_id_raw = parsed.referral.get("source_id")
            source = (
                "ad"
                if source_type in ("ad", "ad_post", "post")
                else "organic"
            )
            metadata: dict[str, Any] = {}
            if source == "ad" and ad_id_raw:
                lookup = await resolve_ad(
                    session,
                    org_id=conv.org_id,
                    ad_id=str(ad_id_raw),
                )
                if lookup:
                    metadata = lookup

            conv.acquisition_source = source
            conv.acquisition_ad_id = (
                str(ad_id_raw) if ad_id_raw else None
            )
            conv.acquisition_campaign_id = metadata.get(
                "campaign_id"
            )
            conv.acquisition_landing_url = str(
                parsed.referral.get("source_url") or ""
            ) or None
            # Persist the whole referral envelope so the chip / ad
            # ROI widget can pull the headline + prefilled body
            # without a follow-up Meta call. Merge in the resolved
            # campaign labels too.
            payload = dict(parsed.referral)
            if metadata:
                payload["_resolved"] = metadata
            conv.acquisition_referral_payload = payload
            await session.commit()
            await session.refresh(conv)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception(
                "attribution capture failed for conv %s", conv.id
            )

    # Step 7: reaction events short-circuit. Locate the target message
    # (by its wamid) and mutate its `reactions` JSONB. No new row, no
    # unread bump, no notification — matches WhatsApp's UX where
    # reactions don't surface as fresh messages in the recipient's
    # inbox count.
    if parsed.reaction is not None:
        await _apply_inbound_reaction(
            session,
            conversation_id=conv.id,
            target_wamid=parsed.reaction["target_channel_message_id"],
            emoji=parsed.reaction.get("emoji") or "",
            reactor_external_id=parsed.reaction.get("reactor_external_id"),
            event_time=sent_at,
        )
        await session.commit()
        return None

    # Step 7: resolve the quoted-reply target back to our UUID by
    # looking up the wamid on `Message.channel_message_id`. If we don't
    # find it (e.g. the original was sent before this conversation was
    # attached to our system), leave `reply_to_message_id` NULL but
    # keep the rest of the inbound row — the frontend renders "Replied
    # to an earlier message" without the snippet.
    reply_to_uuid: uuid.UUID | None = None
    if parsed.reply_to_channel_message_id:
        target = await _da.get_message_by_channel_message_id(
            session,
            channel_message_id=parsed.reply_to_channel_message_id,
            conversation_id=conv.id,
        )
        if target is not None:
            reply_to_uuid = target.id

    msg = Message(
        org_id=conv.org_id,
        conversation_id=conv.id,
        direction=MessageDirection.in_,
        text=parsed.text,
        attachments=parsed.attachments,
        reply_to_message_id=reply_to_uuid,
        channel_message_id=parsed.channel_message_id,
        payload=parsed.raw,
        sent_at=sent_at,
    )
    _da.insert_message(session, msg)
    conv.last_message_at = sent_at
    # whatsapp-platform-upgrade Step 15 — bump the session-window
    # pivot. Every inbound customer message resets the 24-hour clock.
    # Atomic with the message insert so a webhook racing the
    # in-flight UI poll never sees a stale state.
    conv.last_customer_message_at = sent_at
    conv.unread_count = (conv.unread_count or 0) + 1
    await session.commit()
    await session.refresh(msg)
    await session.refresh(conv)

    if conv.assigned_to_id is not None:
        await notify(
            org_id=conv.org_id,
            user_id=conv.assigned_to_id,
            type="conversation.message",
            title=f"New message on {conv.channel.value}",
            body=(parsed.text or "")[:160] or None,
            payload={
                "conversation_id": str(conv.id),
                "channel": conv.channel.value,
            },
        )

    # whatsapp-platform-upgrade Step 26 — QR / wa.me attribution match.
    # Best-effort: if this is a plain inbound (no Meta referral block
    # already captured in Step 24's branch above) and the conversation
    # has no acquisition source yet, try to pair the inbound text with
    # a recent quick-link click whose `prefilled_hash` matches. Single-
    # touch — same convention as Step 24.
    if (
        conv.channel == ConversationChannel.whatsapp
        and not customer_opted_out
        and not conv.acquisition_source
        and parsed.text
    ):
        try:
            from src.app.core.integrations.whatsapp.quick_links import (
                attribute_inbound,
            )

            await attribute_inbound(
                session,
                conversation=conv,
                inbound_text=parsed.text,
            )
            await session.refresh(conv)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception(
                "quick-link attribution match failed for conv %s",
                conv.id,
            )

    # whatsapp-platform-upgrade Step 25 — WhatsApp Flows submission.
    # When the inbound carried an `nfm_reply` attachment, hand the
    # parsed form data off to the flows service. Best-effort: any
    # failure inside the dispatcher is logged + swallowed so the
    # message row + downstream pipeline keep flowing.
    if (
        conv.channel == ConversationChannel.whatsapp
        and parsed.attachments
    ):
        nfm = next(
            (
                a
                for a in parsed.attachments
                if isinstance(a, dict)
                and a.get("type") == "nfm_reply"
            ),
            None,
        )
        if nfm is not None:
            try:
                from src.app.core.integrations.whatsapp.flows_service import (
                    record_submission,
                )

                await record_submission(
                    session,
                    org_id=conv.org_id,
                    flow_token=nfm.get("flow_token"),
                    contact_id=conv.contact_id,
                    conversation_id=conv.id,
                    response_data=dict(nfm.get("form_data") or {}),
                )
            except Exception:  # noqa: BLE001
                import logging

                logging.getLogger(__name__).exception(
                    "flow submission dispatch failed for conv %s", conv.id
                )

    # whatsapp-platform-upgrade Step 22 — DPDP opt-in auto-flip.
    # Runs BEFORE auto-reply / keyword / AI engines so a STOP-keyword
    # customer never gets a greeting or AI follow-up on the same
    # webhook tick. The helper:
    #   * On STOP keyword: flip the contact to `opted_out` and ship
    #     the unsubscribe-confirmation template via the WhatsApp
    #     adapter, then short-circuit the rest of the pipeline.
    #   * On first inbound from a `never_contacted` contact: flip to
    #     `implicit`. Other engines still fire.
    # All failures are caught inside the helper; the inbound row is
    # never rolled back. The contact lookup is best-effort — when
    # the conversation has no `contact_id` yet (e.g. unknown phone),
    # the helper returns None and the pipeline continues unchanged.
    customer_opted_out = False
    if (
        conv.channel == ConversationChannel.whatsapp
        and conv.contact_id is not None
    ):
        from src.app.core.contacts.consent_service import (
            auto_flip_on_inbound,
        )
        from src.app.core.contacts.data_access import get_contact

        try:
            contact = await get_contact(session, conv.contact_id)
            if contact is not None:
                # First inbound = the row we just persisted IS the
                # first inbound on this conversation. The "first ever
                # customer message" signal lives on contact-status
                # rather than conv-history so a customer who reuses
                # the channel after a wipe still counts as
                # implicit-consent on the next inbound.
                is_first = (
                    contact.whatsapp_opt_in_status == "never_contacted"
                )
                result = await auto_flip_on_inbound(
                    session,
                    contact=contact,
                    inbound_text=parsed.text,
                    is_first_inbound=is_first,
                )
                if result is not None and result.persisted:
                    await session.commit()
                    if result.new_status == "opted_out":
                        customer_opted_out = True
                        # Ship the "you've been unsubscribed"
                        # confirmation. Best-effort: any failure
                        # (template missing, adapter down) is logged
                        # but doesn't roll back the opt-out itself
                        # — DPDP compliance trumps the courtesy.
                        from src.app.core.contacts.consent_service import (
                            send_opt_out_confirmation,
                        )

                        await send_opt_out_confirmation(
                            session, conversation=conv
                        )
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception(
                "opt-in auto-flip failed for conv %s", conv.id
            )

    # whatsapp-platform-upgrade Step 16 — fire auto-reply pipeline.
    # Greeting + out-of-hours away dispatch after the inbound row is
    # persisted so cooldown queries see consistent state. Failures
    # are caught inside `dispatch_auto_replies`; this call never
    # raises into the webhook handler.
    if conv.channel == ConversationChannel.whatsapp and not customer_opted_out:
        from src.app.core.integrations.whatsapp.auto_reply import (
            dispatch_auto_replies,
        )

        await dispatch_auto_replies(
            session,
            conversation=conv,
            inbound_message_id=msg.id,
        )

        # whatsapp-platform-upgrade Step 17 — keyword rule engine.
        # Runs AFTER auto-reply so a new-contact greeting fires
        # before any keyword-driven actions. Engine catches its own
        # exceptions; failures here never roll back the inbound row.
        from src.app.core.integrations.whatsapp.keyword_engine import (
            dispatch_keyword_rules,
        )

        await dispatch_keyword_rules(
            session,
            conversation=conv,
            text=parsed.text,
        )

        # whatsapp-platform-upgrade Step 18 — auto-assignment engine.
        # Skips when the conversation already has an `assigned_to_id`
        # (set manually or by a keyword `assign_to_user` action).
        # Engine catches its own exceptions; failures never roll
        # back the inbound row.
        await session.refresh(conv)
        if conv.assigned_to_id is None:
            from src.app.core.integrations.whatsapp.assignment_engine import (
                dispatch_assignment,
            )

            await dispatch_assignment(session, conversation=conv)

        # whatsapp-platform-upgrade Step 19 — AI agent. When the
        # conversation has `ai_handling=true`, the AI reply pipeline
        # generates a response (or escalates to a human on low
        # confidence / handover keyword / explicit AI request).
        # Failures are caught inside; this call never raises into
        # the webhook handler.
        await session.refresh(conv)
        if conv.ai_handling:
            from src.app.core.integrations.whatsapp.ai_handler import (
                dispatch_ai_response,
            )

            await dispatch_ai_response(
                session,
                conversation=conv,
                inbound_text=parsed.text,
            )
    return msg


async def react_to_message(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    user_id: uuid.UUID,
    emoji: str | None,
) -> Message:
    """Outbound reaction (whatsapp-platform-upgrade Step 7).

    Calls the channel adapter's `send_reaction`, then applies the
    reactor's emoji to the target message's `reactions` JSONB locally:

      * `emoji=None|""` removes any existing reaction by this user.
      * Otherwise replaces (Meta enforces one reaction per user per
        message; we mirror that constraint).

    Returns the updated target `Message`. Raises `ValueError` (→ 400)
    if the message doesn't belong to the conversation, has no
    `channel_message_id` yet, or the channel isn't WhatsApp."""
    conv = await get_conversation(session, conversation_id)
    if conv.channel != ConversationChannel.whatsapp:
        raise ValueError(
            "Reactions are only supported on WhatsApp conversations."
        )

    target = await _da.get_message_by_id(session, message_id)
    if target is None or target.conversation_id != conv.id:
        raise ValueError(
            "message_id does not belong to this conversation."
        )
    if not target.channel_message_id:
        raise ValueError(
            "Cannot react to a message that has not been delivered yet."
        )

    adapter = await resolve_whatsapp_adapter(session)
    await adapter.send_reaction(
        external_id=conv.external_id,
        target_channel_message_id=target.channel_message_id,
        emoji=emoji,
    )

    now = datetime.now(timezone.utc)
    target.reactions = _merge_reaction(
        list(target.reactions or []),
        actor=str(user_id),
        emoji=emoji,
        ts=now,
    )
    await session.commit()
    await session.refresh(target)
    return target


def _merge_reaction(
    existing: list[dict[str, Any]],
    *,
    actor: str,
    emoji: str | None,
    ts: datetime,
) -> list[dict[str, Any]]:
    """Replace `actor`'s entry in `existing`; empty `emoji` removes it.

    The list stays at most one entry per `actor` — WhatsApp's
    one-reaction-per-user-per-message rule mirrored locally so the
    frontend doesn't have to re-coalesce on render."""
    rest = [r for r in existing if r.get("actor") != actor]
    if not emoji:
        return rest
    rest.append(
        {"actor": actor, "emoji": emoji, "ts": ts.isoformat()}
    )
    return rest


async def _apply_inbound_reaction(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    target_wamid: str,
    emoji: str,
    reactor_external_id: str | None,
    event_time: datetime,
) -> None:
    """Apply an inbound reaction event to the target message's
    `reactions` JSONB. Silent no-op when the target wamid doesn't
    match any of our message rows — Meta occasionally replays old
    reactions for messages we never persisted (e.g. sent through a
    different system)."""
    target = await _da.get_message_by_channel_message_id(
        session,
        channel_message_id=target_wamid,
        conversation_id=conversation_id,
    )
    if target is None:
        return
    actor = reactor_external_id or "external"
    target.reactions = _merge_reaction(
        list(target.reactions or []),
        actor=actor,
        emoji=emoji,
        ts=event_time,
    )


async def patch_conversation(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    payload: ConversationPatch,
) -> Conversation:
    conv = await get_conversation(session, conversation_id)
    before = _snapshot(conv)
    changed = False
    if payload.assigned_to_id is not None:
        conv.assigned_to_id = payload.assigned_to_id
        changed = True
    if payload.status is not None:
        conv.status = payload.status
        changed = True
    if payload.ai_handling is not None:
        conv.ai_handling = payload.ai_handling
        changed = True
    if changed:
        await session.commit()
        await session.refresh(conv)
        await audit.log(
            "conversations.patched",
            entity_type="conversation",
            entity_id=conv.id,
            before=before,
            after=_snapshot(conv),
        )
    return conv


# --- helpers ---------------------------------------------------------------


async def _find_or_create_conversation(
    session: AsyncSession,
    *,
    channel: ConversationChannel,
    external_id: str,
    received_via_phone_id: str | None = None,
) -> Conversation:
    existing = await _da.find_conversation_for_channel_external(
        session, channel=channel, external_id=external_id
    )
    if existing is not None:
        return existing

    # New conversation — `org_id` comes from `RequestContext` via the
    # TenantScoped mixin (webhook intake sets it on the way in).
    from src.app.shared.context import get_context

    ctx = get_context()
    if ctx.org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="webhook has no tenant context",
        )

    contact_id = None
    if channel in _PHONE_CHANNELS:
        contact_id = await _resolve_or_create_contact_by_phone(
            session, org_id=ctx.org_id, phone=external_id
        )

    # whatsapp-platform-upgrade Step 19 — if the org has
    # `ai_handling_default_enabled=true` on its WhatsApp config,
    # the new conversation lands with `ai_handling=true` so the AI
    # agent handles it from the very first inbound. Best-effort
    # lookup: errors fall back to the default-off behaviour.
    ai_handling_default = False
    if channel == ConversationChannel.whatsapp:
        try:
            from src.app.core.integrations.whatsapp.connect import (
                get_active_config,
            )

            bundle = await get_active_config(session)
            if bundle is not None:
                _, wa_config = bundle
                ai_handling_default = bool(
                    getattr(wa_config, "ai_handling_default_enabled", False)
                )
        except Exception:
            pass

    conv = Conversation(
        org_id=ctx.org_id,
        channel=channel,
        external_id=external_id,
        contact_id=contact_id,
        status=ConversationStatus.open,
        ai_handling=ai_handling_default,
        # whatsapp-platform-upgrade Step 27a — stamp the inbound
        # phone so the composer can default Send-From back to the
        # same number on manual reply. Only set on the create branch
        # — the find branch returns the existing row untouched, so
        # a conversation never gets its received_via_phone_id
        # silently rewritten by a webhook from a different number.
        received_via_phone_id=received_via_phone_id,
    )
    _da.insert_conversation(session, conv)
    await session.flush()
    return conv


async def _resolve_or_create_contact_by_phone(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    phone: str,
) -> uuid.UUID | None:
    """Look up a contact by phone in this org. If none exists, create
    one with `full_name = phone` as a placeholder so the inbox has a
    row to render. Returns the resolved/created contact id, or None if
    the phone string is empty."""
    if not phone:
        return None
    existing = await data_access.get_contact_by_phone(session, phone)
    if existing is not None:
        return existing.id
    contact = Contact(
        org_id=org_id,
        full_name=phone,
        phone=phone,
        source="whatsapp",
    )
    data_access.insert_contact(session, contact)
    await session.flush()
    return contact.id


def _snapshot(c: Conversation) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "channel": c.channel.value,
        "external_id": c.external_id,
        "contact_id": str(c.contact_id) if c.contact_id else None,
        "assigned_to_id": str(c.assigned_to_id) if c.assigned_to_id else None,
        "status": c.status.value,
        "ai_handling": c.ai_handling,
    }


__all__ = [
    "get_conversation",
    "list_conversations",
    "list_messages",
    "patch_conversation",
    "react_to_message",
    "receive_webhook",
    "send_outbound",
]
