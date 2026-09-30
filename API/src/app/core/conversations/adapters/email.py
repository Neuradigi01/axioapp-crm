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
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import API_BASE_URL
from src.app.core import audit
from src.app.core.activities.models import ActivityType
from src.app.core.activities.service import log as activities_log
from src.app.core.channel_endpoints import data_access as endpoints_da
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
from src.app.core.conversations.utils import OutboundAttachment, wake_on_inbound
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
from src.app.shared.storage import get_storage
from src.app.shared.storage.config import storage_backend_name

logger = logging.getLogger(__name__)


# Local-part of `Message-ID` for outbound mail. Stays stable across
# environments so a customer's reply (which echoes the value into
# `In-Reply-To`) always threads back. Set via `EMAIL_MESSAGE_ID_DOMAIN`
# in the shared config.env — do NOT split across local/prod files.
_MESSAGE_ID_DOMAIN = os.getenv("EMAIL_MESSAGE_ID_DOMAIN", "crm.aixoapp.com")

# Step 8 — public tracking base URL for open-pixel + click-rewrite
# links. Uses the env-selected API host (`config.API_BASE_URL`, set
# per env in config.local.env / config.prod.env) so tracked links
# always point at the same origin serving `/api/v1/track/...`.
_TRACKING_BASE_URL = API_BASE_URL.rstrip("/")

# `mailto:` target for the `List-Unsubscribe` header. The MIME
# headers carry both the URL and a mailto so RFC 8058 one-click
# unsubscribe works in Gmail / Outlook / Apple Mail. Stable across
# envs — same reasoning as `_MESSAGE_ID_DOMAIN` above.
_LIST_UNSUB_MAILTO = os.getenv("LIST_UNSUBSCRIBE_MAILTO", "unsubscribe@crm.aixoapp.com")


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


def _mailgun_reply_to_for(smtp_sender: EmailSmtpSender | None) -> str | None:
    """Compute the ``in_<token>@<INBOUND_EMAIL_DOMAIN>`` Reply-To
    address for an SMTP sender, or ``None`` when this send must not be
    rewritten.

    Returns None when:
      * caller isn't sending via SMTP (``smtp_sender is None``) —
        OAuth mailboxes get replies via their own inbound sync, so
        rewriting Reply-To would silently divert replies away from
        the sync and break threading;
      * the sender has ``capture_replies_in_crm=False`` — per-sender
        opt-out (HubSpot-parity — a small-biz owner running SMTP
        against their own Gmail app-password may want replies at
        their own inbox);
      * the sender has no ``inbound_token`` (shouldn't happen post
        migration 0215 but is defensive);
      * ``INBOUND_EMAIL_DOMAIN`` isn't set in the deploy — the platform
        hasn't opted into Mailgun-inbound at all.
    """
    if smtp_sender is None:
        return None
    if not smtp_sender.capture_replies_in_crm:
        return None
    if not smtp_sender.inbound_token:
        return None
    inbound_domain = os.getenv("INBOUND_EMAIL_DOMAIN", "").strip()
    if not inbound_domain:
        return None
    return f"in_{smtp_sender.inbound_token}@{inbound_domain}"


