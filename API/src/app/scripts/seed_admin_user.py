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

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.dev.models import DemoCredential
from src.app.core.permissions.models import Permission, Role, RolePermission
from src.app.core.users.models import OrganizationMember, User, UserInfo
from src.app.scripts.seed_demo_org import DEMO_ORG_ID
from src.app.shared.context import RequestContext, set_context
from src.app.shared.db import async_session
from src.app.shared.security.password import hash_password

ADMIN_ROLE_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
ADMIN_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000011")

PERMISSIONS = [
    ("users.read", "Read users", "users"),
    ("users.write", "Manage users", "users"),
    ("roles.read", "Read roles", "roles"),
    ("roles.write", "Manage roles", "roles"),
    ("audit.read", "Read audit logs", "audit"),
    ("custom_fields.read", "Read custom fields", "custom_fields"),
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
            .values(
                [
                    {"key": key, "description": desc, "module": module}
                    for (key, desc, module) in PERMISSIONS
                ]
            )
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
            .values([{"role_id": ADMIN_ROLE_ID, "permission_id": pid} for pid in permission_ids])
            .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
        )

        # 4) admin user — three-table split (DR.7+). Each table owns
        # one slice of the user's identity:
        #   tbl_user_login          → auth (login handle, password, 2FA)
        #   tbl_user_info           → profile (name, email)
        #   tbl_organization_members → membership + role + is_demo
        #
        # We insert in dependency order, looking up the bigint login
        # PK after the auth row exists so it can be the FK target for
        # the other two. All three inserts are idempotent via
        # `ON CONFLICT DO NOTHING` on their respective unique keys.
        legacy_user_handle = "usr_" + ADMIN_USER_ID.hex
        await session.execute(
            pg_insert(User)
            .values(
                legacy_uuid=ADMIN_USER_ID,
                user_id=legacy_user_handle,
                password=hash_password(ADMIN_PASSWORD),
                is_active=True,
                two_factor_enabled=False,
            )
            .on_conflict_do_nothing(
                index_elements=["legacy_uuid"],
                index_where=text("legacy_uuid IS NOT NULL"),
            )
        )

        # 4b) Resolve the bigint login.id for this UUID identity so we
        # can FK into the profile + membership rows below.
        login_id = (
            await session.execute(select(User.id).where(User.legacy_uuid == ADMIN_USER_ID))
        ).scalar_one()

        # 4c) Profile row. Split the fixed display name into first/last.
        first_name, _, last_name = ADMIN_FULL_NAME.partition(" ")
        await session.execute(
            pg_insert(UserInfo)
            .values(
                member_id=login_id,
                first_name=first_name,
                last_name=last_name,
                email=ADMIN_EMAIL,
                mobile_no=None,
                is_email_verified=False,
                is_mobile_verified=False,
            )
            .on_conflict_do_nothing(index_elements=["member_id"])
        )

        # 4d) Org membership + role + is_demo. The partial unique
        # `uq_org_members_one_active_per_user` constrains one active
        # row per user across all orgs.
        await session.execute(
            pg_insert(OrganizationMember)
            .values(
                organization_id=DEMO_ORG_ID,
                user_member_id=login_id,
                role_id=ADMIN_ROLE_ID,
                status="active",
                is_active=True,
                is_demo=True,
            )
            .on_conflict_do_nothing(index_elements=["organization_id", "user_member_id"])
        )
        # Flip is_demo on the existing membership in case a pre-DR.7
        # seed run left it false.
        await session.execute(
            OrganizationMember.__table__.update()
            .where(OrganizationMember.user_member_id == login_id)
            .where(OrganizationMember.organization_id == DEMO_ORG_ID)
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
