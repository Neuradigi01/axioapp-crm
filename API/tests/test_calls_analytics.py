"""Analytics coverage for /api/v1/calls/analytics.

Seeds a handful of calls across two outcomes and two days, then asserts
that all three chart-ready arrays (outcomes / daily / direction) are
correctly populated and date-windowed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.calls.models import Call, CallDirection, CallOutcome
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission


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


async def _login(client, *, org_slug, email, password) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _seed_calls(org_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """3 calls on day-2, 2 calls on day-1, mix of outcomes + directions."""
    from tests.conftest import TestSession

    async with TestSession() as session:
        connected = CallOutcome(
            org_id=org_id,
            key="connected",
            label="Connected",
            color="#10b981",
        )
        no_answer = CallOutcome(
            org_id=org_id,
            key="no_answer",
            label="No Answer",
            color="#f59e0b",
        )
        session.add_all([connected, no_answer])
        await session.flush()

        # Anchor "today" at 12:00 UTC so neither end of the window
        # straddles a date boundary.
        today = datetime.now(timezone.utc).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        day_minus_1 = today - timedelta(days=1)
        day_minus_2 = today - timedelta(days=2)

        rows = [
            Call(
                org_id=org_id,
                direction=CallDirection.out,
                started_at=day_minus_2,
                outcome_id=connected.id,
                duration_sec=60,
            ),
            Call(
                org_id=org_id,
                direction=CallDirection.out,
                started_at=day_minus_2,
                outcome_id=connected.id,
                duration_sec=120,
            ),
            Call(
                org_id=org_id,
                direction=CallDirection.in_,
                started_at=day_minus_2,
                outcome_id=no_answer.id,
                duration_sec=0,
            ),
            Call(
                org_id=org_id,
                direction=CallDirection.in_,
                started_at=day_minus_1,
                outcome_id=connected.id,
                duration_sec=45,
            ),
            Call(
                org_id=org_id,
                direction=CallDirection.out,
                started_at=day_minus_1,
                outcome_id=None,
                duration_sec=15,
            ),
        ]
        session.add_all(rows)
        await session.commit()

        return {"connected": connected.id, "no_answer": no_answer.id}


@pytest.mark.asyncio
async def test_analytics_returns_three_arrays(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "calls.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )

    outcomes = await _seed_calls(org.id)

    today = datetime.now(timezone.utc).date()
    frm = (today - timedelta(days=3)).isoformat()
    to = today.isoformat()

    resp = await layered_client.get(
        f"/api/v1/calls/analytics?from={frm}&to={to}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["from"] == frm
    assert body["to"] == to

    # Outcomes distribution — 3 connected, 1 no_answer, 1 unassigned.
    by_key = {row["outcome_key"]: row for row in body["outcomes"]}
    assert by_key["connected"]["count"] == 3
    assert by_key["no_answer"]["count"] == 1
    # The unassigned row carries outcome_key=null.
    null_row = next(r for r in body["outcomes"] if r["outcome_key"] is None)
    assert null_row["count"] == 1

    # Daily volume — 3 on day-2, 2 on day-1.
    counts_by_day = {row["day"]: row["count"] for row in body["daily"]}
    assert sum(counts_by_day.values()) == 5
    assert max(counts_by_day.values()) == 3

    # Direction split — 3 out + 2 in.
    by_direction = {r["direction"]: r["count"] for r in body["direction"]}
    assert by_direction.get("out") == 3
    assert by_direction.get("in") == 2

    # Pin the second outcome to ensure it wasn't dropped.
    assert str(outcomes["connected"]) in {
        r["outcome_id"] for r in body["outcomes"] if r["outcome_id"]
    }


@pytest.mark.asyncio
async def test_analytics_window_filters_out_of_range(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "calls.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    await _seed_calls(org.id)

    today = datetime.now(timezone.utc).date()
    # Far in the past — nothing should match.
    frm = (today - timedelta(days=100)).isoformat()
    to = (today - timedelta(days=50)).isoformat()
    resp = await layered_client.get(
        f"/api/v1/calls/analytics?from={frm}&to={to}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["outcomes"] == []
    assert body["daily"] == []
    assert body["direction"] == []


@pytest.mark.asyncio
async def test_analytics_inverted_window_returns_400(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "calls.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.get(
        "/api/v1/calls/analytics?from=2026-05-13&to=2026-05-01",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400, resp.text
