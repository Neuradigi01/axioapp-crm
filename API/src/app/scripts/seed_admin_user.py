"""Seed one admin role, four permissions, and one admin user.

Idempotent — safe to re-run. Uses fixed UUIDs so re-execution is a
no-op (UPSERT with `ON CONFLICT DO NOTHING`).

Tenant context: the seed sets `RequestContext.org_id` to the demo org
id before opening its session so the DB session lifecycle hook in
`src.app.shared.db` issues `set_config('app.org_id', ...)` for the
transaction — required when running against a non-owner role in
production (a no-op against the dev owner role, but cheap to do).

Usage:
    python -m src.app.scripts.seed_admin_user
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.permissions.models import Permission, Role, RolePermission
from src.app.core.users.models import User
from src.app.scripts.seed_demo_org import DEMO_ORG_ID
from src.app.shared.context import RequestContext, set_context
from src.app.shared.db import async_session
from src.app.shared.security.password import hash_password


ADMIN_ROLE_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
ADMIN_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000011")

PERMISSIONS = [
    (uuid.UUID("00000000-0000-0000-0000-000000000020"), "users.read",  "Read users",   "users"),
    (uuid.UUID("00000000-0000-0000-0000-000000000021"), "users.write", "Manage users", "users"),
    (uuid.UUID("00000000-0000-0000-0000-000000000022"), "roles.read",  "Read roles",   "roles"),
    (uuid.UUID("00000000-0000-0000-0000-000000000023"), "roles.write", "Manage roles", "roles"),
]

ADMIN_EMAIL = "admin@demo.local"
ADMIN_PASSWORD = "Admin@123"
ADMIN_FULL_NAME = "Demo Admin"


async def seed_admin_user() -> None:
    set_context(RequestContext(org_id=DEMO_ORG_ID))

    async with async_session() as session:
        # 1) admin role (tenant-scoped on demo org).
        await session.execute(
            pg_insert(Role)
            .values(
                id=ADMIN_ROLE_ID,
                org_id=DEMO_ORG_ID,
                name="admin",
                is_system=True,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )

        # 2) four global permissions.
        await session.execute(
            pg_insert(Permission)
            .values([
                {"id": pid, "key": key, "description": desc, "module": module}
                for (pid, key, desc, module) in PERMISSIONS
            ])
            .on_conflict_do_nothing(index_elements=["id"])
        )

        # 3) admin role gets every permission (4 role_permission rows).
        await session.execute(
            pg_insert(RolePermission)
            .values([
                {"role_id": ADMIN_ROLE_ID, "permission_id": pid}
                for (pid, _, _, _) in PERMISSIONS
            ])
            .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
        )

        # 4) admin user. Hash is computed at seed time so reruns produce
        # different hashes but the row already exists → DO NOTHING.
        await session.execute(
            pg_insert(User)
            .values(
                id=ADMIN_USER_ID,
                org_id=DEMO_ORG_ID,
                email=ADMIN_EMAIL,
                password_hash=hash_password(ADMIN_PASSWORD),
                full_name=ADMIN_FULL_NAME,
                phone=None,
                role_id=ADMIN_ROLE_ID,
                is_active=True,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )

        await session.commit()

    print(f"Admin role:  {ADMIN_ROLE_ID}")
    print(f"Admin user:  {ADMIN_USER_ID} ({ADMIN_EMAIL})")
    print(f"Permissions: {', '.join(key for _, key, _, _ in PERMISSIONS)}")


if __name__ == "__main__":
    asyncio.run(seed_admin_user())
