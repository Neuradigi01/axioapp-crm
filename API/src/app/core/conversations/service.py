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
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.activities.models import ActivityType
from src.app.core.activities.service import log as activities_log
from src.app.core.contacts import service as contacts_service
from src.app.core.contacts.models import Contact
from src.app.core.conversations import data_access as _da
from src.app.core.conversations.adapters import InboundMessage
from src.app.core.conversations.adapters.email import send_email
from src.app.core.conversations.adapters.whatsapp import (
    resolve_whatsapp_adapter,
)
from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
    ConversationStatus,
    Message,
    MessageDirection,
)
from src.app.core.conversations.registry import resolve
from src.app.core.conversations.schemas import ConversationContactSet, ConversationPatch
from src.app.core.email.models import EmailAccountSyncState
from src.app.core.events import bus as events_bus
from src.app.core.events.event_catalog import WHATSAPP_MESSAGE_RECEIVED
from src.app.core.notifications.service import notify
from src.app.core.permissions.service import role_has_permission
from src.app.shared.db.queries import ensure_found
from src.app.shared.storage import get_storage

# Channels whose `external_id` is a phone number; the webhook intake
# tries to resolve / auto-create a contact for these so the inbox can
# show a name instead of the raw phone string.
_PHONE_CHANNELS = {ConversationChannel.whatsapp, ConversationChannel.sms}


# --- reads -----------------------------------------------------------------


async def list_conversations(
    session: AsyncSession,
    *,
    channel: ConversationChannel | None = None,
    status_filter: ConversationStatus | None = None,
    assigned_to: str | None = None,
    q: str | None = None,
    tag_ids: list[uuid.UUID] | None = None,
    unread_only: bool = False,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Conversation], int]:
    # `assigned_to` may be a UUID string (filter to that owner),
    # the sentinel `'unassigned'` (rows with `assigned_to_id IS NULL`),
    # or absent (no filter). Anything else raises 422.
    assigned_to_id: uuid.UUID | None = None
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

    # Visibility is org-wide — every user with ``conversations.read``
    # sees every chat. Ownership (take-over) is what's restricted;
    # see ``ensure_can_write_conversation``.
    return await _da.list_conversations_query(
        session,
        channel=channel,
        status_filter=status_filter,
        assigned_to_id=assigned_to_id,
        assigned_to_unassigned=assigned_to_unassigned,
        q=q,
        tag_ids=tag_ids,
        unread_only=unread_only,
        page=page,
        size=size,
    )


async def open_message_attachment(
    message: Message, safe_key: str
) -> tuple[AsyncIterator[bytes], int]:
    """Open a committed inbound-email attachment for streaming.

    The caller has already checked the message's org and that
    `safe_key` is listed in its attachments. 404 when the blob is gone.
    """
    key = f"{message.org_id}/messages/{message.id}/{safe_key}"
    storage = get_storage()
    try:
        stat = await storage.stat(key)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="attachment not found") from exc
    return storage.open_stream(key), stat.size


async def get_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> Conversation:
    return ensure_found(
        await _da.get_conversation_by_id(session, conversation_id),
        entity="conversation",
    )


async def bulk_last_message_bodies(
    session: AsyncSession, conversation_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str | None]:
    """Thin passthrough to the DAL — kept in service so the router
    doesn't import DAL directly (layered-architecture rule). Returns
    a whitespace-collapsed 140-char snippet per conversation for the
    inbox preview line."""
    return await _da.bulk_last_message_body_for_conversations(session, conversation_ids)


async def compute_ai_active(
    session: AsyncSession,
    conversations: list[Conversation],
) -> dict[uuid.UUID, bool]:
    """Per-conversation "is AI actually going to answer this?" flag,
    mirroring the rule ``send_outbound`` uses to auto-pause on human
    reply: ``NOT ai_paused AND (ai_handling OR org has an active
    assistant bound to this channel)``.

    Fetches the org's active bound-channel set once and evaluates
    each conversation against it in memory — no N+1 on the inbox
    list. Empty when the caller has no conversations."""
    if not conversations:
        return {}
    from src.app.core.ai_assistants import data_access as _ai_da

    bound_channels = await _ai_da.list_active_bound_channels(session)
    result: dict[uuid.UUID, bool] = {}
    for conv in conversations:
        if conv.ai_paused:
            result[conv.id] = False
            continue
        if conv.ai_handling:
            result[conv.id] = True
            continue
        result[conv.id] = conv.channel.value in bound_channels
    return result


# --- access gates ---------------------------------------------------------


async def _caller_can_assign_others(session: AsyncSession, caller_role_id: uuid.UUID) -> bool:
    """Owner + Admin default. Employees don't hold this key, so they
    can only act on their own chat or an unassigned one."""
    return await role_has_permission(session, caller_role_id, "conversations.assign_others")


async def ensure_can_write_conversation(
    session: AsyncSession,
    *,
    conv: Conversation,
    caller_user_id: uuid.UUID,
    caller_role_id: uuid.UUID,
) -> None:
    """Guard for reply / react / tag / mark-read / close / take-over-AI.

    Product rule (locked 2026-09-10):

    * **Unassigned chats** — any user with ``conversations.write`` can
      jump in and reply. The reply auto-claims the chat for the
      sender (mirror of ``send_outbound`` / ``send_email_reply``
      auto-assign). No admin gate — unassigned = free-for-all pool.
    * **Assigned chats** — only the current assignee can act.
      *Other* employees viewing the chat get 403 and see the view-
      only banner. Only Owner / Admin (``conversations.assign_others``)
      can "take over" someone else's chat by reassigning or by
      hitting the Take Over from AI button.

    Rules:

    * Chat unassigned → passes (anyone with write can jump in).
    * Caller is the current assignee → passes.
    * Caller has ``conversations.assign_others`` (Owner / Admin) →
      passes regardless of assignment.
    * Otherwise → 403.
    """
    if conv.assigned_to_id is None:
        return
    if conv.assigned_to_id == caller_user_id:
        return
    if await _caller_can_assign_others(session, caller_role_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "This conversation is assigned to another user. "
            "Ask an Owner or Admin to reassign it before you can act on it."
        ),
    )


async def ensure_can_assign_conversation(
    session: AsyncSession,
    *,
    conv: Conversation,
    caller_user_id: uuid.UUID,
    caller_role_id: uuid.UUID,
    new_assignee_id: uuid.UUID | None,
) -> None:
    """Guard for `PATCH /{id}` when the payload touches
    ``assigned_to_id``. Three allowed transitions:

    * **Owner / Admin** (holds ``conversations.assign_others``) →
      any transition, including reassigning across users and
      unassigning.
    * **Self-take-over** — chat is currently unassigned and the
      caller is setting the assignee to themselves.
    * **Owner-side transfer** — the current assignee is transferring
      *their own* chat to another user (or unassigning it). The
      transfer target can be anyone.

    Every other transition (reassigning someone else's chat,
    stealing another user's chat, setting the assignee to a third
    party from an unassigned state without being Owner/Admin) → 403.
    """
    if await _caller_can_assign_others(session, caller_role_id):
        return
    # Self-take-over of an orphan chat.
    if conv.assigned_to_id is None and new_assignee_id == caller_user_id:
        return
    # Current assignee transferring their own chat (or handing it back
    # to unassigned). New assignee can be any user or None.
    if conv.assigned_to_id == caller_user_id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Only the current assignee, an Owner, or an Admin can change "
            "who this conversation is assigned to."
        ),
    )


