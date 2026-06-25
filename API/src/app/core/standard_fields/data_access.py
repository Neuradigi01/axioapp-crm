"""Data-access layer for the standard_fields overrides module.

Pure query helpers — no transactions, no audit, no registry checks.
Leaf module; never imports a ``service.py``.

Operations cover the ``tbl_standard_field_overrides`` table:

  * ``list_overrides_for_org`` — all overrides for a tenant, with
    total count.
  * ``list_overrides_for_entity`` — overrides for one entity (used by
    the merge + per-entity list endpoint).
  * ``get_override_by_keys`` — single-row lookup by the unique
    ``(org_id, entity, field_key)`` tuple.
  * ``upsert_override`` — ``INSERT ... ON CONFLICT DO UPDATE``
    keyed on the unique constraint. Caller commits.
  * ``delete_override`` — DELETE keyed on the same tuple.

The registry membership check + payload validation + the override
merge logic all stay in ``service.py``.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.standard_fields.models import StandardFieldOverride


async def list_overrides_for_org(
    session: AsyncSession, *, org_id: uuid.UUID
) -> tuple[list[StandardFieldOverride], int]:
    """All override rows for ``org_id``, sorted by entity then
    field_key, plus the total count. Returned as a tuple so the
    list-endpoint response shape can populate ``(items, total)`` in
    one DAL call."""
    rows = (
        await session.execute(
            select(StandardFieldOverride)
            .where(StandardFieldOverride.org_id == org_id)
            .order_by(
                StandardFieldOverride.entity,
                StandardFieldOverride.field_key,
            )
        )
    ).scalars().all()
    total = (
        await session.execute(
            select(func.count())
            .select_from(StandardFieldOverride)
            .where(StandardFieldOverride.org_id == org_id)
        )
    ).scalar_one()
    return list(rows), int(total)


async def list_overrides_for_entity(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    entity: str,
) -> list[StandardFieldOverride]:
    """Override rows for one entity, sorted by ``field_key``. Used by
    the per-entity list endpoint and by the merge."""
    rows = (
        await session.execute(
            select(StandardFieldOverride)
            .where(
                StandardFieldOverride.org_id == org_id,
                StandardFieldOverride.entity == entity,
            )
            .order_by(StandardFieldOverride.field_key)
        )
    ).scalars().all()
    return list(rows)


async def get_override_by_keys(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    entity: str,
    field_key: str,
) -> Optional[StandardFieldOverride]:
    """Single-row lookup by the unique ``(org_id, entity, field_key)``
    tuple. Used by the upsert's pre-read (to capture ``before`` for
    audit) + the reset's existence check."""
    return (
        await session.execute(
            select(StandardFieldOverride).where(
                StandardFieldOverride.org_id == org_id,
                StandardFieldOverride.entity == entity,
                StandardFieldOverride.field_key == field_key,
            )
        )
    ).scalar_one_or_none()


async def upsert_override(
    session: AsyncSession,
    *,
    insert_values: dict[str, Any],
    update_values: dict[str, Any],
) -> None:
    """``INSERT ... ON CONFLICT DO UPDATE`` keyed on the
    ``uq_standard_field_overrides_org_entity_field`` constraint.

    Caller composes both value dicts (service already does payload
    + actor stamping). DAL just executes. Caller commits."""
    stmt = (
        pg_insert(StandardFieldOverride)
        .values(**insert_values)
        .on_conflict_do_update(
            constraint="uq_standard_field_overrides_org_entity_field",
            set_=update_values,
        )
    )
    await session.execute(stmt)


async def delete_override(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    entity: str,
    field_key: str,
) -> None:
    """DELETE the row for ``(org_id, entity, field_key)``. Caller
    commits. Caller has already verified the row exists (so the
    audit ``before`` snapshot is meaningful)."""
    await session.execute(
        delete(StandardFieldOverride).where(
            StandardFieldOverride.org_id == org_id,
            StandardFieldOverride.entity == entity,
            StandardFieldOverride.field_key == field_key,
        )
    )


__all__ = [
    "delete_override",
    "get_override_by_keys",
    "list_overrides_for_entity",
    "list_overrides_for_org",
    "upsert_override",
]
