"""Email channel adapter for the conversations engine.

Email is structurally different from WhatsApp / SMS: every message
carries a subject and threading headers, and outbound goes through
the rep's OWN connected mailbox (not a CRM-owned phone number).
So this adapter exposes both:

  - `EmailAdapter` implementing the channel-registry `ChannelAdapter`
    Protocol (so `register_channel(email, ...)` is a one-line wire);
    its `send()` raises `EmailUseSendEmailEndpoint` because email
    sends need more args than the protocol provides (subject + which
    mailbox to send from). Callers must use the typed `send_email`
    entry point instead — Step 9's frontend compose route does.

  - `send_email(...)` — the typed email-send entry point. Composes
    MIME via the stdlib `email.message.EmailMessage`, sets threading
    headers when replying, dispatches to `core.email.gmail.send` or
    `core.email.microsoft.send` based on the sender's connected
    account, persists a `direction=out` `Message` row, logs an
    `ActivityType.email` activity on the contact.

  - `receive_email(account, matched)` — Step 4's inbound-handler
    signature. Threads the inbound message (Message-ID > References >
    subject), upserts the conversation, persists a `direction=in`
    `Message` row, bumps unread count + last_message_at, notifies
    the assignee.

Both paths run inside the active tenant's context — Step 4's task
sets `RequestContext.org_id` from the account row BEFORE dispatching
to the handler, so the ORM tenant filter + RLS work transparently.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.activities.models import ActivityType
from src.app.core.activities.service import log as activities_log
from src.app.core.contacts.models import Contact
from src.app.core.conversations.adapters import (
    ChannelMessageRef,
    InboundMessage,
)
from src.app.core.conversations.adapters.email_threading import (
    extract_message_id,
    extract_thread_keys,
    subject_thread_key,
)
from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
    ConversationStatus,
    Message,
    MessageDirection,
)
from src.app.core.email import service as email_service
from src.app.core.email.models import (
    EmailAccount,
    EmailAccountProvider,
    EmailAccountSyncState,
)
from src.app.core.notifications.service import notify


logger = logging.getLogger(__name__)


# Subject-based threading look-back window. A re-reply more than 30
# days after the last activity is treated as a new conversation —
# avoids decade-old "Quote for sofa" threads sucking in new emails.
_SUBJECT_THREADING_WINDOW = timedelta(days=30)

# Local-part of `Message-ID` for outbound mail. Stays stable across
# environments so a customer's reply (which echoes the value into
# `In-Reply-To`) always threads back. Override per-deploy if the
# product domain changes via `EMAIL_MESSAGE_ID_DOMAIN` env var.
import os

_MESSAGE_ID_DOMAIN = os.getenv("EMAIL_MESSAGE_ID_DOMAIN", "furnicrm.app")


class EmailUseSendEmailEndpoint(HTTPException):
    """Raised when a caller routes through the generic ChannelAdapter
    `.send()` path for the email channel. The email channel needs
    subject + sender-account args that the protocol doesn't carry —
    callers must use the typed `send_email()` instead. Step 9's
    compose endpoint will."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Email channel send requires subject + sender "
                "account. Use the dedicated email-compose endpoint, "
                "not the generic conversations send."
            ),
        )


class HardCapExceeded(HTTPException):
    """429 — per-account daily hard cap reached. Surfaces to the
    compose UI and Step 7's sequence scheduler so they can defer."""

    def __init__(self, *, sent: int, cap: int) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Daily email send cap reached for this account "
                f"({sent}/{cap}). Try again tomorrow."
            ),
        )


# --- ChannelAdapter Protocol implementation ----------------------------


