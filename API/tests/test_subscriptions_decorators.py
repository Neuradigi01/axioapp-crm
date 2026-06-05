"""Coverage for the FastAPI entitlement decorators.

Step 4 ships the decorator mechanism only — no production route uses
``@requires_feature`` / ``@enforces_cap`` yet. These tests exercise:

  - ``requires_feature`` against Basic, Standard, and Trial orgs.
  - ``enforces_cap`` at, below, and on unlimited caps.
  - Sync and async ``current_provider`` callables.
  - Stacking both decorators on one handler.
  - The wrapper's signature mutation preserves FastAPI's async
    dispatch, including path and query parameters.

The tests build minimal FastAPI apps per scenario and override the
``get_entitlements`` dependency with synthetic ``Entitlements`` bundles.
No DB, no auth machinery — pure unit coverage of the decorator
contract.

An end-to-end smoke (mounting a real route and calling it from a Basic
user's JWT) becomes possible only after Step 7 exposes the
subscription-read API so we can confirm which plan the test user is on.
Until then the decorator's correctness is established here, against
deterministic synthetic bundles.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.core.subscriptions import plans
from src.app.core.subscriptions.decorators import enforces_cap, requires_feature
from src.app.core.subscriptions.dependencies import get_entitlements
from src.app.core.subscriptions.entitlements import Entitlements
from src.app.core.subscriptions.models import Subscription


# ---------------------------------------------------------------------------
# Helpers — synthetic entitlements + test-app wiring
# ---------------------------------------------------------------------------

def _stub_entitlements(
    plan_code: str, *, status: str = "active", seats_purchased: int = 5
) -> Entitlements:
    """Build an unpersisted Subscription + matching Plan, wrap in Entitlements."""
    now = datetime.now(tz=timezone.utc)
    sub = Subscription(
        org_id=uuid.uuid4(),
        plan_code=plan_code,
        status=status,
        billing_cycle="monthly",
        seats_purchased=seats_purchased,
        trial_started_at=now if plan_code == "trial" else None,
        trial_ends_at=now + timedelta(days=14) if plan_code == "trial" else None,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )
    plan = plans.get(plan_code)
    assert plan is not None, f"plan {plan_code!r} missing from registry"
    return Entitlements(org_id=sub.org_id, subscription=sub, plan=plan)


def _client_with_entitlements(app: FastAPI, ent: Entitlements) -> TestClient:
    """Wire ``app`` so ``get_entitlements`` returns ``ent`` for every request."""
    app.dependency_overrides[get_entitlements] = lambda: ent
    return TestClient(app)


# ---------------------------------------------------------------------------
# requires_feature
# ---------------------------------------------------------------------------

def test_requires_feature_blocks_basic_for_locked_feature():
    app = FastAPI()

    @app.post("/workflow")
    @requires_feature("automation.workflows")
    async def create_workflow():
        return {"ok": True}

    client = _client_with_entitlements(app, _stub_entitlements("basic"))
    response = client.post("/workflow")

    assert response.status_code == 402
    detail = response.json()["detail"]
    assert detail["reason"] == "feature_locked"
    assert detail["required_plan"] == "standard"
    assert detail["resource"] is None
    assert detail["cap"] is None
    assert "Standard" in detail["message"]


def test_requires_feature_passes_when_plan_grants_it():
    app = FastAPI()

    @app.post("/workflow")
    @requires_feature("automation.workflows")
    async def create_workflow():
        return {"ok": True}

    client = _client_with_entitlements(app, _stub_entitlements("standard"))
    response = client.post("/workflow")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_requires_feature_blocks_trial_for_standard_feature():
    """Trial mirrors Basic — Standard-tier features stay locked."""
    app = FastAPI()

    @app.post("/whatsapp")
    @requires_feature("integrations.whatsapp")
    async def connect_whatsapp():
        return {"ok": True}

    client = _client_with_entitlements(
        app,
        _stub_entitlements("trial", status="trialing", seats_purchased=3),
    )
    response = client.post("/whatsapp")

    assert response.status_code == 402
    detail = response.json()["detail"]
    assert detail["reason"] == "feature_locked"
    assert detail["required_plan"] == "standard"


# ---------------------------------------------------------------------------
# enforces_cap
# ---------------------------------------------------------------------------

def test_enforces_cap_blocks_at_limit():
    """Basic plan's contacts cap = 5000; a current count of 5000 means the
    next write would push to 5001, which exceeds the cap."""
    app = FastAPI()

    @app.post("/contact")
    @enforces_cap("contacts", current_provider=lambda _org: 5000)
    async def create_contact():
        return {"ok": True}

    client = _client_with_entitlements(app, _stub_entitlements("basic"))
    response = client.post("/contact")

    assert response.status_code == 402
    detail = response.json()["detail"]
    assert detail["reason"] == "cap_reached"
    assert detail["resource"] == "contacts"
    assert detail["cap"] == 5000
    assert detail["required_plan"] in {"standard", "enterprise"}


def test_enforces_cap_passes_below_limit():
    app = FastAPI()

    @app.post("/contact")
    @enforces_cap("contacts", current_provider=lambda _org: 4999)
    async def create_contact():
        return {"ok": True}

    client = _client_with_entitlements(app, _stub_entitlements("basic"))
    response = client.post("/contact")
    assert response.status_code == 200


def test_enforces_cap_always_passes_on_unlimited_plan():
    """Enterprise contacts cap = -1 (unlimited); the provider should not even
    matter for the boundary, but for explicitness we pass a huge count."""
    app = FastAPI()

    @app.post("/contact")
    @enforces_cap("contacts", current_provider=lambda _org: 999_999_999)
    async def create_contact():
        return {"ok": True}

    client = _client_with_entitlements(app, _stub_entitlements("enterprise"))
    response = client.post("/contact")
    assert response.status_code == 200


def test_enforces_cap_skips_provider_on_unlimited_plan():
    """Unlimited caps short-circuit BEFORE the provider runs — the production
    cost saving the spec calls out (provider may hit the DB)."""
    app = FastAPI()
    provider_was_called = {"value": False}

    def explosive_provider(_org_id):
        provider_was_called["value"] = True
        raise AssertionError("provider must not run when cap is unlimited")

    @app.post("/contact")
    @enforces_cap("contacts", current_provider=explosive_provider)
    async def create_contact():
        return {"ok": True}

    client = _client_with_entitlements(app, _stub_entitlements("enterprise"))
    response = client.post("/contact")
    assert response.status_code == 200
    assert provider_was_called["value"] is False


def test_enforces_cap_supports_async_provider():
    """Production providers are async (they hit the DB). Verify the wrapper
    awaits them correctly."""
    app = FastAPI()

    async def async_count(_org_id):
        return 4999

    @app.post("/contact")
    @enforces_cap("contacts", current_provider=async_count)
    async def create_contact():
        return {"ok": True}

    client = _client_with_entitlements(app, _stub_entitlements("basic"))
    response = client.post("/contact")
    assert response.status_code == 200


def test_enforces_cap_passes_org_id_to_provider():
    """The provider receives the caller's org_id from the resolved Entitlements."""
    app = FastAPI()
    seen_org_ids: list[uuid.UUID] = []

    def capture_org(org_id):
        seen_org_ids.append(org_id)
        return 0

    @app.post("/contact")
    @enforces_cap("contacts", current_provider=capture_org)
    async def create_contact():
        return {"ok": True}

    ent = _stub_entitlements("basic")
    client = _client_with_entitlements(app, ent)
    response = client.post("/contact")

    assert response.status_code == 200
    assert seen_org_ids == [ent.org_id]


