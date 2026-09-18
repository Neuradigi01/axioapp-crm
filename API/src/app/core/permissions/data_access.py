"""Data-access layer for the permissions module.

Pure query helpers — no transactions, no audit, no HTTP-status raises.
Leaf module; never imports a ``service.py``.

Operations grouped by entity:

  * ``tbl_permissions`` (global registry — no org_id)
      get_permission_by_key, list_all_permissions,
      list_permissions_by_keys, list_permission_keys_with_ids,
      upsert_permission_key, bulk_upsert_permission_keys
  * ``tbl_roles`` + ``tbl_role_permissions``
      get_role_by_id, list_role_permissions_query,
      role_has_permission_query, find_role_by_name_in_org,
      list_roles_with_counts_in_org (the big composed query with
      correlated subqueries + ``array_agg``),
      insert_role, delete_role_row,
      bulk_insert_role_permissions, delete_role_permissions_for_role
  * Cross-module verifier
      count_active_members_for_role — used by the delete-role guard
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.permissions.models import Permission, Role, RolePermission
from src.app.core.users.models import OrganizationMember

# --- Permission registry ------------------------------------------------


async def get_permission_by_key(session: AsyncSession, key: str) -> Permission | None:
    """Single-row read by the unique ``key``."""
    result = await session.execute(select(Permission).where(Permission.key == key))
    return result.scalar_one_or_none()


async def list_all_permissions(
    session: AsyncSession,
    *,
    source: str | None = None,
) -> list[Permission]:
    """Global registry list — ordered by module then key for stable UI
    grouping. ``source`` filters to a single registration source
    (``"core"`` for Core CRM keys, ``"pack:<name>"`` for a specific
    pack); ``None`` returns everything (internal / diagnostics use)."""
    stmt = select(Permission).order_by(Permission.module.asc(), Permission.key.asc())
    if source is not None:
        stmt = stmt.where(Permission.source == source)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_permissions_by_keys(session: AsyncSession, keys: list[str]) -> list[Permission]:
    """Lookup multiple permissions by key. Used by the bulk-register
    flow's post-upsert re-read."""
    if not keys:
        return []
    result = await session.execute(select(Permission).where(Permission.key.in_(keys)))
    return list(result.scalars().all())


async def list_permission_keys_with_ids(session: AsyncSession, keys: list[str]) -> list[Row]:
    """Return ``[(id, key), ...]`` for the subset of ``keys`` that
    exist. Caller (``_resolve_permission_ids`` in service) compares
    against the input to surface 422 with the missing keys list."""
    if not keys:
        return []
    return list(
        (
            await session.execute(
                select(Permission.id, Permission.key).where(Permission.key.in_(keys))
            )
        ).all()
    )


async def upsert_permission_key(
    session: AsyncSession,
    *,
    key: str,
    module: str,
    source: str = "core",
    description: str | None = None,
) -> None:
    """``INSERT ... ON UPDATE`` on the unique ``key`` column — inserts a
    new row if the key is new, or updates ``source`` / ``module`` /
    ``description`` on an existing row. The source update is what lets
    the startup registration pass move a permission from ``core`` to
    ``pack:<name>`` after the 0230 migration lands (or vice-versa if a
    pack module is retired). Caller commits + re-reads via
    ``get_permission_by_key``."""
    stmt = pg_insert(Permission).values(
        key=key, module=module, source=source, description=description
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={
                "module": stmt.excluded.module,
                "source": stmt.excluded.source,
                "description": stmt.excluded.description,
            },
        )
    )


async def bulk_upsert_permission_keys(session: AsyncSession, rows: list[dict]) -> None:
    """Bulk ``INSERT ... ON UPDATE`` for a list of ``{key, module,
    source, description}`` dicts. Rows without ``source`` default to
    ``"core"`` for backwards-compat with callers pre-dating the source
    column (currently none — every registration path passes it
    explicitly). Caller commits."""
    if not rows:
        return
    normalised = [{**row, "source": row.get("source", "core")} for row in rows]
    stmt = pg_insert(Permission).values(normalised)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={
                "module": stmt.excluded.module,
                "source": stmt.excluded.source,
                "description": stmt.excluded.description,
            },
        )
    )


# --- Role + role_permissions --------------------------------------------


async def get_role_by_id(session: AsyncSession, role_id: uuid.UUID) -> Role | None:
    """Single-row read by PK (tenant-scoped via ORM filter)."""
    result = await session.execute(select(Role).where(Role.id == role_id))
    return result.scalar_one_or_none()