class EmailAdapter:
    """Implements `ChannelAdapter` for the channel registry.

    Stateless; resolved per-call by `core.conversations.registry`
    when the conversation has `channel=email`. The actual email send
    happens via `send_email(...)` — this adapter's `send` is a guard
    that points the caller at the right entry point.
    """

    async def send(
        self,
        *,
        org_id: uuid.UUID,
        external_id: str,
        text: str,
        attachments: list[dict[str, Any]],
    ) -> ChannelMessageRef:
        """Guard rail — email needs subject + sender. Direct callers
        of `conversations.send_outbound(channel=email, ...)` get a
        clear 400 instead of a corrupted send."""
        raise EmailUseSendEmailEndpoint()

    def parse_webhook(self, payload: dict[str, Any]) -> InboundMessage:
        """Email doesn't use channel webhooks — Step 4's sync daemon
        + push handlers (Gmail Pub/Sub, MS Graph subscriptions) are
        the inbound path. The conversations webhook endpoint would
        never route here, but keeping the method satisfies the
        Protocol so the registry can resolve us."""
        raise EmailUseSendEmailEndpoint()


# --- Outbound: send_email() --------------------------------------------


@dataclass(slots=True)
class SendEmailResult:
    """Outcome of a successful outbound email send."""

    message: Message
    conversation: Conversation
    provider_message_id: Optional[str]
    daily_sent_after: int
    near_soft_cap: bool


