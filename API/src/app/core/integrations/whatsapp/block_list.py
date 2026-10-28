"""Block-list service
(whatsapp-platform-upgrade Step 23).

One choke-point for every "is this number blocked?" question + the
CRUD helpers used by the Settings → Block List page. The
``is_blocked`` lookup is the hot path — called on every inbound
webhook and every outbound send — so it's deliberately tiny:

  * Phone normalised to digits-only via :func:`normalise_phone`
    (matches the existing contact-phone convention).
  * Single ``SELECT 1 FROM tbl_whatsapp_block_list`` query with the
    ``(org_id, phone_number)`` index. No JSON joins, no extra hops.

RLS scoping
-----------

``app.org_id`` is set on every transaction via the SQLAlchemy
``after_begin`` hook; every query in this module additionally
filters by ``org_id`` as a belt-and-braces guard so a missing RLS
policy can't accidentally leak the list across tenants.

Caching
-------

We intentionally do **not** cache block-list lookups today. The
table is org-scoped and tiny (most orgs have < 100 blocked
numbers), the index is unique, and the inbound webhook is already
hitting the DB three other times in the same handler. Adding a
Redis cache layer here would buy a microsecond at the cost of a
new invalidation path — defer until profiling shows the lookup
actually matters. The risk-section of the step spec captures this.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.integrations.whatsapp.models import (
    WhatsAppBlockListEntry,
)

logger = logging.getLogger(__name__)


# Closed set of reasons surfaced in the UI dropdown. Kept here so
# the schema validation lives next to the service that consumes it.
BLOCK_REASONS: tuple[str, ...] = (
    "spam",
    "fraud",
    "requested",
    "harassment",
    "other",
)


class BlockListError(RuntimeError):
    """Raised for invalid block-list operations the API should
    translate to 4xx (duplicate, unknown reason, bad phone)."""


@dataclass(frozen=True, slots=True)
class BlockedNumberHit:
    """Lightweight result for the hot-path ``is_blocked`` check.
    Carries the row id + reason so callers can audit *why* a drop
    happened without a second query."""

    id: uuid.UUID
    phone_number: str
    reason: str


_NORMALISE_RE = re.compile(r"\D+")


def normalise_phone(raw: str | None) -> str:
    """Strip everything except digits — same rule the contact phone
    column + the WhatsApp inbound webhook use. Returns ``""`` on
    None / empty so callers can short-circuit cheaply."""
    if not raw:
        return ""
    return _NORMALISE_RE.sub("", str(raw))


def _validate_reason(reason: str) -> str:
    if reason not in BLOCK_REASONS:
        raise BlockListError(f"unknown reason {reason!r}; must be one of {sorted(BLOCK_REASONS)}")
    return reason


async def is_blocked(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    phone: str | None,
) -> BlockedNumberHit | None:
    """Return the matching block-list row when ``phone`` is blocked
    in the active org, ``None`` otherwise.

    Hot path — called from the WhatsApp webhook BEFORE the
    conversation upsert and from the outbound adapter BEFORE the
    Meta API request. Both callers tolerate a None return and treat
    "no row" as "allowed". On DB failure we log + return None so a
    transient error never blocks an honest customer."""
    normalised = normalise_phone(phone)
    if not normalised:
        return None
    try:
        row = (
            await session.execute(
                select(WhatsAppBlockListEntry)
                .where(
                    WhatsAppBlockListEntry.org_id == org_id,
                    WhatsAppBlockListEntry.phone_number == normalised,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
    except Exception:  # noqa: BLE001
        logger.exception(
            "is_blocked lookup failed for org=%s phone=%s",
            org_id,
            normalised,
        )
        return None
    if row is None:
        return None
    return BlockedNumberHit(id=row.id, phone_number=row.phone_number, reason=row.reason)


async def list_entries(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    search: str | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[WhatsAppBlockListEntry], int]:
    """Paginated list for the Settings → Block List page.

    ``search`` does an ``ILIKE %x%`` against ``phone_number`` after
    digit normalisation — operators pasting raw "+91 99…" still
    find the row."""
    base = select(WhatsAppBlockListEntry).where(WhatsAppBlockListEntry.org_id == org_id)
    if search:
        needle = normalise_phone(search)
        if needle:
            base = base.where(WhatsAppBlockListEntry.phone_number.ilike(f"%{needle}%"))

    from sqlalchemy import func

    total_stmt = select(func.count()).select_from(base.subquery())
    total = int((await session.execute(total_stmt)).scalar_one() or 0)

    rows = (
        (
            await session.execute(
                base.order_by(WhatsAppBlockListEntry.created_at.desc())
                .offset(max(0, (page - 1) * size))
                .limit(max(1, min(size, 200)))
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total


async def add_entry(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    phone: str,
    reason: str,
    actor_user_id: uuid.UUID | None = None,
    notes: str | None = None,
) -> WhatsAppBlockListEntry:
    """Block a number. Idempotent on ``(org_id, phone)`` — the
    unique constraint converts a re-block attempt into a 409-shaped
    :class:`BlockListError` so the SPA can surface "already
    blocked" without a hard error."""
    normalised = normalise_phone(phone)
    if not normalised:
        raise BlockListError("phone number is required")
    _validate_reason(reason)

    row = WhatsAppBlockListEntry(
        org_id=org_id,
        phone_number=normalised,
        reason=reason,
        blocked_by_user_id=actor_user_id,
        notes=notes,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise BlockListError(f"phone {phone} is already on the block list") from exc
    await session.refresh(row)

    await audit.log(
        "whatsapp.block_list.added",
        entity_type="whatsapp_block",
        entity_id=row.id,
        after={
            "phone_number": normalised,
            "reason": reason,
            "notes": notes,
        },
    )
    return row


async def remove_entry(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    entry_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> bool:
    """Unblock by row id. Returns True when a row was deleted,
    False when the id is unknown / cross-tenant (RLS already
    blocks the latter; we keep the explicit ``org_id`` filter for
    defence-in-depth)."""
    row = (
        await session.execute(
            select(WhatsAppBlockListEntry).where(
                WhatsAppBlockListEntry.id == entry_id,
                WhatsAppBlockListEntry.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    payload = {
        "phone_number": row.phone_number,
        "reason": row.reason,
    }
    await session.execute(
        delete(WhatsAppBlockListEntry).where(
            WhatsAppBlockListEntry.id == entry_id,
            WhatsAppBlockListEntry.org_id == org_id,
        )
    )
    await session.commit()
    await audit.log(
        "whatsapp.block_list.removed",
        entity_type="whatsapp_block",
        entity_id=entry_id,
        before=payload,
    )
    return True


class BlockedNumberOutbound(RuntimeError):
    """Raised by the adapter / send-guard when an outbound is
    targeted at a blocked phone. The campaign service catches this
    and writes a ``failed`` row with a stable error string so the
    Step-21 failure classifier can bucket it."""

    def __init__(self, phone: str, reason: str) -> None:
        super().__init__(f"phone {phone} is on the block list (reason: {reason})")
        self.phone = phone
        self.reason = reason


__all__ = [
    "BLOCK_REASONS",
    "BlockListError",
    "BlockedNumberHit",
    "BlockedNumberOutbound",
    "add_entry",
    "is_blocked",
    "list_entries",
    "normalise_phone",
    "remove_entry",
]
