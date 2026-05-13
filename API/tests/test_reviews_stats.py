"""Stats coverage for /api/v1/reviews/stats."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.reviews.models import Review, ReviewStatus


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


async def _seed_reviews(org_id: uuid.UUID) -> None:
    """5★, 5★, 4★, 2★ (recent), 1★ (old) — 5 total."""
    from tests.conftest import TestSession

    now = datetime.now(timezone.utc)
    async with TestSession() as session:
        session.add_all([
            Review(org_id=org_id, source="google", rating=5,
                   text="Loved it",   status=ReviewStatus.replied),
            Review(org_id=org_id, source="google", rating=5,
                   text="Excellent",  status=ReviewStatus.pending_reply),
            Review(org_id=org_id, source="facebook", rating=4,
                   text="Good",       status=ReviewStatus.pending_reply),
            Review(org_id=org_id, source="google", rating=2,
                   text="Slow delivery", status=ReviewStatus.pending_reply,
                   created_at=now - timedelta(days=1)),
            Review(org_id=org_id, source="google", rating=1,
                   text="Old gripe", status=ReviewStatus.escalated,
                   created_at=now - timedelta(days=30)),
        ])
        await session.commit()


@pytest.mark.asyncio
async def test_stats_returns_chart_ready_payload(
    layered_client, seeded_admin
):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "reviews.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    await _seed_reviews(org.id)

    resp = await layered_client.get(
        "/api/v1/reviews/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["total"] == 5
    # avg = (5+5+4+2+1)/5 = 3.4
    assert body["average_rating"] == 3.4
    # responded = replied + escalated = 2; response_rate = 40%
    assert body["response_rate_pct"] == 40.0

    by_rating = {row["rating"]: row["count"] for row in body["distribution"]}
    assert by_rating == {1: 1, 2: 1, 4: 1, 5: 2}

    assert body["pending_count"] == 3  # 5★(2nd), 4★, 2★

    # Alerts: rating <= 3 AND created_at >= now - 7 days → only the 2★
    # row (1★ row is 30 days old).
    assert body["alerts_last_7_days"] == 1


@pytest.mark.asyncio
async def test_stats_empty_returns_zeros(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "reviews.read")
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.get(
        "/api/v1/reviews/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["average_rating"] == 0.0
    assert body["response_rate_pct"] == 0.0
    assert body["distribution"] == []
    assert body["pending_count"] == 0
    assert body["alerts_last_7_days"] == 0