async def list_messages(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    limit: int | None = None,
    before_id: uuid.UUID | None = None,
) -> list[Message]:
    """Thin passthrough — service exists so the router can add
    business rules later (visibility, redaction) without touching the
    DAL contract. ``limit=None`` returns the whole thread (used by the
    export paths); pass ``limit`` for the paginated thread view.

    When ``before_id`` is supplied it must resolve to a real row on
    this conversation; otherwise a stale cursor would silently return
    the newest N messages (index look-past behaviour). Raise 404 instead.
    """
    if before_id is not None:
        ensure_found(
            await _da.get_message_by_id(session, before_id),
            entity="message",
        )
    messages = await _da.list_messages_for_conversation(
        session, conversation_id, limit=limit, before_id=before_id
    )
    # Enrich every message with sender_display_name so the note bubble
    # + outbound-message avatar tooltip render authoritatively even
    # for former org members (staffById on the frontend hides inactive
    # users). Single batched lookup — no N+1.
    sender_ids: set[uuid.UUID] = {m.sender_user_id for m in messages if m.sender_user_id}
    if sender_ids:
        name_map = await _da.get_user_display_names_bulk(session, user_uuids=sender_ids)
        for m in messages:
            if m.sender_user_id is not None:
                # Stash on the ORM instance; MessageOut.model_validate
                # picks it up via the new sender_display_name field.
                m.sender_display_name = name_map.get(m.sender_user_id)  # type: ignore[attr-defined]
    return messages


# --- writes ----------------------------------------------------------------


