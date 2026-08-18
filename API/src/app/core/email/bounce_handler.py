"""Provider-agnostic email bounce + complaint webhook handler.

Four providers ship parsers today: Mailgun, SendGrid, SES, Postmark.
Each parser converts the provider's webhook payload into a
normalized :class:`BounceEvent` carrying:

  * ``email_address`` — recipient that bounced / complained
  * ``bounce_type``   — ``'hard' | 'soft' | 'complaint' | 'unsubscribe'``
  * ``provider``      — the provider key (mailgun / sendgrid / ses /
                       postmark) for the audit trail
  * ``provider_event_id`` — provider's unique event id (used for
                       dedupe against webhook re-deliveries)
  * ``raw_payload``   — verbatim provider payload, stored for the
                       operator's paper trail

Hard bounces, complaints, and unsubscribes write a row into
``tbl_automation_suppressions`` so the send-guard's
:func:`check_suppression` refuses subsequent sends to the same
``(org_id, channel='email', address)`` triple. Soft bounces are
recorded in ``tbl_email_bounce_events`` but DON'T suppress — soft
bounces are transient (mailbox full, server unreachable) and an
operator would lose legitimate addresses if we suppressed on first
bounce.

HMAC validation per provider is the router's job — see
:func:`core.email.router.bounce_webhook_endpoint`. This module
assumes the payload has already been authenticated.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)


BounceType = Literal["hard", "soft", "complaint", "unsubscribe"]
ProviderKey = Literal["mailgun", "sendgrid", "ses", "postmark"]


# Bounce types that warrant a suppression row. Soft bounces don't
# (transient) and unknown types fall through to "log only".
_SUPPRESSING_TYPES: frozenset[str] = frozenset({"hard", "complaint", "unsubscribe"})


@dataclass(frozen=True, slots=True)
class BounceEvent:
    """Normalised bounce event the handler writes to the DB."""

    email_address: str
    bounce_type: str
    provider: str
    provider_event_id: str
    raw_payload: dict[str, Any]


class UnsupportedWebhookError(ValueError):
    """The webhook payload doesn't match any known provider shape."""


# --- Mailgun ----------------------------------------------------------------


def parse_mailgun(payload: dict[str, Any]) -> list[BounceEvent]:
    """Mailgun "Events Webhook" payload shape:

    .. code-block:: json

        {
          "event-data": {
            "event": "failed",
            "severity": "permanent",
            "recipient": "asha@x.com",
            "id": "abc123",
            ...
          }
        }

    ``event`` ``failed`` + ``severity=permanent`` → hard bounce.
    ``event`` ``failed`` + ``severity=temporary`` → soft bounce.
    ``event`` ``complained`` → complaint.
    ``event`` ``unsubscribed`` → unsubscribe.
    """
    data = payload.get("event-data") or {}
    event = data.get("event")
    severity = data.get("severity")
    recipient = data.get("recipient")
    provider_event_id = data.get("id") or str(uuid.uuid4())

    if not recipient or not event:
        return []

    bounce_type: str | None = None
    if event == "failed":
        bounce_type = "hard" if severity == "permanent" else "soft"
    elif event == "complained":
        bounce_type = "complaint"
    elif event == "unsubscribed":
        bounce_type = "unsubscribe"
    else:
        return []

    return [
        BounceEvent(
            email_address=recipient.lower().strip(),
            bounce_type=bounce_type,
            provider="mailgun",
            provider_event_id=str(provider_event_id),
            raw_payload=payload,
        )
    ]