async def list_role_permissions_query(
    session: AsyncSession, role_id: uuid.UUID
) -> list[Permission]:
    """Every Permission row linked to ``role_id`` via
    ``tbl_role_permissions``, ordered by ``key``."""
    stmt = (
        select(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
        .order_by(Permission.key)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def role_has_permission_query(session: AsyncSession, *, role_id: uuid.UUID, key: str) -> bool:
    """Single-key existence check. Used by the row-level scope rules
    (e.g. the ``users.read`` gate that decides team-view vs
    personal-view on leads / walk-ins / dashboard)."""
    stmt = (
        select(func.count())
        .select_from(RolePermission)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(RolePermission.role_id == role_id, Permission.key == key)
    )
    return ((await session.execute(stmt)).scalar_one() or 0) > 0


async def find_role_by_name_in_org(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    name: str,
    exclude_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Return the role id (if any) whose name matches in this org.
    ``exclude_id`` lets update-role skip self-collisions."""
    stmt = select(Role.id).where(Role.org_id == org_id, Role.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Role.id != exclude_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_roles_with_counts_in_org(session: AsyncSession, *, org_id: uuid.UUID) -> list[Row]:
    """List the org's roles with permission + member counts and the
    full grant-set as ``permission_keys``.

    The three correlated subqueries (count, count, array_agg) keep the
    listing to a single round-trip; small N (typically 3–10 roles per
    org) so no need to denormalise.
    """
    perm_count = (
        select(func.count(RolePermission.permission_id))
        .where(RolePermission.role_id == Role.id)
        .correlate(Role)
        .scalar_subquery()
    )
    member_count = (
        select(func.count(OrganizationMember.id))
        .where(
            OrganizationMember.role_id == Role.id,
            OrganizationMember.is_active.is_(True),
        )
        .correlate(Role)
        .scalar_subquery()
    )
    perm_keys = (
        select(func.array_agg(Permission.key))
        .select_from(Permission)
        .join(
            RolePermission,
            RolePermission.permission_id == Permission.id,
        )
        .where(RolePermission.role_id == Role.id)
        .correlate(Role)
        .scalar_subquery()
    )
    stmt = (
        select(
            Role.id,
            Role.org_id,
            Role.name,
            Role.is_system,
            Role.created_at,
            perm_count.label("permission_count"),
            member_count.label("member_count"),
            perm_keys.label("permission_keys"),
        )
        .where(Role.org_id == org_id)
        .order_by(Role.is_system.desc(), Role.name.asc())
    )
    return list((await session.execute(stmt)).all())


def insert_role(session: AsyncSession, role: Role) -> None:
    """Register an already-constructed Role for INSERT."""
    session.add(role)


async def delete_role_row(session: AsyncSession, role: Role) -> None:
    """Mark a Role row for DELETE. Caller commits."""
    await session.execute(delete(Role).where(Role.id == role.id))


async def bulk_insert_role_permissions(
    session: AsyncSession,
    *,
    role_id: uuid.UUID,
    permission_ids: list[uuid.UUID],
) -> None:
    """Bulk insert ``(role_id, permission_id)`` rows with
    ``ON CONFLICT DO NOTHING`` on the composite unique constraint.
    Caller commits."""
    if not permission_ids:
        return
    await session.execute(
        pg_insert(RolePermission)
        .values([{"role_id": role_id, "permission_id": pid} for pid in permission_ids])
        .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
    )


async def delete_role_permissions_for_role(session: AsyncSession, role_id: uuid.UUID) -> None:
    """DELETE every ``tbl_role_permissions`` row for ``role_id``.
    Used by the update-role replace-all flow + the delete-role
    cascade."""
    await session.execute(delete(RolePermission).where(RolePermission.role_id == role_id))


# --- Cross-module verifier ----------------------------------------------


async def count_active_members_for_role(session: AsyncSession, role_id: uuid.UUID) -> int:
    """Number of active OrganizationMember rows referencing ``role_id``.
    Used by the delete-role guard to refuse 409 when anyone still
    holds the role."""
    result = await session.execute(
        select(func.count(OrganizationMember.id)).where(
            OrganizationMember.role_id == role_id,
            OrganizationMember.is_active.is_(True),
        )
    )
    return int(result.scalar_one() or 0)


async def list_user_ids_with_permission(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    permission_key: str,
) -> list[uuid.UUID]:
    """All active user ids in ``org_id`` whose role grants ``permission_key``.

    Powers cross-module fan-out notifications (e.g. "a template was
    submitted for review — notify everyone who can approve it").
    Returns an empty list when nobody holds the key — the notifier
    should handle that gracefully (usually a no-op)."""
    stmt = (
        select(OrganizationMember.user_id)
        .join(Role, Role.id == OrganizationMember.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(
            OrganizationMember.org_id == org_id,
            OrganizationMember.is_active.is_(True),
            Permission.key == permission_key,
        )
        .distinct()
    )
    result = await session.execute(stmt)
    return [row for row in result.scalars().all()]


__all__ = [
    "bulk_insert_role_permissions",
    "bulk_upsert_permission_keys",
    "count_active_members_for_role",
    "delete_role_permissions_for_role",
    "delete_role_row",
    "find_role_by_name_in_org",
    "get_permission_by_key",
    "get_role_by_id",
    "insert_role",
    "list_all_permissions",
    "list_user_ids_with_permission",
    "list_permission_keys_with_ids",
    "list_permissions_by_keys",
    "list_role_permissions_query",
    "list_roles_with_counts_in_org",
    "role_has_permission_query",
    "upsert_permission_key",
]