async def send_email_reply(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    body_text: str,
    body_html: str | None = None,
    subject: str | None = None,
    account_id: uuid.UUID | None = None,
) -> Message:
    """Email-channel counterpart to `send_outbound` — routes through
    the typed `send_email(...)` path (subject + connected-mailbox
    account) instead of the generic ChannelAdapter `.send()` (which
    the email adapter guards with `EmailUseSendEmailEndpoint`).

    Defaults so the composer's plain body-only send Just Works:
      * `account_id` — the sender's first `live` connected mailbox.
        Errors 400 when the sender has none.
      * `subject` — pulled from the last inbound message's
        `channel_message_id` metadata if available, otherwise a
        neutral fallback. Callers may override to change wording.
      * threading — auto-picks the newest inbound message id as
        `in_reply_to_message_id` so replies thread in Gmail / Outlook.
    """
    conv = await get_conversation(session, conversation_id)
    if conv.channel != ConversationChannel.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint is for email conversations only.",
        )
    if not conv.contact_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email conversation has no linked contact — cannot reply.",
        )

    # tasks/ai-assistants-omnichannel Step 5 — mirror of the WhatsApp
    # ``send_outbound`` auto-pause. A human replying on an AI-handled
    # email thread implicitly claims the conversation from the AI, so
    # the next inbound doesn't trigger another AI reply that stomps
    # over the human's answer. Intercom / Wati semantics: one implicit
    # takeover, no extra button. Guarded by the same bound-assistant
    # lookup ``send_outbound`` uses so the pause fires only for orgs
    # that actually have AI wired on the email channel.
    if not conv.ai_paused:
        from src.app.core.ai_assistants import data_access as _ai_da
        from src.app.core.ai_assistants.models import AiAssistantChannel

        bound = await _ai_da.find_active_assistant_bound_to_channel(
            session, channel=AiAssistantChannel.email.value
        )
        if bound is not None:
            await apply_auto_pause(
                session,
                conversation=conv,
                actor_user_id=user_id,
                reason="human_reply",
            )
            await session.commit()
            await session.refresh(conv)

    # Default sender: the org's SHARED sender identity from Settings →
    # Integrations → Email Sender. Preference matches
    # ``resolve_org_sender`` (shared/email/org_sender.py): verified SMTP
    # sender first (default, else any), then live OAuth mailbox. Every
    # rep sends through the same org-scoped identity; the persisted
    # Message still records ``sender_user_id`` for author attribution.
    #
    # ``sync_state`` gating on the OAuth branch: any non-``disconnected``
    # row with a live refresh_token can send — sync_state describes
    # INBOUND backfill only (project_email_sender_stuck_syncing_fix).
    smtp_sender_id: uuid.UUID | None = None
    if account_id is None:
        from sqlalchemy import select as _select

        from src.app.core.email.models import EmailAccount
        from src.app.core.email_senders import data_access as _smtp_da

        default_smtp = await _smtp_da.find_default_verified(session, org_id=conv.org_id)
        smtp_row = default_smtp or await _smtp_da.find_any_verified(session, org_id=conv.org_id)
        if smtp_row is not None:
            smtp_sender_id = smtp_row.id
        else:
            oauth = (
                await session.execute(
                    _select(EmailAccount)
                    .where(
                        EmailAccount.org_id == conv.org_id,
                        EmailAccount.sync_state != EmailAccountSyncState.disconnected,
                        EmailAccount.refresh_token_enc.is_not(None),
                    )
                    .order_by(EmailAccount.connected_at.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if oauth is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "This organisation has no connected email account. "
                        "Owner or Admin must connect one in Settings → "
                        "Integrations → Email Sender before anyone can reply "
                        "to email conversations."
                    ),
                )
            account_id = oauth.id

    # Auto-thread on the newest inbound message so Gmail / Outlook
    # collapse the reply into the customer's original thread. Single
    # indexed row instead of pulling the last 50 and scanning.
    last_inbound = await _da.get_last_inbound_message(session, conversation_id)

    # Subject: fall back to a neutral "Re:" — Gmail / Outlook thread on
    # the `In-Reply-To` / `References` MIME headers we set below, so
    # subject is display-only.
    subject_final = subject or "Re: (no subject)"

    result = await send_email(
        session,
        org_id=conv.org_id,
        sender_user_id=user_id,
        account_id=account_id,
        smtp_sender_id=smtp_sender_id,
        contact_id=conv.contact_id,
        subject=subject_final,
        body_text=body_text,
        body_html=body_html,
        in_reply_to_message_id=last_inbound.id if last_inbound else None,
        conversation_id=conversation_id,
    )
    # Ownership handshake — email reply on an *unassigned* thread
    # implicitly claims it for the sender. Same rationale as
    # ``send_outbound`` (WhatsApp) and ``pause_ai``. Re-fetch since
    # ``send_email`` opens its own transaction; the write here is a
    # separate small commit — cheap and keeps the auto-claim local.
    conv_refreshed = await get_conversation(session, conversation_id)
    if conv_refreshed.assigned_to_id is None:
        conv_refreshed.assigned_to_id = user_id
        await session.commit()
    return result.message


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
    # tasks/ai-assistants-omnichannel Step 5 — auto-pause AI when a
    # human replies on an AI-active conversation without clicking
    # Take Over first. Matches Intercom / Wati semantics: one implicit
    # takeover; no extra button to remember. Guarded by both the
    # legacy ``ai_handling`` flag and the new-style bound-assistant
    # lookup so orgs still on the legacy config get the same behaviour.
    if not conv.ai_paused:
        should_pause = bool(conv.ai_handling)
        if not should_pause:
            from src.app.core.ai_assistants import data_access as _ai_da
            from src.app.core.ai_assistants.models import AiAssistantChannel

            channel_map: dict[ConversationChannel, str] = {
                ConversationChannel.whatsapp: AiAssistantChannel.whatsapp.value,
                ConversationChannel.email: AiAssistantChannel.email.value,
            }
            channel_key = channel_map.get(conv.channel)
            if channel_key is not None:
                bound = await _ai_da.find_active_assistant_bound_to_channel(
                    session, channel=channel_key
                )
                should_pause = bound is not None
        if should_pause:
            await apply_auto_pause(
                session,
                conversation=conv,
                actor_user_id=user_id,
                reason="human_reply",
            )
            # Commit the pause + system marker BEFORE the adapter send
            # so a slow adapter can't leave the pause in an unflushed
            # state visible to a concurrent inbound webhook.
            await session.commit()
            await session.refresh(conv)

    # whatsapp-platform-upgrade Step 23 — block-list pre-flight on
    # WhatsApp manual outbound. Refuse cleanly with ValueError →
    # 400 so the SPA surfaces the reason in the composer.
    if conv.channel == ConversationChannel.whatsapp:
        from src.app.core.integrations.whatsapp.block_list import (
            is_blocked,
        )

        block_hit = await is_blocked(session, org_id=conv.org_id, phone=conv.external_id)
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
        resolved_phone_id = send_from_phone_id or getattr(conv, "received_via_phone_id", None)
        adapter = await resolve_whatsapp_adapter(session, phone_id=resolved_phone_id)
    else:
        adapter = resolve(conv.channel)

    if interactive is not None and conv.channel != ConversationChannel.whatsapp:
        # Interactive messages are a WhatsApp-only surface today.
        # Surface as a 400 via the router (ValueError → HTTPException).
        raise ValueError("Interactive messages are only supported on WhatsApp conversations.")

    # Step 7: resolve the reply target to a channel-side wamid the
    # adapter can put inside `context.message_id`. Mismatches (wrong
    # conversation, target has no `channel_message_id` yet because it's
    # still in flight) raise ValueError → 400.
    reply_to_wamid: str | None = None
    if reply_to_message_id is not None:
        target = await _da.get_message_by_id(session, reply_to_message_id)
        if target is None or target.conversation_id != conv.id:
            raise ValueError("reply_to_message_id does not belong to this conversation.")
        if not target.channel_message_id:
            raise ValueError("Cannot reply to a message that has not been delivered yet.")
        reply_to_wamid = target.channel_message_id

    is_first_outbound = (
        await _da.count_outbound_messages_for_conversation(session, conversation_id) == 0
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
    # Messenger + Instagram adapters need the Page ID / IG Business
    # Account ID (stored on `conv.received_via_phone_id` — overloaded
    # for channel-endpoint id) to resolve the right Page-access token.
    if conv.channel in (ConversationChannel.facebook, ConversationChannel.instagram):
        send_kwargs["received_via_phone_id"] = conv.received_via_phone_id
    ref = await adapter.send(**send_kwargs)
    now = datetime.now(UTC)
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
    # Ownership handshake: an outbound send on an *unassigned* chat is
    # the operator implicitly claiming the thread — same "any employee
    # can jump in on an orphan" flow as `pause_ai`. Already-assigned
    # chats keep their owner (the write-access gate at the router has
    # already authorised the sender).
    if conv.assigned_to_id is None:
        conv.assigned_to_id = user_id
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

    # tasks/chatbot-builder Step 6 — human-takeover cancel (Case #10).
    # ``send_outbound`` is the human-authored outbound path; every
    # message it inserts has ``chatbot_run_id IS NULL``. When a human
    # jumps in on a conversation with a parked bot run, cancel the
    # run so the bot doesn't step over the human's reply.
    # Best-effort: any failure inside cancel is logged + swallowed
    # so the outbound message itself is never rolled back.
    try:
        from src.app.core.chatbots import engine as _chatbot_engine

        canceled = await _chatbot_engine.cancel_parked_runs_for_conversation(
            session,
            conversation_id=conv.id,
            reason="human_took_over",
        )
        if canceled:
            import logging

            logging.getLogger(__name__).info(
                "chatbots.human_takeover canceled=%d conv=%s user=%s",
                canceled,
                conv.id,
                user_id,
            )
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("chatbots.human_takeover_failed conv=%s", conv.id)
    return msg


async def send_template_message(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    template_id: uuid.UUID,
    variables: dict[str, str],
    send_from_phone_id: str | None = None,
) -> Message:
    """Send an approved WhatsApp template through an existing
    conversation. Used by the inbox composer's inline template picker
    when the 24-hour session window has expired (Meta's rule: only
    approved templates outside the window).

    Guards:
      * conversation must be WhatsApp — 400 otherwise
      * template must belong to this org and be APPROVED — 404 / 400
      * ``variables`` count must equal the template's ``variable_count``
    """
    from src.app.core.integrations.whatsapp import data_access as _wa_da
    from src.app.core.integrations.whatsapp.block_list import is_blocked
    from src.app.core.integrations.whatsapp.meta_variables import (
        extract_named_body,
        resolve_named_body_to_positional_params,
    )
    from src.app.core.templates import data_access as _templates_da
    from src.app.core.templates.models import TemplateExternalStatus
    from src.app.core.templates.service import ensure_wa_extension_row
    from src.app.core.tenants import data_access as _tenants_da

    conv = await get_conversation(session, conversation_id)
    if conv.channel != ConversationChannel.whatsapp:
        raise ValueError("Template sends are only supported on WhatsApp conversations.")

    block_hit = await is_blocked(session, org_id=conv.org_id, phone=conv.external_id)
    if block_hit is not None:
        raise ValueError(
            f"This number is on the block list "
            f"(reason: {block_hit.reason}). Unblock it from "
            f"Settings → WhatsApp → Block List to send again."
        )

    # The picker + chatbot template node now pass central library IDs
    # (``tbl_message_templates.id``). Resolve central first, then
    # materialize/find the matching WA extension row for the actual
    # Meta send. Legacy callers that still pass a WA extension row
    # id (``tbl_whatsapp_templates.id``) are handled by the fallback
    # branch so existing bookmarks / integrations don't break.
    central = await _templates_da.get_template(session, org_id=conv.org_id, template_id=template_id)
    if central is not None:
        if central.channel != ConversationChannel.whatsapp:
            raise ValueError("Only WhatsApp templates can be sent through this endpoint.")
        if central.external_status != TemplateExternalStatus.approved:
            raise ValueError(
                "Only APPROVED templates can be sent — this template is not approved yet."
            )
        if not central.is_active:
            raise ValueError(
                "This template is inactive; ask an Owner / Admin to activate it "
                "in the templates library before sending."
            )
        template = await ensure_wa_extension_row(session, template=central)
    else:
        template = await _wa_da.get_by_id(session, template_id)
        if template is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="template not found")
        if (template.status or "").upper() != "APPROVED":
            raise ValueError(
                "Only APPROVED templates can be sent — this template is not approved yet."
            )

    # Auto-resolve any CRM named variables (`{{contact.full_name}}`,
    # `{{org.name}}`, ...) in the template's original body against
    # the conversation's contact + org. Meta only sees positional
    # placeholders (its body is the converted copy), so a
    # named-variable template arrives here with `variable_count=0`
    # but Meta still expects one param per slot at send-time.
    # Without this resolution the send hits Meta with 0 params and
    # gets a #132000 "number of localizable_params does not match"
    # 400 — the same fix `campaigns/service.py` applies for shots.
    #
    # Source of truth for the named body is the central template's
    # ``body_text``: WA extension rows created by the Meta sync only
    # carry the positional body and have ``body_components=NULL``,
    # so extracting from the extension alone misses the named form
    # even when the central row still has ``{{contact.first_name}}``.
    named_body: str | None = None
    if central is not None and central.body_text:
        named_body = central.body_text
    if not named_body:
        named_body = extract_named_body(template.body_components)
    contact_data: dict[str, Any] | None = None
    org_data: dict[str, Any] | None = None
    if named_body:
        contact = (
            await contacts_service.get_contact(session, conv.contact_id)
            if conv.contact_id
            else None
        )
        if contact is not None:
            full_name = contact.full_name or ""
            parts = full_name.split(None, 1) if full_name else []
            contact_data = {
                "id": str(contact.id),
                "first_name": parts[0] if parts else "",
                "last_name": parts[1] if len(parts) > 1 else "",
                "full_name": full_name,
                "email": contact.email or "",
                "phone": contact.phone or "",
                "source": getattr(contact, "source", None) or "",
                "custom_data": dict(getattr(contact, "custom_data", None) or {}),
            }
        org = await _tenants_da.get_organization_by_id(session, conv.org_id)
        if org is not None:
            org_data = {
                "name": org.name or "",
                "support_email": getattr(org, "support_email", "") or "",
            }
    auto_variables = resolve_named_body_to_positional_params(named_body, contact_data, org_data)

    # Convert string-keyed operator variables (from the inline picker's
    # `{{n}}` inputs) to int-keyed. Operator entries override any
    # auto-resolved value for the same slot — the picker is the
    # explicit path, auto-resolution is the fallback for named-only
    # templates where the picker renders no inputs.
    parsed_variables: dict[int, str] = dict(auto_variables)
    for key, val in variables.items():
        try:
            parsed_variables[int(key)] = val
        except (TypeError, ValueError) as exc:
            raise ValueError(f"variables key {key!r} must be a numeric string") from exc

    # Sanity-check against Meta's expectation. `variable_count` is the
    # positional-only count on `template.body`; for a named-var
    # template that's 0, so trust the higher of the two.
    expected = max(int(template.variable_count or 0), len(auto_variables))
    if len(parsed_variables) < expected:
        raise ValueError(
            f"Template expects {expected} variable(s) but got {len(parsed_variables)}."
        )

    resolved_phone_id = send_from_phone_id or getattr(conv, "received_via_phone_id", None)
    adapter = await resolve_whatsapp_adapter(session, phone_id=resolved_phone_id)

    is_first_outbound = (
        await _da.count_outbound_messages_for_conversation(session, conversation_id) == 0
    )

    ref = await adapter.send_template(
        org_id=conv.org_id,
        external_id=conv.external_id,
        template_name=template.name,
        language=template.language,
        variables=parsed_variables,
        header_type=template.header_type,
        header_text=template.header_text,
    )
    now = datetime.now(UTC)
    sent_at = ref.sent_at or now

    # Render a plaintext preview of the template so the inbox row +
    # bubble text isn't blank — substitute `{{n}}` with the resolved
    # value the operator typed. Full body components stay in the
    # `payload` JSONB for debugging.
    preview = template.body or f"[template: {template.name}]"
    for idx, val in parsed_variables.items():
        preview = preview.replace("{{" + str(idx) + "}}", val)

    msg = Message(
        org_id=conv.org_id,
        conversation_id=conv.id,
        direction=MessageDirection.out,
        sender_user_id=user_id,
        text=preview,
        attachments=[],
        interactive_payload=None,
        reply_to_message_id=None,
        channel_message_id=ref.channel_message_id,
        payload={
            "adapter_ref": ref.channel_message_id,
            "template": {
                "id": str(template.id),
                "name": template.name,
                "language": template.language,
                "variables": {str(k): v for k, v in parsed_variables.items()},
            },
        },
        sent_at=sent_at,
    )
    _da.insert_message(session, msg)
    conv.last_message_at = sent_at
    # Ownership handshake — template send on an unassigned chat also
    # claims the thread for the sender. See `send_outbound` above.
    if conv.assigned_to_id is None:
        conv.assigned_to_id = user_id
    await session.commit()
    await session.refresh(msg)
    await session.refresh(conv)

    await audit.log(
        "conversations.template_sent",
        entity_type="conversation",
        entity_id=conv.id,
        after={
            "channel": conv.channel.value,
            "external_id": conv.external_id,
            "message_id": str(msg.id),
            "template_id": str(template.id),
            "template_name": template.name,
        },
    )
    if is_first_outbound and conv.contact_id is not None:
        await activities_log(
            entity_type="contact",
            entity_id=conv.contact_id,
            type=ActivityType.whatsapp,
            payload={
                "channel": conv.channel.value,
                "preview": preview[:120],
                "conversation_id": str(conv.id),
                "template_name": template.name,
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
    pre_parsed: InboundMessage | None = None,
) -> Message | None:
    """Process an inbound webhook event.

    Returns the persisted `Message` row for text/media inbound events.
    Returns `None` when the event was a reaction (Step 7) — those don't
    create a new row, they patch the target message's `reactions` JSONB
    in-place. The router still responds 202 in both cases.

    ``pre_parsed`` skips the adapter's ``parse_webhook`` step when the
    caller has already built the canonical ``InboundMessage`` itself —
    used by the WhatsApp Web (unofficial) events receiver, where the
    Node sidecar has already translated Baileys events into the
    canonical shape before forwarding to FastAPI. ``payload`` is still
    passed because downstream code (attribution match in particular)
    keys off it; the caller passes ``inbound.raw`` there for parity
    with the adapter-parsed path.
    """
    if pre_parsed is not None:
        parsed: InboundMessage = pre_parsed
    else:
        adapter = resolve(channel)
        parsed = adapter.parse_webhook(payload)

    conv = await _find_or_create_conversation(
        session,
        channel=channel,
        external_id=parsed.external_id,
        received_via_phone_id=received_via_phone_id,
        sender_name=parsed.sender_name,
    )

    # Serialize concurrent intake on the same conversation. Meta
    # retries webhooks for up to 7 days on any non-2xx / slow response,
    # and the WhatsApp Web sidecar can independently forward the same
    # event; without a lock, two async workers both pass the
    # channel_message_id dedup check (their SELECTs see each other's
    # uncommitted inserts as absent under READ COMMITTED), both persist
    # the inbound, and both dispatch an AI reply → duplicate bubbles.
    # ``pg_advisory_xact_lock`` is transaction-scoped so it releases on
    # commit / rollback with no cleanup path. Cross-conversation
    # parallelism is unaffected — the lock key is per-conversation.
    from sqlalchemy import text as _sql_text

    await session.execute(
        _sql_text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"conv:{conv.id}"},
    )

    sent_at = parsed.sent_at or datetime.now(UTC)

    # whatsapp-platform-upgrade Step 24 — click-to-WhatsApp ad
    # attribution. Single-touch: capture only when the conversation
    # has never recorded an acquisition source. Subsequent inbounds
    # (even from a different ad) don't overwrite the original
    # attribution — multi-touch is a future spec. Best-effort:
    # the ad-id → campaign-name lookup talks to Meta and may fail
    # (token expired, ad deleted, network); we still persist the
    # raw referral payload so the operator gets *some* attribution
    # even on a degraded lookup.
    if parsed.referral and channel == ConversationChannel.whatsapp and not conv.acquisition_source:
        try:
            from src.app.core.integrations.meta.ads_lookup import (
                resolve_ad,
            )

            source_type = str(parsed.referral.get("source_type") or "").lower()
            ad_id_raw = parsed.referral.get("source_id")
            source = "ad" if source_type in ("ad", "ad_post", "post") else "organic"
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
            conv.acquisition_ad_id = str(ad_id_raw) if ad_id_raw else None
            conv.acquisition_campaign_id = metadata.get("campaign_id")
            conv.acquisition_landing_url = str(parsed.referral.get("source_url") or "") or None
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

            logging.getLogger(__name__).exception("attribution capture failed for conv %s", conv.id)

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

    # WhatsApp Cloud API retries webhooks for up to 7 days on non-2xx.
    # Short-circuit if we've already persisted this wamid on this
    # conversation — the DB has a partial unique index guarding it,
    # but skipping the insert avoids an IntegrityError round-trip and
    # keeps the response idempotent (returns the existing row).
    if parsed.channel_message_id:
        existing = await _da.get_message_by_channel_message_id(
            session,
            channel_message_id=parsed.channel_message_id,
            conversation_id=conv.id,
        )
        if existing is not None:
            return existing

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
    if conv.channel == ConversationChannel.whatsapp and not conv.acquisition_source and parsed.text:
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
    if conv.channel == ConversationChannel.whatsapp and parsed.attachments:
        nfm = next(
            (a for a in parsed.attachments if isinstance(a, dict) and a.get("type") == "nfm_reply"),
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
    if conv.channel == ConversationChannel.whatsapp and conv.contact_id is not None:
        from src.app.core.contacts.consent_service import (
            auto_flip_on_inbound,
        )
        from src.app.core.contacts.service import get_contact

        try:
            contact = await get_contact(session, conv.contact_id)
            if contact is not None:
                # First inbound = the row we just persisted IS the
                # first inbound on this conversation. The "first ever
                # customer message" signal lives on contact-status
                # rather than conv-history so a customer who reuses
                # the channel after a wipe still counts as
                # implicit-consent on the next inbound.
                is_first = contact.whatsapp_opt_in_status == "never_contacted"
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

                        await send_opt_out_confirmation(session, conversation=conv)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception("opt-in auto-flip failed for conv %s", conv.id)

    # tasks/chatbot-builder Step 5 — precedence pre-check (Decision §12).
    # If any live bot would match this inbound AND the org has the
    # ``chatbot_disable_inline_when_active_bot`` flag on (default TRUE),
    # skip the inline auto-reply / keyword-rules block below so the
    # bot's response isn't shadowed by a stale inline reply. The bus
    # publisher at the end of this function still fires — that's what
    # actually starts the bot run.
    bot_will_handle = False
    if conv.channel == ConversationChannel.whatsapp and not customer_opted_out:
        try:
            from src.app.core.chatbots.trigger_matcher import has_any_matching_bot
            from src.app.core.tenants import data_access as tenants_da

            org_row = await tenants_da.get_organization_by_id(session, conv.org_id)
            precedence_enabled = bool(
                getattr(org_row, "chatbot_disable_inline_when_active_bot", True)
            )
            if precedence_enabled:
                prior_inbound = await _da.count_inbound_messages_before(
                    session,
                    conversation_id=conv.id,
                    exclude_message_id=msg.id,
                )
                bot_will_handle = await has_any_matching_bot(
                    session,
                    org_id=conv.org_id,
                    channel="whatsapp",
                    text=parsed.text,
                    is_first_message=(prior_inbound == 0),
                )
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception(
                "chatbot.precedence_precheck_failed conv=%s", conv.id
            )
            bot_will_handle = False

    # whatsapp-platform-upgrade Step 16 — fire auto-reply pipeline.
    # Greeting + out-of-hours away dispatch after the inbound row is
    # persisted so cooldown queries see consistent state. Failures
    # are caught inside `dispatch_auto_replies`; this call never
    # raises into the webhook handler.
    if (
        conv.channel == ConversationChannel.whatsapp
        and not customer_opted_out
        and not bot_will_handle
    ):
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

        # tasks/ai-assistants-omnichannel Step 5 — route every
        # inbound through the channel-agnostic AI dispatch. It
        # enforces the ``ai_paused`` takeover flag, checks for
        # handover keywords, resolves the org's bound assistant,
        # and — when appropriate — delegates to the existing
        # WhatsApp AI reply pipeline. Legacy per-conversation
        # ``ai_handling=true`` orgs still get the old path for
        # backward-compat (dispatch handles the branching).
        # Failures are caught inside dispatch; this call never
        # raises into the webhook handler.
        #
        # Precedence guard: skip the org-level AI dispatch when a
        # chatbot will already handle this inbound. Two paths to
        # detect that:
        #
        #   1. ``bot_will_handle`` — a NEW trigger (keyword /
        #      first-message) matches. The trigger matcher will
        #      start a fresh bot run against this inbound.
        #   2. An EXISTING parked bot run on this conversation is
        #      waiting for the next inbound (``park_key=('reply', ...)``).
        #      The matcher will wake it via ``resume_run``, which
        #      re-enters the parked node's handler with the fresh
        #      ``last_inbound_text``. For an ``AI Assistant`` node,
        #      that resume calls ``reply_once`` and sends a reply —
        #      so firing AI dispatch here too would double-reply.
        #
        # Skip AI dispatch in either case. The bot takes precedence
        # because it's the more specific config (an operator
        # explicitly wired a flow for these messages).
        skip_ai_dispatch = bot_will_handle
        if not skip_ai_dispatch:
            from src.app.core.chatbots import data_access as _chatbot_dal

            parked_runs = await _chatbot_dal.list_parked_runs_for_conversation(
                session, conversation_id=conv.id
            )
            skip_ai_dispatch = bool(parked_runs)

        if not skip_ai_dispatch:
            await session.refresh(conv)
            from src.app.core.ai_assistants import dispatch as ai_dispatch

            await ai_dispatch.route_whatsapp_inbound(
                session,
                conversation=conv,
                inbound_text=parsed.text,
            )

    # tasks/chatbot-builder Step 4 — publish whatsapp.message_received.
    # Runs AFTER all existing inline processing (auto-reply / keyword
    # rules / assignment / AI) so behaviour is unchanged for orgs not
    # running bots. Any exception here is caught + logged so a broken
    # subscriber never rolls back the persisted inbound message.
    if conv.channel == ConversationChannel.whatsapp:
        await _publish_inbound_message_received(
            session,
            event_type=WHATSAPP_MESSAGE_RECEIVED,
            conversation=conv,
            message=msg,
            text=parsed.text,
        )
    return msg


async def _publish_inbound_message_received(
    session: AsyncSession,
    *,
    event_type: str,
    conversation: Conversation,
    message: Message,
    text: str | None,
) -> None:
    """Publish the chatbot trigger event with the cross-tenant guard
    from README §Case 18 + the ``is_first_message`` derivation from
    Decision §2.

    Fires audit ``security.cross_tenant_webhook_rejected`` and
    short-circuits when the linked contact belongs to a different
    org than the conversation — that state can only arise from
    upstream WABA misrouting or a compromised phone-number-id
    mapping, either way we refuse to publish an event carrying a
    payload from a mismatched tenant.
    """
    import logging

    logger = logging.getLogger(__name__)

    try:
        # --- Cross-tenant assertion (§Case 18) ------------------------
        if conversation.contact_id is not None:
            contact = await contacts_service.get_contact(session, conversation.contact_id)
            if contact is not None and contact.org_id != conversation.org_id:
                await audit.log(
                    action="security.cross_tenant_webhook_rejected",
                    entity_type="conversation",
                    entity_id=conversation.id,
                    after={
                        "conversation_org_id": str(conversation.org_id),
                        "contact_org_id": str(contact.org_id),
                        "channel": conversation.channel.value,
                    },
                    org_id=conversation.org_id,
                )
                logger.warning(
                    "chatbot.inbound.cross_tenant_rejected conv=%s conv_org=%s contact_org=%s",
                    conversation.id,
                    conversation.org_id,
                    contact.org_id,
                )
                return

        # --- is_first_message derivation (Decision §2) ----------------
        prior_inbound_count = await _da.count_inbound_messages_before(
            session,
            conversation_id=conversation.id,
            exclude_message_id=message.id,
        )
        is_first_message = prior_inbound_count == 0

        # --- Publish --------------------------------------------------
        # Payload holds only fields the matcher + node handlers need;
        # no full contact / conversation serialisation to keep PII
        # bleed off the event bus.
        await events_bus.publish(
            event_type,
            {
                "conversation_id": str(conversation.id),
                "contact_id": (str(conversation.contact_id) if conversation.contact_id else None),
                "message_id": str(message.id),
                "text": text,
                "channel": conversation.channel.value,
                "is_first_message": is_first_message,
                "direction": "in",
            },
            org_id=conversation.org_id,
            event_id=str(message.id),
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "chatbot.inbound.publish_failed event_type=%s conv=%s msg=%s",
            event_type,
            conversation.id,
            message.id,
        )


async def apply_channel_status_to_message(
    session: AsyncSession,
    *,
    channel_message_id: str,
    meta_status: str,
    timestamp: datetime,
) -> Message | None:
    """Reflect a Meta ``statuses[]`` event onto the ``Message`` row +
    publish the workflow event when appropriate.

    Complementary to :func:`campaigns.service.apply_meta_status` which
    only touches the ``CampaignMessage`` mirror. Campaign sends land
    in BOTH tables (Message via the send path, CampaignMessage via
    the dispatcher's bookkeeping); regular inbox sends land only in
    Message. Wiring both keeps the ``read_at`` column consistent
    across the two send paths.

    Only ``delivered`` and ``read`` status events cause a write —
    ``sent`` is already stamped at send time, ``failed`` doesn't
    affect a delivered/read timestamp. Forward-only: an already-read
    row is not downgraded by a late-arriving ``delivered``.

    Publishes ``whatsapp.message_read`` on the read transition so
    workflow triggers can react. Returns the (possibly updated)
    Message or ``None`` when the wamid isn't ours (manual reply from
    the inbox that predates this handler, or wamid from a different
    integration).
    """
    if not channel_message_id or meta_status not in {"delivered", "read"}:
        return None

    row = await _da.get_message_by_channel_id_org_scoped(
        session, channel_message_id=channel_message_id
    )
    if row is None:
        return None

    changed = False
    read_transition = False

    if meta_status == "delivered" and row.delivered_at is None:
        row.delivered_at = timestamp
        changed = True
    elif meta_status == "read":
        if row.delivered_at is None:
            # Meta occasionally skips the ``delivered`` event when the
            # recipient opens the message so quickly the two states
            # collapse. Fill both so downstream analytics don't show a
            # read-with-no-delivery gap.
            row.delivered_at = timestamp
            changed = True
        if row.read_at is None:
            row.read_at = timestamp
            changed = True
            read_transition = True

    if changed:
        await session.commit()
        await session.refresh(row)

    if read_transition:
        conversation = await _da.get_conversation_by_id(session, row.conversation_id)
        await _publish_message_read(
            session,
            conversation=conversation,
            message=row,
            timestamp=timestamp,
        )

    return row


async def _publish_message_read(
    session: AsyncSession,
    *,
    conversation: Conversation | None,
    message: Message,
    timestamp: datetime,
) -> None:
    """Fire ``whatsapp.message_read`` for a freshly-stamped read
    transition. Fire-and-forget; a bus / subscriber failure never
    rolls back the timestamp write above."""
    import logging

    logger = logging.getLogger(__name__)

    if conversation is None:
        return

    from src.app.core.events.event_catalog import WHATSAPP_MESSAGE_READ

    try:
        payload: dict[str, Any] = {
            "conversation_id": str(conversation.id),
            "contact_id": (str(conversation.contact_id) if conversation.contact_id else None),
            "message_id": str(message.id),
            "channel_message_id": message.channel_message_id,
            "channel": conversation.channel.value,
            "read_at": timestamp.isoformat(),
        }
        await events_bus.publish(
            WHATSAPP_MESSAGE_READ,
            payload,
            org_id=conversation.org_id,
            event_id=f"whatsapp_message_read:{message.id}",
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "whatsapp.message_read.publish_failed conv=%s msg=%s",
            conversation.id,
            message.id,
        )


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
        raise ValueError("Reactions are only supported on WhatsApp conversations.")

    target = await _da.get_message_by_id(session, message_id)
    if target is None or target.conversation_id != conv.id:
        raise ValueError("message_id does not belong to this conversation.")
    if not target.channel_message_id:
        raise ValueError("Cannot react to a message that has not been delivered yet.")

    adapter = await resolve_whatsapp_adapter(session)
    await adapter.send_reaction(
        external_id=conv.external_id,
        target_channel_message_id=target.channel_message_id,
        emoji=emoji,
    )

    now = datetime.now(UTC)
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
    rest.append({"actor": actor, "emoji": emoji, "ts": ts.isoformat()})
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


async def start_conversation(
    session: AsyncSession,
    *,
    channel: ConversationChannel,
    contact_id: uuid.UUID,
) -> Conversation:
    """Operator-initiated new thread — the *New conversation* button
    in the inbox lands here. Resolves the contact's phone (WA/SMS)
    or email (Email) as ``external_id`` and delegates to the same
    row-shape webhooks would create for an inbound.

    Idempotent by design: if a conversation on this channel already
    exists for the resolved identifier, we return it instead of
    inserting a duplicate — the operator ends up in the same thread
    whether they clicked *New* or *Continue*."""

    contact = await contacts_service.get_contact(session, contact_id)
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="contact not found",
        )

    if channel in _PHONE_CHANNELS:
        identifier = (contact.phone or "").strip()
        if not identifier:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "This contact has no phone number. Add one on the contact "
                    "before starting a WhatsApp or SMS conversation."
                ),
            )
    elif channel == ConversationChannel.email:
        identifier = (contact.email or "").strip()
        if not identifier:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "This contact has no email address. Add one on the contact "
                    "before starting an email conversation."
                ),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Manual new conversations aren't supported on the {channel.value} channel yet."
            ),
        )

    existing = await _da.find_conversation_for_channel_external(
        session, channel=channel, external_id=identifier
    )
    if existing is not None:
        # Backfill contact_id only if the existing row was unlinked —
        # never overwrite a link a webhook or a different operator set.
        if existing.contact_id is None:
            existing.contact_id = contact_id
            await session.commit()
            await session.refresh(existing)
        return existing

    conv = Conversation(
        org_id=contact.org_id,
        channel=channel,
        external_id=identifier,
        contact_id=contact_id,
        status=ConversationStatus.open,
        ai_handling=False,
    )
    _da.insert_conversation(session, conv)
    await session.commit()
    await session.refresh(conv)
    await audit.log(
        "conversations.started",
        entity_type="conversation",
        entity_id=conv.id,
        before=None,
        after=_snapshot(conv),
    )
    return conv


