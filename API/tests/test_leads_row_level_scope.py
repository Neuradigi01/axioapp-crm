"""Row-level visibility on the leads HTTP endpoints.

The rule is the same one the dashboard already uses to decide
"team view vs personal view": callers with `users.read` see every
lead in the org, callers without it see only leads assigned to them.

Three scenarios:

  1. **List**. Admin (with users.read) gets both their lead and the
     second user's lead; second user (no users.read) gets only their
     own. Any `?assigned_to=<other>` an employee passes is silently
     clamped to self, never honoured.

  2. **Get by id**. A non-privileged caller fetching another user's
     lead gets 404 (we do NOT use 403 — that would leak the lead's
     existence). Their own lead still returns 200.

  3. **Privileged caller can target a specific user**. Admin with
     users.read can still pass `?assigned_to=<some user>` and get
     their narrow filter back.

Run with:
  ``uv run pytest tests/test_leads_row_level_scope.py -v``
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.contacts.models import Contact
from src.app.core.leads.models import Lead, LeadStatus
from src.app.core.permissions.models import Role, RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.pipelines.models import Pipeline, PipelineStage
from src.app.core.users.models import OrganizationMember, User
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.security.password import hash_password
from src.models.user import UserInfo as LegacyUserInfo
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
                .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
            )
        await session.commit()


async def _login(client, *, org_slug: str, email: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _seed_leads_pipeline(org_id: uuid.UUID) -> None:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            p = Pipeline(org_id=org_id, key="leads", name="Leads")
            session.add(p)
            await session.flush()
            session.add(
                PipelineStage(
                    org_id=org_id,
                    pipeline_id=p.id,
                    key="new",
                    name="New",
                    display_order=0,
                    is_won=False,
                    is_lost=False,
                )
            )
            await session.commit()
    finally:
        reset_context(token)


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


async def _make_lead(
    org_id: uuid.UUID,
    *,
    contact_id: uuid.UUID,
    assigned_to_id: uuid.UUID,
) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            lead = Lead(
                org_id=org_id,
                contact_id=contact_id,
                pipeline_stage="new",
                status=LeadStatus.active,
                assigned_to_id=assigned_to_id,
            )
            session.add(lead)
            await session.commit()
            return lead.id
    finally:
        reset_context(token)


async def _make_second_user(
    org_id: uuid.UUID, *, email: str, password: str, role_name: str
) -> dict:
    """Mint a second user in the same org with a fresh role.

    Mirrors the helper used by the dashboard scope tests so the two
    suites stay in lock-step on user-seeding shape.
    """
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
async def test_list_leads_scope_split(layered_client, seeded_admin):
    """Admin (users.read) sees both leads; employee sees only own."""
    org = seeded_admin["org"]
    admin = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "users.read")
    await _seed_leads_pipeline(org.id)

    second = await _make_second_user(
        org.id,
        email="rep@demo.local",
        password="Rep@1234",
        role_name="sales_exec",
    )
    rep = second["user"]
    # Employee only gets leads.read — NO users.read.
    await _grant(second["role"].id, "leads.read")

    contact_id = await _make_contact(org.id, full_name="Anchor")
    admin_lead = await _make_lead(org.id, contact_id=contact_id, assigned_to_id=admin.legacy_uuid)
    rep_lead = await _make_lead(org.id, contact_id=contact_id, assigned_to_id=rep.legacy_uuid)

    # Admin → both leads.
    admin_token = await _login(
        layered_client,
        org_slug=org.slug,
        email=admin.email,
        password=seeded_admin["password"],
    )
    res = await layered_client.get(
        "/api/v1/leads",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200, res.text
    ids = {row["id"] for row in res.json()["items"]}
    assert ids == {str(admin_lead), str(rep_lead)}

    # Employee → only own lead, even when explicitly asking for admin's.
    rep_token = await _login(
        layered_client,
        org_slug=org.slug,
        email=rep.email,
        password=second["password"],
    )
    res = await layered_client.get(
        "/api/v1/leads",
        headers={"Authorization": f"Bearer {rep_token}"},
    )
    assert res.status_code == 200, res.text
    ids = {row["id"] for row in res.json()["items"]}
    assert ids == {str(rep_lead)}

    # Employee clamp: passing ?assigned_to=<admin> is silently ignored.
    res = await layered_client.get(
        f"/api/v1/leads?assigned_to={admin.legacy_uuid}",
        headers={"Authorization": f"Bearer {rep_token}"},
    )
    assert res.status_code == 200
    ids = {row["id"] for row in res.json()["items"]}
    assert ids == {str(rep_lead)}


@pytest.mark.asyncio
async def test_get_lead_returns_404_when_out_of_scope(layered_client, seeded_admin):
    """Employee fetching another user's lead by id → 404, not 403."""
    org = seeded_admin["org"]
    admin = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "users.read")
    await _seed_leads_pipeline(org.id)

    second = await _make_second_user(
        org.id,
        email="rep2@demo.local",
        password="Rep@1234",
        role_name="sales_exec_2",
    )
    rep = second["user"]
    await _grant(second["role"].id, "leads.read")

    contact_id = await _make_contact(org.id, full_name="Anchor")
    admin_lead = await _make_lead(org.id, contact_id=contact_id, assigned_to_id=admin.legacy_uuid)
    rep_lead = await _make_lead(org.id, contact_id=contact_id, assigned_to_id=rep.legacy_uuid)

    rep_token = await _login(
        layered_client,
        org_slug=org.slug,
        email=rep.email,
        password=second["password"],
    )

    # Own lead: 200.
    res = await layered_client.get(
        f"/api/v1/leads/{rep_lead}",
        headers={"Authorization": f"Bearer {rep_token}"},
    )
    assert res.status_code == 200

    # Other user's lead: 404 (not 403 — don't leak existence).
    res = await layered_client.get(
        f"/api/v1/leads/{admin_lead}",
        headers={"Authorization": f"Bearer {rep_token}"},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_privileged_can_filter_to_a_specific_user(layered_client, seeded_admin):
    """Admin (users.read) can still use ?assigned_to=<x> as a filter."""
    org = seeded_admin["org"]
    admin = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "users.read")
    await _seed_leads_pipeline(org.id)

    second = await _make_second_user(
        org.id,
        email="rep3@demo.local",
        password="Rep@1234",
        role_name="sales_exec_3",
    )
    rep = second["user"]

    contact_id = await _make_contact(org.id, full_name="Anchor")
    await _make_lead(org.id, contact_id=contact_id, assigned_to_id=admin.legacy_uuid)
    rep_lead = await _make_lead(org.id, contact_id=contact_id, assigned_to_id=rep.legacy_uuid)

    admin_token = await _login(
        layered_client,
        org_slug=org.slug,
        email=admin.email,
        password=seeded_admin["password"],
    )
    res = await layered_client.get(
        f"/api/v1/leads?assigned_to={rep.legacy_uuid}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    ids = {row["id"] for row in res.json()["items"]}
    assert ids == {str(rep_lead)}
