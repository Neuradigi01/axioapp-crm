"""Service layer for roles and permissions.

Thin functions that wrap `Repository` / `select` against the
`Role`, `Permission`, `RolePermission` models. The auto-tenant
filter from `src.app.shared.orm` scopes `Role` selects by `org_id`
when a `RequestContext` is set; `Permission` is global by design.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.users import data_access
from src.app.shared.audit import log_entity_change
from src.app.core.permissions.models import Permission, Role, RolePermission
from src.app.core.permissions.schemas import RoleCreate, RoleUpdate
from src.app.core.users.models import OrganizationMember


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


async def role_has_permission(
    session: AsyncSession, role_id: uuid.UUID, key: str
) -> bool:
    """`True` iff the role has been granted `key`.

    Single-key existence check used by row-level scope rules (e.g. the
    `users.read` gate that decides "team view vs personal view" on the
    leads / walk-ins / dashboard endpoints). One query — cheaper than
    materialising the full permission set when only one key matters.
    """
    stmt = (
        select(func.count())
        .select_from(RolePermission)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(RolePermission.role_id == role_id, Permission.key == key)
    )
    return ((await session.execute(stmt)).scalar_one() or 0) > 0


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


async def register_permissions(
    session: AsyncSession, keys: list[str]
) -> list[Permission]:
    """Bulk-upsert permission keys into the global registry.

    Each `key` must be `"<module>.<action>"` — the prefix is used to
    populate the `module` column. Called from the module-registry
    startup hook for every `MODULE.permissions` list.
    """
    if not keys:
        return []

    rows = []
    for key in keys:
        module_prefix, _, _ = key.partition(".")
        if not module_prefix:
            raise ValueError(
                f"permission key {key!r} must be '<module>.<action>'"
            )
        rows.append({"key": key, "module": module_prefix, "description": None})

    await session.execute(
        pg_insert(Permission).values(rows).on_conflict_do_nothing(index_elements=["key"])
    )
    await session.commit()

    result = await session.execute(
        select(Permission).where(Permission.key.in_(keys))
    )
    return list(result.scalars().all())


# --- admin reads (drive the management UI) -------------------------------


async def list_roles_in_org(
    session: AsyncSession, *, org_id: uuid.UUID
) -> list[dict]:
    """List the org's roles with permission + member counts.

    Returns plain dicts suitable for `RoleWithCounts.model_validate`.
    The counts are computed via two correlated subqueries — small N
    here (typically 3–10 roles per org) so no need to denormalise.
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
    # array_agg gives us the grant set in a single round-trip; the
    # role-editor pre-checks its boxes off this list. NULL when the
    # role has no grants — we coalesce to an empty array client-side.
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
    rows = (await session.execute(stmt)).all()
    return [
        {
            "id": r.id,
            "org_id": r.org_id,
            "name": r.name,
            "is_system": r.is_system,
            "created_at": r.created_at,
            "permission_count": r.permission_count,
            "member_count": r.member_count,
            "permission_keys": list(r.permission_keys or []),
        }
        for r in rows
    ]


async def list_all_permissions(session: AsyncSession) -> list[Permission]:
    """Global registry list — ordered by module then key for stable UI grouping."""
    result = await session.execute(
        select(Permission).order_by(Permission.module.asc(), Permission.key.asc())
    )
    return list(result.scalars().all())


# --- admin writes (create / update / delete custom roles) ---------------


async def _resolve_permission_ids(
    session: AsyncSession, keys: list[str]
) -> list[uuid.UUID]:
    """Map permission keys → ids. Raises 422 for unknown keys."""
    if not keys:
        return []
    rows = (
        await session.execute(
            select(Permission.id, Permission.key).where(Permission.key.in_(keys))
        )
    ).all()
    found_by_key = {r.key: r.id for r in rows}
    missing = sorted(set(keys) - set(found_by_key))
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown permission keys: {', '.join(missing)}",
        )
    return [found_by_key[k] for k in keys]