async def send_email(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    sender_user_id: uuid.UUID | None = None,
    ai_assistant_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    smtp_sender_id: uuid.UUID | None = None,
    contact_id: uuid.UUID,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    in_reply_to_message_id: uuid.UUID | None = None,
    in_reply_to_raw: str | None = None,
    references_chain_raw: str | None = None,
    conversation_id: uuid.UUID | None = None,
    reply_to: str | None = None,
    attachments: Sequence[OutboundAttachment] = (),
) -> SendEmailResult:
    """Send an email from the org's connected sender identity.

    Exactly one of ``account_id`` (OAuth mailbox — Gmail / Microsoft)
    or ``smtp_sender_id`` (verified SMTP sender, migration 0213) must
    be supplied. OAuth stays the primary path — reply flows, single-
    contact sends, and the sequence scheduler all pass ``account_id``.
    SMTP dispatch is used by the campaigns engine when the operator
    picks an SMTP sender identity for the campaign row.

    Exactly one of ``sender_user_id`` (human-authored) or
    ``ai_assistant_id`` (AI-authored auto-reply) must be supplied. AI
    sends persist with ``sender_user_id=NULL`` on the Message row and
    stamp ``payload.author='ai' + payload.assistant_id=<uuid>`` so
    the frontend + reporting queries can distinguish AI replies from
    human sends without a schema change.

    Both paths share the compliance + tracking machinery below
    (contact opt-out check, CAN-SPAM footer, open-pixel injection,
    click-tracking link rewrite, unsubscribe token). Only the actual
    provider dispatch (Gmail API / Microsoft Graph vs raw SMTP AUTH)
    diverges at the end.

    Threading has two entry points. Human compose flows pass
    ``in_reply_to_message_id`` (a stored Message uuid); the parent's
    ``channel_message_id`` becomes the ``In-Reply-To`` header. AI
    auto-reply flows pass ``in_reply_to_raw`` + ``references_chain_raw``
    directly from the inbound envelope's RFC-5322 headers so we don't
    need to re-query the just-persisted inbound row. Callers pass at
    most one; when neither is set the send goes out unthreaded.

    ``conversation_id`` may be passed when the caller already knows
    which conversation this belongs to (the typical compose path
    from a contact-detail page). When None, we find-or-create one
    keyed on ``(contact_id, channel=email)``.

    ``attachments`` ride in the MIME for every transport. After a
    successful dispatch each file is stored under
    ``{org_id}/messages/{message_id}/{filename}`` and listed on the
    Message row, so the inbox renders + downloads it exactly like an
    inbound email attachment.
    """
    if account_id is not None and smtp_sender_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "send_email accepts at most one of account_id (OAuth) or "
                "smtp_sender_id (SMTP); pass neither to let the org's "
                "send cascade pick the envelope."
            ),
        )
    if (sender_user_id is None) == (ai_assistant_id is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "send_email requires exactly one of sender_user_id (human) or ai_assistant_id (AI)."
            ),
        )

    # --- Envelope resolution -------------------------------------------
    #
    # tasks/email-sending-domains Step 5 — when neither ``account_id``
    # nor ``smtp_sender_id`` is supplied, consult the send cascade to
    # decide the envelope: caller → org default → verified own-domain →
    # platform-from → error. When the cascade picks an SMTP sender or
    # OAuth account, we forward that id into the existing per-kind
    # loader block below (so the ``verified_at`` / ``sync_state``
    # branches stay authoritative). ``own_domain`` / ``platform_from``
    # dispatch via Mailgun's messages.mime endpoint further down.
    envelope_kind: str  # "oauth_account" | "smtp_sender" | "own_domain" | "platform_from"
    dispatch_domain: str | None = None
    envelope_from_address: str | None = None
    envelope_reply_to: str | None = None
    endpoint_created_this_call = False
    # tasks/email-reputation-warmup Step 5 — resolved own-domain UUID
    # kept so the send-gate can key its ceiling/reputation lookup on
    # the specific verified domain row (not just the string dispatch
    # domain).
    resolved_domain_id: uuid.UUID | None = None

    if account_id is None and smtp_sender_id is None:
        # Late import — resolver lives in a peer module, and importing
        # at module top would pull the send cascade into every adapter
        # import path (audit log, activities, campaigns).
        from src.app.core.email_sender_setup.service import (
            SendNotConfiguredError,
            resolve_send_envelope,
        )

        try:
            envelope = await resolve_send_envelope(session, org_id=org_id)
        except SendNotConfiguredError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "No sending path is configured for this org. Connect a "
                    "mailbox, verify an SMTP sender, or claim a sending "
                    "domain before sending email."
                ),
            ) from exc

        envelope_kind = envelope.envelope_type
        if envelope_kind == "smtp_sender":
            smtp_sender_id = envelope.smtp_sender_id
        elif envelope_kind == "oauth_account":
            account_id = envelope.oauth_account_id
        elif envelope_kind == "own_domain":
            dispatch_domain = envelope.dispatch_domain
            envelope_from_address = envelope.from_address
            envelope_reply_to = envelope.reply_to
            resolved_domain_id = envelope.own_domain_id
        elif envelope_kind == "platform_from":
            # Mint / reuse a platform reply-capture endpoint so the
            # ``r-<token>@<inbound>`` Reply-To lands somewhere real.
            # ``endpoint_created_this_call`` gates the first-use in-app
            # nudge fired after the send row lands.
            from src.app.core.conversations.adapters.email_platform_from import (
                build_platform_envelope,
                resolve_or_create_platform_reply_token,
            )

            reply_token, endpoint_created_this_call = await resolve_or_create_platform_reply_token(
                session, org_id=org_id
            )
            platform_env = build_platform_envelope(
                org_id=org_id,
                reply_token=reply_token,
                platform_domain=envelope.dispatch_domain,
            )
            dispatch_domain = platform_env.dispatch_domain
            envelope_from_address = platform_env.from_address
            envelope_reply_to = platform_env.reply_to

    # Resolve sender identity + normalise to a shared shape the
    # downstream MIME builder + persist step consume.
    account: EmailAccount | None = None
    smtp_sender: EmailSmtpSender | None = None
    sender_email: str
    sender_display: str | None
    sender_provider_label: str
    if account_id is not None:
        envelope_kind = "oauth_account"
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
    elif smtp_sender_id is not None:
        envelope_kind = "smtp_sender"
        from src.app.core.email_senders import data_access as smtp_da

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
    else:
        # own_domain or platform_from — Mailgun-managed envelope. No
        # per-row identity in the CRM; the from-address IS the identity.
        # ``envelope_from_address`` was populated in the cascade branch
        # above, so this is a safe unpacking.
        assert envelope_from_address is not None  # noqa: S101
        assert envelope_kind in ("own_domain", "platform_from")  # noqa: S101
        sender_email = envelope_from_address
        sender_display = None
        sender_provider_label = f"mailgun_{envelope_kind}"

    # tasks/email-reputation-warmup Step 5 — send-gate chain. No-op
    # for oauth_account / smtp_sender (reputation tracks only
    # mailgun-mediated envelopes). Raises ``SendGateSkipped`` (or
    # subclass) which we map to a 429 with the skip code so
    # campaign/sequence callers can log + move on. Ordered
    # cheapest-fail-first: reputation → ceiling → wallet → rate.
    from src.app.core.email.reputation.exceptions import SendGateSkipped
    from src.app.core.email.reputation.gates import run_send_gate

    try:
        await run_send_gate(
            session,
            org_id=org_id,
            envelope_type=envelope_kind,
            domain_id=resolved_domain_id,
        )
    except SendGateSkipped as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"skip_code": exc.code.value, "reason": str(exc)},
        ) from exc

    # mailgun-inbound track: rewrite `Reply-To` on SMTP-only outbound.
    original_reply_to = reply_to
    inbound_rewrite = _mailgun_reply_to_for(smtp_sender)
    if inbound_rewrite is not None:
        reply_to = inbound_rewrite
    # own_domain / platform_from Reply-To — apply the envelope's value
    # when the caller didn't override. Never overrides an explicit
    # caller reply_to (some flows want a specific reply target that
    # the envelope's default shouldn't clobber).
    if envelope_reply_to is not None and reply_to is None:
        reply_to = envelope_reply_to

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
    # replying so we can stamp In-Reply-To + References. AI reply
    # flows short-circuit the DB lookup by passing the inbound's raw
    # RFC-5322 Message-ID directly via ``in_reply_to_raw``.
    parent_msg_id: str | None = None
    if in_reply_to_raw is not None:
        parent_msg_id = in_reply_to_raw
    elif in_reply_to_message_id is not None:
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
        references_chain=references_chain_raw,
        reply_to=reply_to,
        list_unsubscribe_url=unsub_url,
        list_unsubscribe_mailto=_LIST_UNSUB_MAILTO,
        attachments=attachments,
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

    if envelope_kind == "oauth_account":
        assert account is not None  # noqa: S101 — narrowed above
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
    elif envelope_kind == "smtp_sender":
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
    else:
        # own_domain or platform_from — Mailgun ``messages.mime``
        # upload. Cascade already picked ``dispatch_domain`` so the
        # POST routes to the right per-domain Mailgun endpoint. Raw
        # MIME is uploaded verbatim so every header we built (Message-
        # ID, threading, List-Unsubscribe, Reply-To, tracking headers)
        # survives Mailgun's send path.
        assert dispatch_domain is not None  # noqa: S101 — set in cascade
        from src.app.core.email.mailgun.api_client import MailgunApiClient
        from src.app.core.email.mailgun.api_client_errors import MailgunApiError

        # tasks/email-reputation-warmup Step 6 — attribution stamps.
        # The events webhook (Step 3) reads these back to route
        # delivered / bounced / complained events to the right
        # ``tbl_organization_email_reputation`` row. ``org`` and
        # ``envelope`` are the minimum needed to key the (org, envelope,
        # domain) tuple; ``domain_id`` disambiguates own_domain rows.
        # Charset locked at ``[A-Za-z0-9_-]`` — UUIDs are hex + dashes,
        # and both envelope enum values are alphanumeric+underscore.
        custom_variables: dict[str, str] = {
            "org": str(org_id),
            "envelope": envelope_kind,
            "domain_id": str(resolved_domain_id) if resolved_domain_id else "none",
        }
        try:
            send_result = await MailgunApiClient().send_mime(
                dispatch_domain,
                to=contact.email,
                raw_mime=raw_bytes,
                custom_variables=custom_variables,
            )
        except MailgunApiError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=("Upstream email provider is unavailable. Try again shortly."),
            ) from exc
        provider_message_id = send_result.mailgun_message_id

    # The email is out — keep a copy of each attachment so the inbox can
    # show + download it. A storage failure must not turn a delivered
    # email into an error; the file is simply left off the row.
    stored_attachments: list[dict[str, Any]] = []
    if attachments:
        storage = get_storage()
        for att in attachments:
            try:
                await storage.put(
                    f"{org_id}/messages/{pre_message_id}/{att.filename}",
                    att.data,
                    content_type=att.content_type,
                )
            except Exception:
                logger.exception(
                    "outbound email attachment store failed message=%s file=%s",
                    pre_message_id,
                    att.filename,
                )
                continue
            stored_attachments.append(
                {
                    "filename": att.filename,
                    "size": len(att.data),
                    "content_type": att.content_type,
                    "storage_key": att.filename,
                    "storage_backend": storage_backend_name(),
                }
            )

    # Persist outbound row. `channel_message_id` is OUR Message-ID
    # (the RFC 5322 token) — the threading detector matches on it
    # when the recipient's reply lands. Provider-side ids go into
    # payload for forensics; threading does NOT depend on them.
    # `id` is pre-allocated above so the tracking tokens we already
    # baked into the HTML reference this exact row.
    now = datetime.now(UTC)
    outbound_payload: dict[str, Any] = {
        "subject": subject,
        "from": sender_email,
        "to": contact.email,
        "in_reply_to": parent_msg_id,
        "provider": sender_provider_label,
        "provider_message_id": provider_message_id,
        "body_html_present": body_html is not None,
    }
    if ai_assistant_id is not None:
        outbound_payload["author"] = "ai"
        outbound_payload["assistant_id"] = str(ai_assistant_id)
    # Preserve any caller-supplied Reply-To that our SMTP-capture
    # rewrite overrode. Auditors + support engineers can see what the
    # send *would* have carried without the rewrite.
    if original_reply_to is not None and original_reply_to != reply_to:
        outbound_payload["original_reply_to"] = original_reply_to
    if reply_to is not None:
        outbound_payload["reply_to"] = reply_to

    msg = Message(
        id=pre_message_id,
        org_id=org_id,
        conversation_id=conversation.id,
        direction=MessageDirection.out,
        sender_user_id=sender_user_id,
        text=body_text,
        attachments=stored_attachments,
        channel_message_id=own_msg_id_bare,
        payload=outbound_payload,
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

    # First-use platform-from nudge — fires exactly once per org, when
    # this send minted the platform_reply_capture endpoint (i.e. the
    # first platform-from send for this org). Best-effort: any lookup
    # or notify failure is logged + swallowed so a broken owner-lookup
    # never rolls back the persisted message.
    if endpoint_created_this_call and envelope_kind == "platform_from":
        try:
            await _notify_first_platform_from_send(session, org_id=org_id)
        except Exception:
            logger.exception("email.platform_from.first_use_notify_failed org=%s", org_id)
    return SendEmailResult(
        message=msg,
        conversation=conversation,
        provider_message_id=provider_message_id,
        daily_sent_after=daily_sent_after,
        near_soft_cap=near_soft_cap,
    )


# --- Inbound: receive_email() ------------------------------------------


async def _persist_inbound_email(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    contact_id: uuid.UUID | None,
    headers: dict[str, str],
    body_text: str,
    body_html: str | None,
    attachments: list[dict[str, Any]],
    channel_message_id: str,
    thread_keys: set[str],
    provider_message_id: str | None,
    provider_message_id_fallback_provider: EmailAccountProvider | None,
    spf_result: str | None,
    dkim_result: str | None,
    auto_generated: bool,
    source_provider: str,
    source_reference: dict[str, Any],
    publish_workflow_events: bool,
    activity_user_id: uuid.UUID | None,
    account_email_label: str | None,
    endpoint_id: uuid.UUID | None = None,
    endpoint_type: str | None = None,
) -> Message | None:
    """Shared inbound-persistence helper for OAuth AND Mailgun paths.

    Both ``receive_email`` (Gmail / Microsoft sync) and Mailgun's
    ingest Celery task funnel through this helper so threading,
    dedup, conversation resolution, unread bump, activity log,
    assignee notify, and workflow-event publishing behave identically
    across providers.

    ``org_id`` is passed EXPLICITLY (Attacker C3 finding from the
    PLANNING_RULES review) — every threading DAL call it makes is
    scoped by ``org_id``, never trusting session-scoped tenant
    context alone.

    Returns the persisted ``Message`` on success; ``None`` when the
    message is a dedup hit (already persisted).

    Sender-auth policy is the CALLER's decision — it passes
    ``publish_workflow_events`` after evaluating SPF/DKIM (Mailgun)
    or ``Authentication-Results`` (OAuth). The helper trusts that
    signal + never publishes when ``auto_generated=True``.
    """
    # Dedupe against the partial unique index added in Step 0
    # (uq_messages_org_channel_msgid). This is the belt half of
    # belt-and-braces — the DB rejects the INSERT if we somehow
    # skipped the check, but doing it here means we don't hit the
    # constraint on every retry.
    if channel_message_id and await _exists_by_rfc_id(session, channel_message_id, org_id=org_id):
        logger.debug(
            "_persist_inbound_email: dedupe hit provider=%s channel_message_id=%s",
            source_provider,
            channel_message_id,
        )
        return None
    # OAuth secondary dedup (some providers ship a stable per-mailbox
    # id in ``provider_message_id`` distinct from the RFC Message-ID).
    if (
        provider_message_id
        and provider_message_id_fallback_provider is not None
        and await _exists_by_provider_id(
            session,
            provider_message_id,
            provider_message_id_fallback_provider,
            org_id=org_id,
        )
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
    #     conversation in the inbox.
    #  3. Create a fresh conversation.
    #
    # If ``contact_id`` is None (Mailgun path: unknown sender or
    # spoof-suspected drop), the thread-key + contact-latest paths
    # both no-op and we create a bare conversation whose
    # ``contact_id`` remains NULL for operator review.
    conversation: Conversation | None = None
    if contact_id is not None:
        conversation = await _find_conversation_by_thread_keys(
            session, org_id, thread_keys, contact_id
        )
        if conversation is None:
            conversation = await _find_latest_email_conversation_for_contact(
                session, contact_id=contact_id, org_id=org_id
            )
    if conversation is None:
        conversation = await _create_email_conversation(
            session,
            org_id=org_id,
            contact_id=contact_id,
            contact_email=_extract_address(headers.get("from", "")),
        )

    # Persist the inbound message.
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "subject": headers.get("subject", ""),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "provider": source_provider,
        "thread_keys": sorted(thread_keys),
        # Provider-specific bookkeeping (Gmail/Microsoft: rfc_message_id,
        # conversation_id_provider; Mailgun: smtp_sender_id,
        # mailgun_delivery_id).
        **source_reference,
    }
    if provider_message_id is not None:
        payload["provider_message_id"] = provider_message_id
    if auto_generated:
        payload["auto_generated"] = True
    # Track 1 Step 4: stamp resolved channel endpoint when the caller
    # supplied one (OAuth sync when the account has a backing endpoint
    # row; Mailgun path uses ``source_reference["endpoint_id"]`` at the
    # caller instead — same shape, single source of truth).
    if endpoint_id is not None:
        payload["endpoint_id"] = str(endpoint_id)
    # tasks/email-inbound-forwarding Step 4 — stamp endpoint_type so
    # downstream analytics + inbox-triage filters can bucket by
    # "reply-capture" vs "forwarded-address" vs "oauth-mailbox"
    # without re-parsing the source_reference dict.
    if endpoint_type is not None:
        payload["endpoint_type"] = endpoint_type

    msg = Message(
        org_id=org_id,
        conversation_id=conversation.id,
        direction=MessageDirection.in_,
        text=body_text or headers.get("subject", "")[:1024],
        attachments=list(attachments or []),
        channel_message_id=channel_message_id,
        payload=payload,
        spf_result=spf_result,
        dkim_result=dkim_result,
        sent_at=now,
    )
    session.add(msg)
    conversation.last_message_at = now
    conversation.unread_count = (conversation.unread_count or 0) + 1
    wake_on_inbound(conversation)
    await session.commit()
    await session.refresh(msg)
    await session.refresh(conversation)

    # Best-effort: contact activity + assignee notification. Skip
    # activity log when we have no contact (Mailgun: unknown sender)
    # — contact activity requires an entity_id.
    if contact_id is not None:
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
                "account_email": account_email_label,
            },
            org_id=org_id,
            user_id=activity_user_id,
        )
    if conversation.assigned_to_id is not None:
        await notify(
            org_id=org_id,
            user_id=conversation.assigned_to_id,
            type="conversation.message",
            title=f"New email from {headers.get('from', 'a contact')}",
            body=(headers.get("subject", "") or "")[:160] or None,
            payload={
                "conversation_id": str(conversation.id),
                "channel": "email",
            },
        )

    if not publish_workflow_events:
        # Caller has already decided (spoof / auto-responder / OAuth
        # SPF-DKIM fail) that no workflow events should fire.
        return msg

    # Bot-vs-AI arbitration — mirrors the WhatsApp path in
    # ``conversations/service.py::receive_webhook`` (Decision §12):
    # a matching bot always takes precedence over the org's AI
    # assistant. If a bot WILL fire (new trigger match) or an
    # existing parked bot run is waiting on this conversation, do
    # not invoke AI dispatch inline — the bot pipeline owns the
    # reply. Fail-soft on pre-check errors (``bot_will_handle =
    # False``): AI is the fallback, so a broken pre-check should
    # never silence AI.
    from src.app.core.conversations import data_access as _conv_da

    bot_will_handle = False
    is_first_message = True
    try:
        prior_inbound = await _conv_da.count_inbound_messages_before(
            session,
            conversation_id=conversation.id,
            exclude_message_id=msg.id,
        )
        is_first_message = prior_inbound == 0

        from src.app.core.chatbots.trigger_matcher import has_any_matching_bot

        bot_will_handle = await has_any_matching_bot(
            session,
            org_id=org_id,
            channel="email",
            text=body_text,
            is_first_message=is_first_message,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "chatbot.precedence_precheck_failed conv=%s",
            conversation.id,
        )
        bot_will_handle = False

    await _publish_email_message_received(
        session,
        conversation=conversation,
        message=msg,
        text=body_text,
    )

    # If the inbound message references a prior message, it's a reply
    # to something we sent — fire the workflow-facing ``email.replied``
    # event alongside the chatbot ``email.message_received`` fire above.
    if thread_keys:
        await _publish_email_replied(
            session,
            conversation=conversation,
            message=msg,
            text=body_text,
            subject=headers.get("subject", ""),
        )

    # AI dispatch — only when the bot pipeline is not going to own
    # this inbound. Same two skip signals the WhatsApp path uses:
    # (1) a new trigger matches, (2) an existing parked bot run is
    # waiting for the next inbound (Ask-Question, Assign-AI-Assistant,
    # etc.). Route through the channel-agnostic entry point so the
    # guardrail (``AI_EMAIL_INBOUND_ENABLED`` flag, role-account /
    # bounce filter, ``ai_paused`` takeover) fires uniformly.
    skip_ai_dispatch = bot_will_handle
    if not skip_ai_dispatch:
        try:
            from src.app.core.chatbots import data_access as _chatbot_dal

            parked_runs = await _chatbot_dal.list_parked_runs_for_conversation(
                session, conversation_id=conversation.id
            )
            skip_ai_dispatch = bool(parked_runs)
        except Exception:  # noqa: BLE001
            logger.exception(
                "chatbot.parked_run_check_failed conv=%s",
                conversation.id,
            )
            skip_ai_dispatch = False

    if not skip_ai_dispatch:
        try:
            from src.app.core.ai_assistants import dispatch as ai_dispatch
            from src.app.core.ai_assistants.email_guardrails import InboundEmail

            _, sender_addr = parseaddr(headers.get("from") or "")
            inbound_envelope = InboundEmail(
                sender_email=sender_addr or "",
                subject=headers.get("subject"),
                body_text=body_text or "",
                headers=headers,
            )
            await ai_dispatch.route_email_inbound(
                session,
                conversation=conversation,
                inbound_email=inbound_envelope,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "ai_dispatch.email_route_failed conv=%s",
                conversation.id,
            )

    return msg


