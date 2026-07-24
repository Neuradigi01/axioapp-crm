"""Pin tests for the customer-friendly condition builder catalog
(``tasks/automation-conditions/`` Step 1).

Four coverage pins guard against drift as the catalog grows:

1. Every catalog entry declares a non-empty ``condition_fields`` tuple
   so the frontend never falls back to Advanced mode silently.
2. Enum-typed fields declare an ``enum_resolver`` key; other types
   must NOT (step-2's registry only dispatches for enum fields).
3. Every ``FieldSpec.path`` resolves cleanly into the enclosing
   entry's ``sample_payload`` — mirrors the runtime drift guard so
   a code review catches drift before merge.
4. Every referenced ``enum_resolver`` key is either in the built-in
   set (populated by step-2) or a pack-owned key. Step-1 only knows
   the built-in list; step-7 extends the assertion for pack keys.

One drift-guard behaviour test and one endpoint shape test round the
file out — ``_register`` must raise loudly on a bad path, and the
``/event-types`` endpoint must serialise ``condition_fields`` for
the frontend to consume.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.automation import event_catalog
from src.app.core.automation.field_specs import FieldSpec, FieldType, path_resolves
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission

# Built-in resolver keys step-1 knows about. Step-2's registry lands
# them concretely; until then we keep the list here so the coverage
# pin can validate every FieldSpec's enum_resolver references a real
# key. Step-7 extends this with pack-owned keys.
_BUILTIN_RESOLVERS: frozenset[str] = frozenset(
    {
        "pipeline_stages",
        "lead_sources",
        "lead_statuses",
        "users",
        "users_roles",
        "tags",
        "appointment_purposes",
        "invoice_statuses",
        "payment_methods",
        "direction_updown",
        "channels",
    }
)


# --- coverage pins ---------------------------------------------------


def test_every_catalog_entry_has_condition_fields():
    """Half-covered is worse than not-covered — the picker teaches
    customers to distrust it. Every event MUST have at least one
    FieldSpec."""
    misses: list[str] = []
    for entry in event_catalog.list_catalog():
        if not entry.condition_fields:
            misses.append(entry.event_type)
    assert not misses, (
        f"{len(misses)} catalog entries lack condition_fields: {misses}. "
        f"Every event MUST declare its filter fields — the frontend consumes "
        f"them to render the condition-builder dropdown."
    )


def test_enum_fields_have_resolver_others_do_not():
    """Enforced by ``FieldSpec.__post_init__`` too, but pin here so a
    grep-audit of the whole catalog surfaces any drift immediately."""
    problems: list[str] = []
    for entry in event_catalog.list_catalog():
        for spec in entry.condition_fields:
            if spec.type is FieldType.enum and not spec.enum_resolver:
                problems.append(f"{entry.event_type}:{spec.path} (enum missing resolver)")
            if spec.type is not FieldType.enum and spec.enum_resolver is not None:
                problems.append(
                    f"{entry.event_type}:{spec.path} "
                    f"({spec.type.value} unexpectedly has resolver {spec.enum_resolver!r})"
                )
    assert not problems, problems


def test_field_spec_paths_resolve_in_sample_payload():
    """Mirrors the runtime drift guard in ``_register`` so a code
    review's grep catches the same class of typo without needing to
    boot the app."""
    problems: list[str] = []
    for entry in event_catalog.list_catalog():
        for spec in entry.condition_fields:
            if not path_resolves(entry.sample_payload, spec.path):
                problems.append(f"{entry.event_type}:{spec.path}")
    assert not problems, f"FieldSpec paths that don't resolve into sample_payload: {problems}"


def test_every_enum_resolver_is_registered_or_builtin():
    """Step-1 only knows the built-in resolver keys. Once step-7
    lands, this test's assertion extends to include pack-registered
    keys. Failing here is a genuine drift — either add the resolver
    to step-2's registry or fix the FieldSpec to point at an
    existing key."""
    unknown: list[str] = []
    for entry in event_catalog.list_catalog():
        for spec in entry.condition_fields:
            if spec.enum_resolver is None:
                continue
            if spec.enum_resolver not in _BUILTIN_RESOLVERS:
                unknown.append(f"{entry.event_type}:{spec.path} -> {spec.enum_resolver!r}")
    assert not unknown, (
        f"FieldSpec references resolver keys not in _BUILTIN_RESOLVERS: {unknown}. "
        f"Either register them in step-2's enum_resolvers module or update "
        f"_BUILTIN_RESOLVERS in this test to include a new built-in."
    )


# --- runtime drift guard behaviour ----------------------------------


def test_register_raises_on_bad_path():
    """Feed a scratch catalog entry with a FieldSpec that references a
    path missing from its sample_payload; ``_register`` must raise
    ValueError so a broken entry can't sneak into the module."""
    with pytest.raises(ValueError, match="FieldSpec drift"):
        event_catalog._register(  # noqa: SLF001 — pin test intentionally hits the internal guard
            event_catalog.CatalogEntry(
                event_type="__pin__.bad_path",
                label="Pin test — bad path",
                description="Scratch entry for the drift guard pin test.",
                sample_payload={"lead": {"pipeline_stage": "new"}},
                condition_fields=(
                    FieldSpec(
                        path="lead.nonexistent_field",
                        label="Nonexistent",
                        type=FieldType.text,
                        group="Lead",
                    ),
                ),
            )
        )
    # The bad entry must NOT have been added to the catalog dict —
    # _register raises before the assignment.
    assert "__pin__.bad_path" not in event_catalog._CATALOG  # noqa: SLF001


# --- /event-types wire shape ----------------------------------------


_AUTOMATION_KEYS = ("automations.read",)


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
async def test_event_types_endpoint_serialises_condition_fields(layered_client, seeded_admin):
    """Every catalog entry ships its ``condition_fields`` on the wire
    so the customer-friendly builder can render dropdowns. Spot-check
    both an enum field (pipeline_stage) and a non-enum currency
    field (budget) on the most variable-rich event."""
    await _grant_keys(seeded_admin["role"].id, *_AUTOMATION_KEYS)
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    resp = await layered_client.get(
        "/api/v1/automations/event-types",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    entries = {e["event_type"]: e for e in resp.json()}
    lead_created = entries["lead.created"]
    assert lead_created["condition_fields"], "lead.created lost its condition_fields"
    paths = {spec["path"]: spec for spec in lead_created["condition_fields"]}
    stage = paths.get("lead.pipeline_stage")
    assert stage is not None, "lead.pipeline_stage spec missing"
    assert stage["type"] == "enum"
    assert stage["enum_resolver"] == "pipeline_stages"
    assert stage["group"] == "Lead"
    budget = paths.get("lead.budget")
    assert budget is not None
    assert budget["type"] == "currency"
    assert budget["enum_resolver"] is None
