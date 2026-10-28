"""Coverage for `GET /api/v1/audit-logs`.

Two angles:
  - pagination + action filter return the rows we wrote.
  - tenant isolation — a viewer in one org cannot see another org's
    audit trail even with the right permission.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.audit.models import AuditLog
from src.app.core.permissions.models import Role, RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.tenants.models import Organization
from src.app.core.users.models import User
from src.app.shared.security.password import hash_password


async def _grant_audit_read(role_id: uuid.UUID) -> None:
    from tests.conftest import TestSession

    async with TestSession() as session:
        perm = await register_permission(
            session, key="audit.read", module="audit", description="Read audit logs"
        )
        await session.execute(
            pg_insert(RolePermission)
            .values(role_id=role_id, permission_id=perm.id)
            .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
        )
        await session.commit()


async def _make_second_tenant() -> dict:
    """Create a second org + admin role + admin user (with audit.read)."""
    from tests.conftest import TestSession

    org = Organization(id=uuid.uuid4(), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
    role = Role(id=uuid.uuid4(), org_id=org.id, name="admin", is_system=True)
    user = User(
        id=uuid.uuid4(),
        org_id=org.id,
        email=f"other-{uuid.uuid4().hex[:6]}@example.local",
        password_hash=hash_password("Other@123"),
        full_name="Other Admin",
        role_id=role.id,
        is_active=True,
    )
    async with TestSession() as session:
        session.add(org)
        await session.flush()
        session.add(role)
        await session.flush()
        session.add(user)
        await session.commit()

    await _grant_audit_read(role.id)
    return {"org": org, "role": role, "user": user, "password": "Other@123"}


async def _insert_audit(org_id: uuid.UUID, action: str, **extra) -> None:
    from tests.conftest import TestSession

    async with TestSession() as session:
        session.add(AuditLog(org_id=org_id, action=action, **extra))
        await session.commit()


async def _login(client, *, org_slug: str, email: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_list_paginates_and_filters_by_action(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant_audit_read(seeded_admin["role"].id)

    # Seed three rows: two of one action, one of another.
    await _insert_audit(org.id, "thing.created", user_id=user.id)
    await _insert_audit(org.id, "thing.created", user_id=user.id)
    await _insert_audit(org.id, "thing.deleted", user_id=user.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )

    # The login itself wrote one auth.login.success row → total = 4 unfiltered.
    all_resp = await layered_client.get(
        "/api/v1/audit-logs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert all_resp.status_code == 200, all_resp.text
    assert all_resp.json()["total"] == 4

    # Filter by action.
    created_resp = await layered_client.get(
        "/api/v1/audit-logs?action=thing.created",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created_resp.status_code == 200
    body = created_resp.json()
    assert body["total"] == 2
    assert all(item["action"] == "thing.created" for item in body["items"])

    # Pagination: size=1 returns 1 row, total stays at 4.
    page1 = await layered_client.get(
        "/api/v1/audit-logs?page=1&size=1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert page1.status_code == 200
    assert page1.json()["total"] == 4
    assert len(page1.json()["items"]) == 1


@pytest.mark.asyncio
async def test_list_is_tenant_isolated(layered_client, seeded_admin):
    """Org A's audit rows are invisible to Org B even with audit.read."""
    org_a = seeded_admin["org"]
    user_a = seeded_admin["user"]
    await _grant_audit_read(seeded_admin["role"].id)

    other = await _make_second_tenant()

    # Write rows on both sides.
    await _insert_audit(org_a.id, "a.only", user_id=user_a.id)
    await _insert_audit(other["org"].id, "b.only", user_id=other["user"].id)

    token_a = await _login(
        layered_client,
        org_slug=org_a.slug,
        email=user_a.email,
        password=seeded_admin["password"],
    )
    a_view = await layered_client.get(
        "/api/v1/audit-logs",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert a_view.status_code == 200
    actions_seen = {row["action"] for row in a_view.json()["items"]}
    assert "a.only" in actions_seen
    assert "b.only" not in actions_seen


@pytest.mark.asyncio
async def test_list_without_audit_read_is_403(layered_client, seeded_admin):
    """A user whose role lacks `audit.read` gets 403 from the list endpoint."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # Intentionally do NOT grant audit.read.

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.get(
        "/api/v1/audit-logs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text