# Track 1 Step 4: OAuth-account → channel-endpoint resolution.
#
# Each ``receive_email`` call opens a fresh session (dispatcher releases
# the caller session before invoking us — see docstring below), so
# per-session caching won't help. Instead a module-level dict caches
# ``account.id → endpoint.id`` with a short TTL so a sync burst pulling
# 100 messages doesn't do 100 endpoint lookups.
#
# The nightly orphan-endpoint sweeper (Step 5) is authoritative on
# endpoint lifecycle; a 5-minute stale cache is acceptable — worst case
# a message gets stamped with a since-deactivated endpoint id for one
# TTL window. Cleared on process restart.
_OAUTH_ENDPOINT_CACHE: dict[uuid.UUID, tuple[uuid.UUID | None, float]] = {}
_OAUTH_ENDPOINT_CACHE_TTL_S = 300


def _endpoints_refactor_enabled() -> bool:
    """Mirror of the mailgun flag — one env var controls both paths.

    Setting ``EMAIL_ENDPOINTS_REFACTOR_ENABLED=false`` reverts BOTH
    OAuth and Mailgun ingest paths to legacy shapes. Rip out the flag
    once Tracks 2/4/5 all consume the endpoints DAL.
    """
    return os.getenv("EMAIL_ENDPOINTS_REFACTOR_ENABLED", "true").strip().lower() != "false"