async def send_email(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    sender_user_id: uuid.UUID,
    account_id: uuid.UUID,
    contact_id: uuid.UUID,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    in_reply_to_message_id: Optional[uuid.UUID] = None,
    conversation_id: Optional[uuid.UUID] = None,
) -> SendEmailResult:
    """Send an email from the rep's connected mailbox.

    Resolves the sender's `EmailAccount` (must be `sync_state='live'`),
    looks up the recipient contact, finds-or-creates the conversation,
    composes a MIME message with proper threading headers, dispatches
    to Gmail or Microsoft, persists the outbound `Message` row, and
    logs an activity on the contact.

    `in_reply_to_message_id` carries the CRM `messages.id` of the
    message being replied to — we read its `channel_message_id`
    (RFC Message-ID) to build the `In-Reply-To` + `References`
    headers. Pass `None` for a fresh thread.

    `conversation_id` may be passed when the caller already knows
    which conversation this belongs to (the typical compose path
    from a contact-detail page). When None, we find-or-create one
    keyed on `(contact_id, channel=email)`.
    """
    account = await email_service.get_account(
        session, account_id=account_id
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email account not found for this org.",
        )
    if account.user_id != sender_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You can only send through your own connected "
                "email account."
            ),
        )
    if account.sync_state == EmailAccountSyncState.disconnected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Email account is disconnected — reconnect in "
                "Settings → Email Accounts."
            ),
        )

    contact = (
        await session.execute(
            select(Contact).where(Contact.id == contact_id)
        )
    ).scalar_one_or_none()
    if contact is None or not contact.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Recipient contact missing or has no email address."
            ),
        )

    # Resolve conversation: explicit id wins; else find-or-create by
    # (contact, email channel). Multiple email threads with the same
    # contact stay in one conversation in v1 — the threading inside
    # a thread is handled by `In-Reply-To`/`References`; the
    # conversation row groups every email exchange with this contact.
    conversation = await _find_or_create_conversation(
        session,
        org_id=org_id,
        contact_id=contact_id,
        contact_email=contact.email,
        conversation_id=conversation_id,
    )

    # Read the prior outbound message's channel_message_id when
    # replying so we can stamp In-Reply-To + References.
    parent_msg_id: Optional[str] = None
    if in_reply_to_message_id is not None:
        parent = (
            await session.execute(
                select(Message).where(
                    Message.id == in_reply_to_message_id
                )
            )
        ).scalar_one_or_none()
        if parent is not None and parent.channel_message_id:
            parent_msg_id = parent.channel_message_id

    # Build the MIME message + a stable Message-ID we own so replies
    # echo it back into our threading detector.
    own_msg_id_raw = make_msgid(domain=_MESSAGE_ID_DOMAIN)
    own_msg_id_bare = own_msg_id_raw.strip("<>")
    mime = _build_outbound_mime(
        from_email=account.email_address,
        from_name=account.display_name,
        to_email=contact.email,
        to_name=contact.full_name,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        message_id=own_msg_id_raw,
        in_reply_to=parent_msg_id,
    )
    raw_bytes = mime.as_bytes()

    # Dispatch by provider. Each adapter applies its own daily-cap
    # check + counter increment (with rollback on failure). We catch
    # the typed `DailyCapExceeded` and re-raise as our public type
    # so callers don't have to know which provider raised.
    provider_message_id: Optional[str] = None
    daily_sent_after = account.daily_sent_count or 0
    near_soft_cap = False

    if account.provider == EmailAccountProvider.gmail:
        from src.app.core.email.gmail import send as gmail_send

        try:
            result = await gmail_send.send(
                account, session, raw_mime=raw_bytes
            )
        except gmail_send.DailyCapExceeded as exc:
            raise HardCapExceeded(
                sent=account.daily_sent_count or 0,
                cap=gmail_send.DEFAULT_HARD_CAP,
            ) from exc
        provider_message_id = result.gmail_message_id
        daily_sent_after = result.daily_sent_after
        near_soft_cap = result.near_soft_cap

    elif account.provider == EmailAccountProvider.microsoft:
        from src.app.core.email.microsoft import send as ms_send

        try:
            result = await ms_send.send(
                account, session, raw_mime=raw_bytes
            )
        except ms_send.DailyCapExceeded as exc:
            raise HardCapExceeded(
                sent=account.daily_sent_count or 0,
                cap=ms_send.DEFAULT_HARD_CAP,
            ) from exc
        provider_message_id = result.provider_message_id  # None for MS
        daily_sent_after = result.daily_sent_after
        near_soft_cap = result.near_soft_cap
    else:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                f"Email provider {account.provider.value} is not "
                "supported in this deploy."
            ),
        )

    # Persist outbound row. `channel_message_id` is OUR Message-ID
    # (the RFC 5322 token) — the threading detector matches on it
    # when the recipient's reply lands. Provider-side ids go into
    # payload for forensics; threading does NOT depend on them.
    now = datetime.now(timezone.utc)
    msg = Message(
        org_id=org_id,
        conversation_id=conversation.id,
        direction=MessageDirection.out,
        sender_user_id=sender_user_id,
        text=body_text,
        attachments=[],
        channel_message_id=own_msg_id_bare,
        payload={
            "subject": subject,
            "from": account.email_address,
            "to": contact.email,
            "in_reply_to": parent_msg_id,
            "provider": account.provider.value,
            "provider_message_id": provider_message_id,
            "body_html_present": body_html is not None,
        },
        sent_at=now,
        delivered_at=now,
    )
    session.add(msg)
    conversation.last_message_at = now
    await session.commit()
    await session.refresh(msg)
    await session.refresh(conversation)

    # Best-effort: contact-timeline activity + audit row.
    await activities_log(
        entity_type="contact",
        entity_id=contact.id,
        type=ActivityType.email,
        payload={
            "direction": "outbound",
            "subject": subject,
            "preview": body_text[:160],
            "conversation_id": str(conversation.id),
            "message_id": str(msg.id),
            "account_email": account.email_address,
        },
        user_id=sender_user_id,
        org_id=org_id,
    )
    await audit.log(
        "email.message_sent",
        entity_type="conversation",
        entity_id=conversation.id,
        after={
            "channel": "email",
            "to": contact.email,
            "subject": subject,
            "message_id": str(msg.id),
            "provider": account.provider.value,
            "provider_message_id": provider_message_id,
        },
    )
    return SendEmailResult(
        message=msg,
        conversation=conversation,
        provider_message_id=provider_message_id,
        daily_sent_after=daily_sent_after,
        near_soft_cap=near_soft_cap,
    )


# --- Inbound: receive_email() ------------------------------------------


