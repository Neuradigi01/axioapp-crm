"""Pure CRUD for the WhatsApp Web sidecar correlation table.

Per the layered-architecture rule: no transactions, no business
logic, no permission checks. Service-layer code drives commits.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.integrations.whatsapp_web.models import WhatsAppWebSession


async def get_session_by_integration(
    db: AsyncSession,
    *,
    integration_id: uuid.UUID,
) -> Optional[WhatsAppWebSession]:
    """Return the (single) Web session row for an integration, if any."""
    stmt = select(WhatsAppWebSession).where(
        WhatsAppWebSession.integration_id == integration_id
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_session_by_sidecar_id(
    db: AsyncSession,
    *,
    sidecar_session_id: str,
) -> Optional[WhatsAppWebSession]:
    """Reverse lookup used by the Step-6 events receiver — sidecar
    posts the correlation id, we resolve back to the row."""
    stmt = select(WhatsAppWebSession).where(
        WhatsAppWebSession.sidecar_session_id == sidecar_session_id
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def upsert_session(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    integration_id: uuid.UUID,
    sidecar_session_id: str,
    **patches: Any,
) -> WhatsAppWebSession:
    """Create-or-update the Web session row for an integration.

    If a row already exists for ``integration_id``, fields in
    ``patches`` are written onto it (the ``sidecar_session_id`` is
    refreshed too — a reconnect mints a new sidecar session). If
    none exists, a new row is staged with the given fields.

    No commit; the service layer owns the transaction boundary.
    """
    row = await get_session_by_integration(db, integration_id=integration_id)
    if row is None:
        row = WhatsAppWebSession(
            org_id=org_id,
            integration_id=integration_id,
            sidecar_session_id=sidecar_session_id,
        )
        for field, value in patches.items():
            setattr(row, field, value)
        db.add(row)
        return row

    row.sidecar_session_id = sidecar_session_id
    for field, value in patches.items():
        setattr(row, field, value)
    return row


async def delete_session(
    db: AsyncSession,
    *,
    integration_id: uuid.UUID,
) -> bool:
    """Hard-delete the Web session row for an integration. Returns
    ``True`` if a row was removed, ``False`` if there was nothing to
    delete. No commit."""
    row = await get_session_by_integration(db, integration_id=integration_id)
    if row is None:
        return False
    await db.delete(row)
    return True


__all__ = [
    "delete_session",
    "get_session_by_integration",
    "get_session_by_sidecar_id",
    "upsert_session",
]
