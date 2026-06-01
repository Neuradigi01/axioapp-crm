"""HTTP-level coverage for the Step 5 power-list features:

  - cursor + offset pagination on GET /leads
  - filter DSL (status/source/budget/custom_data) via the ``filter``
    query param
  - GET /leads/export.csv streaming endpoint
  - 422 on malformed filter / 403 on missing ``leads.export``

Shares the seed helpers from ``test_leads_crud`` (pipeline + contact)
so the focus stays on the new behaviour.
"""
from __future__ import annotations

import json
import uuid

import pytest

from tests.test_leads_crud import (
    _grant,
    _login,
    _seed_contact,
    _seed_leads_pipeline,
)


async def _create_lead(client, headers, *, contact_id, stage="new", budget=None):
    body: dict = {"contact_id": str(contact_id), "pipeline_stage": stage}
    if budget is not None:
        body["budget"] = str(budget)
    resp = await client.post("/api/v1/leads", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_offset_response_carries_total_page_size_and_next_cursor(
    layered_client, seeded_admin
):
    """Offset-mode callers still get the legacy shape, plus ``next_cursor``
    when there's another page."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Seed 6 leads so a size=2 page leaves a next_cursor.
    for i in range(6):
        contact_id = await _seed_contact(org.id, full_name=f"Lead {i}")
        await _create_lead(layered_client, headers, contact_id=contact_id)

    resp = await layered_client.get("/api/v1/leads?size=2", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 6
    assert body["page"] == 1
    assert body["size"] == 2
    assert len(body["items"]) == 2
    assert body["next_cursor"] is not None


@pytest.mark.asyncio
async def test_cursor_walk_exhausts_set(layered_client, seeded_admin):
    """Walking ``next_cursor`` until null yields every row exactly once."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    seeded_ids: set[str] = set()
    for i in range(13):
        contact_id = await _seed_contact(org.id, full_name=f"Walk {i:02d}")
        seeded_ids.add(
            (await _create_lead(layered_client, headers, contact_id=contact_id))["id"]
        )

    seen: set[str] = set()
    cursor: str | None = None
    pages = 0
    while True:
        url = "/api/v1/leads?limit=5&with_total=false"
        if cursor is not None:
            url += f"&cursor={cursor}"
        resp = await layered_client.get(url, headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        for item in body["items"]:
            assert item["id"] not in seen, "cursor walk yielded a duplicate"
            seen.add(item["id"])
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
        assert pages < 10, "cursor walk did not terminate"

    assert seen == seeded_ids


@pytest.mark.asyncio
async def test_with_total_false_omits_count(layered_client, seeded_admin):
    """``with_total=false`` lets clients skip the COUNT — total is None."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    contact_id = await _seed_contact(org.id)
    await _create_lead(layered_client, headers, contact_id=contact_id)

    resp = await layered_client.get(
        "/api/v1/leads?with_total=false", headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["total"] is None


@pytest.mark.asyncio
async def test_filter_dsl_status_qualified(layered_client, seeded_admin):
    """``filter={"all":[{"field":"status","op":"eq","value":"active"}]}`` filters."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    for i in range(3):
        contact_id = await _seed_contact(org.id, full_name=f"F{i}")
        await _create_lead(layered_client, headers, contact_id=contact_id)

    dsl = {"all": [{"field": "status", "op": "eq", "value": "active"}]}
    resp = await layered_client.get(
        f"/api/v1/leads?filter={json.dumps(dsl)}", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 3


@pytest.mark.asyncio
async def test_filter_dsl_unknown_field_rejected(layered_client, seeded_admin):
    """An unknown field is 422 with a pointer."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read")
    await _seed_leads_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    dsl = {"all": [{"field": "not_a_field", "op": "eq", "value": "x"}]}
    resp = await layered_client.get(
        f"/api/v1/leads?filter={json.dumps(dsl)}", headers=headers
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_filter_dsl_invalid_json_rejected(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read")
    await _seed_leads_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await layered_client.get(
        "/api/v1/leads?filter=not-json", headers=headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_csv_export_streams_filtered_rows(layered_client, seeded_admin):
    """Export returns text/csv with one row per matching lead +
    Excel-safe phone."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id, "leads.read", "leads.write", "leads.export"
    )
    await _seed_leads_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    for i in range(4):
        contact_id = await _seed_contact(org.id, full_name=f"Export {i}")
        await _create_lead(layered_client, headers, contact_id=contact_id)

    resp = await layered_client.get("/api/v1/leads/export.csv", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    body = resp.text
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert len(lines) == 5  # header + 4 rows
    assert lines[0].startswith("id,contact_name,contact_phone,contact_email,")
    # Phone column is Excel-safe-prefixed.
    assert '="+91' in body


@pytest.mark.asyncio
async def test_csv_export_requires_permission(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # leads.read only — no leads.export.
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    await _seed_leads_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    resp = await layered_client.get("/api/v1/leads/export.csv", headers=headers)
    assert resp.status_code == 403
