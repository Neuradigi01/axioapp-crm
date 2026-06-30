"""Data-access layer for the custom-fields module.

Pure query helpers — no transactions, no audit, no source-rule
validations. Leaf module; never imports a ``service.py``.

Four operations cover the definitions table:

  * ``get_field_by_id`` — single-row read by PK, scoped to active tenant.
  * ``list_fields_query`` — definitions for one entity, optionally
    including hidden rows, ordered for stable form rendering.
  * ``insert_field`` / ``delete_field_row`` — caller commits; caller
    catches IntegrityError on the
    ``(org_id, entity_type, field_key)`` unique violation.

Per the architecture spec, ``custom_data`` JSONB column-level writes
(inside other entities' service files) stay where they are — those
are property mutations, not "queries".
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.custom_fields.models import CustomFieldDefinition


async def get_field_by_id(
    session: AsyncSession, field_id: uuid.UUID
) -> CustomFieldDefinition | None:
    """Single-row read by PK. ``None`` on miss (or cross-tenant — the
    ORM filter applies)."""
    result = await session.execute(
        select(CustomFieldDefinition).where(CustomFieldDefinition.id == field_id)
    )
    return result.scalar_one_or_none()


async def list_fields_query(
    session: AsyncSession,
    *,
    entity_type: str,
    include_hidden: bool = False,
) -> list[CustomFieldDefinition]:
    """List definitions for one entity, ordered by display_order then
    field_key. Caller decides whether to include hidden rows."""
    stmt = select(CustomFieldDefinition).where(CustomFieldDefinition.entity_type == entity_type)
    if not include_hidden:
        stmt = stmt.where(CustomFieldDefinition.is_hidden.is_(False))
    stmt = stmt.order_by(
        CustomFieldDefinition.display_order,
        CustomFieldDefinition.field_key,
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def insert_field(session: AsyncSession, field: CustomFieldDefinition) -> None:
    """Register an already-constructed CustomFieldDefinition for INSERT."""
    session.add(field)


async def delete_field_row(session: AsyncSession, field: CustomFieldDefinition) -> None:
    """Mark a CustomFieldDefinition row for DELETE. Caller commits."""
    await session.delete(field)


__all__ = [
    "delete_field_row",
    "get_field_by_id",
    "insert_field",
    "list_fields_query",
]
