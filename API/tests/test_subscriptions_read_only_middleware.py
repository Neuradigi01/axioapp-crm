"""Tests for `SubscriptionStateMiddleware` (Step 10).

Each test seeds an org + a subscription in a specific status, logs the
user in to get a JWT, then probes one HTTP endpoint and asserts the
middleware's behaviour by status code.

Distinguishing "middleware blocked" from "handler ran" relies on the
fact that 402 with a `reason` field is only emitted by the middleware
itself — every other code path that produces 402 in this codebase
(entitlement service) emits a `reason` matching the EntitlementError
schema (also fine, but the body shape is identical so the test asserts
on the wire content's `reason` field).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.app.core.subscriptions.models import Subscription

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _login(client, *, email, password, org_slug) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _login_seeded(client, seeded_admin) -> str:
    return await _login(
        client,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
        org_slug=seeded_admin["org"].slug,
    )


async def _insert_subscription(
    org_id: uuid.UUID,
    *,
    plan_code: str,
    status: str,
    billing_cycle: str = "monthly",
    seats_purchased: int = 5,
    trial_started_at: datetime | None = None,
    trial_ends_at: datetime | None = None,
    current_period_start: datetime | None = None,
    current_period_end: datetime | None = None,
    read_only_at: datetime | None = None,
    archived_at: datetime | None = None,
    cancelled_at: datetime | None = None,
) -> uuid.UUID:
    from tests.conftest import TestSession

    now = datetime.now(tz=UTC)
    cps = current_period_start or trial_started_at or now
    cpe = current_period_end or trial_ends_at or (now + timedelta(days=30))

    async with TestSession() as session:
        sub = Subscription(
            org_id=org_id,
            plan_code=plan_code,
            status=status,
            billing_cycle=billing_cycle,
            seats_purchased=seats_purchased,
            trial_started_at=trial_started_at,
            trial_ends_at=trial_ends_at,
            current_period_start=cps,
            current_period_end=cpe,
            read_only_at=read_only_at,
            archived_at=archived_at,
            cancelled_at=cancelled_at,
        )
        session.add(sub)
        await session.commit()
        await session.refresh(sub)
        return sub.id


# Minimal POST endpoint we probe to differentiate "middleware blocked"
# from "handler reached." `/api/v1/contacts` requires `contacts.write`
# permission — the seeded admin lacks it (no permissions seeded), so
# the handler responds with 403. That's fine: the test only needs to
# know whether the response was 402 (middleware blocked) or 403/422/…
# (middleware passed through).
_PROBE_PATH = "/api/v1/contacts"
_PROBE_BODY = {"first_name": "X", "last_name": "Y"}


async def _probe_write(client, token: str | None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return await client.post(_PROBE_PATH, headers=headers, json=_PROBE_BODY)


# ---------------------------------------------------------------------------
# Read endpoints — never blocked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_endpoint_passes_on_read_only_org(
    layered_client,
    seeded_admin,
):
    org = seeded_admin["org"]
    now = datetime.now(tz=UTC)
    await _insert_subscription(
        org.id,
        plan_code="trial",
        status="read_only",
        trial_started_at=now - timedelta(days=15),
        trial_ends_at=now - timedelta(days=1),
        read_only_at=now - timedelta(hours=1),
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await layered_client.get(
        "/api/v1/subscriptions/current",
        headers={"Authorization": f"Bearer {token}"},
    )
    # GET is never blocked — handler ran and returned the composed
    # subscription read body (200) or 4xx for some unrelated reason.
    # The only forbidden code is 402 from this middleware.
    assert resp.status_code != 402, resp.text


# ---------------------------------------------------------------------------
# Write endpoint blocked across the four blocked statuses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,plan_code",
    [
        ("read_only", "trial"),
        ("past_due", "basic"),
        ("archived", "basic"),
        ("cancelled", "basic"),
    ],
)
async def test_write_endpoint_blocked_on_blocked_status(
    layered_client,
    seeded_admin,
    status,
    plan_code,
):
    org = seeded_admin["org"]
    now = datetime.now(tz=UTC)
    timestamps = {}
    if status == "read_only":
        timestamps["read_only_at"] = now - timedelta(hours=1)
    elif status == "archived":
        timestamps["archived_at"] = now - timedelta(days=1)
    elif status == "cancelled":
        timestamps["cancelled_at"] = now - timedelta(days=1)
    await _insert_subscription(
        org.id,
        plan_code=plan_code,
        status=status,
        current_period_start=now - timedelta(days=30),
        current_period_end=now + timedelta(days=1),
        **timestamps,
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _probe_write(layered_client, token)
    assert resp.status_code == 402, resp.text
    body = resp.json()
    assert body["reason"] == status
    assert body["subscription_status"] == status
    assert body["upgrade_url"] == "/user/settings/billing"


# ---------------------------------------------------------------------------
# Allow-list endpoints still reach the handler on a blocked sub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allowlist_subscriptions_change_reaches_handler(
    layered_client,
    seeded_admin,
):
    org = seeded_admin["org"]
    now = datetime.now(tz=UTC)
    await _insert_subscription(
        org.id,
        plan_code="trial",
        status="read_only",
        seats_purchased=3,
        trial_started_at=now - timedelta(days=15),
        trial_ends_at=now - timedelta(days=1),
        read_only_at=now - timedelta(hours=1),
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await layered_client.post(
        "/api/v1/subscriptions/change",
        headers={"Authorization": f"Bearer {token}"},
        json={"to_plan": "basic", "billing_cycle": "monthly", "seats": 5},
    )
    # Handler reaches change_plan, recognises the recovery upgrade,
    # responds with needs_payment. Critical: NOT 402 from middleware.
    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"] == "needs_payment"


@pytest.mark.asyncio
async def test_allowlist_logout_reaches_handler_on_read_only(
    layered_client,
    seeded_admin,
):
    org = seeded_admin["org"]
    now = datetime.now(tz=UTC)
    await _insert_subscription(
        org.id,
        plan_code="trial",
        status="read_only",
        trial_started_at=now - timedelta(days=15),
        trial_ends_at=now - timedelta(days=1),
        read_only_at=now - timedelta(hours=1),
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await layered_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code != 402, resp.text


@pytest.mark.asyncio
async def test_signup_not_blocked_by_stale_read_only_token(
    layered_client,
    seeded_admin,
):
    """Registering a brand-new account must work even when the browser
    still carries a token for a `read_only` org.

    The SPA's auth interceptor attaches the stored JWT to every request,
    signup included, so `TenantContextMiddleware` resolves `org_id` to
    the OLD org and the middleware used to answer 402 "Your trial has
    ended" on a flow that has nothing to do with that org. The new
    account is a different tenant entirely.
    """
    org = seeded_admin["org"]
    now = datetime.now(tz=UTC)
    await _insert_subscription(
        org.id,
        plan_code="trial",
        status="read_only",
        trial_started_at=now - timedelta(days=15),
        trial_ends_at=now - timedelta(days=1),
        read_only_at=now - timedelta(hours=1),
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await layered_client.post(
        "/api/v1/auth/register",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "first_name": "Stale",
            "last_name": "Token",
            "email": "stale.token.signup@example.com",
            "mobile": "+915554545299",
            "password": "dJMRR!ffV9aka2B",
            "confirm_password": "dJMRR!ffV9aka2B",
            "country": "India",
            "state": "Maharashtra",
        },
    )
    assert resp.status_code != 402, resp.text


@pytest.mark.asyncio
async def test_password_reset_not_blocked_on_read_only(
    layered_client,
    seeded_admin,
):
    """Password recovery must stay reachable on a write-locked org —
    it is identity-level, and locking it would strand the user outside
    the account they need in order to pay."""
    org = seeded_admin["org"]
    now = datetime.now(tz=UTC)
    await _insert_subscription(
        org.id,
        plan_code="trial",
        status="read_only",
        trial_started_at=now - timedelta(days=15),
        trial_ends_at=now - timedelta(days=1),
        read_only_at=now - timedelta(hours=1),
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await layered_client.post(
        "/api/v1/auth/forgot-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"identifier": seeded_admin["user"].email},
    )
    assert resp.status_code != 402, resp.text


# ---------------------------------------------------------------------------
# Active / trialing subs pass write routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_sub_passes_write_route(layered_client, seeded_admin):
    org = seeded_admin["org"]
    await _insert_subscription(org.id, plan_code="basic", status="active")

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _probe_write(layered_client, token)
    # The middleware must NOT 402 — actual handler outcome is whatever
    # `/contacts` does with the seeded admin's permissions (likely 403).
    assert resp.status_code != 402, resp.text


@pytest.mark.asyncio
async def test_trialing_sub_passes_write_route(layered_client, seeded_admin):
    """`trialing` is NOT a blocked status — the trial customer must be
    able to write data they will keep when they upgrade."""
    org = seeded_admin["org"]
    now = datetime.now(tz=UTC)
    await _insert_subscription(
        org.id,
        plan_code="trial",
        status="trialing",
        seats_purchased=3,
        trial_started_at=now,
        trial_ends_at=now + timedelta(days=14),
    )

    token = await _login_seeded(layered_client, seeded_admin)
    resp = await _probe_write(layered_client, token)
    assert resp.status_code != 402, resp.text


# ---------------------------------------------------------------------------
# Anonymous requests are not blocked here — auth dependency owns 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_request_passes_through(layered_client):
    """The middleware has no JWT to read; it must defer to the per-route
    auth dependency. Probing `/auth/login` is the cleanest case — it
    has no auth requirement of its own."""
    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={
            "email": "nobody@demo.local",
            "password": "wrong",
            "org_slug": "no-such-org",
        },
    )
    # Login itself returns 401 for bad creds — that's the handler
    # reaching its own auth check, not the middleware short-circuiting.
    assert resp.status_code != 402, resp.text
