"""Contract tests for the Standard Field Overrides registry.

Pure in-process unit tests — no DB, no HTTP. The registry self-validates
at `StandardFieldDef.__post_init__`, so most of the contract is enforced
at registration time; these tests pin the same invariants against the
already-seeded core entries and against direct dataclass construction.
"""
from __future__ import annotations

import pytest

from src.app.core.standard_fields import (
    StandardFieldDef,
    get,
    get_overridable_props,
    list_all,
    list_entities,
    list_for_entity,
)
from src.app.core.permissions.role_templates import ROLE_TEMPLATES


# ---------------------------------------------------------------------------
# Registry coverage
# ---------------------------------------------------------------------------


def test_registry_has_seeds_for_every_core_entity() -> None:
    entities = set(list_entities())
    assert {
        "contact",
        "lead",
        "walk_in",
        "task",
        "appointment",
        "catalog_item",
    }.issubset(entities), f"missing core entities; got {sorted(entities)}"


def test_registry_has_at_least_one_field_per_core_entity() -> None:
    for entity in ("contact", "lead", "walk_in", "task", "appointment", "catalog_item"):
        assert list_for_entity(entity), f"{entity!r} has no registered fields"


def test_registry_has_no_duplicate_entity_field_pairs() -> None:
    defs = list_all()
    pairs = [(d.entity, d.field_key) for d in defs]
    assert len(pairs) == len(set(pairs)), "duplicate (entity, field_key) detected"


def test_registry_has_expected_baseline_size() -> None:
    """Pinned so accidental deletion of a seed breaks a test."""
    assert len(list_all()) >= 25, "registry shrank unexpectedly"


def test_known_field_resolves() -> None:
    budget = get("lead", "budget")
    assert budget is not None
    assert budget.field_type == "currency"
    assert budget.default_label == "Budget (₹)"


def test_unknown_field_returns_none() -> None:
    assert get("unicorn", "horn_length") is None
    assert get_overridable_props("unicorn", "horn_length") == frozenset()


def test_list_for_entity_sorts_by_display_order() -> None:
    contacts = list_for_entity("contact")
    orders = [d.default_display_order for d in contacts]
    assert orders == sorted(orders), f"contact fields out of order: {orders}"


# ---------------------------------------------------------------------------
# Invariant enforcement at registration time (`__post_init__`)
# ---------------------------------------------------------------------------


def _minimal(**overrides) -> dict:
    base = dict(
        entity="example",
        field_key="some_field",
        field_type="text",
        default_label="Example",
        default_placeholder=None,
        default_help=None,
        default_required=False,
        default_min=None,
        default_max=None,
        default_step=None,
        default_display_order=0,
        backend_required=False,
        backend_validators=(),
        overridable_props=frozenset({"label"}),
    )
    base.update(overrides)
    return base


def test_unknown_overridable_prop_rejected() -> None:
    with pytest.raises(ValueError, match="unknown overridable_props"):
        StandardFieldDef(**_minimal(overridable_props=frozenset({"colour"})))


def test_numeric_only_props_rejected_on_text_field() -> None:
    with pytest.raises(ValueError, match="only valid on number/currency"):
        StandardFieldDef(
            **_minimal(field_type="text", overridable_props=frozenset({"min"}))
        )


def test_numeric_only_props_allowed_on_currency_field() -> None:
    StandardFieldDef(
        **_minimal(
            field_type="currency",
            overridable_props=frozenset({"min", "max", "step"}),
        )
    )


def test_required_cannot_be_overridden_when_backend_required() -> None:
    with pytest.raises(ValueError, match="backend_required"):
        StandardFieldDef(
            **_minimal(
                backend_required=True,
                overridable_props=frozenset({"required"}),
            )
        )


def test_hidden_cannot_be_overridden_when_backend_required() -> None:
    with pytest.raises(ValueError, match="backend_required"):
        StandardFieldDef(
            **_minimal(
                backend_required=True,
                overridable_props=frozenset({"hidden"}),
            )
        )


def test_bad_entity_name_rejected() -> None:
    with pytest.raises(ValueError, match="snake_case"):
        StandardFieldDef(**_minimal(entity="Bad-Name"))


def test_bad_field_key_rejected() -> None:
    with pytest.raises(ValueError, match="snake_case"):
        StandardFieldDef(**_minimal(field_key="Bad Key"))


# ---------------------------------------------------------------------------
# Seed-level contract: NOT NULL safety + numeric grammar across the seeds
# ---------------------------------------------------------------------------


def test_seeds_never_expose_required_on_backend_required_fields() -> None:
    for d in list_all():
        if d.backend_required:
            assert "required" not in d.overridable_props, (
                f"{d.entity}.{d.field_key}: exposes 'required' but backend_required=True"
            )
            assert "hidden" not in d.overridable_props, (
                f"{d.entity}.{d.field_key}: exposes 'hidden' but backend_required=True"
            )


def test_seeds_keep_numeric_props_off_non_numeric_fields() -> None:
    numeric = {"number", "currency"}
    illegal = {"min", "max", "step"}
    for d in list_all():
        if d.field_type not in numeric:
            leak = d.overridable_props & illegal
            assert not leak, (
                f"{d.entity}.{d.field_key} ({d.field_type}): exposes numeric-only props {sorted(leak)}"
            )


def test_seeds_all_have_non_empty_label() -> None:
    for d in list_all():
        assert d.default_label.strip(), f"{d.entity}.{d.field_key} has blank default_label"


# ---------------------------------------------------------------------------
# Role-template grants
# ---------------------------------------------------------------------------


def test_admin_role_template_grants_manage_key() -> None:
    admin = ROLE_TEMPLATES["admin"]
    assert "settings.standard_fields.manage" in admin.permission_keys


def test_owner_role_template_grants_manage_key() -> None:
    owner = ROLE_TEMPLATES["owner"]
    # Owner currently uses a curated key list (not ALL_KEYS) — admin keys are
    # the base. Confirm the new key flowed through.
    assert "settings.standard_fields.manage" in owner.permission_keys


def test_employee_role_template_does_not_grant_manage_key() -> None:
    employee = ROLE_TEMPLATES["employee"]
    assert "settings.standard_fields.manage" not in employee.permission_keys


# ---------------------------------------------------------------------------
# Module-descriptor registration
# ---------------------------------------------------------------------------


def test_standard_fields_module_declares_the_permission_key() -> None:
    from src.app.core.standard_fields.module import MODULE

    assert MODULE.id == "standard_fields"
    assert MODULE.permissions == ["settings.standard_fields.manage"]
    # Not in sidebar — reached from Settings (rule 5).
    assert MODULE.menu_position is None
