"""HTTP-level coverage for the lead-scoring engine (Step 5):

- POST /leads/scoring-rules + condition validation
- score recompute on create / update
- permission gate on scoring-rule CRUD
- rule with multiple matches sums + clamps at 100
- scoring rules can't reference contact-joined fields
- bulk recompute endpoint reports the touched count
"""

from __future__ import annotations

import pytest

from tests.test_leads_crud import (
    _grant,
    _login,
    _seed_contact,
    _seed_leads_pipeline,
)


async def _create_rule(client, headers, *, name, condition, points, active=True):
    resp = await client.post(
        "/api/v1/leads/scoring-rules",
        json={
            "name": name,
            "condition": condition,
            "points": points,
            "active": active,
        },
        headers=headers,
    )
    return resp


async def _create_lead(client, headers, *, contact_id, stage="new", budget=None):
    body: dict = {"contact_id": str(contact_id), "pipeline_stage": stage}
    if budget is not None:
        body["budget"] = str(budget)
    resp = await client.post("/api/v1/leads", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_rule_create_and_lead_score_on_write(layered_client, seeded_admin):
    """Adding a rule then creating a matching lead lands ``lead_score == rule.points``."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "leads.read",
        "leads.write",
        "leads.scoring.manage",
    )
    await _seed_leads_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await _create_rule(
        layered_client,
        headers,
        name="Active wins points",
        condition={"all": [{"field": "status", "op": "eq", "value": "active"}]},
        points=30,
    )
    assert resp.status_code == 201, resp.text

    contact_id = await _seed_contact(org.id)
    lead = await _create_lead(layered_client, headers, contact_id=contact_id)
    assert lead["lead_score"] == 30


@pytest.mark.asyncio
async def test_multiple_rules_sum_and_clamp(layered_client, seeded_admin):
    """Two matching rules sum; the engine clamps to 100."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "leads.read",
        "leads.write",
        "leads.scoring.manage",
    )
    await _seed_leads_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    for name, points in [
        ("Active 70", 70),
        ("Active 60", 60),
    ]:
        resp = await _create_rule(
            layered_client,
            headers,
            name=name,
            condition={"all": [{"field": "status", "op": "eq", "value": "active"}]},
            points=points,
        )
        assert resp.status_code == 201

    contact_id = await _seed_contact(org.id)
    lead = await _create_lead(layered_client, headers, contact_id=contact_id)
    # 70 + 60 = 130; clamped at 100.
    assert lead["lead_score"] == 100


@pytest.mark.asyncio
async def test_inactive_rule_does_not_score(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "leads.read",
        "leads.write",
        "leads.scoring.manage",
    )
    await _seed_leads_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    await _create_rule(
        layered_client,
        headers,
        name="Sleeping rule",
        condition={"all": [{"field": "status", "op": "eq", "value": "active"}]},
        points=50,
        active=False,
    )
    contact_id = await _seed_contact(org.id)
    lead = await _create_lead(layered_client, headers, contact_id=contact_id)
    assert lead["lead_score"] == 0


@pytest.mark.asyncio
async def test_scoring_rule_rejects_contact_joined_field(layered_client, seeded_admin):
    """``contact_name`` is contact-joined and not in-memory evaluable;
    using it in a rule condition must be 422."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.scoring.manage")
    await _seed_leads_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    resp = await _create_rule(
        layered_client,
        headers,
        name="Bad rule",
        condition={"all": [{"field": "contact_name", "op": "eq", "value": "John"}]},
        points=10,
    )
    assert resp.status_code == 422
    assert "contact-joined" in resp.text


@pytest.mark.asyncio
async def test_scoring_rule_requires_permission(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # No leads.scoring.manage granted.
    await _grant(seeded_admin["role"].id, "leads.read")
    await _seed_leads_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    for method, path in [
        ("get", "/api/v1/leads/scoring-rules"),
        ("post", "/api/v1/leads/scoring-rules"),
        ("post", "/api/v1/leads/scoring-rules/recompute"),
    ]:
        if method == "get":
            resp = await layered_client.get(path, headers=headers)
        else:
            resp = await layered_client.post(
                path,
                json={
                    "name": "X",
                    "condition": {"all": []},
                    "points": 10,
                },
                headers=headers,
            )
        assert resp.status_code == 403, f"{method.upper()} {path}"


@pytest.mark.asyncio
async def test_recompute_endpoint_returns_touched_count(layered_client, seeded_admin):
    """After flipping a rule's points, the recompute endpoint reports
    how many lead rows changed."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "leads.read",
        "leads.write",
        "leads.scoring.manage",
    )
    await _seed_leads_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Seed 2 leads with no rules → score=0.
    for i in range(2):
        contact_id = await _seed_contact(org.id, full_name=f"R{i}")
        lead = await _create_lead(layered_client, headers, contact_id=contact_id)
        assert lead["lead_score"] == 0

    # Add a rule that grants 40 points to every active lead.
    rule_resp = await _create_rule(
        layered_client,
        headers,
        name="Active = 40",
        condition={"all": [{"field": "status", "op": "eq", "value": "active"}]},
        points=40,
    )
    assert rule_resp.status_code == 201

    # The leads were created BEFORE the rule, so their score is still
    # 0. Recompute should touch both.
    recompute = await layered_client.post("/api/v1/leads/scoring-rules/recompute", headers=headers)
    assert recompute.status_code == 200, recompute.text
    assert recompute.json()["touched"] == 2

    # Re-list and verify scores are now 40.
    listed = await layered_client.get("/api/v1/leads", headers=headers)
    for item in listed.json()["items"]:
        assert item["lead_score"] == 40
