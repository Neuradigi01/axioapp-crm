"""HTTP coverage for `GET /dashboard/funnel`.

Three scenarios exercised end-to-end through the layered FastAPI app:

  1. **Every stage present.** Org with 4 non-terminal stages and 3
     leads (one in stage 0 and one in stage 2). The funnel response
     returns 4 stage buckets in `display_order`, counts `[1, 0, 1, 0]`.
  2. **Scope split.** Two users in one org. The admin (with
     `users.read`) gets org scope and sees both users' leads; the
     second user gets personal scope and sees only their own. Won /
     lost counts respect scope.
  3. **Out-of-range leads excluded.** A lead created 120 days ago is
     excluded by `range=30d` and included by `range=365d`.

Run with:
  ``uv run pytest tests/test_dashboard_funnel_endpoint.py -v``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

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

_STAGES: list[tuple[str, str, bool, bool]] = [
    ("new", "New", False, False),
    ("qualified", "Qualified", False, False),
    ("proposal", "Proposal", False, False),
    ("negotiation", "Negotiation", False, False),
    ("won", "Won", True, False),
    ("lost", "Lost", False, True),
]


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
            for i, (k, name, is_won, is_lost) in enumerate(_STAGES):
                session.add(
                    PipelineStage(
                        org_id=org_id,
                        pipeline_id=p.id,
                        key=k,
                        name=name,
                        display_order=i,
                        is_won=is_won,
                        is_lost=is_lost,
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
    stage_key: str,
    status: LeadStatus = LeadStatus.active,
    created_at: datetime | None = None,
    assigned_to_id: uuid.UUID | None = None,
) -> None:
    from tests.conftest import TestSession

    when = created_at or datetime.now(UTC)
    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            lead = Lead(
                org_id=org_id,
                contact_id=contact_id,
                pipeline_stage=stage_key,
                status=status,
                assigned_to_id=assigned_to_id,
                created_at=when,
                updated_at=when,
            )
            session.add(lead)
            await session.commit()
    finally:
        reset_context(token)


async def _make_second_user(
    org_id: uuid.UUID, *, email: str, password: str, role_name: str
) -> dict:
    """Mint a second user in the same org with a fresh role."""
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
async def test_funnel_every_stage_present(layered_client, seeded_admin):
    """Funnel returns every non-terminal stage; zero-stages render with count=0."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "users.read")
    await _seed_leads_pipeline(org.id)
    contact_id = await _make_contact(org.id, full_name="Anchor")

    # One lead in stage 0 ("new"), one in stage 2 ("proposal").
    await _make_lead(org.id, contact_id=contact_id, stage_key="new")
    await _make_lead(org.id, contact_id=contact_id, stage_key="proposal")

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    res = await layered_client.get(
        "/api/v1/dashboard/funnel?range=30d",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    payload = res.json()

    assert payload["range"] == "30d"
    assert payload["scope"] == "org"
    assert payload["won_count"] == 0
    assert payload["lost_count"] == 0

    stages = payload["stages"]
    # 4 non-terminal stages (won + lost excluded from the funnel list).
    assert [s["stage_name"] for s in stages] == [
        "New",
        "Qualified",
        "Proposal",
        "Negotiation",
    ]
    assert [s["stage_order"] for s in stages] == [0, 1, 2, 3]
    assert [s["count"] for s in stages] == [1, 0, 1, 0]
    assert payload["total_leads_in_range"] == 2


@pytest.mark.asyncio
async def test_funnel_scope_split(layered_client, seeded_admin):
    """Org-scope sees both users' leads; personal-scope sees only own."""
    org = seeded_admin["org"]
    admin = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "users.read")
    await _seed_leads_pipeline(org.id)

    second = await _make_second_user(
        org.id,
        email="second-funnel@demo.local",
        password="Second@123",
        role_name="staff",
    )
    second_user = second["user"]

    contact_id = await _make_contact(org.id, full_name="Anchor")

    # Admin: 2 leads in "new", 1 won.  Second user: 1 lead in "qualified", 1 lost.
    await _make_lead(
        org.id,
        contact_id=contact_id,
        stage_key="new",
        assigned_to_id=admin.legacy_uuid,
    )
    await _make_lead(
        org.id,
        contact_id=contact_id,
        stage_key="new",
        assigned_to_id=admin.legacy_uuid,
    )
    await _make_lead(
        org.id,
        contact_id=contact_id,
        stage_key="won",
        status=LeadStatus.won,
        assigned_to_id=admin.legacy_uuid,
    )
    await _make_lead(
        org.id,
        contact_id=contact_id,
        stage_key="qualified",
        assigned_to_id=second_user.legacy_uuid,
    )
    await _make_lead(
        org.id,
        contact_id=contact_id,
        stage_key="lost",
        status=LeadStatus.lost,
        assigned_to_id=second_user.legacy_uuid,
    )

    # Org-scope caller.
    admin_token = await _login(
        layered_client,
        org_slug=org.slug,
        email=admin.email,
        password=seeded_admin["password"],
    )
    res = await layered_client.get(
        "/api/v1/dashboard/funnel?range=30d",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["scope"] == "org"
    by_name = {s["stage_name"]: s["count"] for s in payload["stages"]}
    assert by_name["New"] == 2
    assert by_name["Qualified"] == 1
    assert payload["won_count"] == 1
    assert payload["lost_count"] == 1
    assert payload["total_leads_in_range"] == 5

    # Personal-scope caller — second user has no users.read.
    second_token = await _login(
        layered_client,
        org_slug=org.slug,
        email=second_user.email,
        password=second["password"],
    )
    res = await layered_client.get(
        "/api/v1/dashboard/funnel?range=30d",
        headers={"Authorization": f"Bearer {second_token}"},
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["scope"] == "personal"
    by_name = {s["stage_name"]: s["count"] for s in payload["stages"]}
    assert by_name["New"] == 0
    assert by_name["Qualified"] == 1
    assert payload["won_count"] == 0
    assert payload["lost_count"] == 1
    assert payload["total_leads_in_range"] == 2


@pytest.mark.asyncio
async def test_funnel_excludes_out_of_range(layered_client, seeded_admin):
    """A 120-days-old lead falls outside 30d but lands inside 365d."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "users.read")
    await _seed_leads_pipeline(org.id)
    contact_id = await _make_contact(org.id, full_name="Anchor")

    long_ago = datetime.now(UTC) - timedelta(days=120)
    await _make_lead(
        org.id,
        contact_id=contact_id,
        stage_key="qualified",
        created_at=long_ago,
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    res = await layered_client.get("/api/v1/dashboard/funnel?range=30d", headers=headers)
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["total_leads_in_range"] == 0
    assert all(s["count"] == 0 for s in payload["stages"])

    res = await layered_client.get("/api/v1/dashboard/funnel?range=365d", headers=headers)
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["total_leads_in_range"] == 1
    by_name = {s["stage_name"]: s["count"] for s in payload["stages"]}
    assert by_name["Qualified"] == 1
