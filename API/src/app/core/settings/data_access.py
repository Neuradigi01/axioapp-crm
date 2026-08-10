"""Data-access layer for the settings module.

Pure query helpers — no transactions, no audit. Leaf module; never
imports a ``service.py``.

Operations cover the single ``tbl_org_settings`` row per org:

  * ``get_org_settings_for_org`` — single-row read keyed by ``org_id``.
  * ``insert_org_settings`` — used by ``get_or_create`` to seed the
    row on first access.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.settings.models import OrgSettings


async def get_org_settings_for_org(session: AsyncSession, org_id: uuid.UUID) -> OrgSettings | None:
    """Single-row read by ``org_id``. ``None`` when the row hasn't been
    seeded yet — caller (``get_or_create``) inserts on miss."""
    result = await session.execute(select(OrgSettings).where(OrgSettings.org_id == org_id))
    return result.scalar_one_or_none()


def insert_org_settings(session: AsyncSession, row: OrgSettings) -> None:
    """Register an already-constructed OrgSettings for INSERT."""
    session.add(row)


async def list_all_org_settings(session: AsyncSession) -> list[OrgSettings]:
    """Return every ``OrgSettings`` row across all tenants.

    Used by the cross-tenant appointment-reminder sweep (celery beat)
    which needs each org's configured reminder offsets in one pass.
    The scanner opens its session WITHOUT setting a request context,
    so the ``do_orm_execute`` tenant filter is a no-op here — same
    pattern ``appointments.find_due_for_reminder`` uses.
    """
    result = await session.execute(select(OrgSettings))
    return list(result.scalars().all())


__all__ = [
    "get_org_settings_for_org",
    "insert_org_settings",
    "list_all_org_settings",
]
