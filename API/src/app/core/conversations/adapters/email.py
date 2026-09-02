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
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.activities.models import ActivityType
from src.app.core.activities.service import log as activities_log
from src.app.core.contacts import data_access as contacts_da
from src.app.core.conversations.adapters import (
    ChannelMessageRef,
    InboundMessage,
)
from src.app.core.conversations.adapters.email_threading import (
    extract_message_id,
    extract_thread_keys,
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
from src.app.core.email.tracking import (
    footer as tracking_footer,
)
from src.app.core.email.tracking import (
    link_rewriter as tracking_links,
)
from src.app.core.email.tracking import (
    pixel as tracking_pixel,
)
from src.app.core.email.tracking import (
    tokens as tracking_tokens,
)
from src.app.core.email_senders.models import EmailSmtpSender
from src.app.core.events import bus as events_bus
from src.app.core.events.event_catalog import EMAIL_MESSAGE_RECEIVED, EMAIL_REPLIED
from src.app.core.notifications.service import notify
from src.app.core.settings.models import OrgSettings
from src.app.core.tenants import data_access as tenants_da

logger = logging.getLogger(__name__)


# Local-part of `Message-ID` for outbound mail. Stays stable across
# environments so a customer's reply (which echoes the value into
# `In-Reply-To`) always threads back. Override per-deploy if the
# product domain changes via `EMAIL_MESSAGE_ID_DOMAIN` env var.
_MESSAGE_ID_DOMAIN = os.getenv("EMAIL_MESSAGE_ID_DOMAIN", "furnicrm.app")

# Step 8 — public tracking base URL. Defaults to local in dev; in
# prod set via env. No trailing slash — pixel/link helpers append the
# full `/api/v1/track/...` path themselves.
_TRACKING_BASE_URL = os.getenv("TRACKING_BASE_URL", "http://localhost:8000").rstrip("/")

# `mailto:` target for the `List-Unsubscribe` header. The MIME
# headers carry both the URL and a mailto so RFC 8058 one-click
# unsubscribe works in Gmail / Outlook / Apple Mail.
_LIST_UNSUB_MAILTO = os.getenv("LIST_UNSUBSCRIBE_MAILTO", "unsubscribe@furnicrm.app")


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
                f"Daily email send cap reached for this account ({sent}/{cap}). Try again tomorrow."
            ),
        )


class OptedOut(HTTPException):
    """451 — recipient previously unsubscribed via the public tracking
    endpoint. Adapters never send to opted-out contacts; Step 7's
    sequence scheduler treats this as a permanent skip and cancels the
    enrollment.

    451 ("Unavailable For Legal Reasons") is the RFC-aligned choice
    for compliance-driven refusals — CAN-SPAM (US) and DPDP (IN)
    both make sending to an unsubscribed contact illegal.
    """

    def __init__(self, *, contact_id: uuid.UUID) -> None:
        super().__init__(
            status_code=451,
            detail=(
                f"Contact {contact_id} has opted out of marketing "
                "emails. Send blocked for compliance."
            ),
        )