async def create_role(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: RoleCreate,
) -> Role:
    """Create a custom role + grant the chosen permission keys.

    Tenant uniqueness is enforced by `uq_roles_org_id_name`; we surface
    a 409 if a role with the same name already exists in this org.
    """
    permission_ids = await _resolve_permission_ids(session, payload.permission_keys)

    existing = (
        await session.execute(
            select(Role.id).where(
                Role.org_id == org_id, Role.name == payload.name
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"role {payload.name!r} already exists in this org",
        )

    role = Role(org_id=org_id, name=payload.name, is_system=False)
    session.add(role)
    await session.flush()

    if permission_ids:
        await session.execute(
            pg_insert(RolePermission)
            .values(
                [
                    {"role_id": role.id, "permission_id": pid}
                    for pid in permission_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
        )

    await session.commit()
    await session.refresh(role)

    await log_entity_change(
        action="roles.created",
        entity_type="role",
        entity_id=role.id,
        after={
            "name": role.name,
            "permission_keys": payload.permission_keys,
        },
    )
    return role


async def update_role(
    session: AsyncSession,
    *,
    role_id: uuid.UUID,
    org_id: uuid.UUID,
    payload: RoleUpdate,
) -> Role:
    """Rename a role and/or replace its permission grants.

    Refuses to touch `is_system=true` rows — those are seeded by the
    pack manifest or core seeds and must stay stable. Admins create
    custom roles instead of editing the system ones.
    """
    role = await data_access.get_role_by_id_in_org(
        session, role_id=role_id, org_id=org_id
    )
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"role {role_id} not found in this org",
        )
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="cannot edit a system role; create a custom role instead",
        )

    changes = payload.model_dump(exclude_unset=True)
    before = {
        "name": role.name,
        "permission_keys": [
            p.key for p in await list_permissions_for_role(session, role.id)
        ],
    }

    if "name" in changes and changes["name"] is not None:
        # Uniqueness check within the org.
        clash = (
            await session.execute(
                select(Role.id).where(
                    Role.org_id == org_id,
                    Role.name == changes["name"],
                    Role.id != role.id,
                )
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"role {changes['name']!r} already exists in this org",
            )
        role.name = changes["name"]

    if "permission_keys" in changes and changes["permission_keys"] is not None:
        new_ids = await _resolve_permission_ids(session, changes["permission_keys"])
        # Replace-all semantics: wipe existing grants, insert new set.
        await session.execute(
            delete(RolePermission).where(RolePermission.role_id == role.id)
        )
        if new_ids:
            await session.execute(
                pg_insert(RolePermission).values(
                    [{"role_id": role.id, "permission_id": pid} for pid in new_ids]
                )
            )

    await session.commit()
    await session.refresh(role)

    after = {
        "name": role.name,
        "permission_keys": [
            p.key for p in await list_permissions_for_role(session, role.id)
        ],
    }
    await log_entity_change(
        action="roles.updated",
        entity_type="role",
        entity_id=role.id,
        before=before,
        after=after,
    )
    return role


async def delete_role(
    session: AsyncSession,
    *,
    role_id: uuid.UUID,
    org_id: uuid.UUID,
) -> None:
    """Delete a custom role. 409 if anyone currently has it."""
    role = await data_access.get_role_by_id_in_org(
        session, role_id=role_id, org_id=org_id
    )
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"role {role_id} not found in this org",
        )
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="cannot delete a system role",
        )

    member_count = (
        await session.execute(
            select(func.count(OrganizationMember.id)).where(
                OrganizationMember.role_id == role.id,
                OrganizationMember.is_active.is_(True),
            )
        )
    ).scalar_one()
    if member_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"cannot delete role: {member_count} active member(s) still "
                "reference it. Reassign them first."
            ),
        )

    snapshot_name = role.name
    await session.execute(
        delete(RolePermission).where(RolePermission.role_id == role.id)
    )
    await session.execute(delete(Role).where(Role.id == role.id))
    await session.commit()

    await log_entity_change(
        action="roles.deleted",
        entity_type="role",
        entity_id=role_id,
        before={"name": snapshot_name},
    )