async def set_conversation_contact(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    payload: ConversationContactSet,
    caller_user_id: uuid.UUID,
    caller_role_id: uuid.UUID,
) -> Conversation:
    """Inbox details rail — link an existing contact to the conversation
    (``payload.contact_id``) or save the sender as a new contact
    (``payload.full_name``).

    Saving reuses a contact that already owns the conversation's phone /
    email instead of creating a duplicate; that contact is renamed only
    while it still carries an auto-generated placeholder name."""
    conv = await get_conversation(session, conversation_id)
    await ensure_can_write_conversation(
        session, conv=conv, caller_user_id=caller_user_id, caller_role_id=caller_role_id
    )
    before = _snapshot(conv)

    if payload.contact_id is not None:
        contact = await contacts_service.get_contact(session, payload.contact_id)
        if contact is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="contact not found")
    else:
        from src.app.core.contacts import data_access as contacts_da

        name = payload.full_name or ""
        identifier = conv.external_id.strip()
        if conv.channel in _PHONE_CHANNELS:
            phone = identifier if identifier.startswith("+") else "+" + identifier
            contact = await contacts_service.get_contact_by_phone(session, phone)
            fields: dict[str, str] = {"phone": phone}
        elif conv.channel == ConversationChannel.email:
            contact = await contacts_da.find_contact_by_email(
                session, org_id=conv.org_id, email=identifier
            )
            fields = {"email": identifier}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Saving contacts isn't supported on the {conv.channel.value} channel.",
            )
        if contact is None:
            contact = Contact(
                org_id=conv.org_id, full_name=name, source=conv.channel.value, **fields
            )
            contacts_service.insert_contact(session, contact)
            await session.flush()
        elif _is_placeholder_name(contact):
            contact.full_name = name

    conv.contact_id = contact.id
    await session.commit()
    await session.refresh(conv)
    await audit.log(
        "conversations.contact_linked",
        entity_type="conversation",
        entity_id=conv.id,
        before=before,
        after=_snapshot(conv),
    )
    return conv