async def _resolve_oauth_endpoint_id(
    session: AsyncSession, account: EmailAccount
) -> uuid.UUID | None:
    """Look up the channel-endpoint UUID backing this OAuth account.

    Returns ``None`` when no endpoint row exists (edge case: account
    created before the Step 1 backfill AND the Step 5 sweeper hasn't
    reconciled yet — persist proceeds without the stamp, logged at
    warning level for operator visibility).
    """
    now_ts = time.time()
    hit = _OAUTH_ENDPOINT_CACHE.get(account.id)
    if hit is not None:
        endpoint_id, cached_at = hit
        if now_ts - cached_at < _OAUTH_ENDPOINT_CACHE_TTL_S:
            return endpoint_id

    rows = await endpoints_da.find_active_for_org(
        session,
        org_id=account.org_id,
        endpoint_type="oauth_mailbox",
    )
    resolved: uuid.UUID | None = None
    for endpoint, details in rows:
        if details is not None and details.oauth_account_id == account.id:
            resolved = endpoint.id
            break

    if resolved is None:
        logger.warning(
            "oauth_endpoint_lookup: no active endpoint for account=%s org=%s "
            "(will retry on next sync tick; nightly sweeper reconciles)",
            account.id,
            account.org_id,
        )

    _OAUTH_ENDPOINT_CACHE[account.id] = (resolved, now_ts)
    return resolved


