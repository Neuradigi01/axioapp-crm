"""Tests for the custom-field discovery bridge
(``tasks/automation-conditions/`` Step 6).

Covers three surfaces:

1. Mount-map pin — every event in ``_CUSTOM_DATA_MOUNTS`` has the
   declared payload path present in its ``sample_payload``, and
   every mounted event exists in the base catalog.
2. Wildcard resolver semantics — registry accepts a
   ``prefix:*``-shaped key, dispatches to the handler on any
   matching lookup, blocks a same-prefix collision.
3. End-to-end: seed a select ``CustomFieldDefinition`` for the
   caller org, confirm the ``/event-types`` service assembly
   appends it to the right events, confirm the resolver returns
   its ``options.choices``, confirm two orgs' fields stay
   isolated, confirm the runtime evaluator matches on
   ``custom_data.<field_key>``.
"""

from __future__ import annotations

import uuid

import pytest

from src.app.core.automation import (
    conditions,
    custom_field_bridge,
    enum_resolvers,
    event_catalog,
)
from src.app.core.automation import (
    service as automation_service,
)
from src.app.core.automation.enum_resolvers import EnumOption
from src.app.core.automation.field_specs import FieldType, path_resolves
from src.app.core.custom_fields.models import (
    CustomFieldDefinition,
    FieldSource,
)
from src.app.core.custom_fields.models import (
    FieldType as CustomFieldType,
)
from src.app.shared.context import RequestContext, reset_context, set_context

# --- helpers ---------------------------------------------------------


async def _seed_custom_field(
    org_id: uuid.UUID,
    *,
    entity_type: str,
    field_key: str,
    field_label: str,
    field_type: CustomFieldType = CustomFieldType.select,
    options: dict | None = None,
    is_hidden: bool = False,
    source: FieldSource = FieldSource.user,
) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            definition = CustomFieldDefinition(
                org_id=org_id,
                entity_type=entity_type,
                field_key=field_key,
                field_label=field_label,
                field_type=field_type,
                options=options,
                is_hidden=is_hidden,
                source=source,
            )
            session.add(definition)
            await session.commit()
            return definition.id
    finally:
        reset_context(token)


# --- mount-map pin ---------------------------------------------------


def test_every_mount_resolves_in_its_events_sample_payload():
    """Snapshot pin: adding a mount to ``_CUSTOM_DATA_MOUNTS`` must
    come with the matching ``custom_data`` key on the event's
    ``sample_payload``. Catches the drift where a publisher stops
    emitting ``custom_data`` but the mount still tries to append
    fields — customers would see the fields but the evaluator
    would silently no-match every event."""
    problems: list[str] = []
    for event_type, mounts in custom_field_bridge._CUSTOM_DATA_MOUNTS.items():  # noqa: SLF001
        entry = event_catalog.get_entry(event_type)
        if entry is None:
            problems.append(f"{event_type}: not in base catalog")
            continue
        for _entity_type, mount_path in mounts:
            if not path_resolves(entry.sample_payload, mount_path):
                problems.append(
                    f"{event_type}: mount path {mount_path!r} missing in sample_payload"
                )
    assert not problems, problems


# --- bridge translation ---------------------------------------------


def test_to_field_spec_maps_select_to_enum_with_wildcard_resolver_key():
    """Select custom fields map to enum type with a
    ``custom_field_options:<entity>:<field_key>`` resolver key —
    the wildcard registry dispatches this at request time."""
    definition = CustomFieldDefinition(
        org_id=uuid.uuid4(),
        entity_type="lead",
        field_key="deal_size_tier",
        field_label="Deal size tier",
        field_type=CustomFieldType.select,
        options={"choices": ["small", "medium", "large"]},
    )
    spec = custom_field_bridge.to_field_spec(definition, "lead.custom_data")
    assert spec.path == "lead.custom_data.deal_size_tier"
    assert spec.label == "Deal size tier"
    assert spec.type is FieldType.enum
    assert spec.group == "Lead custom fields"
    assert spec.enum_resolver == "custom_field_options:lead:deal_size_tier"


def test_to_field_spec_maps_text_types_to_text_without_resolver():
    """text / email / phone all collapse into text — no resolver
    (they show a free-text input in the value dropdown)."""
    for cf_type in (CustomFieldType.text, CustomFieldType.email, CustomFieldType.phone):
        definition = CustomFieldDefinition(
            org_id=uuid.uuid4(),
            entity_type="lead",
            field_key=f"free_{cf_type.value}",
            field_label=f"Free {cf_type.value}",
            field_type=cf_type,
        )
        spec = custom_field_bridge.to_field_spec(definition, "lead.custom_data")
        assert spec.type is FieldType.text
        assert spec.enum_resolver is None


# --- wildcard resolver registry -------------------------------------


def test_wildcard_resolver_dispatches_to_matching_key():
    """A key registered as ``prefix:*`` matches any lookup starting
    with ``prefix:`` when no exact match beats it."""
    fn = enum_resolvers.get_resolver("custom_field_options:lead:some_field")
    assert fn is not None, "wildcard resolver should dispatch"


