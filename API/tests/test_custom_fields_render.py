"""GET /api/v1/custom-fields/{entity_type}/render

Verifies:
  - only non-hidden rows come back;
  - ordering follows `display_order` (and `field_key` as tiebreak);
  - render payload is the slim shape (no internal columns like
    `source` / `pack_id` / `id` / timestamps).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.custom_fields.models import (
    CustomFieldDefinition,
    FieldSource,
    FieldType,
)
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission


async def _grant(role_id: uuid.UUID, *keys: str) -> None:
    from tests.conftest import TestSession

    async with TestSession() as session:
        for key in keys:
            perm = await register_permission(
                session, key=key, module="custom_fields", description=key
            )
            await session.execute(
                pg_insert(RolePermission)
                .values(role_id=role_id, permission_id=perm.id)
                .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
            )
        await session.commit()


async def _login(client, *, org_slug, email, password) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _seed(org_id: uuid.UUID, rows: list[dict]) -> None:
    from tests.conftest import TestSession

    async with TestSession() as session:
        for row in rows:
            session.add(
                CustomFieldDefinition(
                    id=uuid.uuid4(),
                    org_id=org_id,
                    entity_type=row.get("entity_type", "contact"),
                    field_key=row["field_key"],
                    field_label=row["field_label"],
                    field_type=row.get("field_type", FieldType.text),
                    is_hidden=row.get("is_hidden", False),
                    display_order=row.get("display_order", 0),
                    source=row.get("source", FieldSource.user),
                )
            )
        await session.commit()


@pytest.mark.asyncio
async def test_render_returns_only_non_hidden_ordered(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "custom_fields.read")

    await _seed(
        org.id,
        [
            {"field_key": "c", "field_label": "C", "display_order": 30},
            {"field_key": "a", "field_label": "A", "display_order": 10},
            {"field_key": "b", "field_label": "B", "display_order": 20},
            {
                "field_key": "hidden_one",
                "field_label": "Hidden",
                "display_order": 5,
                "is_hidden": True,
            },
        ],
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.get(
        "/api/v1/custom-fields/contact/render",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    keys = [row["field_key"] for row in body]
    assert keys == ["a", "b", "c"], keys
    assert "hidden_one" not in keys

    # Render payload is slim — no source/id/timestamps.
    sample = body[0]
    assert set(sample.keys()) == {
        "field_key",
        "field_label",
        "field_type",
        "options",
        "is_required",
        "display_order",
        "validation",
    }


@pytest.mark.asyncio
async def test_list_can_include_hidden(layered_client, seeded_admin):
    """The list endpoint honours `include_hidden=true`."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "custom_fields.read")

    await _seed(
        org.id,
        [
            {"field_key": "visible", "field_label": "Visible"},
            {"field_key": "hidden", "field_label": "Hidden", "is_hidden": True},
        ],
    )

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    default = await layered_client.get(
        "/api/v1/custom-fields?entity_type=contact", headers=headers
    )
    visible_only = {row["field_key"] for row in default.json()}
    assert visible_only == {"visible"}

    with_hidden = await layered_client.get(
        "/api/v1/custom-fields?entity_type=contact&include_hidden=true",
        headers=headers,
    )
    keys = {row["field_key"] for row in with_hidden.json()}
    assert keys == {"visible", "hidden"}
