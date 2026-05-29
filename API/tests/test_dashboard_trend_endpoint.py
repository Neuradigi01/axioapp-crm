"""HTTP coverage for `GET /dashboard/trend`.

Three scenarios exercised end-to-end through the layered FastAPI app:

  1. **Series length & zero-fill** — 3 leads seeded across 2
     non-adjacent days within the last 7d. The 7d series returns
     exactly 7 points; the two seeded days carry positive values, the
     other five carry 0.
  2. **Scope split** — two users in one org. The admin (with
     `users.read`) gets org scope and sees both users' leads; the
     second user (no `users.read`) gets personal scope and sees only
     their own.
  3. **Validation errors** — bad `metric` / `range` query params
     return FastAPI's standard 422 shape.

Run with:
  ``uv run pytest tests/test_dashboard_trend_endpoint.py -v``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.contacts.models import Contact
from src.app.core.leads.models import Lead, LeadStatus
from src.app.core.permissions.models import Role, RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.tenants.models import Organization
from src.app.core.users.models import OrganizationMember, User
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


async def _make_lead(
    org_id: uuid.UUID,
    *,
    contact_id: uuid.UUID,
    created_at: datetime,
    assigned_to_id: uuid.UUID | None = None,
) -> None:
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
                created_at=created_at,
                updated_at=created_at,
            )
            session.add(lead)
            await session.commit()
    finally:
        reset_context(token)


async def _make_second_user(
    org_id: uuid.UUID, *, email: str, password: str, role_name: str
) -> dict:
    """Mint a second user in the same org with a fresh role.

    Mirrors the `seeded_admin` fixture's three-table layout
    (`tbl_user_login` + `tbl_user_info` + `tbl_organization_members`)
    so the layered `User` mapper resolves `.email`, `.org_id`,
    `.role_id` via selectin. Returns `{user, role, password}`.
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
                mobile_no="0000000001",
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
async def test_trend_series_length_and_zero_fill(layered_client, seeded_admin):
    """7-day series fills missing buckets with 0; seeded days carry counts."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "users.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    contact_id = await _make_contact(org.id, full_name="Anchor")
    now = datetime.now(timezone.utc)
    today_noon = datetime(
        now.year, now.month, now.day, 12, 0, tzinfo=timezone.utc
    )

    # 2 leads today, 1 lead three days ago. Days -1, -2, -4, -5, -6
    # remain empty and must come back zero-filled.
    await _make_lead(org.id, contact_id=contact_id, created_at=today_noon)
    await _make_lead(org.id, contact_id=contact_id, created_at=today_noon)
    await _make_lead(
        org.id, contact_id=contact_id, created_at=today_noon - timedelta(days=3)
    )

    res = await layered_client.get(
        "/api/v1/dashboard/trend?metric=leads_created&range=7d",
        headers=headers,
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["metric"] == "leads_created"
    assert payload["range"] == "7d"
    assert payload["scope"] == "org"

    points = payload["points"]
    assert len(points) == 7

    # Ascending dates with no gaps.
    dates = [p["date"] for p in points]
    assert dates == sorted(dates)
    assert dates[-1] == today_noon.date().isoformat()
    assert dates[0] == (today_noon.date() - timedelta(days=6)).isoformat()

    by_date = {p["date"]: p["value"] for p in points}
    assert by_date[today_noon.date().isoformat()] == 2.0
    assert by_date[(today_noon.date() - timedelta(days=3)).isoformat()] == 1.0

    # Five remaining buckets are zero-filled.
    zero_buckets = [
        v for d, v in by_date.items()
        if d not in {
            today_noon.date().isoformat(),
            (today_noon.date() - timedelta(days=3)).isoformat(),
        }
    ]
    assert len(zero_buckets) == 5
    assert all(v == 0.0 for v in zero_buckets)


@pytest.mark.asyncio
async def test_trend_scope_split(layered_client, seeded_admin):
    """Org-scope sees both users' leads; personal-scope sees only own."""
    org = seeded_admin["org"]
    admin = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "users.read")

    second = await _make_second_user(
        org.id,
        email="second@demo.local",
        password="Second@123",
        role_name="staff",
    )
    second_user = second["user"]

    contact_id = await _make_contact(org.id, full_name="Anchor")
    now = datetime.now(timezone.utc)
    today_noon = datetime(
        now.year, now.month, now.day, 12, 0, tzinfo=timezone.utc
    )

    # 5 leads owned by admin, 5 by the second user, all today.
    for _ in range(5):
        await _make_lead(
            org.id,
            contact_id=contact_id,
            created_at=today_noon,
            assigned_to_id=admin.legacy_uuid,
        )
    for _ in range(5):
        await _make_lead(
            org.id,
            contact_id=contact_id,
            created_at=today_noon,
            assigned_to_id=second_user.legacy_uuid,
        )

    # Org-scope caller (admin with users.read).
    admin_token = await _login(
        layered_client,
        org_slug=org.slug,
        email=admin.email,
        password=seeded_admin["password"],
    )
    res = await layered_client.get(
        "/api/v1/dashboard/trend?metric=leads_created&range=7d",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["scope"] == "org"
    assert sum(p["value"] for p in payload["points"]) == 10.0

    # Personal-scope caller (second user, no users.read).
    second_token = await _login(
        layered_client,
        org_slug=org.slug,
        email=second_user.email,
        password=second["password"],
    )
    res = await layered_client.get(
        "/api/v1/dashboard/trend?metric=leads_created&range=7d",
        headers={"Authorization": f"Bearer {second_token}"},
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["scope"] == "personal"
    assert sum(p["value"] for p in payload["points"]) == 5.0


@pytest.mark.asyncio
async def test_trend_rejects_bad_metric_and_range(layered_client, seeded_admin):
    """FastAPI validates the `Literal` typed query params and returns 422."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    res = await layered_client.get(
        "/api/v1/dashboard/trend?range=99d", headers=headers
    )
    assert res.status_code == 422

    res = await layered_client.get(
        "/api/v1/dashboard/trend?metric=banana", headers=headers
    )
    assert res.status_code == 422
