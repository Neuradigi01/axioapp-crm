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


__all__ = ["get_org_settings_for_org", "insert_org_settings"]