async def patch_conversation(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    payload: ConversationPatch,
    caller_user_id: uuid.UUID,
    caller_role_id: uuid.UUID,
) -> Conversation:
    conv = await get_conversation(session, conversation_id)

    # Assignment change hits its own rule set (self-take-over allowed,
    # own-chat transfer allowed, everything else Owner/Admin). Other
    # fields (status, ai_handling) fall back to the generic write gate
    # — the assignee or an admin can flip them; a bystander can't.
    if payload.assigned_to_id is not None:
        await ensure_can_assign_conversation(
            session,
            conv=conv,
            caller_user_id=caller_user_id,
            caller_role_id=caller_role_id,
            new_assignee_id=payload.assigned_to_id,
        )
    if payload.status is not None or payload.ai_handling is not None:
        await ensure_can_write_conversation(
            session,
            conv=conv,
            caller_user_id=caller_user_id,
            caller_role_id=caller_role_id,
        )

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


async def mark_conversation_read(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
) -> Conversation:
    """Zero out ``unread_count`` on a conversation.

    Was a Phase-1 UX gap flagged in J.6 — inbound webhooks bumped the
    unread counter (see ``receive_webhook``) but there was no user-facing
    path to clear it, so the list badge accumulated forever. This is the
    write side of that read.

    Idempotent: if the count is already 0 we skip the commit + audit so
    the row keeps its previous ``updated_at`` and the audit trail isn't
    spammed with no-op ``conversations.marked_read`` entries when the
    thread is already open in another tab.
    """
    conv = await get_conversation(session, conversation_id)
    if (conv.unread_count or 0) == 0:
        return conv
    before = _snapshot(conv)
    conv.unread_count = 0
    await session.commit()
    await session.refresh(conv)
    await audit.log(
        "conversations.marked_read",
        entity_type="conversation",
        entity_id=conv.id,
        before=before,
        after=_snapshot(conv),
    )
    return conv