def _clear_oauth_endpoint_cache() -> None:
    """Test hook. Not called in production."""
    _OAUTH_ENDPOINT_CACHE.clear()


async def receive_email(account: EmailAccount, matched: dict[str, Any]) -> Message | None:
    """Step 4's inbound-handler signature. Called from
    `email_tasks._dispatch_inbound` for every `MatchedMessage` the
    sync routines pulled.

    Thin wrapper over ``_persist_inbound_email`` that maps the OAuth
    matched-message dict into the shared helper's kwargs. Preserves
    byte-identical output for OAuth callers (Gmail / Microsoft sync
    behaviour is unchanged after this refactor).

    Opens its own session — Step 4's dispatcher releases the caller
    session before invoking us so we don't nest sessions across the
    await chain.
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
        headers: dict[str, str] = matched.get("headers") or {}
        rfc_message_id = extract_message_id(headers)
        provider_message_id = matched.get("message_id")
        # OAuth stores the RFC Message-ID (or provider id when RFC is
        # missing) as ``channel_message_id`` — same as prior behaviour.
        channel_message_id = rfc_message_id or provider_message_id
        if not channel_message_id:
            # No addressable id at all — silently drop; the sync will
            # try again on the next tick if the provider re-lists it.
            return None
        thread_keys = extract_thread_keys(headers)
        body_text = (matched.get("body_text") or "").strip()
        # Track 1 Step 4: resolve backing channel-endpoint under the
        # feature flag. ``None`` when the flag is off OR the account has
        # no endpoint row yet (Step 5 sweeper reconciles those).
        endpoint_id: uuid.UUID | None = None
        if _endpoints_refactor_enabled():
            endpoint_id = await _resolve_oauth_endpoint_id(session, account)
        return await _persist_inbound_email(
            session,
            org_id=account.org_id,
            contact_id=contact_id,
            headers=headers,
            body_text=body_text,
            body_html=None,
            attachments=[],
            channel_message_id=channel_message_id,
            thread_keys=thread_keys,
            provider_message_id=provider_message_id,
            provider_message_id_fallback_provider=account.provider,
            # OAuth sync doesn't extract structured SPF/DKIM columns
            # today; ``_email_auth_passed(headers)`` below applies the
            # legacy Authentication-Results check for workflow gating.
            spf_result=None,
            dkim_result=None,
            auto_generated=False,
            source_provider=account.provider.value,
            source_reference={
                "conversation_id_provider": matched.get("conversation_id"),
                "rfc_message_id": rfc_message_id,
            },
            # Preserve legacy OAuth policy: publish workflow events iff
            # the Authentication-Results header didn't say fail. The
            # Mailgun path passes False when its own SPF/DKIM parsers
            # detect spoof; the two policies converge on the same
            # helper.
            publish_workflow_events=_email_auth_passed(headers),
            activity_user_id=account.user_id,
            account_email_label=account.email_address,
            endpoint_id=endpoint_id,
        )


# --- Helpers ------------------------------------------------------------


async def _notify_first_platform_from_send(session: AsyncSession, *, org_id: uuid.UUID) -> None:
    """Fire the "you're on platform sending" in-app nudge to the org
    Owner exactly once per org.

    Idempotency is defensive (no DB-side ``UNIQUE(org_id, type)`` yet):
    we short-circuit when :func:`already_notified_first_platform_from`
    reports a prior row. Belt for the migration-less path — Step 5b
    could add a partial unique index if the metric shows duplicates.

    Owner is resolved by joining the org's ``Owner`` role
    (``name='Owner'``, ``is_system=True``) with its active
    ``OrganizationMember`` and taking the linked ``User.legacy_uuid``.
    Every org has exactly one Owner post-signup — if the lookup returns
    zero rows we log + skip; the outbound send already succeeded.

    Caller wraps in try/except and swallows every failure — a failing
    notify never rolls back the persisted outbound message.
    """
    from src.app.core.conversations.adapters.email_platform_from import (
        FIRST_USE_NOTIFICATION_KEY,
        FIRST_USE_NOTIFICATION_TYPE,
        already_notified_first_platform_from,
    )

    if await already_notified_first_platform_from(session, org_id=org_id):
        return

    # Late imports — notifications/permissions/users are all peer
    # modules; importing at top would pull them into the adapter's
    # cold-start path just for a first-use nudge fired once per org.
    from src.app.core.notifications.service import notify
    from src.app.core.permissions.models import Role
    from src.app.core.users.models import OrganizationMember, User

    owner_row = (
        await session.execute(
            select(User.legacy_uuid)
            .join(
                OrganizationMember,
                OrganizationMember.user_member_id == User.id,
            )
            .join(Role, Role.id == OrganizationMember.role_id)
            .where(OrganizationMember.organization_id == org_id)
            .where(OrganizationMember.is_active.is_(True))
            .where(Role.name == "Owner")
            .where(Role.is_system.is_(True))
            .limit(1)
        )
    ).scalar_one_or_none()
    if owner_row is None:
        logger.warning(
            "platform_from.first_use_notify: no active Owner for org=%s — skipped",
            org_id,
        )
        return

    await notify(
        org_id=org_id,
        user_id=owner_row,
        type=FIRST_USE_NOTIFICATION_TYPE,
        title="Your organisation is now sending email via the platform",
        body=(
            "You just sent your first email using the CRM's shared "
            "sending domain. Replies land in Conversations. Claim your "
            "own sending domain in Settings → Email to boost "
            "deliverability."
        ),
        payload={"notification_key": FIRST_USE_NOTIFICATION_KEY},
    )


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
    references_chain: str | None = None,
    reply_to: str | None = None,
    list_unsubscribe_url: str | None = None,
    list_unsubscribe_mailto: str | None = None,
    attachments: Sequence[OutboundAttachment] = (),
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
        # `References` should be a space-separated chain of every
        # ancestor Message-ID. When the caller passes the full chain
        # (AI reply flow — inbound envelope carried it) prefer that;
        # human compose falls back to the single-parent shape kept
        # from Step 8's original v1 behaviour.
        msg["References"] = references_chain or bracketed
    if body_html:
        # Plain text first (most permissive), then HTML alternative.
        msg.set_content(body_text)
        msg.add_alternative(body_html, subtype="html")
    else:
        msg.set_content(body_text)
    # Attachments turn the alternative body into multipart/mixed.
    for att in attachments:
        maintype, _, subtype = att.content_type.partition("/")
        msg.add_attachment(
            att.data,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=att.filename,
        )
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
    org_id: uuid.UUID | None = None,
) -> Conversation | None:
    """Return the most recent email conversation this contact belongs
    to, regardless of status. Used by BOTH the inbound flow (after
    thread-key match fails) and the outbound flow (when the caller
    didn't pin a specific conversation_id) so email delivery for one
    contact always concentrates in a single row.

    ``org_id`` is optional to preserve the OAuth call sites that run
    inside a set-tenant-context session; Mailgun's Celery task passes
    it explicitly so the query never trusts session-scoped context
    alone (Attacker C3 finding from PLANNING_RULES review).

    Ordering: ``last_message_at DESC NULLS LAST`` mirrors the inbox
    list — the conversation the operator was most recently looking at
    is the same one new email lands on."""
    stmt = (
        select(Conversation)
        .where(Conversation.channel == ConversationChannel.email)
        .where(Conversation.contact_id == contact_id)
    )
    if org_id is not None:
        stmt = stmt.where(Conversation.org_id == org_id)
    stmt = stmt.order_by(Conversation.last_message_at.desc().nullslast()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


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
    `channel_message_id` matches one of `thread_keys`.

    Both queries are org-scoped **explicitly** (Attacker C3 finding):
    a captured Message-ID from Org A's outbound cannot thread an
    inbound into Org B's conversations even if the session's tenant
    context is somehow bypassed. The `contact_id` + `channel` filters
    are belt-and-braces on top."""
    if not thread_keys:
        return None
    rows = (
        await session.execute(
            select(Message.conversation_id)
            .where(Message.org_id == org_id)
            .where(Message.channel_message_id.in_(list(thread_keys)))
        )
    ).all()
    if not rows:
        return None
    candidate_ids = {r[0] for r in rows}
    convs = (
        (
            await session.execute(
                select(Conversation)
                .where(Conversation.org_id == org_id)
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


async def _exists_by_rfc_id(
    session: AsyncSession, rfc_id: str, *, org_id: uuid.UUID | None = None
) -> bool:
    """Dedupe lookup — would this ``channel_message_id`` create a
    duplicate row inside the target org?

    ``org_id`` is optional to preserve OAuth callers; Mailgun path
    passes it explicitly (Attacker C3 finding). When set, the query
    uses the partial unique index ``uq_messages_org_channel_msgid``
    added in Step 0 for an O(log n) lookup."""
    stmt = select(Message.id).where(Message.channel_message_id == rfc_id)
    if org_id is not None:
        stmt = stmt.where(Message.org_id == org_id)
    rows = (await session.execute(stmt.limit(1))).first()
    return rows is not None


async def _exists_by_provider_id(
    session: AsyncSession,
    provider_message_id: str,
    provider: EmailAccountProvider,
    *,
    org_id: uuid.UUID | None = None,
) -> bool:
    """Secondary dedupe — for inbound messages where the RFC
    Message-ID is malformed/missing, fall back to checking the
    provider's own id stamped into `payload.provider_message_id`."""
    if not provider_message_id:
        return False
    stmt = select(Message.id).where(
        Message.payload["provider_message_id"].astext == provider_message_id
    )
    if org_id is not None:
        stmt = stmt.where(Message.org_id == org_id)
    rows = (await session.execute(stmt.limit(1))).first()
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