class MissingCompanyAddress(HTTPException):
    """400 — CAN-SPAM requires a physical sender address on every
    commercial email. Adapter refuses the send when the org hasn't
    configured one in Settings → Store profile."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Your organisation has no physical address configured. "
                "Add one in Settings → Store profile before sending — "
                "CAN-SPAM and DPDP both require it on every marketing "
                "email."
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
    provider_message_id: str | None
    daily_sent_after: int
    near_soft_cap: bool


async def send_email(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    sender_user_id: uuid.UUID,
    account_id: uuid.UUID | None = None,
    smtp_sender_id: uuid.UUID | None = None,
    contact_id: uuid.UUID,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    in_reply_to_message_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    reply_to: str | None = None,
) -> SendEmailResult:
    """Send an email from the org's connected sender identity.

    Exactly one of ``account_id`` (OAuth mailbox — Gmail / Microsoft)
    or ``smtp_sender_id`` (verified SMTP sender, migration 0213) must
    be supplied. OAuth stays the primary path — reply flows, single-
    contact sends, and the sequence scheduler all pass ``account_id``.
    SMTP dispatch is used by the campaigns engine when the operator
    picks an SMTP sender identity for the campaign row.

    Both paths share the compliance + tracking machinery below
    (contact opt-out check, CAN-SPAM footer, open-pixel injection,
    click-tracking link rewrite, unsubscribe token). Only the actual
    provider dispatch (Gmail API / Microsoft Graph vs raw SMTP AUTH)
    diverges at the end.

    Threading only applies to the OAuth path (Gmail / Microsoft
    surface RFC-5322 ``Message-Id`` headers we can echo). SMTP sends
    still generate a Message-ID for the outbound row but don't
    consume ``in_reply_to_message_id`` — campaign broadcasts don't
    thread against a prior conversation anyway.

    ``conversation_id`` may be passed when the caller already knows
    which conversation this belongs to (the typical compose path
    from a contact-detail page). When None, we find-or-create one
    keyed on ``(contact_id, channel=email)``.
    """
    if (account_id is None) == (smtp_sender_id is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "send_email requires exactly one of account_id (OAuth) or smtp_sender_id (SMTP)."
            ),
        )

    # Resolve sender identity + normalise to a shared shape the
    # downstream MIME builder + persist step consume.
    account: EmailAccount | None = None
    smtp_sender: EmailSmtpSender | None = None
    sender_email: str
    sender_display: str | None
    sender_provider_label: str
    if account_id is not None:
        account = await email_service.get_account(session, account_id=account_id)
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Email account not found for this org.",
            )
        # Org-shared mailbox model: any rep in the org can send through
        # the account connected in Settings → Integrations. RLS on the
        # session already scopes ``get_account`` to the caller's org, so
        # cross-tenant sends are blocked at the DAL boundary. The persisted
        # Message row carries ``sender_user_id`` (who clicked Send) for
        # audit — the OAuth account row's ``user_id`` is just "which
        # human's OAuth grant we're using", NOT "who authored the message".
        if account.sync_state == EmailAccountSyncState.disconnected:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=("Email account is disconnected — reconnect in Settings → Email Accounts."),
            )
        sender_email = account.email_address
        sender_display = account.display_name
        sender_provider_label = account.provider.value
    else:
        from src.app.core.email_senders import data_access as smtp_da

        assert smtp_sender_id is not None  # noqa: S101 — narrowed above
        smtp_sender = await smtp_da.get_by_id(session, org_id=org_id, sender_id=smtp_sender_id)
        if smtp_sender is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="SMTP sender not found for this org.",
            )
        if smtp_sender.verified_at is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "SMTP sender is not verified — enter the 6-digit code from "
                    "Integrations → Email Sender first."
                ),
            )
        sender_email = smtp_sender.from_address
        sender_display = smtp_sender.display_name
        sender_provider_label = "smtp"

    contact = await contacts_da.get_contact(session, contact_id)
    if contact is None or not contact.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("Recipient contact missing or has no email address."),
        )
    # Step 8 — opt-out compliance gate. Any prior unsubscribe blocks
    # every future send to this contact. Sequence scheduler maps the
    # 451 to a permanent skip + cancels the enrollment.
    if getattr(contact, "email_opt_out", False):
        raise OptedOut(contact_id=contact.id)

    # Step 8 — CAN-SPAM physical-address gate. Load the org's settings
    # row so we can both (a) refuse the send when no address is set
    # and (b) compose the footer from the structured fields below.
    org_settings = (
        await session.execute(select(OrgSettings).where(OrgSettings.org_id == org_id))
    ).scalar_one_or_none()
    if not tracking_footer.has_required_address(org_settings):
        raise MissingCompanyAddress()
    org_row = await tenants_da.get_organization_by_id(session, org_id)

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
    parent_msg_id: str | None = None
    if in_reply_to_message_id is not None:
        parent = (
            await session.execute(select(Message).where(Message.id == in_reply_to_message_id))
        ).scalar_one_or_none()
        if parent is not None and parent.channel_message_id:
            parent_msg_id = parent.channel_message_id

    # Build the MIME message + a stable Message-ID we own so replies
    # echo it back into our threading detector.
    own_msg_id_raw = make_msgid(domain=_MESSAGE_ID_DOMAIN)
    own_msg_id_bare = own_msg_id_raw.strip("<>")

    # Step 8 — pre-allocate the messages.id so the tracking tokens
    # encode a stable per-send identifier. Without this we'd have a
    # chicken-and-egg between the token (needs id) and the row (needs
    # token-decorated HTML to commit). The Message constructor accepts
    # an explicit `id` so this is a clean swap.
    pre_message_id = uuid.uuid4()

    # Build the tracking tokens. Each kind carries the same message_id
    # but a different kind char so the public router can route /o vs
    # /c vs /unsubscribe with one decoder.
    open_token = tracking_tokens.encode(message_id=pre_message_id, kind="o")
    click_token = tracking_tokens.encode(message_id=pre_message_id, kind="c")
    unsub_token = tracking_tokens.encode(message_id=pre_message_id, kind="u")
    unsub_url = f"{_TRACKING_BASE_URL}/api/v1/track/unsubscribe/{unsub_token}"

    # Apply pixel + link rewriting + footer to the HTML body. The
    # plain-text alternative is left untouched — tracking only makes
    # sense in the HTML branch where the recipient's client can
    # fetch an `<img>` and follow a wrapped `<a href>`.
    tracked_body_html: str | None = body_html
    if body_html is not None:
        tracked_body_html = tracking_pixel.inject(
            body_html, token=open_token, base_url=_TRACKING_BASE_URL
        )
        tracked_body_html = tracking_links.rewrite(
            tracked_body_html,
            token=click_token,
            base_url=_TRACKING_BASE_URL,
        )
        footer_html = tracking_footer.build(
            org_name=getattr(org_row, "name", "") or "",
            org_settings=org_settings,
            unsubscribe_url=unsub_url,
        )
        tracked_body_html = tracking_footer.append(tracked_body_html, footer_html=footer_html)

    mime = _build_outbound_mime(
        from_email=sender_email,
        from_name=sender_display,
        to_email=contact.email,
        to_name=contact.full_name,
        subject=subject,
        body_text=body_text,
        body_html=tracked_body_html,
        message_id=own_msg_id_raw,
        in_reply_to=parent_msg_id,
        reply_to=reply_to,
        list_unsubscribe_url=unsub_url,
        list_unsubscribe_mailto=_LIST_UNSUB_MAILTO,
    )
    raw_bytes = mime.as_bytes()

    # Dispatch by sender kind. OAuth mailboxes go through their
    # provider-specific send helper (owns the daily-cap counter +
    # DailyCapExceeded → HardCapExceeded translation). SMTP senders
    # dispatch via OrgSmtpBackend — no per-account daily cap in v1
    # (the provider's own quota is the ceiling), so the caps default
    # to 0 / False for the returned SendEmailResult.
    provider_message_id: str | None = None
    daily_sent_after = 0
    near_soft_cap = False

    if account is not None:
        daily_sent_after = account.daily_sent_count or 0
        if account.provider == EmailAccountProvider.gmail:
            from src.app.core.email.gmail import send as gmail_send

            try:
                result = await gmail_send.send(account, session, raw_mime=raw_bytes)
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
                result = await ms_send.send(account, session, raw_mime=raw_bytes)
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
                    f"Email provider {account.provider.value} is not supported in this deploy."
                ),
            )
    else:
        # SMTP path (migration 0213). Dispatch the same `raw_bytes` MIME
        # we built above — the one carrying Message-ID, Date,
        # List-Unsubscribe, List-Unsubscribe-Post, Reply-To, and
        # threading headers. Rebuilding a minimal MIME inside the
        # backend (the prior implementation) dropped all of these,
        # which caused Gmail to junk bulk sends under its Feb-2024
        # bulk-sender rules. SMTP-level failures bubble out as
        # aiosmtplib exceptions which the campaign send-batch catches
        # + marks the recipient row failed.
        assert smtp_sender is not None  # noqa: S101 — narrowed above
        from src.app.shared.email.org_sender import OrgSmtpBackend as _OrgSmtpBackend

        await _OrgSmtpBackend(sender=smtp_sender).send_raw(
            raw_bytes=raw_bytes,
            envelope_from=sender_email,
            envelope_to=contact.email,
        )
        # SMTP doesn't hand us a provider-side message id — the RFC
        # Message-Id we minted (own_msg_id_bare) is the threading key.
        provider_message_id = None

    # Persist outbound row. `channel_message_id` is OUR Message-ID
    # (the RFC 5322 token) — the threading detector matches on it
    # when the recipient's reply lands. Provider-side ids go into
    # payload for forensics; threading does NOT depend on them.
    # `id` is pre-allocated above so the tracking tokens we already
    # baked into the HTML reference this exact row.
    now = datetime.now(UTC)
    msg = Message(
        id=pre_message_id,
        org_id=org_id,
        conversation_id=conversation.id,
        direction=MessageDirection.out,
        sender_user_id=sender_user_id,
        text=body_text,
        attachments=[],
        channel_message_id=own_msg_id_bare,
        payload={
            "subject": subject,
            "from": sender_email,
            "to": contact.email,
            "in_reply_to": parent_msg_id,
            "provider": sender_provider_label,
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
            "account_email": sender_email,
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
            "provider": sender_provider_label,
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


async def receive_email(account: EmailAccount, matched: dict[str, Any]) -> Message | None:
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
            "receive_email: no contact_id in matched; skipping account=%s provider_message_id=%s",
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
        if rfc_message_id and await _exists_by_rfc_id(session, rfc_message_id):
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
        #     that matches a known prior message — honours real email-
        #     client threading so the same reply chain always lands in
        #     the same conversation regardless of subject drift.
        #  2. Failing that, the most recent email conversation for this
        #     contact — matches the outbound flow so a customer with
        #     multiple different-subject inbounds still shows as ONE
        #     conversation in the inbox (CRM-inbox model, not Zendesk-
        #     ticket model). Subject-based splitting was removed on
        #     2026-08-26 after users repeatedly saw the same email
        #     address duplicated across rows.
        #  3. Create a fresh conversation.
        thread_keys = extract_thread_keys(headers)
        conversation = await _find_conversation_by_thread_keys(
            session, account.org_id, thread_keys, contact_id
        )
        if conversation is None:
            conversation = await _find_latest_email_conversation_for_contact(
                session, contact_id=contact_id
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
        now = datetime.now(UTC)
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

        # tasks/chatbot-builder Step 4 — publish email.message_received.
        # Fail-closed on SPF / DKIM explicit failures (audit +
        # short-circuit). IMAP-fetched mail carries the mailbox
        # provider's ``Authentication-Results`` header; we honour it
        # rather than doing our own DNS-heavy verification (that path
        # can land as a follow-up once the bot triggers on inbound
        # email surface real spoofing attempts).
        if not _email_auth_passed(headers):
            logger.info(
                "chatbot.email.spf_dkim_failed account=%s msg=%s",
                account.id,
                msg.id,
            )
            return msg

        await _publish_email_message_received(
            session,
            conversation=conversation,
            message=msg,
            text=body_text,
        )

        # If the inbound message references a prior message (via
        # In-Reply-To / References headers), it's a reply to something
        # we sent — fire the workflow-facing ``email.replied`` event
        # alongside the chatbot ``email.message_received`` fire above.
        # Distinct events because reply-to-CRM-outbound has different
        # workflow semantics than "any inbound landed" (the reply is
        # the trigger for sales-follow-up flows).
        if thread_keys:
            await _publish_email_replied(
                session,
                conversation=conversation,
                message=msg,
                text=body_text,
                subject=headers.get("subject", ""),
            )
        return msg


# --- Helpers ------------------------------------------------------------


def _email_auth_passed(headers: dict[str, str]) -> bool:
    """Fail-closed SPF / DKIM check for inbound email
    (``tasks/chatbot-builder`` Step 4).

    Honours the ``Authentication-Results`` header set by the receiving
    mailbox provider (Gmail, Microsoft, custom SMTP with an auth
    validator in front). Returns ``False`` only on an explicit
    ``spf=fail``, ``spf=softfail``, ``dkim=fail``, or ``dmarc=fail``
    verdict — a missing header (older provider, test fixture) is
    treated as pass so legitimate inbound isn't dropped over a
    metadata gap. Full DKIM signature verification (via ``dkimpy``)
    is a follow-up if abuse warrants it.
    """
    auth_results = headers.get("authentication-results") or headers.get("Authentication-Results")
    if not auth_results:
        return True
    lowered = auth_results.lower()
    for verdict in ("spf=fail", "spf=softfail", "dkim=fail", "dmarc=fail"):
        if verdict in lowered:
            return False
    return True


async def _publish_email_message_received(
    session: AsyncSession,
    *,
    conversation: Conversation,
    message: Message,
    text: str | None,
) -> None:
    """Fire the ``email.message_received`` chatbot trigger event
    (``tasks/chatbot-builder`` Step 4). Failures inside the bus are
    caught + logged so a broken subscriber never rolls back the
    persisted inbound message.

    Every inbound email conversation is authenticated by the per-
    account IMAP fetcher; ``conversation.org_id`` already matches
    ``account.org_id``. No cross-tenant contact assertion needed here
    — the email module has no phone-number-id-style WABA misrouting
    risk. The Case #18 assertion is WA-only.
    """
    from src.app.core.conversations import data_access as _conv_da

    try:
        prior_inbound = await _conv_da.count_inbound_messages_before(
            session,
            conversation_id=conversation.id,
            exclude_message_id=message.id,
        )
        is_first_message = prior_inbound == 0

        await events_bus.publish(
            EMAIL_MESSAGE_RECEIVED,
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
            "chatbot.email.publish_failed conv=%s msg=%s",
            conversation.id,
            message.id,
        )


async def _publish_email_replied(
    session: AsyncSession,
    *,
    conversation: Conversation,
    message: Message,
    text: str | None,
    subject: str,
) -> None:
    """Fire ``email.replied`` when an inbound email threads back to a
    prior outbound. Distinct from ``email.message_received`` (which
    fires on every inbound) — this event fires only when the sender
    replied to something the CRM sent, which is the trigger operators
    want for sales-follow-up + support-response workflows.

    Fire-and-forget: a bus/subscriber failure never rolls back the
    persisted inbound message.
    """
    try:
        payload: dict[str, Any] = {
            "conversation_id": str(conversation.id),
            "contact_id": (str(conversation.contact_id) if conversation.contact_id else None),
            "message_id": str(message.id),
            "subject": subject or "",
            "preview": (text or "")[:500],
            "channel": conversation.channel.value,
        }
        await events_bus.publish(
            EMAIL_REPLIED,
            payload,
            org_id=conversation.org_id,
            event_id=f"email_replied:{message.id}",
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "email.replied.publish_failed conv=%s msg=%s",
            conversation.id,
            message.id,
        )


def _build_outbound_mime(
    *,
    from_email: str,
    from_name: str | None,
    to_email: str,
    to_name: str | None,
    subject: str,
    body_text: str,
    body_html: str | None,
    message_id: str,
    in_reply_to: str | None,
    reply_to: str | None = None,
    list_unsubscribe_url: str | None = None,
    list_unsubscribe_mailto: str | None = None,
) -> EmailMessage:
    """Assemble a multipart/alternative MIME message via stdlib
    `email.message.EmailMessage`. Sets threading headers when
    `in_reply_to` is provided. The MIME bytes from `.as_bytes()`
    are what we hand to the provider's send.

    When `list_unsubscribe_url` is provided, the `List-Unsubscribe`
    and `List-Unsubscribe-Post` headers are set per RFC 8058 (Gmail /
    Outlook / Apple Mail show a one-click unsubscribe button in the
    UI). Both header forms are concatenated — Gmail prefers the URL,
    Outlook the mailto, so providing both maximises the surface.

    `Date` is always set. Gmail's / Microsoft's send APIs would inject
    one on our behalf, but raw SMTP relays don't always — and mail
    without a Date header is a strong spam signal for most receiving
    MTAs. Emitting it here keeps every transport path consistent.

    `Reply-To` is set only when the caller provides one (campaigns
    surface a Reply-to field on the Content step; single-thread compose
    doesn't). Absent Reply-To, replies go back to the From address.
    """
    msg = EmailMessage()
    msg["From"] = f'"{from_name}" <{from_email}>' if from_name else from_email
    msg["To"] = f'"{to_name}" <{to_email}>' if to_name else to_email
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg["Date"] = formatdate(localtime=True)
    if reply_to:
        msg["Reply-To"] = reply_to
    # Step 8 — RFC 8058 one-click unsubscribe. Mailto first so an
    # MUA without web-fetch support still has a working path.
    if list_unsubscribe_url:
        parts: list[str] = []
        if list_unsubscribe_mailto:
            parts.append(f"<mailto:{list_unsubscribe_mailto}>")
        parts.append(f"<{list_unsubscribe_url}>")
        msg["List-Unsubscribe"] = ", ".join(parts)
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    if in_reply_to:
        # Both headers carry the prior message id in angle brackets.
        # Servers expect `<id@host>` form even though our column
        # stores the bare value.
        bracketed = in_reply_to if in_reply_to.startswith("<") else f"<{in_reply_to}>"
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
    conversation_id: uuid.UUID | None,
) -> Conversation:
    """Outbound find-or-create. Explicit `conversation_id` wins; else
    we reuse the existing email conversation for this contact when
    one exists, else create a fresh one. Inbound uses the same
    per-contact fallback via ``_find_latest_email_conversation_for_contact``
    so both directions consistently merge into one row per contact."""
    if conversation_id is not None:
        existing = (
            await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    existing = await _find_latest_email_conversation_for_contact(session, contact_id=contact_id)
    if existing is not None:
        return existing

    return await _create_email_conversation(
        session,
        org_id=org_id,
        contact_id=contact_id,
        contact_email=contact_email,
    )


async def _find_latest_email_conversation_for_contact(
    session: AsyncSession,
    *,
    contact_id: uuid.UUID,
) -> Conversation | None:
    """Return the most recent email conversation this contact belongs
    to, regardless of status. Used by BOTH the inbound flow (after
    thread-key match fails) and the outbound flow (when the caller
    didn't pin a specific conversation_id) so email delivery for one
    contact always concentrates in a single row.

    Ordering: ``last_message_at DESC NULLS LAST`` mirrors the inbox
    list — the conversation the operator was most recently looking at
    is the same one new email lands on."""
    return (
        await session.execute(
            select(Conversation)
            .where(Conversation.channel == ConversationChannel.email)
            .where(Conversation.contact_id == contact_id)
            .order_by(Conversation.last_message_at.desc().nullslast())
            .limit(1)
        )
    ).scalar_one_or_none()


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
) -> Conversation | None:
    """Return the conversation that owns any prior message whose
    `channel_message_id` matches one of `thread_keys`. The
    `contact_id` filter is belt-and-braces: a forged thread key
    that collides with another customer's id would still be
    scoped to this contact's conversations."""
    if not thread_keys:
        return None
    rows = (
        await session.execute(
            select(Message.conversation_id).where(Message.channel_message_id.in_(list(thread_keys)))
        )
    ).all()
    if not rows:
        return None
    candidate_ids = {r[0] for r in rows}
    convs = (
        (
            await session.execute(
                select(Conversation)
                .where(Conversation.id.in_(list(candidate_ids)))
                .where(Conversation.contact_id == contact_id)
                .where(Conversation.channel == ConversationChannel.email)
                .order_by(Conversation.last_message_at.desc().nullslast())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    return convs


async def _exists_by_rfc_id(session: AsyncSession, rfc_id: str) -> bool:
    """Dedupe lookup — would this RFC Message-ID create a duplicate
    row inside this org? RLS scopes the search."""
    rows = (
        await session.execute(
            select(Message.id).where(Message.channel_message_id == rfc_id).limit(1)
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
            select(Message.id)
            .where(Message.payload["provider_message_id"].astext == provider_message_id)
            .limit(1)
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
    "MissingCompanyAddress",
    "OptedOut",
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
from src.app.core.conversations.registry import register_channel  # noqa: E402
from src.app.core.email.sync_daemon import register_inbound_handler  # noqa: E402


def _step5_register() -> None:
    register_channel(ConversationChannel.email, lambda: EmailAdapter())
    register_inbound_handler(receive_email)


_step5_register()
