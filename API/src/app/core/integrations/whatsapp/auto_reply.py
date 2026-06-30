"""WhatsApp auto-reply pipeline
(whatsapp-platform-upgrade Step 16).

Single entry point — :func:`dispatch_auto_replies` — invoked from
``conversations.service.receive_webhook`` after every inbound WhatsApp
message lands. Decides whether to fire a greeting and/or out-of-hours
away message, then writes the outbound rows + ships them through the
adapter.

Pipeline order:
  1. Greeting — first message from this contact in 24h, greeting
     enabled, and we haven't greeted in the cooldown window.
  2. Away — outside business hours, away enabled, no away reply in
     the cooldown window.

Each step is independent — both can fire on the same inbound (a new
contact messaging outside hours gets greeting + away). The cooldown
keys are stored as ``payload.auto_reply_type`` on the outbound row
(``greeting`` / ``away``) so the helper can count prior auto-replies
without a separate audit table.

In-session vs out-of-session (Step 15 helper):
  * In-session → free-text reply with variable substitution.
  * Out-of-session → linked approved template; skip if no template
    is configured (operator hasn't set one yet).

Variable substitution supports ``{{contact.first_name}}``,
``{{contact.full_name}}``, and ``{{org.name}}``. Unknown placeholders
are left as-is so a typo doesn't render a broken message.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.contacts import data_access
from src.app.core.contacts.models import Contact
from src.app.core.conversations.adapters.whatsapp import (
    WhatsAppNotConnected,
    resolve_whatsapp_adapter,
)
from src.app.core.conversations.models import (
    Conversation,
    Message,
    MessageDirection,
)
from src.app.core.conversations.whatsapp_session import (
    compute_session_state,
)
from src.app.core.integrations.whatsapp.connect import get_active_config
from src.app.core.integrations.whatsapp.models import (
    WhatsAppAccountConfig,
    WhatsAppTemplate,
)
from src.app.core.tenants.models import Organization

logger = logging.getLogger(__name__)


# 24-hour cooldown — one auto-reply of each type per contact per day.
# Matches the spec; longer would feel cold (a customer messaging two
# days apart should get re-greeted? Arguable — keep it conservative
# at 24h so a same-day re-message doesn't double-fire).
_COOLDOWN = timedelta(hours=24)

_VARIABLE_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def substitute_variables(
    text: str,
    *,
    contact: Contact | None = None,
    org: Organization | None = None,
) -> str:
    """Replace ``{{contact.first_name}}`` / ``{{contact.full_name}}`` /
    ``{{org.name}}`` placeholders with the contact / org values.
    Unknown variables pass through untouched so a typo is visible to
    the operator rather than silently dropped."""
    if not text:
        return text

    first_name = contact.full_name.split(" ", 1)[0] if contact and contact.full_name else ""
    full_name = contact.full_name if contact and contact.full_name else ""
    org_name = org.name if org and org.name else ""

    values: dict[str, str] = {
        "contact.first_name": first_name,
        "contact.full_name": full_name,
        "org.name": org_name,
    }

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return values.get(key, match.group(0))

    return _VARIABLE_RE.sub(_replace, text)


# --- business hours -----------------------------------------------------


def is_within_business_hours(
    hours: list[dict[str, Any]] | None,
    *,
    now: datetime | None = None,
) -> bool:
    """Return True if `now` falls inside any open interval of the
    operator-configured business hours.

    Schedule shape (from Step 11):
        [{day: 0..6, intervals: [{open: "HH:MM", close: "HH:MM"}, ...]}]
    Day 0 = Monday, ISO-style. An empty / NULL `hours` is treated as
    "always open" — out-of-hours auto-reply is opt-in via the
    `away_enabled` flag; if the operator forgot to set hours, we
    don't surprise them by spamming away messages.

    Times are interpreted in UTC. Tenant-local TZ handling is a
    future refinement; for now operators are expected to set hours
    in the same TZ they read them in."""
    if not hours:
        return True
    current = now or datetime.now(UTC)
    weekday = current.weekday()  # 0=Mon..6=Sun
    current_time = current.time()
    for day in hours:
        if not isinstance(day, dict):
            continue
        if day.get("day") != weekday:
            continue
        intervals = day.get("intervals") or []
        for iv in intervals:
            if not isinstance(iv, dict):
                continue
            open_str = iv.get("open")
            close_str = iv.get("close")
            if not isinstance(open_str, str) or not isinstance(close_str, str):
                continue
            try:
                open_t = _parse_hhmm(open_str)
                close_t = _parse_hhmm(close_str)
            except ValueError:
                continue
            if open_t <= current_time < close_t:
                return True
    return False


def _parse_hhmm(value: str) -> time:
    """Parse ``HH:MM`` → ``time``. Raises ValueError on bad input."""
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"bad HH:MM: {value!r}")
    return time(hour=int(parts[0]), minute=int(parts[1]))


# --- cooldown -----------------------------------------------------------


async def _recent_auto_reply_exists(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    auto_reply_type: str,
    now: datetime,
) -> bool:
    """Cooldown check — does the conversation have an outbound
    auto-reply row of the given type within the last 24 hours?

    The cooldown key lives on ``Message.payload['auto_reply_type']``
    so we don't need a separate audit table. Uses Postgres JSONB
    `->>` access via SQLAlchemy's `op` operator."""
    cutoff = now - _COOLDOWN
    stmt = (
        select(Message.id)
        .where(Message.conversation_id == conversation_id)
        .where(Message.direction == MessageDirection.out)
        .where(Message.sent_at >= cutoff)
        .where(Message.payload["auto_reply_type"].astext == auto_reply_type)
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    return row is not None


async def _is_first_inbound(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    excluding_message_id: uuid.UUID | None = None,
) -> bool:
    """True when the conversation has no prior inbound messages aside
    from the one we just persisted. The just-inserted row is
    excluded via `excluding_message_id` so the caller doesn't have
    to delay the auto-reply dispatch until after a separate flush."""
    from sqlalchemy import func

    stmt = (
        select(func.count())
        .select_from(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.direction == MessageDirection.in_)
    )
    if excluding_message_id is not None:
        stmt = stmt.where(Message.id != excluding_message_id)
    count = (await session.execute(stmt)).scalar_one() or 0
    return count == 0


# --- send paths ---------------------------------------------------------


async def _send_auto_reply_text(
    session: AsyncSession,
    *,
    config: WhatsAppAccountConfig,
    conversation: Conversation,
    text: str,
    auto_reply_type: str,
) -> Message:
    """Send a free-text auto-reply via the Cloud API + persist the
    outbound row with the cooldown marker on `payload`. Used when the
    contact is in their 24-hour session window."""
    adapter = await resolve_whatsapp_adapter(session)
    ref = await adapter.send(
        org_id=conversation.org_id,
        external_id=conversation.external_id,
        text=text,
        attachments=[],
    )
    now = datetime.now(UTC)
    sent_at = ref.sent_at or now
    msg = Message(
        org_id=conversation.org_id,
        conversation_id=conversation.id,
        direction=MessageDirection.out,
        sender_user_id=None,
        text=text,
        attachments=[],
        channel_message_id=ref.channel_message_id,
        payload={
            "auto_reply": True,
            "auto_reply_type": auto_reply_type,
            "adapter_ref": ref.channel_message_id,
        },
        sent_at=sent_at,
    )
    session.add(msg)
    conversation.last_message_at = sent_at
    await session.commit()
    await session.refresh(msg)
    await audit.log(
        f"conversations.auto_reply.{auto_reply_type}_sent",
        entity_type="conversation",
        entity_id=conversation.id,
        after={"text_preview": text[:120]},
    )
    return msg


async def _send_auto_reply_template(
    session: AsyncSession,
    *,
    config: WhatsAppAccountConfig,
    conversation: Conversation,
    template: WhatsAppTemplate,
    auto_reply_type: str,
) -> Message:
    """Out-of-session path — ship an approved template instead of
    free text. Variable substitution is operator-side: the template
    body is sent verbatim with no `{{n}}` interpolation (auto-reply
    templates should be parameter-free; that's an operator-side
    choice when they wire one)."""
    adapter = await resolve_whatsapp_adapter(session)
    ref = await adapter.send_template(
        org_id=conversation.org_id,
        external_id=conversation.external_id,
        template_name=template.name,
        language=template.language,
        variables={},
        header_type=template.header_type,
        header_text=template.header_text,
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
        payload={
            "auto_reply": True,
            "auto_reply_type": auto_reply_type,
            "template_id": str(template.id),
            "adapter_ref": ref.channel_message_id,
        },
        sent_at=sent_at,
    )
    session.add(msg)
    conversation.last_message_at = sent_at
    await session.commit()
    await session.refresh(msg)
    await audit.log(
        f"conversations.auto_reply.{auto_reply_type}_template_sent",
        entity_type="conversation",
        entity_id=conversation.id,
        after={"template_id": str(template.id)},
    )
    return msg


async def _resolve_template(
    session: AsyncSession, template_id: uuid.UUID | None
) -> WhatsAppTemplate | None:
    if template_id is None:
        return None
    return (
        await session.execute(
            select(WhatsAppTemplate).where(
                WhatsAppTemplate.id == template_id,
                WhatsAppTemplate.status == "APPROVED",
            )
        )
    ).scalar_one_or_none()


# --- pipeline -----------------------------------------------------------


async def dispatch_auto_replies(
    session: AsyncSession,
    *,
    conversation: Conversation,
    inbound_message_id: uuid.UUID,
) -> list[str]:
    """Run the greeting → away pipeline for an inbound message.

    Returns the list of auto-reply types that fired (``["greeting"]``,
    ``["greeting", "away"]``, etc.) — caller uses this for logging
    + tests. All failures are caught + logged; auto-reply errors
    never roll back the inbound message persist.
    """
    fired: list[str] = []

    try:
        bundle = await get_active_config(session)
    except Exception:
        logger.exception("auto_reply: could not load org config")
        return fired
    if bundle is None:
        return fired
    _, config = bundle

    if not config.greeting_enabled and not config.away_enabled:
        return fired

    now = datetime.now(UTC)
    session_state = compute_session_state(conversation.last_customer_message_at, now=now)
    in_session = session_state["in_session"]

    # Resolve contact + org once for variable substitution.
    contact: Contact | None = None
    if conversation.contact_id is not None:
        contact = await data_access.get_contact(session, conversation.contact_id)
    org = (
        await session.execute(select(Organization).where(Organization.id == conversation.org_id))
    ).scalar_one_or_none()

    # --- Greeting branch -----------------------------------------------
    if config.greeting_enabled:
        try:
            is_first = await _is_first_inbound(
                session,
                conversation_id=conversation.id,
                excluding_message_id=inbound_message_id,
            )
            cooled = await _recent_auto_reply_exists(
                session,
                conversation_id=conversation.id,
                auto_reply_type="greeting",
                now=now,
            )
            if is_first and not cooled:
                if in_session and config.greeting_message:
                    rendered = substitute_variables(
                        config.greeting_message, contact=contact, org=org
                    )
                    await _send_auto_reply_text(
                        session,
                        config=config,
                        conversation=conversation,
                        text=rendered,
                        auto_reply_type="greeting",
                    )
                    fired.append("greeting")
                elif not in_session:
                    template = await _resolve_template(session, config.greeting_template_id)
                    if template is not None:
                        await _send_auto_reply_template(
                            session,
                            config=config,
                            conversation=conversation,
                            template=template,
                            auto_reply_type="greeting",
                        )
                        fired.append("greeting")
                    # else: no template configured — silent skip
        except WhatsAppNotConnected:
            logger.info("auto_reply.greeting skipped: org not connected")
        except Exception:
            logger.exception(
                "auto_reply.greeting send failed for conv %s",
                conversation.id,
            )

    # --- Away branch ----------------------------------------------------
    if config.away_enabled and not is_within_business_hours(config.business_hours, now=now):
        try:
            cooled = await _recent_auto_reply_exists(
                session,
                conversation_id=conversation.id,
                auto_reply_type="away",
                now=now,
            )
            if not cooled:
                if in_session and config.away_message:
                    rendered = substitute_variables(config.away_message, contact=contact, org=org)
                    await _send_auto_reply_text(
                        session,
                        config=config,
                        conversation=conversation,
                        text=rendered,
                        auto_reply_type="away",
                    )
                    fired.append("away")
                elif not in_session:
                    template = await _resolve_template(session, config.away_template_id)
                    if template is not None:
                        await _send_auto_reply_template(
                            session,
                            config=config,
                            conversation=conversation,
                            template=template,
                            auto_reply_type="away",
                        )
                        fired.append("away")
        except WhatsAppNotConnected:
            logger.info("auto_reply.away skipped: org not connected")
        except Exception:
            logger.exception("auto_reply.away send failed for conv %s", conversation.id)

    return fired


__all__ = [
    "dispatch_auto_replies",
    "is_within_business_hours",
    "substitute_variables",
]