async def receive_email(
    account: EmailAccount, matched: dict[str, Any]
) -> Optional[Message]:
    """Step 4's inbound-handler signature. Called from
    `email_tasks._dispatch_inbound` for every `MatchedMessage` the
    sync routines pulled.

    Opens its own session (Step 4 holds one but releases it before
    calling here — we MUST not nest sessions across the await chain).
    Tenant context is set BEFORE calling here by Step 4's task body,
    so the ORM tenant filter + RLS are active inside our session.

    Returns the persisted `Message` on success; `None` when the
    matched message would be a duplicate (already persisted with
    the same provider message id) or when contact resolution drops
    it (matched dict missing contact_id).
    """
    contact_id = matched.get("contact_id")
    if contact_id is None:
        logger.debug(
            "receive_email: no contact_id in matched; skipping "
            "account=%s provider_message_id=%s",
            account.id,
            matched.get("message_id"),
        )
        return None

    from src.app.shared.db import async_session

    async with async_session() as session:
        # Dedupe: provider_message_id is unique per inbox + we've
        # already persisted this one if there's a row with matching
        # channel_message_id headers.message-id from the provider.
        headers: dict[str, str] = matched.get("headers") or {}
        rfc_message_id = extract_message_id(headers)
        provider_message_id = matched.get("message_id")
        if rfc_message_id and await _exists_by_rfc_id(
            session, rfc_message_id
        ):
            logger.debug(
                "receive_email: dedupe hit account=%s rfc_id=%s",
                account.id,
                rfc_message_id,
            )
            return None
        if provider_message_id and await _exists_by_provider_id(
            session, provider_message_id, account.provider
        ):
            return None

        # Find existing conversation by:
        #  1. Any thread key (Message-ID / References / In-Reply-To)
        #     that matches a known prior message.
        #  2. Failing that, subject + contact within 30 days.
        thread_keys = extract_thread_keys(headers)
        conversation = await _find_conversation_by_thread_keys(
            session, account.org_id, thread_keys, contact_id
        )
        if conversation is None:
            subject = headers.get("subject", "")
            conversation = await _find_conversation_by_subject(
                session,
                org_id=account.org_id,
                contact_id=contact_id,
                subject=subject,
            )
        if conversation is None:
            conversation = await _create_email_conversation(
                session,
                org_id=account.org_id,
                contact_id=contact_id,
                contact_email=_extract_address(headers.get("from", "")),
            )

        # Persist the inbound message. `channel_message_id` is the
        # RFC Message-ID so future replies thread back through us.
        body_text = (matched.get("body_text") or "").strip()
        now = datetime.now(timezone.utc)
        msg = Message(
            org_id=account.org_id,
            conversation_id=conversation.id,
            direction=MessageDirection.in_,
            text=body_text or headers.get("subject", "")[:1024],
            attachments=[],
            channel_message_id=rfc_message_id or provider_message_id,
            payload={
                "subject": headers.get("subject", ""),
                "from": headers.get("from", ""),
                "to": headers.get("to", ""),
                "provider": account.provider.value,
                "provider_message_id": provider_message_id,
                "conversation_id_provider": matched.get("conversation_id"),
                "rfc_message_id": rfc_message_id,
                "thread_keys": sorted(thread_keys),
            },
            sent_at=now,
        )
        session.add(msg)
        conversation.last_message_at = now
        conversation.unread_count = (conversation.unread_count or 0) + 1
        await session.commit()
        await session.refresh(msg)
        await session.refresh(conversation)

        # Best-effort: contact activity + assignee notification.
        await activities_log(
            entity_type="contact",
            entity_id=contact_id,
            type=ActivityType.email,
            payload={
                "direction": "inbound",
                "subject": headers.get("subject", ""),
                "preview": (body_text or "")[:160],
                "conversation_id": str(conversation.id),
                "message_id": str(msg.id),
                "account_email": account.email_address,
            },
            org_id=account.org_id,
            user_id=account.user_id,
        )
        if conversation.assigned_to_id is not None:
            await notify(
                org_id=account.org_id,
                user_id=conversation.assigned_to_id,
                type="conversation.message",
                title=f"New email from {headers.get('from', 'a contact')}",
                body=(headers.get("subject", "") or "")[:160] or None,
                payload={
                    "conversation_id": str(conversation.id),
                    "channel": "email",
                },
            )
        return msg


