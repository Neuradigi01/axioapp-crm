"""Seed one admin role, the baseline permissions, and one admin user.

Idempotent. The role + user use fixed UUIDs so re-execution is a no-op
on those rows. Permissions are resolved by `key` after upsert — that
matters because the module-registry startup hook (in `main.py`'s
lifespan) may have already inserted some of these keys with auto-
generated UUIDs, so a hardcoded-ID insert would collide on the unique
`key` constraint.

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

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.dev.models import DemoCredential
from src.app.core.permissions.models import Permission, Role, RolePermission
from src.app.core.users.models import User
from src.app.scripts.seed_demo_org import DEMO_ORG_ID
from src.app.shared.context import RequestContext, set_context
from src.app.shared.db import async_session
from src.app.shared.security.password import hash_password


ADMIN_ROLE_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
ADMIN_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000011")

PERMISSIONS = [
    ("users.read",          "Read users",           "users"),
    ("users.write",         "Manage users",         "users"),
    ("roles.read",          "Read roles",           "roles"),
    ("roles.write",         "Manage roles",         "roles"),
    ("audit.read",          "Read audit logs",      "audit"),
    ("custom_fields.read",  "Read custom fields",   "custom_fields"),
    ("custom_fields.write", "Manage custom fields", "custom_fields"),
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

        # 2) Baseline permissions. Resolve by `key` because some keys
        # may already exist (registered by the module-registry startup
        # hook) with a different id.
        await session.execute(
            pg_insert(Permission)
            .values([
                {"key": key, "description": desc, "module": module}
                for (key, desc, module) in PERMISSIONS
            ])
            .on_conflict_do_nothing(index_elements=["key"])
        )

        # Look up the actual ids that the DB ended up holding.
        keys = [key for (key, _, _) in PERMISSIONS]
        rows = (
            await session.execute(
                select(Permission.id, Permission.key).where(Permission.key.in_(keys))
            )
        ).all()
        permission_ids = [r.id for r in rows]

        # 3) admin role gets every baseline permission.
        await session.execute(
            pg_insert(RolePermission)
            .values([
                {"role_id": ADMIN_ROLE_ID, "permission_id": pid}
                for pid in permission_ids
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
                is_demo=True,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        # If the row already existed from a pre-`is_demo` seed, flip
        # the flag on the existing row so the dev-only demo-logins
        # endpoint surfaces it.
        await session.execute(
            User.__table__.update()
            .where(User.id == ADMIN_USER_ID)
            .values(is_demo=True)
        )

        # 5) Demo credential row backing /api/v1/_dev/demo-logins.
        await session.execute(
            pg_insert(DemoCredential)
            .values(
                user_id=ADMIN_USER_ID,
                plain_password=ADMIN_PASSWORD,
                label="Furniture CRM — Admin",
            )
            .on_conflict_do_nothing(index_elements=["user_id"])
        )

        await session.commit()

    print(f"Admin role:  {ADMIN_ROLE_ID}")
    print(f"Admin user:  {ADMIN_USER_ID} ({ADMIN_EMAIL})")
    print(f"Permissions: {', '.join(key for (key, _, _) in PERMISSIONS)}")


if __name__ == "__main__":
    asyncio.run(seed_admin_user())
