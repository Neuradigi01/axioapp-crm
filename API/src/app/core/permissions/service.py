"""Service layer for roles and permissions.

Thin functions that wrap `Repository` / `select` against the
`Role`, `Permission`, `RolePermission` models. The auto-tenant
filter from `src.app.shared.orm` scopes `Role` selects by `org_id`
when a `RequestContext` is set; `Permission` is global by design.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.permissions.models import Permission, Role, RolePermission


async def get_role_by_id(session: AsyncSession, role_id: uuid.UUID) -> Role | None:
    result = await session.execute(select(Role).where(Role.id == role_id))
    return result.scalar_one_or_none()


async def list_permissions_for_role(
    session: AsyncSession, role_id: uuid.UUID
) -> list[Permission]:
    """Return every Permission row linked to `role_id` via `role_permissions`."""
    stmt = (
        select(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
        .order_by(Permission.key)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def register_permission(
    session: AsyncSession,
    *,
    key: str,
    module: str,
    description: str | None = None,
) -> Permission:
    """Idempotently insert a permission row into the global registry.

    Returns the existing or newly-created `Permission`. Safe to call
    on startup or from tests — duplicate keys are a no-op.
    """
    await session.execute(
        pg_insert(Permission)
        .values(key=key, module=module, description=description)
        .on_conflict_do_nothing(index_elements=["key"])
    )
    result = await session.execute(select(Permission).where(Permission.key == key))
    return result.scalar_one()