# --- Helpers ------------------------------------------------------------


def _build_outbound_mime(
    *,
    from_email: str,
    from_name: Optional[str],
    to_email: str,
    to_name: Optional[str],
    subject: str,
    body_text: str,
    body_html: Optional[str],
    message_id: str,
    in_reply_to: Optional[str],
) -> EmailMessage:
    """Assemble a multipart/alternative MIME message via stdlib
    `email.message.EmailMessage`. Sets threading headers when
    `in_reply_to` is provided. The MIME bytes from `.as_bytes()`
    are what we hand to the provider's send."""
    msg = EmailMessage()
    msg["From"] = (
        f'"{from_name}" <{from_email}>' if from_name else from_email
    )
    msg["To"] = (
        f'"{to_name}" <{to_email}>' if to_name else to_email
    )
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    if in_reply_to:
        # Both headers carry the prior message id in angle brackets.
        # Servers expect `<id@host>` form even though our column
        # stores the bare value.
        bracketed = (
            in_reply_to
            if in_reply_to.startswith("<")
            else f"<{in_reply_to}>"
        )
        msg["In-Reply-To"] = bracketed
        # `References` should be a space-separated chain; for v1 we
        # don't walk further back than the immediate parent. Step 8
        # (tracking) will keep the chain growing properly.
        msg["References"] = bracketed
    if body_html:
        # Plain text first (most permissive), then HTML alternative.
        msg.set_content(body_text)
        msg.add_alternative(body_html, subtype="html")
    else:
        msg.set_content(body_text)
    return msg