async def mark_conversation_unread(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
) -> Conversation:
    """Flip a conversation back to unread by setting ``unread_count = 1``
    if it's currently 0.

    Users need this to "come back to this later" after opening a thread
    they can't address right now. Setting the count to exactly 1 (rather
    than restoring the historical peak) matches how Gmail / Slack /
    Intercom behave — the badge signals "something to see" without
    lying about how many inbound messages are actually unseen; the next
    inbound bumps it normally.

    Idempotent: no-op (no audit spam) when the row is already unread.
    """
    conv = await get_conversation(session, conversation_id)
    if (conv.unread_count or 0) > 0:
        return conv
    before = _snapshot(conv)
    conv.unread_count = 1
    await session.commit()
    await session.refresh(conv)
    await audit.log(
        "conversations.marked_unread",
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
    sender_name: str | None = None,
) -> Conversation:
    existing = await _da.find_conversation_for_channel_external(
        session, channel=channel, external_id=external_id
    )
    if existing is not None:
        if channel in _PHONE_CHANNELS:
            if existing.contact_id is None:
                # Conversations created before contact auto-linking (or
                # whose contact was deleted) re-link on the next inbound
                # — to the contact that owns this number, else a new one.
                existing.contact_id = await _resolve_or_create_contact_by_phone(
                    session, org_id=existing.org_id, phone=external_id, name=sender_name
                )
            elif sender_name:
                await _maybe_name_placeholder_contact(
                    session, contact_id=existing.contact_id, name=sender_name
                )
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
            session, org_id=ctx.org_id, phone=external_id, name=sender_name
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
                ai_handling_default = bool(getattr(wa_config, "ai_handling_default_enabled", False))
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


