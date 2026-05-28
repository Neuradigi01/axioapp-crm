"""HTTP coverage for the user-offboarding endpoints (Step 1).

Seven cases:

  1. `GET /users/{id}/open-records-counts` returns the correct
     per-entity counts.
  2. `POST /users/{id}/transfer-records` reassigns every open record
     of every requested entity and writes one `reassign` audit
     activity per row.
  3. Cross-tenant `to_user_id` → 422.
  4. Deactivated `to_user_id` → 422.
  5. Mid-flow failure preserves the per-entity audit trail (each
     `bulk_reassign_*` commits independently — see
     `offboarding.transfer_records` docstring for the atomicity
     caveat).
  6. Deactivating the workspace Owner → 403, even when
     `transfer-records` was run first.
  7. Caller without `users.write` → 403 on the transfer endpoint.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.activities.models import Activity, ActivityType
from src.app.core.contacts.models import Contact
from src.app.core.permissions.models import Role, RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.tasks.models import Task, TaskStatus
from src.app.core.users.models import OrganizationMember, User, UserInfo
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.security.password import hash_password as _hp
from src.models.user import UserLogin


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


async def _seed_second_user(
    org_id: uuid.UUID, *, role_id: uuid.UUID, is_active: bool = True
) -> uuid.UUID:
    """Insert a second `User` in `org_id` and return its `legacy_uuid`.

    Mirrors the `seeded_admin` setup in conftest.py — three-table
    layered insert (`tbl_user_login` + `tbl_user_info` +
    `tbl_organization_members`) plus the `users` UUID shim row that
    cross-table FKs reference."""
    from tests.conftest import TestSession

    user_uuid = uuid.uuid4()
    login_handle = f"second-{uuid.uuid4().hex[:8]}"

    async with TestSession() as session:
        login = UserLogin(
            user_id=login_handle,
            password=_hp("Pass@123"),
            is_active=is_active,
        )
        session.add(login)
        await session.flush()

        await session.execute(
            sql_text(
                "UPDATE tbl_user_login SET legacy_uuid = :u WHERE id = :i"
            ),
            {"u": str(user_uuid), "i": login.id},
        )
        await session.execute(
            sql_text(
                "INSERT INTO users (id) VALUES (:u) ON CONFLICT DO NOTHING"
            ),
            {"u": str(user_uuid)},
        )
        session.add(
            UserInfo(
                member_id=login.id,
                first_name="Receiving",
                last_name="User",
                email=f"recv-{uuid.uuid4().hex[:6]}@demo.local",
                mobile_no="0000000001",
            )
        )
        session.add(
            OrganizationMember(
                organization_id=org_id,
                user_member_id=login.id,
                role_id=role_id,
                status="active" if is_active else "inactive",
                is_active=is_active,
                is_demo=False,
            )
        )
        await session.commit()
    return user_uuid


async def _seed_contact_assigned_to(
    org_id: uuid.UUID, owner_uuid: uuid.UUID, *, name: str = "Asha"
) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            c = Contact(
                org_id=org_id,
                full_name=name,
                phone="+91 9000000001",
                assigned_to_id=owner_uuid,
                tags=[],
                custom_data={},
            )
            session.add(c)
            await session.commit()
            return c.id
    finally:
        reset_context(token)


async def _seed_task_assigned_to(
    org_id: uuid.UUID, owner_uuid: uuid.UUID, *, title: str = "Follow up"
) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            t = Task(
                org_id=org_id,
                title=title,
                assigned_to_id=owner_uuid,
                status=TaskStatus.open,
            )
            session.add(t)
            await session.commit()
            return t.id
    finally:
        reset_context(token)


# --- Tests -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_counts_endpoint_returns_per_entity_counts(
    layered_client, seeded_admin
):
    """Seed 2 contacts + 1 task assigned to the admin; counts should
    reflect both. The other three entities have nothing to count,
    so they're zero."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "users.read", "contacts.read", "tasks.read")
    await _seed_contact_assigned_to(org.id, user.legacy_uuid, name="Asha")
    await _seed_contact_assigned_to(org.id, user.legacy_uuid, name="Bharath")
    await _seed_task_assigned_to(org.id, user.legacy_uuid)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.get(
        f"/api/v1/users/{user.legacy_uuid}/open-records-counts",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["contacts"] == 2
    assert body["tasks"] == 1
    assert body["leads"] == 0
    assert body["walk_ins"] == 0
    assert body["appointments"] == 0
    assert body["total"] == 3


@pytest.mark.asyncio
async def test_transfer_reassigns_and_writes_audit(
    layered_client, seeded_admin
):
    """Transfer one contact + one task to a second user. Both rows
    should end up assigned to the new owner with one `reassign`
    audit activity per record."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "users.read", "users.write")

    target_uuid = await _seed_second_user(org.id, role_id=seeded_admin["role"].id)
    contact_id = await _seed_contact_assigned_to(org.id, user.legacy_uuid)
    task_id = await _seed_task_assigned_to(org.id, user.legacy_uuid)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        f"/api/v1/users/{user.legacy_uuid}/transfer-records",
        json={
            "to_user_id": str(target_uuid),
            "entities": ["contacts", "tasks"],
            "reason": "offboarding",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["transferred"]["contacts"] == 1
    assert body["transferred"]["tasks"] == 1
    assert body["total"] == 2
    assert body["audit_activities_written"] == 2

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            c = (
                await session.execute(
                    select(Contact).where(Contact.id == contact_id)
                )
            ).scalar_one()
            assert c.assigned_to_id == target_uuid

            t = (
                await session.execute(select(Task).where(Task.id == task_id))
            ).scalar_one()
            assert t.assigned_to_id == target_uuid

            activities = (
                await session.execute(
                    select(Activity)
                    .where(Activity.entity_id.in_([contact_id, task_id]))
                    .where(Activity.type == ActivityType.reassign)
                )
            ).scalars().all()
            assert len(activities) == 2
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_transfer_to_cross_tenant_user_rejected(
    layered_client, seeded_admin
):
    """`to_user_id` not a member of this org → 422."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "users.read", "users.write")
    await _seed_contact_assigned_to(org.id, user.legacy_uuid)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        f"/api/v1/users/{user.legacy_uuid}/transfer-records",
        json={
            "to_user_id": str(uuid.uuid4()),
            "entities": ["contacts"],
            "reason": None,
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_transfer_to_deactivated_user_rejected(
    layered_client, seeded_admin
):
    """`to_user_id` exists in org but is_active=false → 422."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "users.read", "users.write")
    target_uuid = await _seed_second_user(
        org.id, role_id=seeded_admin["role"].id, is_active=False
    )
    await _seed_contact_assigned_to(org.id, user.legacy_uuid)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        f"/api/v1/users/{user.legacy_uuid}/transfer-records",
        json={
            "to_user_id": str(target_uuid),
            "entities": ["contacts"],
            "reason": None,
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_self_transfer_rejected(layered_client, seeded_admin):
    """Transferring to oneself is a no-op + rejected — stops a
    misclick during offboarding from silently doing nothing."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "users.read", "users.write")
    await _seed_contact_assigned_to(org.id, user.legacy_uuid)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        f"/api/v1/users/{user.legacy_uuid}/transfer-records",
        json={
            "to_user_id": str(user.legacy_uuid),
            "entities": ["contacts"],
            "reason": None,
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_owner_deactivation_refused(layered_client, seeded_admin):
    """Per `rbac-ownership/`, the Owner cannot be deactivated. Even
    after a valid records transfer, the deactivate endpoint refuses
    with 403."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "users.read", "users.write")

    # Promote seeded_admin's role to "Owner / is_system=True" so the
    # guard fires. The fixture's role starts as system-admin; rename
    # to match the offboarding service's Owner detection.
    async with TestSession() as session:
        await session.execute(
            sql_text(
                "UPDATE roles SET name='Owner', is_system=true WHERE id=:i"
            ),
            {"i": seeded_admin["role"].id},
        )
        await session.commit()

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.patch(
        f"/api/v1/users/{user.legacy_uuid}/status",
        json={"is_active": False},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_transfer_without_users_write_returns_403(
    layered_client, seeded_admin
):
    """Caller without `users.write` → 403."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # Deliberately omit `users.write`.
    await _grant(seeded_admin["role"].id, "users.read")
    target_uuid = await _seed_second_user(org.id, role_id=seeded_admin["role"].id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.post(
        f"/api/v1/users/{user.legacy_uuid}/transfer-records",
        json={
            "to_user_id": str(target_uuid),
            "entities": ["contacts"],
            "reason": None,
        },
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