async def _find_or_create_conversation(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    contact_id: uuid.UUID,
    contact_email: str,
    conversation_id: Optional[uuid.UUID],
) -> Conversation:
    """Outbound find-or-create. Explicit `conversation_id` wins; else
    we reuse the existing email conversation for this contact when
    one exists, else create a fresh one."""
    if conversation_id is not None:
        existing = (
            await session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    existing = (
        await session.execute(
            select(Conversation)
            .where(Conversation.channel == ConversationChannel.email)
            .where(Conversation.contact_id == contact_id)
            .order_by(Conversation.last_message_at.desc().nullslast())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    return await _create_email_conversation(
        session,
        org_id=org_id,
        contact_id=contact_id,
        contact_email=contact_email,
    )


async def _create_email_conversation(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    contact_id: uuid.UUID,
    contact_email: str,
) -> Conversation:
    conv = Conversation(
        org_id=org_id,
        channel=ConversationChannel.email,
        external_id=(contact_email or "").lower()[:255],
        contact_id=contact_id,
        status=ConversationStatus.open,
    )
    session.add(conv)
    await session.flush()
    return conv


async def _find_conversation_by_thread_keys(
    session: AsyncSession,
    org_id: uuid.UUID,
    thread_keys: set[str],
    contact_id: uuid.UUID,
) -> Optional[Conversation]:
    """Return the conversation that owns any prior message whose
    `channel_message_id` matches one of `thread_keys`. The
    `contact_id` filter is belt-and-braces: a forged thread key
    that collides with another customer's id would still be
    scoped to this contact's conversations."""
    if not thread_keys:
        return None
    rows = (
        await session.execute(
            select(Message.conversation_id)
            .where(Message.channel_message_id.in_(list(thread_keys)))
        )
    ).all()
    if not rows:
        return None
    candidate_ids = {r[0] for r in rows}
    convs = (
        await session.execute(
            select(Conversation)
            .where(Conversation.id.in_(list(candidate_ids)))
            .where(Conversation.contact_id == contact_id)
            .where(Conversation.channel == ConversationChannel.email)
            .order_by(Conversation.last_message_at.desc().nullslast())
            .limit(1)
        )
    ).scalars().first()
    return convs


async def _find_conversation_by_subject(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    contact_id: uuid.UUID,
    subject: str,
) -> Optional[Conversation]:
    """Subject-based fallback. Looks for an OPEN email conversation
    for the same contact within the last 30 days whose most recent
    message's `payload.subject` normalises to the same key."""
    key = subject_thread_key(subject)
    if not key:
        return None
    cutoff = datetime.now(timezone.utc) - _SUBJECT_THREADING_WINDOW
    candidates = (
        await session.execute(
            select(Conversation)
            .where(Conversation.channel == ConversationChannel.email)
            .where(Conversation.contact_id == contact_id)
            .where(Conversation.status == ConversationStatus.open)
            .where(
                and_(
                    Conversation.last_message_at.isnot(None),
                    Conversation.last_message_at >= cutoff,
                )
            )
            .order_by(Conversation.last_message_at.desc())
            .limit(10)
        )
    ).scalars().all()

    for conv in candidates:
        # Fetch the most recent message in this conversation; check
        # if its subject normalises to the same key. A small N (one
        # per conv from the candidate list) keeps this cheap.
        latest = (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest is None:
            continue
        latest_subject = (latest.payload or {}).get("subject", "")
        if subject_thread_key(latest_subject) == key:
            return conv
    return None


async def _exists_by_rfc_id(
    session: AsyncSession, rfc_id: str
) -> bool:
    """Dedupe lookup — would this RFC Message-ID create a duplicate
    row inside this org? RLS scopes the search."""
    rows = (
        await session.execute(
            select(Message.id)
            .where(Message.channel_message_id == rfc_id)
            .limit(1)
        )
    ).first()
    return rows is not None


async def _exists_by_provider_id(
    session: AsyncSession,
    provider_message_id: str,
    provider: EmailAccountProvider,
) -> bool:
    """Secondary dedupe — for inbound messages where the RFC
    Message-ID is malformed/missing, fall back to checking the
    provider's own id stamped into `payload.provider_message_id`."""
    if not provider_message_id:
        return False
    # JSONB indexed lookup; this is rare-path so a sequential scan
    # is acceptable. The RFC-id check above catches the common case.
    rows = (
        await session.execute(
            select(Message.id).where(
                Message.payload["provider_message_id"].astext
                == provider_message_id
            ).limit(1)
        )
    ).first()
    return rows is not None


def _extract_address(header_value: str) -> str:
    """`"Asha" <asha@x.com>` → `asha@x.com`. Empty input → empty."""
    if not header_value:
        return ""
    _name, addr = parseaddr(header_value)
    return (addr or "").lower()


__all__ = [
    "EmailAdapter",
    "EmailUseSendEmailEndpoint",
    "HardCapExceeded",
    "SendEmailResult",
    "receive_email",
    "send_email",
]


# --- Module-import side effects: register with the two registries ----
#
# 1. Channel registry — so `conversations.resolve(email)` returns our
#    adapter. The send guard above 400s any caller using the generic
#    `send_outbound` path; this just makes the registry lookup succeed
#    instead of raising `ChannelNotRegistered`.
#
# 2. Step 4 inbound-handler registry — `receive_email` becomes the
#    target of every `MatchedMessage` the Gmail / Microsoft sync
#    primitives produce. Without this registration the Step 4 daemon
#    drops matched messages with a debug log.
#
# Idempotent: re-importing this module just overwrites the
# registrations with the same callables.
from src.app.core.conversations.registry import register_channel
from src.app.core.email.sync_daemon import register_inbound_handler


def _step5_register() -> None:
    register_channel(ConversationChannel.email, lambda: EmailAdapter())
    register_inbound_handler(receive_email)


_step5_register()
