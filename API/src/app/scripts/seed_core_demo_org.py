"""Seed a second demo org without the furniture pack.

Used by the Phase 4.5 mini-phase ("Demo Roles Setup") to demonstrate
the layered architecture: same code base, two orgs side-by-side, one
with the furniture pack (sidebar shows Inventory / Custom Orders /
Field Ops / Billing & POS) and one without (sidebar shows only
Layer-1 / core modules).

Inserts:
  - `core-demo` organization (pack_id='core' — a non-furniture marker;
    `organizations.pack_id` is NOT NULL so we can't use NULL).
  - Three system roles: Admin / Owner / Employee.
  - Role permissions: each role gets a curated subset of EXISTING
    permission keys. We resolve by `key` because the module registry
    populated those rows at app startup with auto-generated UUIDs.
  - Three users (one per role) with hashed passwords.
  - One `org_settings` row (via the standard `get_or_create` helper).

Idempotent — re-running the script produces zero writes. All inserts
use fixed UUIDs + `ON CONFLICT DO NOTHING`.

Usage:
    docker exec template_api-api-1 python -m src.app.scripts.seed_core_demo_org
"""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.permissions.models import Permission, Role, RolePermission
from src.app.core.settings.service import get_or_create as get_or_create_settings
from src.app.core.tenants.models import Organization
from src.app.core.users.models import User
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.db import async_session
from src.app.shared.security.password import hash_password


# Fixed UUIDs keep re-runs idempotent.
CORE_DEMO_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

ADMIN_ROLE_ID = uuid.UUID("00000000-0000-0000-0000-000000000020")
OWNER_ROLE_ID = uuid.UUID("00000000-0000-0000-0000-000000000021")
EMPLOYEE_ROLE_ID = uuid.UUID("00000000-0000-0000-0000-000000000022")

ADMIN_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000023")
OWNER_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000024")
EMPLOYEE_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000025")


CORE_DEMO_ORG = {
    "id": CORE_DEMO_ORG_ID,
    "name": "Core CRM Demo",
    "slug": "core-demo",
    # `organizations.pack_id` is NOT NULL with server_default='furniture'.
    # We use 'core' as the marker for "no vertical pack installed". The
    # value is informational — no code branches on it; the absence of
    # pack-installed rows (no fp_* permissions on this org's roles) is
    # what actually makes the sidebar show core-only.
    "pack_id": "core",
    "pack_version": None,
    "currency": "INR",
    "tax_rate": Decimal("0.00"),
    "timezone": "Asia/Kolkata",
}


# --- Permission sets ----------------------------------------------------
#
# Every key MUST already exist in the `permissions` table (populated
# by the module-registry startup hook). We do not create permissions
# here; we just grant existing ones.


_ADMIN_KEYS: list[str] = [
    "users.read", "users.write",
    "roles.read", "roles.write",
    "audit.read",
    "custom_fields.read", "custom_fields.write",
    "settings.read", "settings.write",
    "contacts.read", "contacts.write",
    "leads.read", "leads.write",
    "appointments.read", "appointments.write",
    # Walk-ins: sidebar gates on `walkins.*` (module descriptor), but the
    # furniture pack.yaml emits `walk_ins.*` keys too. Grant both so this
    # role works against either lookup path.
    "walkins.read", "walkins.write",
    "walk_ins.read", "walk_ins.write",
    "catalog.read", "catalog.write",
    "conversations.read", "conversations.write",
    "calls.read", "calls.write", "calls.outcomes.manage",
    "reviews.read", "reviews.write",
    "campaigns.read", "campaigns.write", "campaigns.send",
    "tasks.read", "tasks.write",
    # Pipelines: descriptor declares `pipelines.manage` (not `.write`),
    # which is the sidebar gate. Grant both forms.
    "pipelines.read", "pipelines.manage", "pipelines.write",
    "activities.read", "activities.write",
    "staff.read", "staff.write",
    "attendance.write",
    "billing.read", "billing.write", "billing.refund",
]

# Owner = Admin minus team / role config writes and refunds.
_OWNER_KEYS: list[str] = [
    k for k in _ADMIN_KEYS
    if k not in {"users.write", "roles.write", "billing.refund"}
]

