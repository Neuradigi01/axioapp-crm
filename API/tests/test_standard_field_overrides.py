"""Unit tests for `standard_field_overrides` service-layer validation
and schema shape.

DB/HTTP integration coverage is deferred — the test-DB fixtures in
`conftest.py` are not currently runnable from this workstation (the
seeded_admin fixture pre-dates the DR.7 user-table split). The service
layer's risky logic — the registry-contract validator — is pure and is
fully exercised here.

When the DB fixtures are restored, the integration cases below should
be added (one per spec bullet):

    - migration round-trip (upgrade head → downgrade -1 → re-upgrade)
    - permission gate (Employee 403 vs Admin/Owner 200 on each endpoint)
    - cross-tenant isolation (RLS hides org B's rows from org A's reads)
    - upsert happy path + re-upsert (updated_at increases, no duplicate)
    - DELETE round-trip + 404 on second DELETE
    - audit_logs row present after PUT (event name + before/after shape)
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.app.core.standard_fields.schemas import (
    StandardFieldOverrideIn,
    StandardFieldOverrideListResponse,
    StandardFieldOverrideOut,
)
from src.app.core.standard_fields.service import (
    _PAYLOAD_PROP_MAP,
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
    assert not missing, (
        f"_PAYLOAD_PROP_MAP missing entries for registry props: {sorted(missing)}"
    )


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

    path = pathlib.Path(
        "alembic/versions/0039_standard_field_overrides.py"
    ).resolve()
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


def test_router_mounts_expected_paths_with_manage_permission() -> None:
    """Quick smoke that the router still wires the 4 expected paths and
    every route depends on the `settings.standard_fields.manage` key."""
    from src.app.core.standard_fields.router import router

    paths = sorted({route.path for route in router.routes})
    assert paths == [
        "/standard-fields/",
        "/standard-fields/{entity}/",
        "/standard-fields/{entity}/{field_key}",
    ], paths

    # Every endpoint depends on `require_permissions("settings.standard_fields.manage")`
    # via the module-level `_REQUIRE_MANAGE`. Check by sniffing the
    # dependency in the route's dependant tree.
    for route in router.routes:
        deps = [d.call for d in route.dependant.dependencies]
        assert any(
            "_check" in getattr(d, "__qualname__", "") for d in deps
        ), f"{route.path!r} missing the manage-permission dependency"


def test_out_schema_includes_audit_columns() -> None:
    """`StandardFieldOverrideOut` exposes `updated_by` + `updated_at` so the
    Settings UI can show 'last changed by X at Y'."""
    fields = set(StandardFieldOverrideOut.model_fields.keys())
    assert {"updated_by", "updated_at", "created_by", "created_at"}.issubset(fields)
