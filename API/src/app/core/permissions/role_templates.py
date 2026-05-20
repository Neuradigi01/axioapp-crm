"""Role-template registry + installer.

Vertical-neutral defaults that get stamped into a freshly-created org
(by the signup flow in `core.auth.service.register_with_new_org`).
Owner / Admin / Employee are all auto-instantiated on org creation
(option A decision, locked 2026-05-20). All three land as ordinary
rows in `roles` — the Owner row carries `is_system=true` so it's
locked, Admin and Employee are `is_system=false` and Owner-editable.

`permission_keys` lists are resolved against the live `permissions`
registry at install time. Unknown keys raise — better to break the
install than silently miss a grant.

The seeded demo orgs (`demo`, `core-demo`) use their own hand-rolled
inserts in `scripts/seed_*.py`. The template registry here is the
canonical source for *self-signup* orgs.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.permissions.models import Permission, Role, RolePermission


class UnknownPermissionKey(RuntimeError):
    """A template references a key not present in the live registry."""


class OwnerAlreadyExists(RuntimeError):
    """Attempted to install a second Owner role into an org."""


# Sentinel meaning "every permission key currently registered." The
# installer resolves it by reading the full `permissions` table at
# install time — newly-registered modules' keys are automatically
# granted to Owner on the next org signup without code changes here.
ALL_KEYS = "__all__"


_ADMIN_KEYS: list[str] = [
    "users.read", "users.write",
    "roles.read", "roles.write",
    "audit.read",
    "custom_fields.read", "custom_fields.write",
    "settings.read", "settings.write",
    "contacts.read", "contacts.write",
    "leads.read", "leads.write",
    "appointments.read", "appointments.write",
    "walkins.read", "walkins.write",
    "walk_ins.read", "walk_ins.write",
    "catalog.read", "catalog.write",
    "conversations.read", "conversations.write",
    "calls.read", "calls.write", "calls.outcomes.manage",
    "reviews.read", "reviews.write",
    "campaigns.read", "campaigns.write", "campaigns.send",
    "tasks.read", "tasks.write",
    "pipelines.read", "pipelines.manage", "pipelines.write",
    "activities.read", "activities.write",
    "staff.read", "staff.write",
    "attendance.write",
]


_EMPLOYEE_KEYS: list[str] = [
    "contacts.read", "contacts.write",
    "leads.read", "leads.write",
    "activities.read", "activities.write",
    "tasks.read", "tasks.write",
    "appointments.read", "appointments.write",
    "walkins.read", "walkins.write",
    "walk_ins.read", "walk_ins.write",
    "catalog.read",
    "conversations.read", "conversations.write",
    "calls.read", "calls.write",
    "pipelines.read",
]


@dataclass(frozen=True)
class RoleTemplate:
    key: str
    name: str
    is_system: bool
    is_owner: bool
    permission_keys: list[str] | str
    description: str
    auto_install_on_org_create: bool = True
    extra_keys: list[str] = field(default_factory=list)


ROLE_TEMPLATES: dict[str, RoleTemplate] = {
    "owner": RoleTemplate(
        key="owner",
        name="Owner",
        is_system=True,
        is_owner=True,
        permission_keys=ALL_KEYS,
        description="Full system access. Cannot be edited or deleted.",
    ),
    "admin": RoleTemplate(
        key="admin",
        name="Admin",
        is_system=False,
        is_owner=False,
        permission_keys=_ADMIN_KEYS,
        description=(
            "Manage users, leads, contacts, deals; view reports; "
            "configure settings. No billing or ownership transfer."
        ),
    ),
    "employee": RoleTemplate(
        key="employee",
        name="Employee",
        is_system=False,
        is_owner=False,
        permission_keys=_EMPLOYEE_KEYS,
        description=(
            "View assigned leads; manage own tasks/contacts/deals; "
            "limited reports. No user management."
        ),
    ),
}


async def _resolve_keys(
    session: AsyncSession, template: RoleTemplate
) -> list[uuid.UUID]:
    """Map a template's permission_keys list (or ALL_KEYS sentinel) to ids."""
    if template.permission_keys == ALL_KEYS:
        rows = (await session.execute(select(Permission.id))).all()
        return [r.id for r in rows]

    keys = list(template.permission_keys)
    if not keys:
        return []
    rows = (
        await session.execute(
            select(Permission.id, Permission.key).where(Permission.key.in_(keys))
        )
    ).all()
    found = {r.key: r.id for r in rows}
    missing = sorted(set(keys) - set(found))
    if missing:
        raise UnknownPermissionKey(
            f"template {template.key!r} references unregistered keys: "
            f"{', '.join(missing)}"
        )
    return [found[k] for k in keys]


async def _install_one(
    session: AsyncSession, *, org_id: uuid.UUID, template: RoleTemplate
) -> Role:
    if template.is_owner:
        existing_owner = (
            await session.execute(
                select(Role.id).where(
                    Role.org_id == org_id, Role.is_system.is_(True), Role.name == "Owner"
                )
            )
        ).scalar_one_or_none()
        if existing_owner is not None:
            raise OwnerAlreadyExists(
                f"org {org_id} already has an Owner role"
            )

    existing = (
        await session.execute(
            select(Role).where(Role.org_id == org_id, Role.name == template.name)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    role = Role(org_id=org_id, name=template.name, is_system=template.is_system)
    session.add(role)
    await session.flush()

    permission_ids = await _resolve_keys(session, template)
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

    return role


async def install(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_keys: list[str] | None = None,
) -> dict[str, Role]:
    """Install the named templates into the given org.

    `template_keys=None` installs every template with
    `auto_install_on_org_create=True` (Owner + Admin + Employee for the
    default registry). Idempotent — calling again returns the existing
    rows without writing. All inserts run on the caller's session; the
    caller manages the outer transaction.

    Returns a `{template_key: Role}` map so the signup flow can pluck
    out the Owner row to assign on `tbl_organization_members.role_id`.
    """
    if template_keys is None:
        template_keys = [
            k for k, t in ROLE_TEMPLATES.items() if t.auto_install_on_org_create
        ]

    installed: dict[str, Role] = {}
    for key in template_keys:
        template = ROLE_TEMPLATES.get(key)
        if template is None:
            raise UnknownPermissionKey(f"unknown role template: {key!r}")
        installed[key] = await _install_one(
            session, org_id=org_id, template=template
        )
    return installed