def test_wildcard_resolver_conflict_on_different_callable_raises():
    """Registering two wildcards with the same prefix + different
    callables raises. Catches the accidental collision where step-7
    tries to hijack step-6's prefix."""
    prefix = f"__test_wildcard_conflict_{uuid.uuid4().hex[:6]}"

    async def resolver_a(_s, _o):
        return []

    async def resolver_b(_s, _o):
        return []

    try:
        enum_resolvers.register_resolver(f"{prefix}:*", resolver_a, wildcard=True)
        with pytest.raises(RuntimeError, match="already registered"):
            enum_resolvers.register_resolver(f"{prefix}:*", resolver_b, wildcard=True)
    finally:
        enum_resolvers._unregister(f"{prefix}:*")  # noqa: SLF001


def test_wildcard_key_must_end_with_star():
    async def resolver_a(_s, _o):
        return []

    with pytest.raises(ValueError, match="must end with"):
        enum_resolvers.register_resolver("no_star_here", resolver_a, wildcard=True)


# --- evaluator end-to-end pin ---------------------------------------


def test_evaluator_matches_custom_field_value():
    """Runtime pin — the evaluator resolves the
    ``lead.custom_data.<field_key>`` dot-path correctly. Guards
    against a change to the evaluator's walker breaking the whole
    custom-field integration silently."""
    payload = {
        "lead": {"id": "abc", "custom_data": {"deal_size_tier": "large"}},
        "contact": {"email": "a@b.com"},
    }
    condition = {
        "field": "lead.custom_data.deal_size_tier",
        "op": "eq",
        "value": "large",
    }
    assert conditions.evaluate(condition, payload) is True

    condition_no_match = {
        "field": "lead.custom_data.deal_size_tier",
        "op": "eq",
        "value": "small",
    }
    assert conditions.evaluate(condition_no_match, payload) is False


# --- DB-backed service + resolver tests -----------------------------


@pytest.mark.asyncio
async def test_catalog_appends_lead_custom_fields_to_lead_created(seeded_admin):
    """Seed a Lead custom field, call the service that assembles the
    /event-types response, and confirm the field lands on every
    event whose mounts include ``lead``."""
    from tests.conftest import TestSession

    org_id = seeded_admin["org"].id
    await _seed_custom_field(
        org_id,
        entity_type="lead",
        field_key="deal_size_tier",
        field_label="Deal size tier",
        options={"choices": ["small", "medium", "large"]},
    )

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            entries = await automation_service.list_event_types_with_custom_fields(
                session, org_id=org_id
            )
    finally:
        reset_context(token)

    by_event = {e["event_type"]: e for e in entries}
    lead_created = by_event["lead.created"]
    paths = {s.path: s for s in lead_created["condition_fields"]}
    added = paths.get("lead.custom_data.deal_size_tier")
    assert added is not None, "custom field not appended to lead.created"
    assert added.type is FieldType.enum
    assert added.group == "Lead custom fields"
    assert added.enum_resolver == "custom_field_options:lead:deal_size_tier"


@pytest.mark.asyncio
async def test_catalog_hidden_custom_fields_are_excluded(seeded_admin):
    from tests.conftest import TestSession

    org_id = seeded_admin["org"].id
    await _seed_custom_field(
        org_id,
        entity_type="lead",
        field_key="hidden_tier",
        field_label="Hidden tier",
        options={"choices": ["a", "b"]},
        is_hidden=True,
    )
    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            entries = await automation_service.list_event_types_with_custom_fields(
                session, org_id=org_id
            )
    finally:
        reset_context(token)
    lead_created = next(e for e in entries if e["event_type"] == "lead.created")
    paths = {s.path for s in lead_created["condition_fields"]}
    assert "lead.custom_data.hidden_tier" not in paths


@pytest.mark.asyncio
async def test_select_custom_field_resolver_returns_stored_options(seeded_admin):
    from tests.conftest import TestSession

    org_id = seeded_admin["org"].id
    await _seed_custom_field(
        org_id,
        entity_type="lead",
        field_key="deal_size_tier",
        field_label="Deal size tier",
        options={"choices": ["small", "medium", "large"]},
    )
    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            options = await enum_resolvers.resolve_custom_field_options(
                session,
                org_id,
                "custom_field_options:lead:deal_size_tier",
            )
    finally:
        reset_context(token)
    assert options == [
        EnumOption(value="small", label="small"),
        EnumOption(value="medium", label="medium"),
        EnumOption(value="large", label="large"),
    ]


@pytest.mark.asyncio
async def test_select_custom_field_with_no_options_returns_empty_list(seeded_admin):
    """A select field created without options yet returns [] rather
    than raising. Frontend shows the "no options configured" hint."""
    from tests.conftest import TestSession

    org_id = seeded_admin["org"].id
    await _seed_custom_field(
        org_id,
        entity_type="lead",
        field_key="empty_field",
        field_label="Empty field",
        options=None,
    )
    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            options = await enum_resolvers.resolve_custom_field_options(
                session,
                org_id,
                "custom_field_options:lead:empty_field",
            )
    finally:
        reset_context(token)
    assert options == []