# Employee = day-to-day workers. No settings, no team management, no
# billing write, no refunds.
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
    "billing.read",
    "pipelines.read",
]


_ROLES: list[tuple[uuid.UUID, str, list[str]]] = [
    (ADMIN_ROLE_ID, "Admin", _ADMIN_KEYS),
    (OWNER_ROLE_ID, "Owner", _OWNER_KEYS),
    (EMPLOYEE_ROLE_ID, "Employee", _EMPLOYEE_KEYS),
]


_USERS: list[tuple[uuid.UUID, str, str, str, uuid.UUID]] = [
    (ADMIN_USER_ID,    "admin@core-demo.local",    "Admin@123",    "Core Demo Admin",    ADMIN_ROLE_ID),
    (OWNER_USER_ID,    "owner@core-demo.local",    "Owner@123",    "Core Demo Owner",    OWNER_ROLE_ID),
    (EMPLOYEE_USER_ID, "employee@core-demo.local", "Employee@123", "Core Demo Employee", EMPLOYEE_ROLE_ID),
]


async def seed_core_demo_org() -> None:
    # Establish tenant context so RLS lets us insert tenant-scoped rows.
    token = set_context(RequestContext(org_id=CORE_DEMO_ORG_ID))
    try:
        async with async_session() as session:
            # 1) Organization.
            await session.execute(
                pg_insert(Organization)
                .values(**CORE_DEMO_ORG)
                .on_conflict_do_nothing(index_elements=["id"])
            )

            # 2) Roles.
            await session.execute(
                pg_insert(Role)
                .values([
                    {
                        "id": role_id,
                        "org_id": CORE_DEMO_ORG_ID,
                        "name": name,
                        "is_system": True,
                    }
                    for (role_id, name, _) in _ROLES
                ])
                .on_conflict_do_nothing(index_elements=["id"])
            )

            # 3) Resolve permission ids by key — registry-managed.
            all_keys = sorted({k for (_, _, keys) in _ROLES for k in keys})
            rows = (
                await session.execute(
                    select(Permission.id, Permission.key).where(
                        Permission.key.in_(all_keys)
                    )
                )
            ).all()
            id_by_key: dict[str, uuid.UUID] = {r.key: r.id for r in rows}

            missing = sorted(set(all_keys) - set(id_by_key))
            if missing:
                raise RuntimeError(
                    "Missing permission keys (registry not populated?): "
                    + ", ".join(missing)
                )

            # 4) Role permissions.
            role_perm_rows: list[dict[str, uuid.UUID]] = []
            for (role_id, _, keys) in _ROLES:
                for k in keys:
                    role_perm_rows.append(
                        {"role_id": role_id, "permission_id": id_by_key[k]}
                    )
            await session.execute(
                pg_insert(RolePermission)
                .values(role_perm_rows)
                .on_conflict_do_nothing(
                    index_elements=["role_id", "permission_id"]
                )
            )

            # 5) Users.
            await session.execute(
                pg_insert(User)
                .values([
                    {
                        "id": user_id,
                        "org_id": CORE_DEMO_ORG_ID,
                        "email": email,
                        "password_hash": hash_password(password),
                        "full_name": full_name,
                        "phone": None,
                        "role_id": role_id,
                        "is_active": True,
                    }
                    for (user_id, email, password, full_name, role_id) in _USERS
                ])
                .on_conflict_do_nothing(index_elements=["id"])
            )

            await session.commit()

            # 6) Org settings row (idempotent helper — creates on first call).
            await get_or_create_settings(session, org_id=CORE_DEMO_ORG_ID)
    finally:
        reset_context(token)

    print()
    print(f"Org:    {CORE_DEMO_ORG_ID}  slug='core-demo'  pack_id='core'")
    print("Roles:")
    for (role_id, name, keys) in _ROLES:
        print(f"  {name:10s} {role_id}  perms={len(keys)}")
    print("Users:")
    for (user_id, email, password, _, _) in _USERS:
        print(f"  {email:30s} {password}  id={user_id}")
    print()
    print("Done. Login via /accounts/login with org_slug='core-demo'.")


if __name__ == "__main__":
    asyncio.run(seed_core_demo_org())
