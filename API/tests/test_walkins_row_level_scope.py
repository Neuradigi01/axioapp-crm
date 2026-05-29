"""Row-level visibility on the walk-ins HTTP endpoints.

Mirrors the leads scope tests: callers with `users.read` see every
walk-in in the org, callers without it see only walk-ins assigned to
them. Get-by-id returns 404 (not 403) for out-of-scope rows so the
endpoint doesn't leak existence.

Run with:
  ``uv run pytest tests/test_walkins_row_level_scope.py -v``
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.contacts.models import Contact
from src.app.core.permissions.models import Role, RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.users.models import OrganizationMember, User
from src.app.core.walk_ins.models import WalkIn, WalkInStatus
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.security.password import hash_password
from src.models.user import UserInfo as LegacyUserInfo, UserLogin


async def _grant(role_id: uuid.UUID, *keys: str) -> None:
    from tests.conftest import TestSession

    async with TestSession() as session:
        for key in keys:
            perm = await register_permission(
                session, key=key, module=key.split(".")[0], description=key
            )
            await session.execute(
                pg_insert(RolePermission)
                .values(role_id=role_id, permission_id=perm.id)
                .on_conflict_do_nothing(
                    index_elements=["role_id", "permission_id"]
                )
            )
        await session.commit()


async def _login(client, *, org_slug: str, email: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _make_contact(org_id: uuid.UUID, *, full_name: str) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            contact = Contact(org_id=org_id, full_name=full_name)
            session.add(contact)
            await session.commit()
            return contact.id
    finally:
        reset_context(token)


async def _make_walkin(
    org_id: uuid.UUID,
    *,
    contact_id: uuid.UUID,
    assigned_to_id: uuid.UUID,
) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            row = WalkIn(
                org_id=org_id,
                contact_id=contact_id,
                assigned_to_id=assigned_to_id,
                status=WalkInStatus.browsing,
            )
            session.add(row)
            await session.commit()
            return row.id
    finally:
        reset_context(token)


async def _make_second_user(
    org_id: uuid.UUID, *, email: str, password: str, role_name: str
) -> dict:
    from tests.conftest import TestSession

    role_uuid = uuid.uuid4()
    user_uuid = uuid.uuid4()
    login_handle = f"test-{uuid.uuid4().hex[:8]}"

    role = Role(id=role_uuid, org_id=org_id, name=role_name, is_system=False)
    user_login = UserLogin(
        user_id=login_handle,
        password=hash_password(password),
        is_active=True,
    )

    async with TestSession() as session:
        session.add(role)
        await session.flush()

        session.add(user_login)
        await session.flush()

        await session.execute(
            sql_text("UPDATE tbl_user_login SET legacy_uuid = :uuid WHERE id = :id"),
            {"uuid": str(user_uuid), "id": user_login.id},
        )
        await session.execute(
            sql_text("INSERT INTO users (id) VALUES (:uuid) ON CONFLICT DO NOTHING"),
            {"uuid": str(user_uuid)},
        )

        session.add(
            LegacyUserInfo(
                member_id=user_login.id,
                first_name="Second",
                last_name="User",
                email=email,
                mobile_no="0000000002",
            )
        )
        session.add(
            OrganizationMember(
                organization_id=org_id,
                user_member_id=user_login.id,
                role_id=role_uuid,
                status="active",
                is_active=True,
                is_demo=False,
            )
        )
        await session.commit()

        result = await session.execute(select(User).where(User.id == user_login.id))
        user = result.scalar_one()

    return {"user": user, "role": role, "password": password}


@pytest.mark.asyncio
async def test_list_walkins_scope_split(layered_client, seeded_admin):
    """Admin (users.read) sees both walk-ins; employee sees only own."""
    org = seeded_admin["org"]
    admin = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "walkins.read", "users.read")

    second = await _make_second_user(
        org.id,
        email="rep-w1@demo.local",
        password="Rep@1234",
        role_name="shop_floor_1",
    )
    rep = second["user"]
    await _grant(second["role"].id, "walkins.read")

    contact_id = await _make_contact(org.id, full_name="Anchor")
    admin_walkin = await _make_walkin(
        org.id, contact_id=contact_id, assigned_to_id=admin.legacy_uuid
    )
    rep_walkin = await _make_walkin(
        org.id, contact_id=contact_id, assigned_to_id=rep.legacy_uuid
    )

    # Admin → both walk-ins.
    admin_token = await _login(
        layered_client,
        org_slug=org.slug,
        email=admin.email,
        password=seeded_admin["password"],
    )
    res = await layered_client.get(
        "/api/v1/walk-ins",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200, res.text
    ids = {row["id"] for row in res.json()}
    assert ids == {str(admin_walkin), str(rep_walkin)}

    # Employee → only own.
    rep_token = await _login(
        layered_client,
        org_slug=org.slug,
        email=rep.email,
        password=second["password"],
    )
    res = await layered_client.get(
        "/api/v1/walk-ins",
        headers={"Authorization": f"Bearer {rep_token}"},
    )
    assert res.status_code == 200, res.text
    ids = {row["id"] for row in res.json()}
    assert ids == {str(rep_walkin)}

    # Employee clamp: ?assigned_to=<admin> is silently ignored.
    res = await layered_client.get(
        f"/api/v1/walk-ins?assigned_to={admin.legacy_uuid}",
        headers={"Authorization": f"Bearer {rep_token}"},
    )
    assert res.status_code == 200
    ids = {row["id"] for row in res.json()}
    assert ids == {str(rep_walkin)}


@pytest.mark.asyncio
async def test_get_walkin_returns_404_when_out_of_scope(
    layered_client, seeded_admin
):
    """Employee fetching another user's walk-in by id → 404."""
    org = seeded_admin["org"]
    admin = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "walkins.read", "users.read")

    second = await _make_second_user(
        org.id,
        email="rep-w2@demo.local",
        password="Rep@1234",
        role_name="shop_floor_2",
    )
    rep = second["user"]
    await _grant(second["role"].id, "walkins.read")

    contact_id = await _make_contact(org.id, full_name="Anchor")
    admin_walkin = await _make_walkin(
        org.id, contact_id=contact_id, assigned_to_id=admin.legacy_uuid
    )
    rep_walkin = await _make_walkin(
        org.id, contact_id=contact_id, assigned_to_id=rep.legacy_uuid
    )

    rep_token = await _login(
        layered_client,
        org_slug=org.slug,
        email=rep.email,
        password=second["password"],
    )

    res = await layered_client.get(
        f"/api/v1/walk-ins/{rep_walkin}",
        headers={"Authorization": f"Bearer {rep_token}"},
    )
    assert res.status_code == 200

    res = await layered_client.get(
        f"/api/v1/walk-ins/{admin_walkin}",
        headers={"Authorization": f"Bearer {rep_token}"},
    )
    assert res.status_code == 404
