"""Tests for the live enum resolver + registry
(``tasks/automation-conditions/`` Step 2).

Covers three surfaces:

1. Registry semantics — idempotent register, conflicting-callable
   raises, get / list behaviour.
2. Built-in resolver shapes — every static resolver returns
   ``EnumOption`` instances; the DB-backed ``pipeline_stages``
   resolver reads the caller org's actual rows.
3. ``POST /event-types/{event}/field-values`` endpoint — happy path,
   404s (unknown event / unknown field), 422 (non-enum field), 200
   with ``[]`` when the org hasn't configured any options yet.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.automation import enum_resolvers
from src.app.core.automation.enum_resolvers import EnumOption
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.pipelines.models import Pipeline, PipelineStage
from src.app.shared.context import RequestContext, reset_context, set_context

_AUTOMATION_READ = ("automations.read",)


# --- registry semantics ---------------------------------------------


async def _dummy_resolver(_session, _org_id):  # noqa: ANN001 — test helper
    return [EnumOption(value="x", label="X")]


async def _other_dummy_resolver(_session, _org_id):  # noqa: ANN001
    return [EnumOption(value="y", label="Y")]


def test_register_resolver_is_idempotent_for_same_callable():
    """Same key + same callable → no-op. Guards against test-reload
    or duplicate-import edge cases from raising spuriously."""
    key = f"__test_idem_{uuid.uuid4().hex[:8]}"
    try:
        enum_resolvers.register_resolver(key, _dummy_resolver)
        enum_resolvers.register_resolver(key, _dummy_resolver)  # re-register same fn
        assert enum_resolvers.get_resolver(key) is _dummy_resolver
    finally:
        enum_resolvers._unregister(key)  # noqa: SLF001 — test cleanup


def test_register_resolver_conflicts_on_different_callable():
    """Same key + different callable → RuntimeError. Catches accidental
    key collisions between core and a pack (step-7)."""
    key = f"__test_conflict_{uuid.uuid4().hex[:8]}"
    try:
        enum_resolvers.register_resolver(key, _dummy_resolver)
        with pytest.raises(RuntimeError, match="already registered"):
            enum_resolvers.register_resolver(key, _other_dummy_resolver)
    finally:
        enum_resolvers._unregister(key)  # noqa: SLF001


def test_get_resolver_returns_none_for_unknown_key():
    """Router relies on this to map to 404 rather than raising."""
    assert enum_resolvers.get_resolver(f"__missing_{uuid.uuid4().hex[:8]}") is None


def test_list_registered_keys_contains_every_built_in():
    keys = enum_resolvers.list_registered_keys()
    for expected in (
        "pipeline_stages",
        "lead_sources",
        "lead_statuses",
        "users",
        "appointment_purposes",
        "invoice_statuses",
        "payment_methods",
        "direction_updown",
        "channels",
    ):
        assert expected in keys, f"built-in resolver {expected!r} not registered"


# --- static resolvers -----------------------------------------------


@pytest.mark.asyncio
async def test_static_direction_updown_returns_two_options():
    result = await enum_resolvers.resolve_direction_updown(None, uuid.uuid4())
    values = [o.value for o in result]
    assert values == ["up", "down"]
    assert all(isinstance(o, EnumOption) for o in result)


@pytest.mark.asyncio
async def test_static_lead_sources_includes_widget_and_meta():
    """LeadSource enum members must all serialise, with a friendly
    label override for the multi-word ones."""
    result = await enum_resolvers.resolve_lead_sources(None, uuid.uuid4())
    by_value = {o.value: o.label for o in result}
    assert by_value["widget"] == "Widget"
    assert by_value["google_ads"] == "Google Ads"
    assert by_value["meta_ads"] == "Meta Ads"
    assert by_value["whatsapp_flow"] == "WhatsApp Flow"


@pytest.mark.asyncio
async def test_static_payment_methods_upcases_upi_and_emi():
    """Static resolvers Title-Case by default; overrides handle the
    acronyms so the customer doesn't see 'Upi' / 'Emi' in a
    dropdown."""
    result = await enum_resolvers.resolve_payment_methods(None, uuid.uuid4())
    by_value = {o.value: o.label for o in result}
    assert by_value["upi"] == "UPI"
    assert by_value["emi"] == "EMI"
    assert by_value["cash"] == "Cash"


# --- DB-backed resolver ---------------------------------------------


async def _seed_leads_pipeline(
    org_id: uuid.UUID,
) -> None:
    """Insert a small `leads` pipeline for the caller org so the
    ``pipeline_stages`` resolver has something to return."""
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            pipeline = Pipeline(org_id=org_id, key="leads", name="Leads")
            session.add(pipeline)
            await session.flush()
            for i, (key, name) in enumerate(
                [("new", "New"), ("qualified", "Qualified"), ("won", "Won")]
            ):
                session.add(
                    PipelineStage(
                        org_id=org_id,
                        pipeline_id=pipeline.id,
                        key=key,
                        name=name,
                        color="#000000",
                        display_order=i,
                    )
                )
            await session.commit()
    finally:
        reset_context(token)


@pytest.mark.asyncio
async def test_pipeline_stages_resolver_returns_seeded_stages(seeded_admin):
    """Seed a 3-stage pipeline for the caller org and verify the
    resolver returns them in display_order."""
    from tests.conftest import TestSession

    org_id = seeded_admin["org"].id
    await _seed_leads_pipeline(org_id)

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            result = await enum_resolvers.resolve_pipeline_stages(session, org_id)
    finally:
        reset_context(token)

    keys = [o.value for o in result]
    assert keys == ["new", "qualified", "won"]
    labels = [o.label for o in result]
    assert labels == ["New", "Qualified", "Won"]


@pytest.mark.asyncio
async def test_pipeline_stages_resolver_returns_empty_when_org_has_none(seeded_admin):
    """Fresh org with no pipelines configured → resolver returns []
    rather than raising. Frontend renders the "no stages" hint."""
    from tests.conftest import TestSession

    org_id = seeded_admin["org"].id
    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            result = await enum_resolvers.resolve_pipeline_stages(session, org_id)
    finally:
        reset_context(token)
    assert result == []


# --- /field-values endpoint -----------------------------------------


async def _grant_keys(role_id: uuid.UUID, *keys: str) -> None:
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


async def _login(layered_client, *, org_slug: str, email: str, password: str) -> str:
    resp = await layered_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_field_values_endpoint_returns_static_enum_options(layered_client, seeded_admin):
    """Happy path for a static resolver — pick `lead.created` /
    `source` and verify the response matches the LeadSource enum."""
    await _grant_keys(seeded_admin["role"].id, *_AUTOMATION_READ)
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/automations/event-types/lead.created/field-values",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "source"},
    )
    assert resp.status_code == 200, resp.text
    by_value = {o["value"]: o["label"] for o in resp.json()}
    assert by_value["widget"] == "Widget"
    assert by_value["google_ads"] == "Google Ads"
    # Response carries the private cache header.
    assert "max-age=60" in resp.headers.get("Cache-Control", "")


@pytest.mark.asyncio
async def test_field_values_endpoint_returns_live_pipeline_stages(layered_client, seeded_admin):
    """DB-backed happy path — seed a 3-stage pipeline for the caller
    org and verify the resolver returns those exact keys."""
    await _grant_keys(seeded_admin["role"].id, *_AUTOMATION_READ)
    await _seed_leads_pipeline(seeded_admin["org"].id)
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/automations/event-types/lead.created/field-values",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "lead.pipeline_stage"},
    )
    assert resp.status_code == 200, resp.text
    values = [o["value"] for o in resp.json()]
    assert values == ["new", "qualified", "won"]


@pytest.mark.asyncio
async def test_field_values_endpoint_404_when_event_unknown(layered_client, seeded_admin):
    await _grant_keys(seeded_admin["role"].id, *_AUTOMATION_READ)
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/automations/event-types/nope.fake/field-values",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "source"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "automation.event_not_found"


@pytest.mark.asyncio
async def test_field_values_endpoint_404_when_field_not_in_spec(layered_client, seeded_admin):
    await _grant_keys(seeded_admin["role"].id, *_AUTOMATION_READ)
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/automations/event-types/lead.created/field-values",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "lead.totally_made_up_field"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "automation.field_not_found"


@pytest.mark.asyncio
async def test_field_values_endpoint_422_when_field_not_enum(layered_client, seeded_admin):
    """Currency / text fields have no value pool — endpoint rejects
    with 422 rather than silently returning []."""
    await _grant_keys(seeded_admin["role"].id, *_AUTOMATION_READ)
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/automations/event-types/lead.created/field-values",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "lead.budget"},  # currency type
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "automation.field_not_enum"


@pytest.mark.asyncio
async def test_field_values_endpoint_200_empty_when_org_has_no_stages(layered_client, seeded_admin):
    """Fresh org, no pipeline_stages rows → endpoint returns 200 + []
    (frontend renders the "no stages configured" hint)."""
    await _grant_keys(seeded_admin["role"].id, *_AUTOMATION_READ)
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.post(
        "/api/v1/automations/event-types/lead.created/field-values",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "lead.pipeline_stage"},
    )
    assert resp.status_code == 200
    assert resp.json() == []
