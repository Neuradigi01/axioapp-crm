"""Opt-in / opt-out transition service
(whatsapp-platform-upgrade Step 22).

Single public entry point — :func:`record_transition` — that
performs an idempotent status change on a contact + writes the
matching ``ConsentEvent`` row + emits an audit event. Every call
site (manual API endpoint, STOP-keyword auto-flip, form-widget
ingest, bulk-import wizard) funnels through here so the consent
log is the single source of truth.

STOP-keyword detection
----------------------

``detect_stop_keyword`` runs a compiled regex over inbound text.
The default set covers English + Hindi (Devanagari + romanised);
operators can extend the table without touching this file by
overriding the env var ``WHATSAPP_STOP_KEYWORDS`` (comma-separated)
— same pattern as Step 21's cost-rate override.

Idempotency
-----------

Re-recording the same status with the same source is a no-op (no
new row, no audit emit). A status change ALWAYS emits a row, even
if the underlying fields (recorded_at, actor) differ. This keeps
the audit trail clean without losing any legitimate transitions.

Confirmation template
---------------------

When the flip is to ``opted_out``, the consent service tries to
send a "you've been unsubscribed" template through the WhatsApp
adapter. If no opt-out template is configured the flip still
persists — DPDP compliance trumps the courtesy notice. The
template send failure is logged but does not raise.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.contacts.models import (
    WHATSAPP_OPT_IN_SOURCES,
    WHATSAPP_OPT_IN_STATUSES,
    ConsentEvent,
    Contact,
)

logger = logging.getLogger(__name__)


# Default STOP keywords. Substring + case-insensitive match against the
# stripped inbound text. Operators extending the list via env var
# don't lose these defaults — we union, not replace.
_DEFAULT_STOP_KEYWORDS: tuple[str, ...] = (
    # English
    "stop",
    "unsubscribe",
    "opt out",
    "opt-out",
    "remove me",
    "cancel",
    "no more",
    # Hindi — Devanagari
    "बंद करो",
    "रोको",
    "अनसब्सक्राइब",
    # Hindi — romanised
    "band karo",
    "roko",
    "ruko",
)


class ConsentError(RuntimeError):
    """Raised when an opt-in transition cannot be persisted (unknown
    contact, invalid status, etc.). Endpoints translate to 422."""


@dataclass(frozen=True, slots=True)
class TransitionResult:
    contact_id: uuid.UUID
    old_status: str | None
    new_status: str
    persisted: bool  # False on idempotent no-op
    event_id: uuid.UUID | None


def _normalised_keywords() -> list[str]:
    raw = os.getenv("WHATSAPP_STOP_KEYWORDS", "").strip()
    extra: list[str] = []
    if raw:
        for token in raw.split(","):
            token = token.strip().lower()
            if token:
                extra.append(token)
    # Union — defaults always included.
    seen: set[str] = set()
    out: list[str] = []
    for kw in (*_DEFAULT_STOP_KEYWORDS, *extra):
        lowered = kw.lower()
        if lowered not in seen:
            seen.add(lowered)
            out.append(lowered)
    return out


def detect_stop_keyword(text: str | None) -> bool:
    """True if the inbound text matches any STOP keyword.

    Match rules:
      * Lowercased substring.
      * For pure-ASCII keywords, we also enforce a word boundary so
        "I'll stop by tomorrow" doesn't auto-opt-out the customer.
      * For Unicode (Hindi) keywords, plain substring — Devanagari +
        the romanised aliases are already distinctive enough that a
        word-boundary check would be over-engineering.
    """
    if not text:
        return False
    lowered = text.strip().lower()
    if not lowered:
        return False
    for kw in _normalised_keywords():
        if not kw:
            continue
        if kw.isascii():
            # Word-boundary match — guard against incidental substring hits.
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, lowered):
                return True
        else:
            if kw in lowered:
                return True
    return False


def _validate_status(status: str) -> str:
    if status not in WHATSAPP_OPT_IN_STATUSES:
        raise ConsentError(
            f"unknown opt-in status {status!r}; must be one of {sorted(WHATSAPP_OPT_IN_STATUSES)}"
        )
    return status


def _validate_source(source: str | None) -> str | None:
    if source is None:
        return None
    if source not in WHATSAPP_OPT_IN_SOURCES:
        raise ConsentError(
            f"unknown opt-in source {source!r}; must be one of {sorted(WHATSAPP_OPT_IN_SOURCES)}"
        )
    return source


async def record_transition(
    session: AsyncSession,
    *,
    contact: Contact,
    new_status: str,
    source: str | None,
    actor_user_id: uuid.UUID | None = None,
    reason: str | None = None,
    request_evidence: dict[str, Any] | None = None,
    ip_address: str | None = None,
    commit: bool = True,
) -> TransitionResult:
    """Persist a status transition on ``contact`` + append a
    ``ConsentEvent`` row + emit an audit event.

    Idempotent on identical (status, source) — no-op returns
    ``persisted=False`` and ``event_id=None``. The caller can rely
    on this when wiring the STOP-keyword auto-flip: every inbound
    will call this method, but only the first will write a row.

    ``commit=False`` lets the caller defer the commit if it's
    bundling several writes into one transaction (e.g. the form
    widget creates the contact + records the opt-in in the same
    request)."""
    _validate_status(new_status)
    _validate_source(source)

    old_status = contact.whatsapp_opt_in_status
    if old_status == new_status:
        # Idempotent no-op. Source / actor refresh is intentionally
        # skipped — the original capture is the legally-meaningful
        # one.
        return TransitionResult(
            contact_id=contact.id,
            old_status=old_status,
            new_status=new_status,
            persisted=False,
            event_id=None,
        )

    now = datetime.now(UTC)
    contact.whatsapp_opt_in_status = new_status
    contact.whatsapp_opt_in_source = source
    if new_status == "opted_out":
        contact.whatsapp_opt_out_recorded_at = now
        contact.whatsapp_opt_out_reason = reason
    else:
        contact.whatsapp_opt_in_recorded_at = now
        contact.whatsapp_opt_in_recorded_by_user_id = actor_user_id
        # If a previously opted-out contact re-opts-in, clear the
        # opt-out fields so the campaign guard reads a clean slate.
        contact.whatsapp_opt_out_recorded_at = None
        contact.whatsapp_opt_out_reason = None

    event = ConsentEvent(
        org_id=contact.org_id,
        contact_id=contact.id,
        channel="whatsapp",
        old_status=old_status,
        new_status=new_status,
        source=source,
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        reason=reason,
        request_evidence=request_evidence or {},
    )
    session.add(event)

    if commit:
        await session.commit()
        await session.refresh(contact)
        await session.refresh(event)

    await audit.log(
        "contacts.opt_in_changed",
        entity_type="contact",
        entity_id=contact.id,
        before={"whatsapp_opt_in_status": old_status},
        after={
            "whatsapp_opt_in_status": new_status,
            "whatsapp_opt_in_source": source,
            "actor_user_id": (str(actor_user_id) if actor_user_id else None),
            "reason": reason,
        },
    )

    return TransitionResult(
        contact_id=contact.id,
        old_status=old_status,
        new_status=new_status,
        persisted=True,
        event_id=event.id,
    )


async def list_consent_events(
    session: AsyncSession,
    *,
    contact_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[ConsentEvent]:
    """Most-recent-first history for one contact. RLS-scoped via
    the standard ``app.org_id`` setting — no manual filter needed.

    ``offset`` supports paging past the 200-row window so a contact
    with a long consent history stays fully auditable."""
    stmt = (
        select(ConsentEvent)
        .where(ConsentEvent.contact_id == contact_id)
        .order_by(ConsentEvent.recorded_at.desc())
        .offset(max(0, offset))
        .limit(max(1, min(limit, 200)))
    )
    return list((await session.execute(stmt)).scalars().all())


async def count_consent_events(
    session: AsyncSession,
    *,
    contact_id: uuid.UUID,
) -> int:
    """Total consent-event count for one contact — drives the "N more"
    affordance in the opt-in history panel."""
    from sqlalchemy import func as _func

    result = await session.execute(
        select(_func.count(ConsentEvent.id)).where(ConsentEvent.contact_id == contact_id)
    )
    return int(result.scalar_one() or 0)


async def auto_flip_on_inbound(
    session: AsyncSession,
    *,
    contact: Contact | None,
    inbound_text: str | None,
    is_first_inbound: bool,
) -> TransitionResult | None:
    """Apply the two automatic rules from the Step 22 spec:

      * STOP keyword → ``opted_out`` (highest priority).
      * First inbound from a ``never_contacted`` row → ``implicit``.

    Returns the ``TransitionResult`` when a flip actually happened
    (so the caller can decide whether to ship the opt-out
    confirmation template), or ``None`` on no-op. Idempotent on
    re-entry because :func:`record_transition` is.
    """
    if contact is None:
        return None

    if detect_stop_keyword(inbound_text):
        return await record_transition(
            session,
            contact=contact,
            new_status="opted_out",
            source="stop_keyword",
            reason="customer-sent STOP keyword",
            request_evidence={"inbound_text": inbound_text or ""},
            commit=False,
        )

    if is_first_inbound and contact.whatsapp_opt_in_status == "never_contacted":
        return await record_transition(
            session,
            contact=contact,
            new_status="implicit",
            source="inbound_first_message",
            request_evidence={"inbound_text": inbound_text or ""},
            commit=False,
        )
    return None


async def send_opt_out_confirmation(
    session: AsyncSession,
    *,
    conversation: Any,
) -> None:
    """Ship a "you've been unsubscribed" confirmation through the
    WhatsApp adapter.

    Strategy:
      1. Look up an approved utility template named one of
         ``opt_out_confirmation`` / ``unsubscribe_confirmation`` /
         ``stop_confirmation`` for the org.
      2. If found, send it via the adapter as a template message.
      3. If none exists, log + skip. DPDP rule: the opt-out flip is
         the legally-meaningful action; the confirmation is a
         courtesy and its absence must never block compliance.

    Best-effort throughout — caller (the webhook handler) catches
    any escaping exception so the inbound message processing path
    is unaffected."""
    try:
        from src.app.core.conversations.adapters.whatsapp import (
            resolve_whatsapp_adapter,
        )
        from src.app.core.conversations.models import (
            Message,
            MessageDirection,
        )
        from src.app.core.integrations.whatsapp.models import (
            WhatsAppTemplate,
        )

        template = (
            await session.execute(
                select(WhatsAppTemplate)
                .where(
                    WhatsAppTemplate.name.in_(
                        (
                            "opt_out_confirmation",
                            "unsubscribe_confirmation",
                            "stop_confirmation",
                        )
                    ),
                    WhatsAppTemplate.status == "APPROVED",
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if template is None:
            logger.info(
                "send_opt_out_confirmation: no opt-out template configured; "
                "opt-out persisted without confirmation"
            )
            return

        adapter = await resolve_whatsapp_adapter(session)
        ref = await adapter.send_template(
            org_id=conversation.org_id,
            external_id=conversation.external_id,
            template_name=template.name,
            language=template.language,
            variables=[],
        )
        now = datetime.now(UTC)
        sent_at = ref.sent_at or now
        msg = Message(
            org_id=conversation.org_id,
            conversation_id=conversation.id,
            direction=MessageDirection.out,
            sender_user_id=None,
            text=template.body,
            attachments=[],
            channel_message_id=ref.channel_message_id,
            payload={"author": "system", "kind": "opt_out_confirmation"},
            sent_at=sent_at,
        )
        session.add(msg)
        conversation.last_message_at = sent_at
        await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception(
            "send_opt_out_confirmation failed for contact %s",
            getattr(conversation, "contact_id", None),
        )


__all__ = [
    "ConsentError",
    "TransitionResult",
    "auto_flip_on_inbound",
    "detect_stop_keyword",
    "list_consent_events",
    "record_transition",
    "send_opt_out_confirmation",
]
