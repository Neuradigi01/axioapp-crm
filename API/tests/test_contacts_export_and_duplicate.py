"""HTTP-level coverage for contacts CSV export + duplicate-check.

Four cases:

  1. `GET /contacts/export.csv` returns the right MIME, filename
     pattern, header row, and at least one data row.
  2. `GET /contacts/check-duplicate?phone=...` matches by last-10
     digit suffix (handles `+91 9000…` vs `9000…`).
  3. `GET /contacts/check-duplicate?email=...` matches case-insensitive.
  4. `?exclude_id=` skips the row currently being edited.
"""

from __future__ import annotations

import csv
import io
import uuid

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.contacts.models import Contact
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.shared.context import RequestContext, reset_context, set_context


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


async def _make_contact(
    org_id: uuid.UUID,
    *,
    full_name: str,
    phone: str | None = None,
    email: str | None = None,
) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            contact = Contact(
                org_id=org_id,
                full_name=full_name,
                phone=phone,
                email=email,
            )
            session.add(contact)
            await session.commit()
            return contact.id
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_csv_export_returns_streamed_csv_with_header_and_row(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "contacts.read", "contacts.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    await _make_contact(
        org.id,
        full_name="Export Me",
        phone="+91 9000000099",
        email="export@example.com",
    )

    resp = await layered_client.get("/api/v1/contacts/export.csv", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    cd = resp.headers["content-disposition"]
    assert "attachment" in cd and ".csv" in cd

    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0] == [
        "id",
        "full_name",
        "phone",
        "email",
        "source",
        "tags",
        "assigned_to_id",
        "last_activity_at",
        "created_at",
        "updated_at",
    ]
    names = {r[1] for r in rows[1:]}
    assert "Export Me" in names


@pytest.mark.asyncio
async def test_dup_check_phone_suffix_matches_e164_variants(layered_client, seeded_admin):
    """Saved phone '+91 9000000001' matches incoming query '9000000001'."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "contacts.read", "contacts.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    cid = await _make_contact(org.id, full_name="Asha", phone="+91 9000000001")

    resp = await layered_client.get(
        "/api/v1/contacts/check-duplicate?phone=9000000001", headers=headers
    )
    assert resp.status_code == 200, resp.text
    matches = resp.json()["matches"]
    assert len(matches) == 1
    assert matches[0]["id"] == str(cid)
    assert matches[0]["full_name"] == "Asha"


@pytest.mark.asyncio
async def test_dup_check_email_is_case_insensitive(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "contacts.read", "contacts.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    cid = await _make_contact(org.id, full_name="Rahul", email="rahul@example.com")

    resp = await layered_client.get(
        "/api/v1/contacts/check-duplicate?email=RAHUL%40Example.com",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    matches = resp.json()["matches"]
    assert len(matches) == 1
    assert matches[0]["id"] == str(cid)


@pytest.mark.asyncio
async def test_dup_check_exclude_id_skips_self(layered_client, seeded_admin):
    """Edit modal passes its own id so the row doesn't match itself."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "contacts.read", "contacts.write")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    cid = await _make_contact(org.id, full_name="Self", phone="9000000077")

    resp = await layered_client.get(
        f"/api/v1/contacts/check-duplicate?phone=9000000077&exclude_id={cid}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["matches"] == []
