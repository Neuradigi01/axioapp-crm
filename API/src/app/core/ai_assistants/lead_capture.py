"""Auto-lead-capture helper for the AI-assistants runtime
(``tasks/ai-assistants`` Step 16).

Two modes:

  * ``detect_email`` — every user message is regex-scanned for an
    email. On match: upsert a Contact by email +
    dedup-or-create a Lead + attach the contact to the conversation.
  * ``ask_at_turn`` — at conversation turn N the runtime injects a
    system-side prompt telling the model to weave the ask into its
    reply. The visitor's next message is then handled by the same
    detect-email path.

The regex is intentionally permissive (RFC-perfect email regex is
famously ~4KB and doesn't matter for lead capture) — false
positives inside a longer sentence with unusual punctuation get
turned into a real Lead only after the Contact upsert normalises
the string. Better to over-capture and let the operator merge
duplicates than to under-capture and lose a hot lead.

Reuses existing infrastructure — never invents:
  * :func:`contacts.service.get_or_create_placeholder_contact`
    for the Contact upsert (idempotent by email).
  * :func:`leads.ingest.ingest` for the Lead dedup + creation
    (routing + activity-log entries fire from there).
  * Direct UPDATE on ``tbl_conversations.contact_id`` for the
    conversation → contact link (no dedicated service helper
    exists; documented DAL exception in the layered pin-test).
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.ai_assistants.models import AiAssistant, LeadCaptureMode
from src.app.core.contacts.service import get_or_create_placeholder_contact
from src.app.core.leads.ingest import ingest as leads_ingest
from src.app.core.leads.models import LeadSource
from src.app.core.leads.schemas import LeadCreate

logger = logging.getLogger(__name__)

# Case-insensitive email match. Intentionally lax — a stricter
# regex would miss "j.o+notes@sub.example.co.uk" shapes that show
# up in real customer support conversations. Any false positive
# creates a Contact with a bad email; the operator sees it in the
# leads list + merges/deletes.
_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
)

DEFAULT_ASK_MESSAGE = (
    "By the way — if you'd like us to follow up personally, "
    "could you share your email address? (Optional.)"
)


@dataclass(frozen=True, slots=True)
class CaptureOutcome:
    """Non-None on the happy path. ``lead_id`` is ``None`` if the
    text didn't contain an email; ``skipped_reason`` is populated
    on the fall-through branches so the runtime can log why it
    didn't capture."""

    lead_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    matched_email: str | None = None
    skipped_reason: str | None = None


def extract_email(text: str | None) -> str | None:
    """Return the first email found in ``text``, lower-cased. ``None``
    if no match. Trimmed to guard against trailing punctuation that
    slipped past the regex (e.g. ``foo@bar.com,``)."""
    if not text:
        return None
    match = _EMAIL_RE.search(text)
    if match is None:
        return None
    # Strip trailing punctuation that the regex character class may
    # have swallowed via a preceding label (e.g. "email me at
    # foo@bar.com." — the "." at the end is a sentence terminator,
    # not part of the email). We only clean the last char — anything
    # more aggressive risks eating a valid TLD.
    email = match.group(0)
    while email and email[-1] in ".,;:!?)]}":
        email = email[:-1]
    return email.lower()


def should_ask_at_turn(
    assistant: AiAssistant,
    *,
    current_turn: int,
) -> bool:
    """True when the assistant is in ``ask_at_turn`` mode AND this
    is the target turn. Runtime bumps ``current_turn`` per user
    message; the ask fires exactly once when the turn count matches
    ``lead_capture_turn_n``."""
    if assistant.lead_capture_mode != LeadCaptureMode.ask_at_turn:
        return False
    return current_turn == max(1, assistant.lead_capture_turn_n or 3)


def ask_message_for(assistant: AiAssistant) -> str:
    """Body of the ask injection. Uses the operator-configured text
    when set; falls back to a neutral default."""
    return (assistant.lead_capture_message or "").strip() or DEFAULT_ASK_MESSAGE


async def capture_lead_from_message(
    session: AsyncSession,
    *,
    assistant: AiAssistant,
    conversation_id: uuid.UUID,
    user_message: str,
) -> CaptureOutcome:
    """Scan ``user_message`` for an email, create a Contact + Lead if
    one lands, and attach the Contact to the conversation. Idempotent
    across repeat calls with the same email — the ``get_or_create``
    contact path + ``leads.ingest`` dedup path guarantee no duplicates.

    Fail-soft: any exception is logged + returned as a
    ``skipped_reason`` outcome rather than propagating. Lead capture
    is a nice-to-have; a hiccup in the lead pipeline should NEVER
    break the chat reply the visitor is waiting for.
    """
    if assistant.lead_capture_mode == LeadCaptureMode.off:
        return CaptureOutcome(skipped_reason="lead_capture_off")

    email = extract_email(user_message)
    if email is None:
        return CaptureOutcome(skipped_reason="no_email_in_message")

    try:
        contact = await get_or_create_placeholder_contact(
            session,
            org_id=assistant.org_id,
            external_id=email,
            channel="email",
        )
    except Exception as exc:
        logger.warning(
            "ai_assistants.lead_capture contact_upsert_failed org=%s email=%s err=%r",
            assistant.org_id,
            email,
            exc,
        )
        return CaptureOutcome(
            matched_email=email, skipped_reason="contact_upsert_failed"
        )

    lead_payload = LeadCreate(
        contact_id=contact.id,
        source=LeadSource.ai_assistant,
        attribution={
            "assistant_id": str(assistant.id),
            "captured_via": "ai_assistant_conversation",
        },
    )
    try:
        result = await leads_ingest(
            session,
            org_id=assistant.org_id,
            source=LeadSource.ai_assistant,
            contact_id=contact.id,
            lead_payload=lead_payload,
            actor_user_id=None,
        )
    except Exception as exc:
        logger.warning(
            "ai_assistants.lead_capture ingest_failed org=%s email=%s err=%r",
            assistant.org_id,
            email,
            exc,
        )
        return CaptureOutcome(
            contact_id=contact.id,
            matched_email=email,
            skipped_reason="lead_ingest_failed",
        )

    # Link the conversation to the contact so the inbox row shows a
    # named person instead of the session-token snippet. Only set if
    # currently NULL — an operator who manually re-linked shouldn't
    # get overwritten by a later email match.
    try:
        await session.execute(
            sql_text(
                """
                UPDATE tbl_conversations
                SET contact_id = :contact_id
                WHERE id = :conv_id
                  AND contact_id IS NULL
                """
            ),
            {"contact_id": str(contact.id), "conv_id": str(conversation_id)},
        )
    except Exception as exc:
        logger.warning(
            "ai_assistants.lead_capture conv_attach_failed conv=%s err=%r",
            conversation_id,
            exc,
        )

    logger.info(
        "ai_assistants.lead_capture ok org=%s assistant=%s lead=%s contact=%s "
        "action=%s",
        assistant.org_id,
        assistant.id,
        result.lead_id,
        contact.id,
        result.action,
    )
    return CaptureOutcome(
        lead_id=result.lead_id,
        contact_id=contact.id,
        matched_email=email,
    )


__all__ = [
    "DEFAULT_ASK_MESSAGE",
    "CaptureOutcome",
    "ask_message_for",
    "capture_lead_from_message",
    "extract_email",
    "should_ask_at_turn",
]