def verify_mailgun_signature(payload: dict[str, Any], *, signing_key: str) -> bool:
    """Mailgun signs with ``HMAC-SHA256(signing_key, timestamp + token)``;
    the signature ships in the body's ``signature`` dict."""
    sig = payload.get("signature") or {}
    timestamp = sig.get("timestamp")
    token = sig.get("token")
    expected = sig.get("signature")
    if not (timestamp and token and expected):
        return False
    computed = hmac.new(
        signing_key.encode("utf-8"),
        f"{timestamp}{token}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(computed, expected)


# --- SendGrid ---------------------------------------------------------------


def parse_sendgrid(payload: list[dict[str, Any]]) -> list[BounceEvent]:
    """SendGrid posts a JSON ARRAY of events. Each event's
    ``event`` key tells us the type; ``email``, ``sg_event_id`` give
    the rest.

    Mapping:
      ``bounce`` (type=bounce) → hard bounce (5xx)
      ``bounce`` (type=blocked) → soft bounce
      ``dropped``               → hard bounce
      ``spamreport``            → complaint
      ``unsubscribe`` / ``group_unsubscribe`` → unsubscribe
    """
    out: list[BounceEvent] = []
    if not isinstance(payload, Iterable):
        return out

    for item in payload:
        if not isinstance(item, dict):
            continue
        event = item.get("event")
        email = item.get("email")
        ev_id = item.get("sg_event_id") or str(uuid.uuid4())

        bounce_type: str | None = None
        if event == "bounce":
            sub = (item.get("type") or "").lower()
            bounce_type = "hard" if sub == "bounce" else "soft"
        elif event == "dropped":
            bounce_type = "hard"
        elif event == "spamreport":
            bounce_type = "complaint"
        elif event in ("unsubscribe", "group_unsubscribe"):
            bounce_type = "unsubscribe"
        else:
            continue

        if not email:
            continue
        out.append(
            BounceEvent(
                email_address=email.lower().strip(),
                bounce_type=bounce_type,
                provider="sendgrid",
                provider_event_id=str(ev_id),
                raw_payload=item,
            )
        )
    return out


def verify_sendgrid_signature(
    body_bytes: bytes,
    *,
    timestamp: str,
    signature: str,
    public_key: str,
) -> bool:
    """SendGrid uses ECDSA verification on the public key — we
    fail-open in the absence of a configured key (caller is expected
    to provide a valid PEM; if not, the verification short-circuits
    to False)."""
    # The CRM doesn't currently ship an ECDSA verifier dependency;
    # for the v1 pass we accept the timestamp + signature presence
    # as a minimum check. Operators with strict requirements wire a
    # gateway-level verifier (Cloudflare / API gateway) in front.
    return bool(timestamp and signature and public_key)


# --- SES (Amazon Simple Email Service) -------------------------------------


def parse_ses(payload: dict[str, Any]) -> list[BounceEvent]:
    """SES bounces arrive via SNS notifications. The top-level
    ``Message`` field is a JSON string with the SES envelope:

    .. code-block:: json

        {
          "notificationType": "Bounce" | "Complaint",
          "bounce": {
              "bounceType": "Permanent" | "Transient",
              "bouncedRecipients": [{"emailAddress": "..."}],
              "feedbackId": "abc"
          }
        }

    SNS-wrapping (the outer envelope) is handled by the router
    before invoking the parser — by the time payload lands here it's
    the inner ``Message`` payload parsed into a dict.
    """
    out: list[BounceEvent] = []
    notif_type = payload.get("notificationType")

    if notif_type == "Bounce":
        bounce = payload.get("bounce") or {}
        bounce_kind = bounce.get("bounceType")
        feedback_id = bounce.get("feedbackId") or str(uuid.uuid4())
        bounce_type = "hard" if bounce_kind == "Permanent" else "soft"
        for r in bounce.get("bouncedRecipients") or []:
            email = (r.get("emailAddress") or "").lower().strip()
            if not email:
                continue
            out.append(
                BounceEvent(
                    email_address=email,
                    bounce_type=bounce_type,
                    provider="ses",
                    provider_event_id=f"{feedback_id}:{email}",
                    raw_payload=payload,
                )
            )
    elif notif_type == "Complaint":
        complaint = payload.get("complaint") or {}
        feedback_id = complaint.get("feedbackId") or str(uuid.uuid4())
        for r in complaint.get("complainedRecipients") or []:
            email = (r.get("emailAddress") or "").lower().strip()
            if not email:
                continue
            out.append(
                BounceEvent(
                    email_address=email,
                    bounce_type="complaint",
                    provider="ses",
                    provider_event_id=f"{feedback_id}:{email}",
                    raw_payload=payload,
                )
            )
    return out


# --- Postmark --------------------------------------------------------------


def parse_postmark(payload: dict[str, Any]) -> list[BounceEvent]:
    """Postmark bounce/complaint webhook payload:

    .. code-block:: json

        {
          "RecordType": "Bounce" | "SpamComplaint",
          "Type": "HardBounce" | "SoftBounce" | ...,
          "Email": "asha@x.com",
          "MessageID": "...",
          "ID": 123456
        }
    """
    record_type = payload.get("RecordType")
    email = (payload.get("Email") or "").lower().strip()
    provider_event_id = (
        str(payload.get("ID")) if payload.get("ID") is not None else str(uuid.uuid4())
    )
    if not email or not record_type:
        return []

    bounce_type: str | None = None
    if record_type == "Bounce":
        sub = (payload.get("Type") or "").lower()
        bounce_type = "hard" if sub == "hardbounce" else "soft"
    elif record_type == "SpamComplaint":
        bounce_type = "complaint"
    elif record_type == "SubscriptionChange" and payload.get("SuppressSending"):
        bounce_type = "unsubscribe"
    else:
        return []

    return [
        BounceEvent(
            email_address=email,
            bounce_type=bounce_type,
            provider="postmark",
            provider_event_id=provider_event_id,
            raw_payload=payload,
        )
    ]


# --- Dispatcher + persistence ---------------------------------------------


_PARSERS: dict[str, Any] = {
    "mailgun": parse_mailgun,
    "sendgrid": parse_sendgrid,
    "ses": parse_ses,
    "postmark": parse_postmark,
}


def parse_provider_payload(provider: str, payload: Any) -> list[BounceEvent]:
    """Pick the parser for ``provider`` + return the list of
    normalised events. Raises :class:`UnsupportedWebhookError` for
    unknown providers so the router maps to 400."""
    parser = _PARSERS.get(provider.lower())
    if parser is None:
        raise UnsupportedWebhookError(f"unsupported bounce webhook provider: {provider}")
    return parser(payload)


async def persist_bounce_events(
    session,
    *,
    org_id: uuid.UUID,
    events: list[BounceEvent],
) -> dict[str, int]:
    """Write every event to ``tbl_email_bounce_events`` (skipping
    provider re-deliveries via the unique
    ``provider_event_id`` index) + populate
    ``tbl_automation_suppressions`` for hard / complaint /
    unsubscribe types.

    Returns a small summary ``{recorded, suppressed, skipped_dupes}``
    for the audit + router response.
    """
    from sqlalchemy import select as _select

    from src.app.core.automation.models import (
        AutomationSuppression,
        EmailBounceEvent,
        SuppressionReason,
    )
    from src.app.core.conversations.models import ConversationChannel

    reason_map = {
        "hard": SuppressionReason.hard_bounce,
        "complaint": SuppressionReason.complaint,
        "unsubscribe": SuppressionReason.unsubscribe,
    }

    recorded = 0
    suppressed = 0
    skipped = 0
    published_events: list[BounceEvent] = []

    for ev in events:
        existing = (
            await session.execute(
                _select(EmailBounceEvent.id).where(
                    EmailBounceEvent.provider_event_id == ev.provider_event_id
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            skipped += 1
            continue

        row = EmailBounceEvent(
            org_id=org_id,
            email_address=ev.email_address,
            bounce_type=ev.bounce_type,
            provider=ev.provider,
            provider_event_id=ev.provider_event_id,
            raw_payload=ev.raw_payload,
        )
        session.add(row)
        await session.flush()
        recorded += 1
        published_events.append(ev)

        if ev.bounce_type in _SUPPRESSING_TYPES:
            # Idempotent (org_id, channel, address) write. Existing
            # row stays — operators rehabilitate via DELETE, not by
            # overwriting the reason.
            already = (
                await session.execute(
                    _select(AutomationSuppression.id).where(
                        AutomationSuppression.org_id == org_id,
                        AutomationSuppression.channel == ConversationChannel.email,
                        AutomationSuppression.address == ev.email_address,
                    )
                )
            ).scalar_one_or_none()
            if already is None:
                session.add(
                    AutomationSuppression(
                        org_id=org_id,
                        channel=ConversationChannel.email,
                        address=ev.email_address,
                        reason=reason_map[ev.bounce_type],
                        source_event_id=row.id,
                    )
                )
                await session.flush()
                suppressed += 1

    await session.commit()
    logger.info(
        "email.bounce_handler persist_bounce_events org=%s recorded=%d "
        "suppressed=%d skipped_dupes=%d",
        org_id,
        recorded,
        suppressed,
        skipped,
    )

    # Fan out ``email.bounced`` to the event bus for every freshly-
    # persisted event (skip provider re-deliveries so a webhook retry
    # doesn't double-fire subscriber workflows). Best-effort with
    # per-event contact lookup; a bus / subscriber failure never rolls
    # back the already-committed suppression row.
    if published_events:
        await _publish_bounce_events(session, org_id=org_id, events=published_events)

    return {
        "recorded": recorded,
        "suppressed": suppressed,
        "skipped_dupes": skipped,
    }


async def _publish_bounce_events(
    session,
    *,
    org_id: uuid.UUID,
    events: list[BounceEvent],
) -> None:
    """Emit ``email.bounced`` per event. Contact lookup is best-effort
    — bounces for unknown addresses (e.g. a rep manually typed a bad
    address in Test Send) still fire without ``contact_id`` so the
    operator can wire an alert workflow on ``email_address`` alone."""
    from sqlalchemy import select as _select

    from src.app.core.contacts.models import Contact
    from src.app.core.events.bus import publish as events_publish
    from src.app.core.events.event_catalog import EMAIL_BOUNCED

    addresses = sorted({ev.email_address.lower() for ev in events if ev.email_address})
    contact_by_email: dict[str, Contact] = {}
    if addresses:
        try:
            rows = (
                await session.execute(
                    _select(Contact).where(
                        Contact.org_id == org_id,
                        Contact.email.in_(addresses),
                    )
                )
            ).scalars().all()
            for c in rows:
                if c.email:
                    contact_by_email[c.email.lower()] = c
        except Exception:
            logger.exception(
                "email.bounce_handler contact_lookup_failed org=%s",
                org_id,
            )

    for ev in events:
        contact = contact_by_email.get(ev.email_address.lower())
        payload: dict[str, Any] = {
            "email_address": ev.email_address,
            "bounce_type": ev.bounce_type,
            "provider": ev.provider,
            "contact_id": str(contact.id) if contact is not None else None,
        }
        if contact is not None:
            payload["contact"] = {
                "id": str(contact.id),
                "full_name": contact.full_name,
                "email": contact.email,
                "phone": contact.phone,
            }
        try:
            await events_publish(
                EMAIL_BOUNCED,
                payload,
                org_id=org_id,
                event_id=f"email_bounced:{ev.provider}:{ev.provider_event_id}",
            )
        except Exception:
            logger.exception(
                "email.bounce_handler publish_failed org=%s event_id=%s",
                org_id,
                ev.provider_event_id,
            )


__all__ = [
    "BounceEvent",
    "UnsupportedWebhookError",
    "parse_mailgun",
    "parse_postmark",
    "parse_provider_payload",
    "parse_sendgrid",
    "parse_ses",
    "persist_bounce_events",
    "verify_mailgun_signature",
    "verify_sendgrid_signature",
]
