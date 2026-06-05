"""Coverage for the YAML-backed plan registry and the public /plans API.

Pure tests — no DB usage. The registry is file-IO + Pydantic only.
HTTP tests reuse the existing AsyncClient + ASGITransport pattern from
the other layered-router tests.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from src.app.core.subscriptions import plans, plans_cli
from src.app.core.subscriptions.plans import (
    KNOWN_FEATURE_KEYS,
    UNLIMITED_SENTINEL,
    Cap,
)


# ---------------------------------------------------------------------------
# Registry — pure unit tests against the real plans.yaml
# ---------------------------------------------------------------------------

EXPECTED_CODES = {"trial", "basic", "standard", "enterprise"}


def setup_function(_fn) -> None:
    """Reset cached registry between tests so any reload(path=...) in one
    test does not bleed into the next."""
    plans.reload()


def test_yaml_loads_cleanly():
    all_plans = plans.all()
    assert len(all_plans) == 4
    assert {p.code for p in all_plans} == EXPECTED_CODES


def test_all_returns_display_order_ascending():
    all_plans = plans.all()
    assert [p.code for p in all_plans] == ["trial", "basic", "standard", "enterprise"]


def test_public_hides_trial_and_sorts():
    public = plans.public()
    assert [p.code for p in public] == ["basic", "standard", "enterprise"]


def test_get_returns_trial_too():
    plan = plans.get("trial")
    assert plan is not None
    assert plan.code == "trial"
    assert plan.is_public is False


def test_get_returns_none_on_unknown_code():
    assert plans.get("free") is None
    assert plans.get("FREE") is None  # case-sensitive


def test_cap_unlimited_sentinel():
    enterprise = plans.get("enterprise")
    assert enterprise is not None
    assert enterprise.caps.contacts == UNLIMITED_SENTINEL
    assert Cap.is_unlimited(enterprise.caps.contacts) is True

    basic = plans.get("basic")
    assert basic is not None
    assert basic.caps.contacts == 5000
    assert Cap.is_unlimited(basic.caps.contacts) is False


def test_trial_features_mirror_basic():
    """Founder decision: trial gives a taste of Basic, not Standard."""
    trial = plans.get("trial")
    basic = plans.get("basic")
    assert trial is not None and basic is not None
    assert trial.features.as_dict() == basic.features.as_dict()


def test_standard_unlocks_automation_and_whatsapp():
    standard = plans.get("standard")
    assert standard is not None
    assert standard.features.has("automation.workflows") is True
    assert standard.features.has("integrations.whatsapp") is True
    assert standard.features.has("ads.google_webhook") is True
    assert standard.features.has("sso.saml") is False  # Enterprise-only


def test_enterprise_unlocks_everything():
    enterprise = plans.get("enterprise")
    assert enterprise is not None
    for key in KNOWN_FEATURE_KEYS:
        assert enterprise.features.has(key) is True, f"Enterprise should grant {key!r}"


def test_has_feature_unknown_key_returns_false():
    basic = plans.get("basic")
    assert basic is not None
    # Should not raise — unknown keys silently return False so callers
    # do not need to defensively try/except every check.
    assert basic.features.has("nonexistent.thing") is False


def test_currency_and_discount():
    assert plans.currency() == "USD"
    assert plans.annual_discount_pct() == 20


def test_pricing_cents_helpers():
    standard = plans.get("standard")
    assert standard is not None
    assert standard.pricing.monthly_bundle_usd == 145
    assert standard.pricing.monthly_bundle_cents == 14500
    assert standard.pricing.extra_seat_monthly_cents == 2900


def test_annual_discount_matches_each_paid_plan():
    """Spot-check: every paid plan's annual price equals monthly * 12 * 0.80
    within a small rounding tolerance. Catches mistyped annual prices."""
    for code in ("basic", "standard", "enterprise"):
        plan = plans.get(code)
        assert plan is not None
        expected_annual = round(plan.pricing.monthly_bundle_usd * 12 * 0.80)
        # The YAML uses pre-computed values; tolerate ±$2 for rounding.
        assert abs(plan.pricing.annual_bundle_usd - expected_annual) <= 2, (
            f"{code}: annual ${plan.pricing.annual_bundle_usd} "
            f"!= 20%-off-monthly ${expected_annual}"
        )


# ---------------------------------------------------------------------------
# Strict validation — fixtures break the YAML and assert it rejects
# ---------------------------------------------------------------------------

VALID_YAML_TEMPLATE = """
version: 1
currency: USD
annual_discount_pct: 20
plans:
  - code: basic
    name: Basic
    display_order: 1
    is_public: true
    trial_duration_days: 0
    pricing:
      monthly_bundle_usd: 60
      annual_bundle_usd: 576
      included_seats: 5
      extra_seat_monthly_usd: 12
      extra_seat_annual_usd: 120
    caps:
      contacts: 5000
      leads_per_month: 1000
      storage_mb: 5120
      pipelines: 1
      custom_fields_per_entity: 5
      form_widgets: 1
      form_submissions_per_month: 100
      automation_runs_per_month: 0
      api_calls_per_day: 0
      branches: 1
      email_sends_per_month: 1000
      sms_sends_per_month: 0
    features:
      contacts.read: true
