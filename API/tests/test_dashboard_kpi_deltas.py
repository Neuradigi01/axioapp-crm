"""HTTP coverage for `/dashboard/summary` period-over-period deltas.

Three end-to-end scenarios driven through the layered FastAPI app:

  1. **Growth** — org scope: 5 leads created today, 4 yesterday.
     The `leads.new_today` card carries `previous_value=4`,
     `delta_pct=25.0`, `delta_direction="up"`.
  2. **Flat** — personal scope: 1 appointment today, 1 yesterday for the
     caller. The `appointments.my_today` card carries
     `delta_pct=0.0`, `delta_direction="flat"`.
  3. **Zero baseline** — org scope: 3 leads today, none yesterday. The
     `leads.new_today` card carries `previous_value=0`,
     `delta_pct=100.0`, `delta_direction="up"` (no division-by-zero).

Also asserts the `top_performers` leaderboard card returns explicit
`null` deltas — those fields are reserved for scalar formats only.

Run with: ``uv run pytest tests/test_dashboard_kpi_deltas.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.appointments.models import Appointment, AppointmentStatus
from src.app.core.contacts.models import Contact
from src.app.core.leads.models import Lead, LeadStatus
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


async def _make_contact(org_id: uuid.UUID, *, full_name: str) -> uuid.UUID:
    """Insert a minimal contact via the ORM so leads / appointments can
    reference it. Avoids the HTTP create path (which needs permissions
    and JSON shaping unrelated to the delta logic under test).
    """
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
    """Insert a lead with an explicit `created_at`. The HTTP path uses
    `now()` server-side; for deltas we need to seed precise yesterday /
    today / 30d-ago timestamps.
    """
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


async def _make_appointment(
    org_id: uuid.UUID,
    *,
    contact_id: uuid.UUID,
    scheduled_at: datetime,
    assigned_to_id: uuid.UUID,
) -> None:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            appt = Appointment(
                org_id=org_id,
                contact_id=contact_id,
                title="Demo appointment",
                scheduled_at=scheduled_at,
                duration_min=30,
                status=AppointmentStatus.scheduled,
                assigned_to_id=assigned_to_id,
            )
            session.add(appt)
            await session.commit()
    finally:
        reset_context(token)


def _find_card(cards: list[dict], key: str) -> dict:
    matches = [c for c in cards if c["key"] == key]
    assert matches, f"card {key!r} not present in payload"
    return matches[0]


@pytest.mark.asyncio
async def test_org_scope_growth_delta_up(layered_client, seeded_admin):
    """5 leads today vs 4 yesterday → +25 % up arrow."""
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
    now = datetime.now(UTC)
    today_noon = datetime(now.year, now.month, now.day, 12, 0, tzinfo=UTC)
    yesterday_noon = today_noon - timedelta(days=1)

    for _ in range(5):
        await _make_lead(org.id, contact_id=contact_id, created_at=today_noon)
    for _ in range(4):
        await _make_lead(org.id, contact_id=contact_id, created_at=yesterday_noon)

    res = await layered_client.get("/api/v1/dashboard/summary", headers=headers)
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["scope"] == "org"

    card = _find_card(payload["cards"], "leads.new_today")
    assert card["value"] == 5
    assert card["previous_value"] == 4
    assert card["delta_pct"] == 25.0
    assert card["delta_direction"] == "up"


@pytest.mark.asyncio
async def test_personal_scope_flat_delta(layered_client, seeded_admin):
    """1 appointment today vs 1 yesterday for the caller → flat 0 %."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # No `users.read` granted → personal scope.
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    contact_id = await _make_contact(org.id, full_name="Anchor")
    now = datetime.now(UTC)
    today_noon = datetime(now.year, now.month, now.day, 12, 0, tzinfo=UTC)
    yesterday_noon = today_noon - timedelta(days=1)

    await _make_appointment(
        org.id,
        contact_id=contact_id,
        scheduled_at=today_noon,
        assigned_to_id=user.legacy_uuid,
    )
    await _make_appointment(
        org.id,
        contact_id=contact_id,
        scheduled_at=yesterday_noon,
        assigned_to_id=user.legacy_uuid,
    )

    res = await layered_client.get("/api/v1/dashboard/summary", headers=headers)
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["scope"] == "personal"

    card = _find_card(payload["cards"], "appointments.my_today")
    assert card["value"] == 1
    assert card["previous_value"] == 1
    assert card["delta_pct"] == 0.0
    assert card["delta_direction"] == "flat"


@pytest.mark.asyncio
async def test_org_scope_zero_baseline_delta_up(layered_client, seeded_admin):
    """3 leads today vs none yesterday → +100 % up, no division-by-zero."""
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
    now = datetime.now(UTC)
    today_noon = datetime(now.year, now.month, now.day, 12, 0, tzinfo=UTC)

    for _ in range(3):
        await _make_lead(org.id, contact_id=contact_id, created_at=today_noon)

    res = await layered_client.get("/api/v1/dashboard/summary", headers=headers)
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["scope"] == "org"

    card = _find_card(payload["cards"], "leads.new_today")
    assert card["value"] == 3
    assert card["previous_value"] == 0
    assert card["delta_pct"] == 100.0
    assert card["delta_direction"] == "up"

    # And every scalar card has all three delta fields populated, while
    # the leaderboard (`top_performers`) — when present — leaves them as
    # explicit nulls. `top_performers` is omitted when no leads exist
    # this week, so we only assert when it's there.
    for card in payload["cards"]:
        if card["format"] in {"number", "currency", "percent"}:
            assert card["previous_value"] is not None, card["key"]
            assert card["delta_pct"] is not None, card["key"]
            assert card["delta_direction"] in {"up", "down", "flat"}, card["key"]
        elif card["format"] == "leaderboard":
            assert card["previous_value"] is None
            assert card["delta_pct"] is None
            assert card["delta_direction"] is None
