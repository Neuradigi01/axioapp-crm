"""Cross-channel dedup helpers for the centralised ingest service.

Two layers of deduplication apply to every inbound lead, regardless
of channel (manual, bulk, widget, Google Ads, Meta Ads):

  1. **Contact dedup** (`find_existing_contact`) — reuse the
     bulk-import helper. A row whose phone OR email matches an
     existing contact in the org gets attached to that contact rather
     than minting a duplicate. Defined in `leads/imports/dedup.py`;
     re-exported here so all five channels have one import path.

  2. **Lead dedup** (`find_open_lead_for_contact`, NEW in Step 6) —
     if the resolved contact already has an OPEN (`status='active'`)
     lead, the ingest service appends a "Touchpoint via {source}"
     activity to that lead instead of creating a second one.
     `status IN ('won','lost')` leads do NOT block — those are closed
     and a fresh inquiry deserves a fresh lead row.

Both functions run raw SQL via `text()` to belt-and-suspenders the
ORM tenant filter — the worker code that calls these has already set
the request context (so RLS authorises), but the raw `text()` API
doesn't pick up the `do_orm_execute` listener, so explicit `org_id`
WHERE clauses are mandatory.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Re-export the bulk-import helper unchanged. Existing call sites in
# `leads/imports/tasks.py` keep their direct import; new call sites
# (ingest.py) import from here so the shared dedup surface lives in
# one place.
from src.app.core.leads.imports.dedup import (  # noqa: F401
    find_existing_contact,
    lowercase_email,
    normalize_phone,
)


async def find_open_lead_for_contact(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    contact_id: uuid.UUID,
) -> Optional[uuid.UUID]:
    """Return the most recent OPEN lead's id for `contact_id` in
    `org_id`, or None if none exists.

    "Open" = `status='active'` (the project uses `active|won|lost`,
    not `closed_won|closed_lost`). A new inbound touch on a contact
    whose only lead is `won` or `lost` creates a NEW lead — those
    deals are settled and a fresh inquiry deserves a fresh opportunity.

    Ordered by `created_at DESC` so when a contact has multiple open
    leads (rare, but possible if two reps both manually created one),
    the most recent wins.

    Raw SQL + explicit `org_id` because the ORM tenant filter doesn't
    apply to `text()` queries.
    """
    sql = text(
        """
        SELECT id FROM tbl_leads
        WHERE org_id = :org_id
          AND contact_id = :contact_id
          AND status = 'active'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    return (
        await session.execute(
            sql,
            {
                "org_id": str(org_id),
                "contact_id": str(contact_id),
            },
        )
    ).scalar()


__all__ = [
    "find_existing_contact",
    "find_open_lead_for_contact",
    "lowercase_email",
    "normalize_phone",
]