# ---------------------------------------------------------------------------
# Stacking
# ---------------------------------------------------------------------------

def test_stacked_decorators_both_pass_on_entitled_plan():
    """Standard grants automation + automation_runs cap is 5000; both gates clear."""
    app = FastAPI()

    @app.post("/automation/workflow")
    @requires_feature("automation.workflows")
    @enforces_cap("automation_runs_per_month", current_provider=lambda _org: 100)
    async def create_workflow():
        return {"ok": True}

    client = _client_with_entitlements(app, _stub_entitlements("standard"))
    response = client.post("/automation/workflow")
    assert response.status_code == 200


def test_stacked_decorators_feature_failure_blocks_request():
    """Basic org without automation rights hits feature_locked even if the
    cap counter is at zero."""
    app = FastAPI()

    @app.post("/automation/workflow")
    @requires_feature("automation.workflows")
    @enforces_cap("automation_runs_per_month", current_provider=lambda _org: 0)
    async def create_workflow():
        return {"ok": True}

    client = _client_with_entitlements(app, _stub_entitlements("basic"))
    response = client.post("/automation/workflow")
    assert response.status_code == 402
    assert response.json()["detail"]["reason"] == "feature_locked"


def test_stacked_decorators_cap_failure_blocks_when_feature_passes():
    """Standard org with feature granted but the resource cap reached."""
    app = FastAPI()

    @app.post("/automation/workflow")
    @requires_feature("automation.workflows")
    @enforces_cap("automation_runs_per_month", current_provider=lambda _org: 5000)
    async def create_workflow():
        return {"ok": True}

    client = _client_with_entitlements(app, _stub_entitlements("standard"))
    response = client.post("/automation/workflow")
    assert response.status_code == 402
    detail = response.json()["detail"]
    assert detail["reason"] == "cap_reached"
    assert detail["resource"] == "automation_runs_per_month"
    assert detail["cap"] == 5000


# ---------------------------------------------------------------------------
# Signature / dispatch
# ---------------------------------------------------------------------------

def test_decorator_rejects_sync_handlers():
    """Wrapping a sync function is a programmer bug — fail loud at import."""
    with pytest.raises(TypeError, match="async"):
        @requires_feature("contacts.write")
        def sync_handler():  # pragma: no cover — TypeError before body runs
            return None


def test_decorator_preserves_async_dispatch_with_path_and_query_args():
    """Handler path / query args survive the wrapper's signature rewrite."""
    app = FastAPI()

    @app.get("/contacts/{contact_id}")
    @requires_feature("contacts.read")
    async def get_contact(contact_id: int, expand: bool = False):
        return {"id": contact_id, "expand": expand}

    client = _client_with_entitlements(app, _stub_entitlements("basic"))
    response = client.get("/contacts/42", params={"expand": "true"})
    assert response.status_code == 200
    assert response.json() == {"id": 42, "expand": True}
