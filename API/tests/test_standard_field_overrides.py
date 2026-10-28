"""Unit tests for `standard_field_overrides` service-layer validation,
schema shape, and the registry+overrides merge logic.

DB/HTTP integration coverage is deferred — the test-DB fixtures in
`conftest.py` are not currently runnable from this workstation (the
seeded_admin fixture pre-dates the DR.7 user-table split). The service
layer's risky logic — the registry-contract validator and the merge —
is pure and is fully exercised here.

When the DB fixtures are restored, the integration cases below should
be added (one per spec bullet):

    Step 2:
    - migration round-trip (upgrade head → downgrade -1 → re-upgrade)
    - permission gate (Employee 403 vs Admin/Owner 200 on each endpoint)
    - cross-tenant isolation (RLS hides org B's rows from org A's reads)
    - upsert happy path + re-upsert (updated_at increases, no duplicate)
    - DELETE round-trip + 404 on second DELETE
    - audit_logs row present after PUT (event name + before/after shape)

    Step 3:
    - render with no overrides: every registered field with defaults
    - render after upsert: budget shows new label/min, is_overridden=true
    - display-order reflow: PUT display_order=0 reorders the response
    - hidden field still present in response (client filters)
    - Employee can call render (no manage permission required)
    - cross-tenant isolation on /render
    - 404 on unknown entity render
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.app.core.standard_fields import registry as field_registry
from src.app.core.standard_fields.models import StandardFieldOverride
from src.app.core.standard_fields.schemas import (
    StandardFieldOverrideIn,
    StandardFieldOverrideListResponse,
    StandardFieldOverrideOut,
    StandardFieldRendered,
    StandardFieldRenderedListResponse,
)
from src.app.core.standard_fields.service import (
    _OVERRIDE_COLUMNS,
    _PAYLOAD_PROP_MAP,
    _coalesce_numeric,
    _is_overridden,
    _merge,
    _validate_payload_against_registry,
)

# ---------------------------------------------------------------------------
# Registry-contract validator — happy paths
# ---------------------------------------------------------------------------


def test_validator_accepts_label_on_any_registered_field() -> None:
    _validate_payload_against_registry(
        entity="lead",
        field_key="budget",
        payload=StandardFieldOverrideIn(label="Project Budget (₹)"),
    )  # no raise


def test_validator_accepts_full_currency_payload_on_budget() -> None:
    _validate_payload_against_registry(
        entity="lead",
        field_key="budget",
        payload=StandardFieldOverrideIn(
            label="Project Budget (₹)",
            placeholder="0.00",
            help_text="Estimated lead value.",
            is_required=True,
            is_hidden=False,
            min_value=5000.0,
            max_value=5_000_000.0,
            step_value=1.0,
            display_order=2,
        ),
    )  # no raise


def test_validator_accepts_label_only_on_locked_field() -> None:
    """`contact.full_name` only allows label/placeholder/help/display_order."""
    _validate_payload_against_registry(
        entity="contact",
        field_key="full_name",
        payload=StandardFieldOverrideIn(label="Customer name"),
    )  # no raise


def test_validator_accepts_no_op_payload() -> None:
    """Empty body is a no-op upsert — should not raise."""
    _validate_payload_against_registry(
        entity="lead",
        field_key="budget",
        payload=StandardFieldOverrideIn(),
    )


# ---------------------------------------------------------------------------
# Registry-contract validator — 404 paths
# ---------------------------------------------------------------------------


def test_validator_404_on_unknown_entity() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_payload_against_registry(
            entity="unicorn",
            field_key="horn_length",
            payload=StandardFieldOverrideIn(label="x"),
        )
    assert exc.value.status_code == 404
    assert "not in registry" in str(exc.value.detail).lower()


def test_validator_404_on_unknown_field_key_for_real_entity() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_payload_against_registry(
            entity="lead",
            field_key="imaginary_field",
            payload=StandardFieldOverrideIn(label="x"),
        )
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Registry-contract validator — 422 paths
# ---------------------------------------------------------------------------


def test_validator_422_on_required_override_for_backend_required_field() -> None:
    """`contact.full_name` has backend_required=True → `required` is locked."""
    with pytest.raises(HTTPException) as exc:
        _validate_payload_against_registry(
            entity="contact",
            field_key="full_name",
            payload=StandardFieldOverrideIn(is_required=False),
        )
    assert exc.value.status_code == 422
    body = exc.value.detail
    assert isinstance(body, dict)
    assert any("is_required" in e for e in body["errors"])


def test_validator_422_on_hidden_override_for_locked_field() -> None:
    """`lead.pipeline_stage` is backend_required → `hidden` is locked."""
    with pytest.raises(HTTPException) as exc:
        _validate_payload_against_registry(
            entity="lead",
            field_key="pipeline_stage",
            payload=StandardFieldOverrideIn(is_hidden=True),
        )
    assert exc.value.status_code == 422


def test_validator_422_on_numeric_prop_for_text_field() -> None:
    """`contact.full_name` is text → `min`/`max`/`step` not in overridable_props."""
    with pytest.raises(HTTPException) as exc:
        _validate_payload_against_registry(
            entity="contact",
            field_key="full_name",
            payload=StandardFieldOverrideIn(min_value=5.0),
        )
    assert exc.value.status_code == 422


def test_validator_422_collects_all_disallowed_props() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_payload_against_registry(
            entity="contact",
            field_key="full_name",
            payload=StandardFieldOverrideIn(
                is_required=False,
                is_hidden=True,
                min_value=5.0,
                label="ok-this-one-is-allowed",
            ),
        )
    body = exc.value.detail
    assert isinstance(body, dict)
    error_text = " ".join(body["errors"])
    assert "is_required" in error_text
    assert "is_hidden" in error_text
    assert "min_value" in error_text
    # label is allowed for contact.full_name — must not appear:
    assert "label" not in error_text


# ---------------------------------------------------------------------------
# `_PAYLOAD_PROP_MAP` covers every registry-defined override token
# ---------------------------------------------------------------------------


def test_payload_prop_map_covers_every_valid_registry_prop() -> None:
    """If the registry grows a new overridable prop the map must catch it."""
    from src.app.core.standard_fields.registry import _VALID_PROPS

    mapped_tokens = set(_PAYLOAD_PROP_MAP.values())
    missing = _VALID_PROPS - mapped_tokens
    assert not missing, f"_PAYLOAD_PROP_MAP missing entries for registry props: {sorted(missing)}"


def test_payload_prop_map_keys_match_pydantic_field_names() -> None:
    """Every map key must correspond to an attribute on the In schema."""
    payload = StandardFieldOverrideIn()
    for payload_key in _PAYLOAD_PROP_MAP:
        assert hasattr(payload, payload_key), (
            f"_PAYLOAD_PROP_MAP key {payload_key!r} not on StandardFieldOverrideIn"
        )


# ---------------------------------------------------------------------------
# Pydantic schema constraints
# ---------------------------------------------------------------------------


def test_label_max_length_enforced() -> None:
    with pytest.raises(ValueError):
        StandardFieldOverrideIn(label="x" * 256)


def test_placeholder_max_length_enforced() -> None:
    with pytest.raises(ValueError):
        StandardFieldOverrideIn(placeholder="x" * 256)


def test_display_order_bounds_enforced() -> None:
    with pytest.raises(ValueError):
        StandardFieldOverrideIn(display_order=-1)
    with pytest.raises(ValueError):
        StandardFieldOverrideIn(display_order=1000)
    # boundary values are accepted:
    StandardFieldOverrideIn(display_order=0)
    StandardFieldOverrideIn(display_order=999)


def test_help_text_has_no_length_cap() -> None:
    """`help_text` maps to TEXT — long strings should not be rejected."""
    StandardFieldOverrideIn(help_text="x" * 5000)


def test_list_response_total_independent_of_items_length() -> None:
    resp = StandardFieldOverrideListResponse(items=[], total=0)
    assert resp.total == 0
    assert resp.items == []


# ---------------------------------------------------------------------------
# Migration revision sanity (no DB needed — just imports the file)
# ---------------------------------------------------------------------------


def test_migration_file_revision_and_down_revision() -> None:
    """Pin the alembic revision id and predecessor so a rebase doesn't
    silently strand the migration in dependency-purgatory."""
    import importlib.util
    import pathlib

    path = pathlib.Path("alembic/versions/0039_standard_field_overrides.py").resolve()
    spec = importlib.util.spec_from_file_location("mig0039", str(path))
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    assert module.revision == "0039_standard_field_overrides"
    assert module.down_revision == "0038_organizations_created_via"
    assert callable(module.upgrade)
    assert callable(module.downgrade)


# ---------------------------------------------------------------------------
# Module-router sanity
# ---------------------------------------------------------------------------


def test_router_mounts_expected_paths() -> None:
    """The router wires the management endpoints (list/upsert/reset) plus
    the openly-authenticated render endpoint."""
    from src.app.core.standard_fields.router import router

    paths = sorted({route.path for route in router.routes})
    assert paths == [
        "/standard-fields/",
        "/standard-fields/{entity}/",
        "/standard-fields/{entity}/render",
        "/standard-fields/{entity}/{field_key}",
    ], paths


def test_management_routes_gated_on_manage_permission_render_is_not() -> None:
    """Management endpoints (list/upsert/reset) use the manage gate;
    the render endpoint uses plain `get_current_user`."""
    from src.app.core.standard_fields.router import router

    for route in router.routes:
        deps = [d.call for d in route.dependant.dependencies]
        has_check = any("_check" in getattr(d, "__qualname__", "") for d in deps)
        is_render = route.path.endswith("/render")
        if is_render:
            assert not has_check, "render endpoint should not require the manage permission"
        else:
            assert has_check, f"{route.path!r} missing the manage-permission dependency"


def test_out_schema_includes_audit_columns() -> None:
    """`StandardFieldOverrideOut` exposes `updated_by` + `updated_at` so the
    Settings UI can show 'last changed by X at Y'."""
    fields = set(StandardFieldOverrideOut.model_fields.keys())
    assert {"updated_by", "updated_at", "created_by", "created_at"}.issubset(fields)


# ---------------------------------------------------------------------------
# Merge logic — `_coalesce_numeric`, `_is_overridden`, `_merge`
# ---------------------------------------------------------------------------


def _bare_override(**columns) -> StandardFieldOverride:
    """Construct an in-memory `StandardFieldOverride` for merge testing.

    No session.add — pure model instance. Fills every override column
    with `None` by default, callers override the ones the test cares about.
    """
    defaults: dict = {col: None for col in _OVERRIDE_COLUMNS}
    defaults["entity"] = "lead"
    defaults["field_key"] = "budget"
    defaults.update(columns)
    return StandardFieldOverride(**defaults)


def test_coalesce_numeric_prefers_override_when_set() -> None:
    assert _coalesce_numeric(5000, 0.0) == 5000.0


def test_coalesce_numeric_falls_back_to_registry_when_override_null() -> None:
    assert _coalesce_numeric(None, 0.01) == 0.01


def test_coalesce_numeric_handles_decimal_override() -> None:
    """Service layer passes Decimal from DB; we cast to float for JSON."""
    import decimal

    out = _coalesce_numeric(decimal.Decimal("5000.000000"), 0.0)
    assert out == 5000.0
    assert isinstance(out, float)


def test_coalesce_numeric_returns_none_when_both_null() -> None:
    assert _coalesce_numeric(None, None) is None


def test_is_overridden_false_when_no_row() -> None:
    assert _is_overridden(None) is False


def test_is_overridden_false_for_empty_row() -> None:
    """An override row with every column NULL is not 'overridden' —
    avoids surfacing a Reset button for a row that does nothing."""
    assert _is_overridden(_bare_override()) is False


def test_is_overridden_true_for_any_set_column() -> None:
    assert _is_overridden(_bare_override(label="Custom")) is True
    assert _is_overridden(_bare_override(is_required=False)) is True
    assert _is_overridden(_bare_override(display_order=0)) is True


def test_merge_returns_defaults_when_no_override() -> None:
    budget = field_registry.get("lead", "budget")
    rendered = _merge(budget, None)

    assert rendered.entity == "lead"
    assert rendered.field_key == "budget"
    assert rendered.field_type == "currency"
    assert rendered.label == "Budget (₹)"
    assert rendered.placeholder == "0.00"
    assert rendered.is_required is False
    assert rendered.is_hidden is False
    assert rendered.min_value == 0.0
    assert rendered.step_value == 0.01
    assert rendered.display_order == 1
    assert rendered.is_overridden is False
    assert "label" in rendered.overridable_props


def test_merge_overlays_label_only() -> None:
    budget = field_registry.get("lead", "budget")
    override = _bare_override(label="Project Budget (₹)")

    rendered = _merge(budget, override)

    assert rendered.label == "Project Budget (₹)"
    # Everything else stays at the registry default:
    assert rendered.placeholder == "0.00"
    assert rendered.is_required is False
    assert rendered.min_value == 0.0
    assert rendered.is_overridden is True


def test_merge_overlays_numeric_values() -> None:
    import decimal

    budget = field_registry.get("lead", "budget")
    override = _bare_override(
        min_value=decimal.Decimal("5000.000000"),
        max_value=decimal.Decimal("5000000.000000"),
        step_value=decimal.Decimal("1.000000"),
    )

    rendered = _merge(budget, override)

    assert rendered.min_value == 5000.0
    assert rendered.max_value == 5_000_000.0
    assert rendered.step_value == 1.0


def test_merge_required_true_overlay() -> None:
    budget = field_registry.get("lead", "budget")
    override = _bare_override(is_required=True)

    rendered = _merge(budget, override)
    assert rendered.is_required is True


def test_merge_hidden_true_overlay() -> None:
    source = field_registry.get("contact", "source")
    override = _bare_override(entity="contact", field_key="source", is_hidden=True)

    rendered = _merge(source, override)
    assert rendered.is_hidden is True


def test_merge_locked_field_carries_correct_overridable_props_list() -> None:
    """`contact.full_name` only allows label/placeholder/help/display_order
    — the rendered row carries that whitelist verbatim so the UI can
    grey out the locked knobs."""
    full_name = field_registry.get("contact", "full_name")
    rendered = _merge(full_name, None)

    assert set(rendered.overridable_props) == {
        "label",
        "placeholder",
        "help",
        "display_order",
    }


def test_merge_carries_backend_required_and_validators_unchanged() -> None:
    budget = field_registry.get("lead", "budget")
    rendered = _merge(budget, _bare_override(is_required=True))

    assert rendered.backend_required is False
    assert "must be ≥ 0" in rendered.backend_validators


def test_rendered_schema_validates_numeric_floats() -> None:
    """The Pydantic schema accepts plain float — service casts Decimal at the merge step."""
    StandardFieldRendered(
        entity="lead",
        field_key="budget",
        field_type="currency",
        label="Budget (₹)",
        is_required=False,
        is_hidden=False,
        min_value=5000.0,
        display_order=1,
        backend_required=False,
        backend_validators=["must be ≥ 0"],
        is_overridden=True,
        overridable_props=["label"],
    )


def test_rendered_list_response_carries_entity_marker() -> None:
    """`entity` echoed back so the client can verify it's looking at the
    response for the request it sent."""
    resp = StandardFieldRenderedListResponse(entity="lead", items=[])
    assert resp.entity == "lead"
    assert resp.items == []


# ---------------------------------------------------------------------------
# Sort behaviour of `render_for_entity` — exercised without DB via a
# small fake `_fetch_overrides_map` patch.
# ---------------------------------------------------------------------------


def test_render_sort_respects_override_display_order_then_registry_order(
    monkeypatch,
) -> None:
    """If two fields share `display_order`, registry insertion order
    decides the tiebreak — otherwise the UI would jitter between requests."""
    import asyncio

    from src.app.core.standard_fields import service as sfo_service

    async def fake_fetch(_session, *, org_id, entity):
        # Move `expected_close_date` to display_order=0 (top), Budget to 0 too.
        # Pipeline_stage stays default at 0. Tiebreak by registry index:
        # registry order for "lead" is: pipeline_stage(0), budget(1), expected_close_date(2).
        return {
            "expected_close_date": _bare_override(
                entity="lead", field_key="expected_close_date", display_order=0
            ),
            "budget": _bare_override(entity="lead", field_key="budget", display_order=0),
        }

    monkeypatch.setattr(sfo_service, "_fetch_overrides_map", fake_fetch)

    # uuid.UUID irrelevant since fake_fetch ignores org_id.
    import uuid as _uuid

    items = asyncio.run(
        sfo_service.render_for_entity(
            session=None,  # type: ignore[arg-type]
            org_id=_uuid.uuid4(),
            entity="lead",
        )
    )

    # All three rows have effective display_order=0; tiebreak by
    # registry insertion order (pipeline_stage → budget → expected_close_date).
    keys = [item.field_key for item in items]
    assert keys == ["pipeline_stage", "budget", "expected_close_date"]


def test_render_unknown_entity_raises_404() -> None:
    import asyncio
    import uuid as _uuid

    from src.app.core.standard_fields.service import (
        EntityNotInRegistry,
        render_for_entity,
    )

    with pytest.raises(EntityNotInRegistry) as exc:
        asyncio.run(
            render_for_entity(
                session=None,  # type: ignore[arg-type]
                org_id=_uuid.uuid4(),
                entity="unicorn",
            )
        )
    assert exc.value.status_code == 404


def test_render_unknown_entity_does_not_call_db(monkeypatch) -> None:
    """Early-fail before touching the session — avoids a wasted SELECT
    for callers probing for unknown entities."""
    import asyncio
    import uuid as _uuid

    from src.app.core.standard_fields import service as sfo_service

    called = False

    async def trap_fetch(_session, *, org_id, entity):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(sfo_service, "_fetch_overrides_map", trap_fetch)

    with pytest.raises(sfo_service.EntityNotInRegistry):
        asyncio.run(
            sfo_service.render_for_entity(
                session=None,  # type: ignore[arg-type]
                org_id=_uuid.uuid4(),
                entity="unicorn",
            )
        )
    assert called is False, "render_for_entity hit the DB for an unknown entity"