"""


def _write_yaml(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "plans.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_unknown_feature_key_rejected(tmp_path):
    bad = VALID_YAML_TEMPLATE + "      bogus.key: true\n"
    path = _write_yaml(tmp_path, bad)
    with pytest.raises(ValidationError) as excinfo:
        plans.reload(path)
    # Pydantic v2 surfaces the extra-field name in the error message.
    assert "bogus" in str(excinfo.value).lower() or "extra" in str(excinfo.value).lower()


def test_missing_feature_keys_default_to_false(tmp_path):
    path = _write_yaml(tmp_path, VALID_YAML_TEMPLATE)
    plans.reload(path)
    basic = plans.get("basic")
    assert basic is not None
    # Only contacts.read was set true — everything else should default to false.
    assert basic.features.has("contacts.read") is True
    assert basic.features.has("contacts.write") is False
    assert basic.features.has("automation.workflows") is False


def test_duplicate_plan_codes_rejected(tmp_path):
    body = VALID_YAML_TEMPLATE + VALID_YAML_TEMPLATE.split("plans:\n")[1]
    path = _write_yaml(tmp_path, body)
    with pytest.raises(ValidationError):
        plans.reload(path)


def test_cap_below_minus_one_rejected(tmp_path):
    body = VALID_YAML_TEMPLATE.replace(
        "contacts: 5000", "contacts: -5"
    )
    path = _write_yaml(tmp_path, body)
    with pytest.raises(ValidationError):
        plans.reload(path)


def test_negative_price_rejected(tmp_path):
    body = VALID_YAML_TEMPLATE.replace(
        "monthly_bundle_usd: 60", "monthly_bundle_usd: -10"
    )
    path = _write_yaml(tmp_path, body)
    with pytest.raises(ValidationError):
        plans.reload(path)


# ---------------------------------------------------------------------------
# CLI — exits 0 on the real YAML, 1 on a broken fixture
# ---------------------------------------------------------------------------

def test_cli_validates_real_yaml(capsys):
    rc = plans_cli.main(["validate"])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "OK: 4 plans loaded." in captured.out


def test_cli_fails_on_broken_yaml(tmp_path, capsys):
    bad_path = _write_yaml(tmp_path, VALID_YAML_TEMPLATE + "      bogus.key: true\n")
    rc = plans_cli.main(["validate", str(bad_path)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "ERROR" in captured.err


def test_cli_missing_argument_returns_2(capsys):
    rc = plans_cli.main([])
    assert rc == 2


# ---------------------------------------------------------------------------
# HTTP — the two public endpoints
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client():
    from src.app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_list_plans_endpoint(client):
    resp = await client.get("/api/v1/plans")
    assert resp.status_code == 200
    body = resp.json()
    assert body["currency"] == "USD"
    assert body["annual_discount_pct"] == 20
    codes = [p["code"] for p in body["plans"]]
    assert codes == ["basic", "standard", "enterprise"]  # display_order asc, trial hidden


@pytest.mark.asyncio
async def test_list_plans_includes_full_shape(client):
    resp = await client.get("/api/v1/plans")
    basic = next(p for p in resp.json()["plans"] if p["code"] == "basic")
    assert basic["pricing"]["monthly_bundle_usd"] == 60
    assert basic["pricing"]["included_seats"] == 5
    assert basic["caps"]["contacts"] == 5000
    assert basic["features"]["contacts.read"] is True
    assert basic["features"]["automation.workflows"] is False


@pytest.mark.asyncio
async def test_get_plan_by_code_includes_trial(client):
    resp = await client.get("/api/v1/plans/trial")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "trial"
    assert body["is_public"] is False
    assert body["pricing"]["included_seats"] == 3


@pytest.mark.asyncio
async def test_get_plan_unknown_returns_404(client):
    resp = await client.get("/api/v1/plans/free")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_endpoints_are_unauthenticated(client):
    # No Authorization header. Should still succeed.
    resp = await client.get("/api/v1/plans")
    assert resp.status_code == 200
    resp = await client.get("/api/v1/plans/standard")
    assert resp.status_code == 200