# Name given to contacts auto-created from a WhatsApp number whose sender
# supplied no profile name.
UNKNOWN_WHATSAPP_CONTACT_NAME = "Unknown WhatsApp contact"


async def _resolve_or_create_contact_by_phone(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    phone: str,
    name: str | None = None,
) -> uuid.UUID | None:
    """Look up a contact by phone in this org. If none exists, create
    one named after the sender's WhatsApp profile name (``name``), or
    the ``"Unknown WhatsApp contact"`` placeholder when the channel
    didn't supply one. An existing placeholder-named contact is renamed
    to ``name``. Returns the resolved/created contact id, or None if
    the phone string is empty."""
    if not phone:
        return None
    # Contacts persist in E.164 (`+919876543210`) — inbound WhatsApp
    # sends `919876543210` (no `+`). Normalise once so both the lookup
    # and the placeholder insert land on the canonical form.
    normalised = phone if phone.startswith("+") else "+" + phone
    existing = await contacts_service.get_contact_by_phone(session, normalised)
    if existing is not None:
        if name and _is_placeholder_name(existing):
            existing.full_name = name
        return existing.id
    # The frontend list surfaces the phone as a secondary line, so a
    # nameless sender still reads as a contact rather than a raw number.
    # Operators rename it from the conversation's contact card.
    contact = Contact(
        org_id=org_id,
        full_name=name or UNKNOWN_WHATSAPP_CONTACT_NAME,
        phone=normalised,
        source="whatsapp",
    )
    contacts_service.insert_contact(session, contact)
    await session.flush()
    return contact.id


def _is_placeholder_name(contact: Contact) -> bool:
    """True when the contact still carries an auto-generated name —
    the current placeholder, the legacy ``full_name = phone`` seed, or
    blank — so a real WhatsApp profile name may replace it. Names an
    operator typed are never overwritten."""
    current = (contact.full_name or "").strip()
    return current in ("", UNKNOWN_WHATSAPP_CONTACT_NAME, contact.phone or "")


async def _maybe_name_placeholder_contact(
    session: AsyncSession, *, contact_id: uuid.UUID, name: str
) -> None:
    """Rename a linked contact that still has a placeholder name to the
    sender's WhatsApp profile name (dirty ORM change, flushed with the
    inbound message's commit)."""
    contact = await contacts_service.get_contact(session, contact_id)
    if contact is not None and _is_placeholder_name(contact):
        contact.full_name = name


async def resync_external_id_for_contact_phone(
    session: AsyncSession,
    *,
    contact_id: uuid.UUID,
    new_phone: str,
) -> int:
    """Cascade a contact-side phone edit onto every WhatsApp/SMS
    conversation linked to that contact.

    The conversation row snapshots the counterparty phone into
    ``external_id`` at inbound time (see ``_find_or_create_conversation``)
    and never updated it. Result: an operator adds a country code on the
    Contacts page → the inbox header keeps rendering the old raw phone
    AND the next inbound spawns a *second* conversation (Meta's E.164
    matches nothing on ``ix_conversations_channel_external_id``).
    This function is called from ``contacts.service.update_contact``
    when ``phone`` changes so both problems disappear at edit time.

    Duplicate-safe: if another live conversation already owns
    ``(channel, new_external_id)`` — the common case when the customer
    already messaged after the edit, spawning the second row — the
    stale row is left alone rather than renamed into a hard conflict.
    Merging the two threads is a separate operator-driven action.

    Returns the number of conversation rows actually renamed. Caller
    owns the transaction — this function only stages the UPDATE(s)."""
    if not new_phone:
        return 0
    normalised = new_phone if new_phone.startswith("+") else "+" + new_phone
    linked = await _da.list_phone_conversations_for_contact(session, contact_id=contact_id)
    renamed = 0
    for conv in linked:
        if conv.external_id == normalised:
            continue
        conflict = await _da.conversation_exists_for_channel_external(
            session,
            channel=conv.channel,
            external_id=normalised,
            exclude_id=conv.id,
        )
        if conflict:
            continue
        conv.external_id = normalised
        renamed += 1
    return renamed


