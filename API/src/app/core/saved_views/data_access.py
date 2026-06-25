"""Data-access layer for the saved_views module.

Pure query helpers — no transactions, no audit, no permission checks.
Leaf module; never imports a ``service.py``.

Operations:

  * ``get_view_by_id`` — single-row read for the ownership check.
  * ``list_views_for_user_and_entity`` — visibility-aware list (owned
    + shared) for the menu render.
  * ``find_view_by_owner_entity_name`` — pre-check used by create +
    rename to surface 409 without leaning on the post-commit
    ``IntegrityError`` path.
  * ``insert_view`` / ``delete_view_row`` — caller commits.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.saved_views.models import SavedView


async def get_view_by_id(
    session: AsyncSession, view_id: uuid.UUID
) -> Optional[SavedView]:
    """Single-row read by PK. RLS keeps cross-tenant rows invisible;
    service-level ownership / sharing is enforced by callers."""
    result = await session.execute(
        select(SavedView).where(SavedView.id == view_id)
    )
    return result.scalar_one_or_none()


async def list_views_for_user_and_entity(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    entity: str,
) -> list[SavedView]:
    """Views the user can see for ``entity``: owned + shared. Owned
    first, then shared, alphabetical within each bucket."""
    stmt = (
        select(SavedView)
        .where(
            SavedView.org_id == org_id,
            SavedView.entity == entity,
            or_(
                SavedView.owner_user_id == user_id,
                SavedView.shared.is_(True),
            ),
        )
        .order_by(
            (SavedView.owner_user_id != user_id).asc(),
            SavedView.name.asc(),
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def find_view_by_owner_entity_name(
    session: AsyncSession,
    *,
    owner_user_id: uuid.UUID,
    entity: str,
    name: str,
) -> Optional[SavedView]:
    """Pre-check on the unique ``(owner_user_id, entity, name)`` tuple
    — used by create + rename to surface 409 without relying on the
    commit-side IntegrityError path."""
    result = await session.execute(
        select(SavedView).where(
            SavedView.owner_user_id == owner_user_id,
            SavedView.entity == entity,
            SavedView.name == name,
        )
    )
    return result.scalar_one_or_none()


def insert_view(session: AsyncSession, view: SavedView) -> None:
    """Register an already-constructed SavedView for INSERT."""
    session.add(view)


async def delete_view_row(
    session: AsyncSession, view: SavedView
) -> None:
    """Mark a SavedView row for DELETE. Caller commits."""
    await session.delete(view)


__all__ = [
    "delete_view_row",
    "find_view_by_owner_entity_name",
    "get_view_by_id",
    "insert_view",
    "list_views_for_user_and_entity",
]
