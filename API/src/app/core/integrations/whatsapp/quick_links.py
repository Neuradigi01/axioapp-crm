"""WhatsApp quick-contact links service
(whatsapp-platform-upgrade Step 26).

Three concerns, one module:

  1. **Slug generation** — 8-char base62 with collision retry.
  2. **Click recording** — fast-path insert + counter bump used by
     the public ``/wa/{code}`` 302 redirect. The redirect path runs
     without a JWT, so we set the ``app.public_quick_link='1'`` PG
     setting to allow the RLS policy to pass for that transaction
     only (mirrors the data-deletion endpoint's bypass pattern).
  3. **Attribution match** — called from ``receive_webhook`` when
     an inbound text could be a customer-side echo of the
     prefilled message. Pairs the inbound with the most recent
     unmatched click whose ``prefilled_hash`` matches + flips the
     conversation's ``acquisition_*`` columns (Step 24).

The 10-minute attribution window is a manager-tunable env var
``WHATSAPP_QUICK_LINK_WINDOW_MIN`` (default 10). Wider windows
catch more legit conversions but risk false positives when a busy
billboard generates concurrent inbounds.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, text as sql_text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.conversations.models import Conversation
from src.app.core.integrations.whatsapp.models import (
    WhatsAppQuickLink,
    WhatsAppQuickLinkClick,
)

logger = logging.getLogger(__name__)


_SLUG_CHARSET = string.ascii_letters + string.digits  # base62
_SLUG_LEN = 8
_SLUG_MAX_RETRIES = 10
_DEFAULT_WINDOW_MIN = 10


class QuickLinksError(RuntimeError):
    """4xx-shaped error raised by the service layer; the router
    translates to HTTPException."""


def _digits_only(raw: str) -> str:
    return "".join(c for c in raw if c.isdigit())


def hash_prefilled(message: Optional[str]) -> Optional[str]:
    """Stable SHA-256 of the normalised prefilled text. Whitespace
    collapsed + lowercased so a customer who pastes the message with
    a stray newline still attributes correctly. Returns None on an
    empty / None input so the inbound-match logic can short-circuit."""
    if not message:
        return None
    normalised = " ".join(str(message).lower().split())
    if not normalised:
        return None
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _new_slug() -> str:
    return "".join(secrets.choice(_SLUG_CHARSET) for _ in range(_SLUG_LEN))


def _hash_ip(ip: Optional[str]) -> Optional[str]:
    """Stable but anonymous IP hash for repeat-click dedup. SHA-256
    truncated to 16 hex chars — collision-tolerant for the small
    populations we track."""
    if not ip:
        return None
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def list_links(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    page: int = 1,
    size: int = 50,
) -> tuple[list[WhatsAppQuickLink], int]:
    """Paginated list for the Settings → WhatsApp → Quick links page."""
    from sqlalchemy import func

    base = select(WhatsAppQuickLink).where(
        WhatsAppQuickLink.org_id == org_id
    )
    total_stmt = select(func.count()).select_from(base.subquery())
    total = int((await session.execute(total_stmt)).scalar_one() or 0)
    rows = (
        await session.execute(
            base.order_by(WhatsAppQuickLink.created_at.desc())
            .offset(max(0, (page - 1) * size))
            .limit(max(1, min(size, 200)))
        )
    ).scalars().all()
    return list(rows), total


async def create_link(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_user_id: Optional[uuid.UUID],
    label: str,
    phone_number: str,
    prefilled_message: Optional[str],
) -> WhatsAppQuickLink:
    """Create a quick link. Retries on slug collision up to
    ``_SLUG_MAX_RETRIES`` before giving up — 62^8 ≈ 218 trillion,
    so the retry budget is generous."""
    phone = _digits_only(phone_number)
    if not phone:
        raise QuickLinksError(
            "phone_number is required (digits-only)."
        )
    if not label.strip():
        raise QuickLinksError("label is required.")
    prefilled = (prefilled_message or "").strip() or None

    last_exc: Exception | None = None
    for _ in range(_SLUG_MAX_RETRIES):
        row = WhatsAppQuickLink(
            org_id=org_id,
            code=_new_slug(),
            label=label.strip(),
            phone_number=phone,
            prefilled_message=prefilled,
            prefilled_hash=hash_prefilled(prefilled),
            created_by_user_id=actor_user_id,
        )
        session.add(row)
        try:
            await session.commit()
            await session.refresh(row)
            await audit.log(
                "whatsapp.quick_link.created",
                entity_type="whatsapp_quick_link",
                entity_id=row.id,
                after={
                    "code": row.code,
                    "label": row.label,
                    "phone": row.phone_number,
                },
            )
            return row
        except IntegrityError as exc:
            last_exc = exc
            await session.rollback()
            continue
    raise QuickLinksError(
        "Could not allocate a unique slug after several attempts."
    ) from last_exc


async def update_link(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    link_id: uuid.UUID,
    label: Optional[str] = None,
    phone_number: Optional[str] = None,
    prefilled_message: Optional[str] = None,
) -> WhatsAppQuickLink:
    row = await _resolve_link(session, org_id=org_id, link_id=link_id)
    if label is not None:
        row.label = label.strip() or row.label
    if phone_number is not None:
        digits = _digits_only(phone_number)
        if digits:
            row.phone_number = digits
    if prefilled_message is not None:
        cleaned = prefilled_message.strip() or None
        row.prefilled_message = cleaned
        row.prefilled_hash = hash_prefilled(cleaned)
    row.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(row)
    return row


async def delete_link(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    link_id: uuid.UUID,
) -> None:
    row = await _resolve_link(session, org_id=org_id, link_id=link_id)
    await session.delete(row)
    await session.commit()
    await audit.log(
        "whatsapp.quick_link.deleted",
        entity_type="whatsapp_quick_link",
        entity_id=link_id,
        before={"code": row.code, "label": row.label},
    )


async def _resolve_link(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    link_id: uuid.UUID,
) -> WhatsAppQuickLink:
    row = (
        await session.execute(
            select(WhatsAppQuickLink).where(
                WhatsAppQuickLink.id == link_id,
                WhatsAppQuickLink.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise QuickLinksError("link not found")
    return row


# ---------------------------------------------------------------------------
# Public redirect — slug → wa.me target
# ---------------------------------------------------------------------------


async def resolve_by_code(
    session: AsyncSession, *, code: str
) -> Optional[WhatsAppQuickLink]:
    """Lookup a link by slug. Used by the public ``/wa/{code}``
    endpoint, which has no tenant context — we set
    ``app.public_quick_link='1'`` on the transaction so RLS allows
    the read. The setting is transaction-local and clears on
    commit."""
    await session.execute(
        sql_text("SELECT set_config('app.public_quick_link', '1', true)")
    )
    row = (
        await session.execute(
            select(WhatsAppQuickLink).where(WhatsAppQuickLink.code == code)
        )
    ).scalar_one_or_none()
    return row


def build_wa_me_url(link: WhatsAppQuickLink) -> str:
    """Construct the destination ``wa.me`` URL for a link. Uses
    ``urllib.parse.quote`` so non-ASCII / emoji prefilled bodies
    pass through correctly."""
    from urllib.parse import quote

    phone = _digits_only(link.phone_number)
    base = f"https://wa.me/{phone}"
    if link.prefilled_message:
        return f"{base}?text={quote(link.prefilled_message, safe='')}"
    return base


async def record_click(
    session: AsyncSession,
    *,
    link: WhatsAppQuickLink,
    source: str,
    ua_family: Optional[str],
    referrer: Optional[str],
    ip: Optional[str],
) -> None:
    """Insert a click row + bump the appropriate denormalised
    counter. Called by the public redirect path. Best-effort:
    any failure is logged but the user-facing 302 still goes out.

    ``source`` is ``'link'`` for short-URL clicks or ``'qr'`` for
    QR-code scans (the redirect endpoint passes ``?src=qr``)."""
    try:
        await session.execute(
            sql_text(
                "SELECT set_config('app.public_quick_link', '1', true)"
            )
        )
        click = WhatsAppQuickLinkClick(
            org_id=link.org_id,
            link_id=link.id,
            source=source if source in ("link", "qr") else "link",
            ua_family=(ua_family or "")[:64] or None,
            referrer=(referrer or "")[:2048] or None,
            ip_hash=_hash_ip(ip),
        )
        session.add(click)
        column = (
            WhatsAppQuickLink.scan_count
            if click.source == "qr"
            else WhatsAppQuickLink.click_count
        )
        await session.execute(
            update(WhatsAppQuickLink)
            .where(WhatsAppQuickLink.id == link.id)
            .values({column: column + 1})
        )
        await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception(
            "record_click failed for link=%s; redirect continues",
            link.id,
        )


# ---------------------------------------------------------------------------
# Inbound attribution match
# ---------------------------------------------------------------------------


def _window_minutes() -> int:
    try:
        return max(
            1,
            min(
                240,
                int(
                    os.getenv(
                        "WHATSAPP_QUICK_LINK_WINDOW_MIN",
                        str(_DEFAULT_WINDOW_MIN),
                    )
                ),
            ),
        )
    except ValueError:
        return _DEFAULT_WINDOW_MIN


async def attribute_inbound(
    session: AsyncSession,
    *,
    conversation: Conversation,
    inbound_text: Optional[str],
) -> Optional[WhatsAppQuickLink]:
    """Best-effort pair an inbound text with a recent quick-link
    click. Returns the matched link when an attribution was
    written; ``None`` when nothing matched / the conversation was
    already attributed.

    Matching rule:
      * The inbound text hashes to a known link's
        ``prefilled_hash``.
      * The match is org-scoped (cross-tenant clicks never
        attribute).
      * The conversation has no prior ``acquisition_source`` (single
        touch — same convention as Step 24).
      * There's at least one click on that link within the
        configured window without a prior ``matched_at``.

    On success: flip the conversation's ``acquisition_source='qr'``
    + ``acquisition_campaign_id=<link.id>`` so the existing chip +
    Ad-ROI surfaces light up; stamp the click row's ``matched_at``
    + ``matched_conversation_id``; bump the link's
    ``attributed_conversation_count`` counter."""
    if conversation.acquisition_source:
        return None
    inbound_hash = hash_prefilled(inbound_text)
    if not inbound_hash:
        return None

    link = (
        await session.execute(
            select(WhatsAppQuickLink).where(
                WhatsAppQuickLink.org_id == conversation.org_id,
                WhatsAppQuickLink.prefilled_hash == inbound_hash,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        return None

    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=_window_minutes()
    )
    click = (
        await session.execute(
            select(WhatsAppQuickLinkClick)
            .where(
                WhatsAppQuickLinkClick.link_id == link.id,
                WhatsAppQuickLinkClick.matched_at.is_(None),
                WhatsAppQuickLinkClick.recorded_at >= cutoff,
            )
            .order_by(WhatsAppQuickLinkClick.recorded_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if click is None:
        return None

    now = datetime.now(timezone.utc)
    click.matched_at = now
    click.matched_conversation_id = conversation.id

    conversation.acquisition_source = "qr"
    conversation.acquisition_campaign_id = str(link.id)
    conversation.acquisition_landing_url = (
        f"/wa/{link.code}"
    )
    conversation.acquisition_referral_payload = {
        "source": "qr_quick_link",
        "link_id": str(link.id),
        "link_label": link.label,
        "link_code": link.code,
        "click_source": click.source,
        "matched_at": now.isoformat(),
    }

    await session.execute(
        update(WhatsAppQuickLink)
        .where(WhatsAppQuickLink.id == link.id)
        .values(
            attributed_conversation_count=(
                WhatsAppQuickLink.attributed_conversation_count + 1
            )
        )
    )
    await session.commit()
    await audit.log(
        "whatsapp.quick_link.attributed",
        entity_type="conversation",
        entity_id=conversation.id,
        after={
            "link_id": str(link.id),
            "link_code": link.code,
            "label": link.label,
        },
    )
    return link


async def link_stats(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    link_id: uuid.UUID,
) -> dict:
    """Stats card payload — denormalised counters + click vs scan
    split + last 10 clicks."""
    link = await _resolve_link(session, org_id=org_id, link_id=link_id)
    recent = (
        await session.execute(
            select(WhatsAppQuickLinkClick)
            .where(WhatsAppQuickLinkClick.link_id == link.id)
            .order_by(WhatsAppQuickLinkClick.recorded_at.desc())
            .limit(10)
        )
    ).scalars().all()
    return {
        "id": str(link.id),
        "code": link.code,
        "label": link.label,
        "clicks": link.click_count,
        "scans": link.scan_count,
        "attributed_conversations": link.attributed_conversation_count,
        "recent_clicks": [
            {
                "id": str(c.id),
                "source": c.source,
                "ua_family": c.ua_family,
                "referrer": c.referrer,
                "recorded_at": c.recorded_at.isoformat(),
                "matched": c.matched_at is not None,
            }
            for c in recent
        ],
    }


__all__ = [
    "QuickLinksError",
    "attribute_inbound",
    "build_wa_me_url",
    "create_link",
    "delete_link",
    "hash_prefilled",
    "link_stats",
    "list_links",
    "record_click",
    "resolve_by_code",
    "update_link",
]