def _snapshot(c: Conversation) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "channel": c.channel.value,
        "external_id": c.external_id,
        "contact_id": str(c.contact_id) if c.contact_id else None,
        "assigned_to_id": str(c.assigned_to_id) if c.assigned_to_id else None,
        "status": c.status.value,
        "ai_handling": c.ai_handling,
        "ai_paused": c.ai_paused,
    }


# --- AI pause / resume (omnichannel Step 3) -------------------------------


async def _display_name_for(
    session: AsyncSession,
    user_uuid: uuid.UUID | None,
) -> str | None:
    """Resolve one ``tbl_user_login.legacy_uuid`` to a display name.
    ``None`` when the row can't be found — the calling toast falls back
    to a generic label ("another user"). Reuses the bulk helper the
    thread-message enricher already exposes so we don't invent a new
    query."""
    if user_uuid is None:
        return None
    names = await _da.get_user_display_names_bulk(session, user_uuids=[user_uuid])
    return names.get(user_uuid)


def _insert_takeover_system_message(
    session: AsyncSession,
    *,
    conv: Conversation,
    holder_name: str | None,
    event: str,
    now: datetime,
) -> None:
    """Append a marker message so the thread transcript records the
    handoff. ``event`` is ``"ai_paused"`` or ``"ai_resumed"``; the
    payload carries the event key so the frontend can render a
    distinct system-message row (centred, muted, no bubble). No
    channel-adapter send happens — this is transcript-only."""
    who = holder_name or "A team member"
    if event == "ai_paused":
        body = f"— {who} took over from AI —"
    else:
        body = f"— {who} returned this conversation to AI —"
    msg = Message(
        org_id=conv.org_id,
        conversation_id=conv.id,
        direction=MessageDirection.out,
        sender_user_id=None,
        text=body,
        attachments=[],
        payload={"author": "system", "event": event},
        sent_at=now,
    )
    _da.insert_message(session, msg)
    conv.last_message_at = now


async def pause_ai(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> Conversation:
    """First-come-first-serve human takeover. Compare-and-set on
    ``ai_paused=false``; if the CAS misses, look up the current holder
    and raise 409 with their name so the loser's UI can render the
    ``"Alice just took this over."`` toast.

    Also inserts a system marker message ("— Alice took over from
    AI —") into the thread so the transcript records the handoff.
    """
    conv = await get_conversation(session, conversation_id)
    before = _snapshot(conv)
    now = datetime.now(UTC)
    won = await _da.pause_conversation_ai_cas(
        session,
        conversation_id=conv.id,
        actor_user_id=actor_user_id,
        now=now,
    )
    if not won:
        holder_uuid, paused_at = await _da.get_conversation_ai_pause_holder(
            session, conversation_id
        )
        holder_name = await _display_name_for(session, holder_uuid)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "reason": "already_taken_over",
                "holder_user_id": str(holder_uuid) if holder_uuid else None,
                "holder_name": holder_name,
                "paused_at": paused_at.isoformat() if paused_at else None,
            },
        )
    # Ownership handshake: taking over from AI on an *unassigned* chat
    # implicitly self-assigns the actor. Preserves the existing
    # assignment when the chat already had a human owner (Owner/Admin
    # jumping in on someone else's thread doesn't steal it — the
    # ``ensure_can_write_conversation`` router gate has already
    # authorised them; keeping the assignee stable avoids surprise
    # notification re-routing).
    if conv.assigned_to_id is None:
        conv.assigned_to_id = actor_user_id
    actor_name = await _display_name_for(session, actor_user_id)
    _insert_takeover_system_message(
        session,
        conv=conv,
        holder_name=actor_name,
        event="ai_paused",
        now=now,
    )
    await session.commit()
    await session.refresh(conv)
    await audit.log(
        "conversations.ai_paused",
        entity_type="conversation",
        entity_id=conv.id,
        before=before,
        after=_snapshot(conv),
    )
    return conv


async def apply_auto_pause(
    session: AsyncSession,
    *,
    conversation: Conversation,
    actor_user_id: uuid.UUID | None,
    reason: str,
) -> bool:
    """System-authored pause used by the omnichannel dispatch
    (``ai_assistants/dispatch.py``) and the human-outbound auto-pause
    path. ``actor_user_id`` is the human whose action triggered the
    pause (None for keyword-driven handover — the customer is not a
    user). ``reason`` is one of ``handover_keyword`` / ``human_reply``
    / a future extension; it's stored on the marker message's payload
    so analytics can attribute later.

    Returns True iff the CAS won (conversation was actually flipped).
    Silent no-op when the conversation is already paused; safer than
    raising because callers hit this on every inbound and won't want
    to distinguish first vs subsequent messages after a takeover."""
    now = datetime.now(UTC)
    # Use system uuid (all zeros) when no actor — the marker payload
    # captures the semantic reason so we don't need a nullable column.
    actor_for_cas = actor_user_id or uuid.UUID(int=0)
    won = await _da.pause_conversation_ai_cas(
        session,
        conversation_id=conversation.id,
        actor_user_id=actor_for_cas,
        now=now,
    )
    if not won:
        return False
    holder_name = await _display_name_for(session, actor_user_id) if actor_user_id else None
    if reason == "handover_keyword":
        body = "— Customer requested a human; AI is paused. —"
    elif reason == "human_reply":
        who = holder_name or "A team member"
        body = f"— {who} replied; AI is paused. —"
    else:
        body = "— AI is paused. —"
    msg = Message(
        org_id=conversation.org_id,
        conversation_id=conversation.id,
        direction=MessageDirection.out,
        sender_user_id=actor_user_id,
        text=body,
        attachments=[],
        payload={"author": "system", "event": "ai_paused", "reason": reason},
        sent_at=now,
    )
    _da.insert_message(session, msg)
    conversation.last_message_at = now
    return True


async def resume_ai(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    caller_is_admin: bool,
) -> Conversation:
    """Return control back to AI. Only the current holder OR an
    admin (``settings.conversations.manage`` permission — router-side
    check) can resume; non-holder / non-admin gets 403. Losing the
    CAS (row wasn't paused) surfaces as 409 ``not_paused``."""
    conv = await get_conversation(session, conversation_id)
    before = _snapshot(conv)
    if not conv.ai_paused:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "not_paused"},
        )
    if conv.ai_paused_by_user_id != actor_user_id and not caller_is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"reason": "not_holder"},
        )
    now = datetime.now(UTC)
    won = await _da.resume_conversation_ai_cas(session, conversation_id=conv.id)
    if not won:  # pragma: no cover — CAS race after the ai_paused read
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "not_paused"},
        )
    # Ownership handshake: handing the thread back to AI drops the
    # human assignee. Product model: "AI is handling" == no human
    # owner. Keeping the ex-holder assigned would misroute the next
    # inbound notification to someone who's already stepped away.
    # The bound assistant answers the next inbound; if a human needs
    # to jump back in, ``send_outbound`` / ``send_email_reply`` will
    # implicit-claim the thread again.
    conv.assigned_to_id = None
    actor_name = await _display_name_for(session, actor_user_id)
    _insert_takeover_system_message(
        session,
        conv=conv,
        holder_name=actor_name,
        event="ai_resumed",
        now=now,
    )
    await session.commit()
    await session.refresh(conv)
    await audit.log(
        "conversations.ai_resumed",
        entity_type="conversation",
        entity_id=conv.id,
        before=before,
        after=_snapshot(conv),
    )
    return conv


__all__ = [
    "apply_auto_pause",
    "ensure_can_write_conversation",
    "get_conversation",
    "list_conversations",
    "list_messages",
    "patch_conversation",
    "pause_ai",
    "react_to_message",
    "receive_webhook",
    "resume_ai",
    "send_outbound",
    "start_conversation",
]
