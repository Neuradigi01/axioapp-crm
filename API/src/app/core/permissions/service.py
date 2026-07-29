"""Service layer for roles and permissions.

Thin functions that wrap the permissions DAL against the `Role`,
`Permission`, `RolePermission` models. The auto-tenant filter from
`src.app.shared.orm` scopes `Role` selects by `org_id` when a
`RequestContext` is set; `Permission` is global by design.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.permissions import data_access as _da
from src.app.core.permissions.models import Permission, Role
from src.app.core.permissions.schemas import RoleCreate, RoleUpdate
from src.app.core.users import service as users_service
from src.app.shared.audit import log_entity_change


async def get_role_by_id(session: AsyncSession, role_id: uuid.UUID) -> Role | None:
    return await _da.get_role_by_id(session, role_id)


async def list_permissions_for_role(session: AsyncSession, role_id: uuid.UUID) -> list[Permission]:
    """Return every Permission row linked to `role_id` via `role_permissions`."""
    return await _da.list_role_permissions_query(session, role_id)


async def template_keys_for_role(session: AsyncSession, role_id: uuid.UUID) -> set[str]:
    """Return the permission keys defined for this role in its role
    template, if any.

    System roles (Owner) are locked to their template; user-editable
    template roles (Admin, Employee, Sales Manager, Support Agent) are
    matched by ``name`` — new keys added to a template later still work
    for existing installs without a manual re-sync. Only additive: we
    never subtract from the DB grants via the template (respects user
    edits to Admin/Employee).

    Returns an empty set for custom roles or unknown template names.
    """
    role = await _da.get_role_by_id(session, role_id)
    if role is None:
        return set()
    # Local import to avoid a circular dep at module load
    # (role_templates → service → role_templates is otherwise
    # possible if new helpers get added here).
    from src.app.core.permissions.role_templates import ROLE_TEMPLATES

    for template in ROLE_TEMPLATES.values():
        if template.name == role.name and (
            template.is_system == role.is_system or template.is_owner
        ):
            keys = template.permission_keys
            if isinstance(keys, str):  # "*" wildcard placeholder
                return set()
            return set(keys)
    return set()


async def role_has_permission(session: AsyncSession, role_id: uuid.UUID, key: str) -> bool:
    """`True` iff the role has been granted `key` — either directly in
    the DB or via the role's matching template. Template fallback keeps
    Owner (and Admin/Employee where unedited) automatically current with
    newly-added permission keys without a manual re-sync per org."""
    if await _da.role_has_permission_query(session, role_id=role_id, key=key):
        return True
    return key in await template_keys_for_role(session, role_id)


async def register_permission(
    session: AsyncSession,
    *,
    key: str,
    module: str,
    description: str | None = None,
) -> Permission:
    """Idempotently insert a permission row into the global registry."""
    await _da.upsert_permission_key(session, key=key, module=module, description=description)
    result = await _da.get_permission_by_key(session, key)
    assert result is not None  # upsert just ensured the row exists
    return result


async def register_permissions(session: AsyncSession, keys: list[str]) -> list[Permission]:
    """Bulk-upsert permission keys into the global registry."""
    if not keys:
        return []

    rows = []
    for key in keys:
        module_prefix, _, _ = key.partition(".")
        if not module_prefix:
            raise ValueError(f"permission key {key!r} must be '<module>.<action>'")
        rows.append({"key": key, "module": module_prefix, "description": None})

    await _da.bulk_upsert_permission_keys(session, rows)
    await session.commit()

    return await _da.list_permissions_by_keys(session, keys)


# --- admin reads (drive the management UI) -------------------------------


async def list_roles_in_org(session: AsyncSession, *, org_id: uuid.UUID) -> list[dict]:
    """List the org's roles with permission + member counts."""
    rows = await _da.list_roles_with_counts_in_org(session, org_id=org_id)
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
    """Global registry list — ordered by module then key."""
    return await _da.list_all_permissions(session)


# --- admin writes (create / update / delete custom roles) ---------------


async def _resolve_permission_ids(session: AsyncSession, keys: list[str]) -> list[uuid.UUID]:
    """Map permission keys → ids. Raises 422 for unknown keys."""
    if not keys:
        return []
    rows = await _da.list_permission_keys_with_ids(session, keys)
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
    """Create a custom role + grant the chosen permission keys."""
    permission_ids = await _resolve_permission_ids(session, payload.permission_keys)

    existing = await _da.find_role_by_name_in_org(session, org_id=org_id, name=payload.name)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"role {payload.name!r} already exists in this org",
        )

    role = Role(org_id=org_id, name=payload.name, is_system=False)
    _da.insert_role(session, role)
    await session.flush()

    await _da.bulk_insert_role_permissions(session, role_id=role.id, permission_ids=permission_ids)

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
    """Rename a role and/or replace its permission grants."""
    role = await users_service.get_role_by_id_in_org(session, role_id=role_id, org_id=org_id)
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
        "permission_keys": [p.key for p in await list_permissions_for_role(session, role.id)],
    }

    if "name" in changes and changes["name"] is not None:
        clash = await _da.find_role_by_name_in_org(
            session,
            org_id=org_id,
            name=changes["name"],
            exclude_id=role.id,
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"role {changes['name']!r} already exists in this org",
            )
        role.name = changes["name"]

    if "permission_keys" in changes and changes["permission_keys"] is not None:
        new_ids = await _resolve_permission_ids(session, changes["permission_keys"])
        # Replace-all semantics: wipe existing grants, insert new set.
        await _da.delete_role_permissions_for_role(session, role.id)
        await _da.bulk_insert_role_permissions(session, role_id=role.id, permission_ids=new_ids)

    await session.commit()
    await session.refresh(role)

    after = {
        "name": role.name,
        "permission_keys": [p.key for p in await list_permissions_for_role(session, role.id)],
    }
    await log_entity_change(
        action="roles.updated",
        entity_type="role",
        entity_id=role.id,
        before=before,
        after=after,
    )
    return role


async def install_role_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_key: str,
) -> Role:
    """Install a single role template into the org. Owns the
    transaction so the router stays thin."""
    from src.app.core.permissions import role_templates

    result = await role_templates.install(session, org_id=org_id, template_keys=[template_key])
    await session.commit()
    role = result[template_key]
    await session.refresh(role)
    return role


async def delete_role(
    session: AsyncSession,
    *,
    role_id: uuid.UUID,
    org_id: uuid.UUID,
) -> None:
    """Delete a custom role. 409 if anyone currently has it."""
    role = await users_service.get_role_by_id_in_org(session, role_id=role_id, org_id=org_id)
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

    member_count = await _da.count_active_members_for_role(session, role.id)
    if member_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"cannot delete role: {member_count} active member(s) still "
                "reference it. Reassign them first."
            ),
        )

    snapshot_name = role.name
    await _da.delete_role_permissions_for_role(session, role.id)
    await _da.delete_role_row(session, role)
    await session.commit()

    await log_entity_change(
        action="roles.deleted",
        entity_type="role",
        entity_id=role_id,
        before={"name": snapshot_name},
    )
