"""Coverage for the entitlement service.

Two layers of tests:

  - **Pure-Python `Entitlements` tests** — instantiate the dataclass
    directly with a stub subscription. No DB. Cover `has_feature`,
    `cap_for`, `is_within_cap`, and `is_read_only` across all four
    canonical plans.
  - **`load_for_org` / `require_feature` / `require_capacity` tests**
    — hit the real test DB via the existing `test_db` fixture so we
    cover the integration: a subscription row in Postgres, the plan
    pulled from `plans.yaml`, and the structured `EntitlementError`
    raised on the right path.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.app.core.subscriptions import plans
from src.app.core.subscriptions.entitlements import (
    Entitlements,
    load_for_org,
    require_capacity,
    require_feature,
)
from src.app.core.subscriptions.exceptions import EntitlementError
from src.app.core.subscriptions.models import Subscription
from src.app.core.subscriptions.plans import KNOWN_FEATURE_KEYS
from src.app.core.tenants.models import Organization


# ---------------------------------------------------------------------------
# Helpers — synthetic entitlements bundles (no DB)
# ---------------------------------------------------------------------------

def _stub_subscription(
    plan_code: str,
    *,
    status: str = "active",
    seats_purchased: int = 5,
    trial_ends_at: datetime | None = None,
) -> Subscription:
    """Build an unpersisted Subscription row with the bare minimum to feed Entitlements."""
    now = datetime.now(tz=timezone.utc)
    return Subscription(
        org_id=uuid.uuid4(),
        plan_code=plan_code,
        status=status,
        billing_cycle="monthly",
        seats_purchased=seats_purchased,
        trial_started_at=now if plan_code == "trial" else None,
        trial_ends_at=trial_ends_at,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )


def _entitlements_for(plan_code: str, **kwargs) -> Entitlements:
    sub = _stub_subscription(plan_code, **kwargs)
    plan = plans.get(plan_code)
    assert plan is not None, f"plan {plan_code!r} missing from registry"
    return Entitlements(org_id=sub.org_id, subscription=sub, plan=plan)


# ---------------------------------------------------------------------------
# Feature gates — pure
# ---------------------------------------------------------------------------

def test_basic_grants_basic_features():
    ent = _entitlements_for("basic")
    assert ent.has_feature("contacts.write") is True
    assert ent.has_feature("walkins.read") is True
    assert ent.has_feature("pipelines.read") is True
    assert ent.has_feature("automation.workflows") is False
    assert ent.has_feature("integrations.whatsapp") is False
    assert ent.has_feature("sso.saml") is False


def test_trial_mirrors_basic_feature_set():
    trial = _entitlements_for("trial")
    basic = _entitlements_for("basic")
    for key in KNOWN_FEATURE_KEYS:
        assert trial.has_feature(key) == basic.has_feature(key), (
            f"feature drift between trial and basic on {key!r}"
        )


def test_standard_unlocks_standard_features():
    ent = _entitlements_for("standard")
    assert ent.has_feature("automation.workflows") is True
    assert ent.has_feature("integrations.whatsapp") is True
    assert ent.has_feature("integrations.email_imap_smtp") is True
    assert ent.has_feature("ads.google_webhook") is True
    assert ent.has_feature("ads.meta_webhook") is True
    assert ent.has_feature("calls.recording") is True
    assert ent.has_feature("campaigns.email") is True
    assert ent.has_feature("sso.saml") is False
    assert ent.has_feature("audit.full_log") is False


def test_enterprise_grants_every_known_feature():
    ent = _entitlements_for("enterprise")
    for key in KNOWN_FEATURE_KEYS:
        assert ent.has_feature(key) is True, f"Enterprise missing {key!r}"


def test_unknown_feature_key_returns_false():
    ent = _entitlements_for("standard")
    assert ent.has_feature("nonexistent.thing") is False


# ---------------------------------------------------------------------------
# Caps — pure
# ---------------------------------------------------------------------------

def test_basic_cap_math():
    ent = _entitlements_for("basic")
    assert ent.cap_for("contacts") == 5000
    assert ent.is_within_cap("contacts", 4999) is True
    assert ent.is_within_cap("contacts", 5000) is False


def test_enterprise_unlimited_cap_always_in():
    ent = _entitlements_for("enterprise")
    assert ent.cap_for("contacts") == -1
    assert ent.is_within_cap("contacts", 999_999_999) is True
    assert ent.is_within_cap("automation_runs_per_month", 1_000_000) is True


def test_unknown_resource_raises_keyerror():
    ent = _entitlements_for("standard")
    with pytest.raises(KeyError):
        ent.cap_for("nonexistent_resource")


# ---------------------------------------------------------------------------
# Status / is_read_only — pure
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "status,expected",
    [
        ("trialing", False),
        ("active", False),
        ("past_due", True),
        ("read_only", True),
        ("archived", True),
        ("cancelled", True),
    ],
)
def test_is_read_only_reflects_status(status, expected):
    ent = _entitlements_for("basic", status=status)
    assert ent.is_read_only is expected


# ---------------------------------------------------------------------------
# Integration tests — load_for_org / require_feature / require_capacity
# ---------------------------------------------------------------------------

import pytest_asyncio  # noqa: E402 — kept beside its fixture for locality


def _make_org(name: str) -> Organization:
    return Organization(id=uuid.uuid4(), name=name, slug=f"{name}-{uuid.uuid4().hex[:6]}")


@pytest_asyncio.fixture
async def trial_org(test_db):
    """Org with a fresh trial subscription."""
    o = _make_org("Trial Co")
    test_db.add(o)
    await test_db.flush()
    now = datetime.now(tz=timezone.utc)
    test_db.add(
        Subscription(
            org_id=o.id,
            plan_code="trial",
            status="trialing",
            billing_cycle="monthly",
            seats_purchased=3,
            trial_started_at=now,
            trial_ends_at=now + timedelta(days=14),
            current_period_start=now,
            current_period_end=now + timedelta(days=14),
        )
    )
    await test_db.commit()
    return o


@pytest_asyncio.fixture
async def basic_org(test_db):
    o = _make_org("Basic Co")
    test_db.add(o)
    await test_db.flush()
    now = datetime.now(tz=timezone.utc)
    test_db.add(
        Subscription(
            org_id=o.id,
            plan_code="basic",
            status="active",
            billing_cycle="monthly",
            seats_purchased=5,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
    )
    await test_db.commit()
    return o


@pytest_asyncio.fixture
async def standard_org(test_db):
    o = _make_org("Standard Co")
    test_db.add(o)
    await test_db.flush()
    now = datetime.now(tz=timezone.utc)
    test_db.add(
        Subscription(
            org_id=o.id,
            plan_code="standard",
            status="active",
            billing_cycle="monthly",
            seats_purchased=5,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
    )
    await test_db.commit()
    return o


@pytest_asyncio.fixture
async def expired_trial_org(test_db):
    """Org whose trial expired — status=read_only, plan_code=trial."""
    o = _make_org("Expired Trial Co")
    test_db.add(o)
    await test_db.flush()
    now = datetime.now(tz=timezone.utc)
    test_db.add(
        Subscription(
            org_id=o.id,
            plan_code="trial",
            status="read_only",
            billing_cycle="monthly",
            seats_purchased=3,
            trial_started_at=now - timedelta(days=15),
            trial_ends_at=now - timedelta(days=1),
            current_period_start=now - timedelta(days=15),
            current_period_end=now - timedelta(days=1),
            read_only_at=now - timedelta(hours=1),
        )
    )
    await test_db.commit()
    return o


@pytest_asyncio.fixture
async def archived_paid_org(test_db):
    """Org that was on Standard then archived."""
    o = _make_org("Archived Co")
    test_db.add(o)
    await test_db.flush()
    now = datetime.now(tz=timezone.utc)
    test_db.add(
        Subscription(
            org_id=o.id,
            plan_code="standard",
            status="archived",
            billing_cycle="monthly",
            seats_purchased=5,
            current_period_start=now - timedelta(days=60),
            current_period_end=now - timedelta(days=30),
            archived_at=now - timedelta(days=10),
        )
    )
    await test_db.commit()
    return o


# ----- load_for_org ----------------------------------------------------------

@pytest.mark.asyncio
async def test_load_for_org_returns_bundle(test_db, basic_org):
    ent = await load_for_org(test_db, basic_org.id)
    assert ent.plan_code == "basic"
    assert ent.is_read_only is False
    assert ent.seats_purchased == 5


@pytest.mark.asyncio
async def test_load_for_org_raises_when_no_active_sub(test_db):
    """An org with no subscription row at all surfaces as `read_only` 402."""
    o = _make_org("Subless Co")
    test_db.add(o)
    await test_db.commit()
    with pytest.raises(EntitlementError) as excinfo:
        await load_for_org(test_db, o.id)
    assert excinfo.value.reason == "read_only"


@pytest.mark.asyncio
async def test_load_for_org_raises_on_unknown_plan_code(test_db):
    """A stale subscription pointing at a removed plan raises loudly."""
    o = _make_org("Stale Plan Co")
    test_db.add(o)
    await test_db.flush()
    now = datetime.now(tz=timezone.utc)
    test_db.add(
        Subscription(
            org_id=o.id,
            plan_code="oldtier",  # not in plans.yaml
            status="active",
            billing_cycle="monthly",
            seats_purchased=5,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
    )
    await test_db.commit()
    with pytest.raises(RuntimeError) as excinfo:
        await load_for_org(test_db, o.id)
    assert "oldtier" in str(excinfo.value)


# ----- require_feature -------------------------------------------------------

@pytest.mark.asyncio
async def test_require_feature_passes_on_entitled_plan(test_db, standard_org):
    await require_feature(test_db, standard_org.id, "automation.workflows")
    # no exception = pass


@pytest.mark.asyncio
async def test_require_feature_raises_feature_locked_on_basic(test_db, basic_org):
    with pytest.raises(EntitlementError) as excinfo:
        await require_feature(test_db, basic_org.id, "automation.workflows")
    err = excinfo.value
    assert err.reason == "feature_locked"
    assert err.required_plan == "standard"


@pytest.mark.asyncio
async def test_require_feature_raises_feature_locked_on_trial(test_db, trial_org):
    """Trial = Basic features → Standard features remain locked."""
    with pytest.raises(EntitlementError) as excinfo:
        await require_feature(test_db, trial_org.id, "integrations.whatsapp")
    assert excinfo.value.reason == "feature_locked"
    assert excinfo.value.required_plan == "standard"


@pytest.mark.asyncio
async def test_require_feature_raises_trial_expired(test_db, expired_trial_org):
    """A trial in read_only state surfaces as `trial_expired`, not plain `read_only`."""
    with pytest.raises(EntitlementError) as excinfo:
        await require_feature(test_db, expired_trial_org.id, "contacts.write")
    assert excinfo.value.reason == "trial_expired"


@pytest.mark.asyncio
async def test_require_feature_raises_read_only_for_archived_paid(test_db, archived_paid_org):
    """An archived previously-paid org surfaces as `read_only`, not `trial_expired`."""
    with pytest.raises(EntitlementError) as excinfo:
        await require_feature(test_db, archived_paid_org.id, "contacts.write")
    assert excinfo.value.reason == "read_only"


# ----- require_capacity ------------------------------------------------------

@pytest.mark.asyncio
async def test_require_capacity_passes_under_cap(test_db, basic_org):
    await require_capacity(test_db, basic_org.id, "contacts", current=4999)


@pytest.mark.asyncio
async def test_require_capacity_raises_at_cap(test_db, basic_org):
    with pytest.raises(EntitlementError) as excinfo:
        await require_capacity(test_db, basic_org.id, "contacts", current=5000)
    err = excinfo.value
    assert err.reason == "cap_reached"
    assert err.resource == "contacts"
    assert err.cap == 5000
    # Suggested upgrade tier should be the next paid plan with a higher contacts cap.
    assert err.required_plan in ("standard", "enterprise")


@pytest.mark.asyncio
async def test_require_capacity_passes_on_unlimited(test_db, basic_org):
    """No org has an unlimited contacts cap on Basic, so build an Enterprise
    org inline and verify the unlimited branch."""
    o = _make_org("Enterprise Co")
    test_db.add(o)
    await test_db.flush()
    now = datetime.now(tz=timezone.utc)
    test_db.add(
        Subscription(
            org_id=o.id,
            plan_code="enterprise",
            status="active",
            billing_cycle="annual",
            seats_purchased=5,
            current_period_start=now,
            current_period_end=now + timedelta(days=365),
        )
    )
    await test_db.commit()
    await require_capacity(test_db, o.id, "contacts", current=999_999)


@pytest.mark.asyncio
async def test_require_capacity_raises_trial_expired_before_cap_check(
    test_db, expired_trial_org
):
    """Read-only short-circuit fires BEFORE the cap math is consulted."""
    with pytest.raises(EntitlementError) as excinfo:
        await require_capacity(test_db, expired_trial_org.id, "contacts", current=0)
    assert excinfo.value.reason == "trial_expired"


# ---------------------------------------------------------------------------
# EntitlementError structured detail
# ---------------------------------------------------------------------------

def test_entitlement_error_detail_shape():
    err = EntitlementError(
        "feature_locked", required_plan="standard"
    )
    assert err.status_code == 402
    assert err.detail["reason"] == "feature_locked"
    assert err.detail["required_plan"] == "standard"
    assert err.detail["resource"] is None
    assert err.detail["cap"] is None
    assert "message" in err.detail
