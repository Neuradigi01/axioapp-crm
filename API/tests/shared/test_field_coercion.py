"""Unit tests for the per-type coercion dispatch in
``shared.custom_fields.coercion``.

Each test pins the 422 detail-string format the FE dynamic-form
renderer parses. The dispatch-table covers every ``FieldType`` value —
adding a new type without a registered coercer surfaces as a 500.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.app.core.custom_fields.models import FieldType
from src.app.shared.custom_fields.coercion import (
    _COERCERS,
    coerce_boolean,
    coerce_iso_date,
    coerce_iso_datetime,
    coerce_number,
    coerce_string,
    coerce_string_list,
    coerce_value,
)


# --- dispatch-table coverage --------------------------------------------


def test_dispatch_covers_every_field_type() -> None:
    """If a new ``FieldType`` is added without a coercer entry,
    ``coerce_value`` falls through to a 500. Cheaper to catch via this
    set-equality test."""
    assert set(_COERCERS) == set(FieldType)


# --- string-based coercer (text / phone / email / select) --------------


@pytest.mark.parametrize(
    "field_type",
    [FieldType.text, FieldType.phone, FieldType.email, FieldType.select],
)
def test_string_coercer_used_for_string_types(field_type: FieldType) -> None:
    assert _COERCERS[field_type] is coerce_string


def test_coerce_string_accepts_string() -> None:
    assert coerce_string("name", "alpha") == "alpha"


def test_coerce_string_rejects_non_string() -> None:
    with pytest.raises(HTTPException) as exc:
        coerce_string("name", 42)
    assert exc.value.status_code == 422
    assert exc.value.detail == "custom_data.name: expected string"


# --- multiselect ---------------------------------------------------------


def test_coerce_string_list_accepts_list_of_strings() -> None:
    assert coerce_string_list("tags", ["a", "b"]) == ["a", "b"]


def test_coerce_string_list_rejects_non_list() -> None:
    with pytest.raises(HTTPException) as exc:
        coerce_string_list("tags", "a")
    assert exc.value.detail == "custom_data.tags: expected list of strings"


def test_coerce_string_list_rejects_mixed_list() -> None:
    with pytest.raises(HTTPException) as exc:
        coerce_string_list("tags", ["a", 1])
    assert exc.value.detail == "custom_data.tags: expected list of strings"


# --- number / currency --------------------------------------------------


@pytest.mark.parametrize("field_type", [FieldType.number, FieldType.currency])
def test_number_coercer_shared_by_number_and_currency(field_type: FieldType) -> None:
    assert _COERCERS[field_type] is coerce_number


def test_coerce_number_accepts_int_and_float() -> None:
    assert coerce_number("budget", 100) == 100
    assert coerce_number("budget", 9.99) == 9.99


def test_coerce_number_rejects_bool() -> None:
    """``bool`` is a subclass of ``int`` — must be rejected explicitly so
    ``True`` doesn't slip into a number field."""
    with pytest.raises(HTTPException) as exc:
        coerce_number("budget", True)
    assert exc.value.detail == "custom_data.budget: expected number"


def test_coerce_number_rejects_string() -> None:
    with pytest.raises(HTTPException) as exc:
        coerce_number("budget", "100")
    assert exc.value.detail == "custom_data.budget: expected number"


# --- boolean ------------------------------------------------------------


def test_coerce_boolean_accepts_bool() -> None:
    assert coerce_boolean("active", True) is True
    assert coerce_boolean("active", False) is False


def test_coerce_boolean_rejects_int() -> None:
    """``1`` is truthy but isn't a bool — keep types strict at the
    JSON edge."""
    with pytest.raises(HTTPException) as exc:
        coerce_boolean("active", 1)
    assert exc.value.detail == "custom_data.active: expected boolean"


# --- date ---------------------------------------------------------------


def test_coerce_iso_date_accepts_valid() -> None:
    assert coerce_iso_date("dob", "2026-06-02") == "2026-06-02"


def test_coerce_iso_date_rejects_non_string() -> None:
    with pytest.raises(HTTPException) as exc:
        coerce_iso_date("dob", 20260602)
    assert exc.value.detail == "custom_data.dob: expected ISO date string"


def test_coerce_iso_date_rejects_garbage_string() -> None:
    with pytest.raises(HTTPException) as exc:
        coerce_iso_date("dob", "not-a-date")
    assert exc.value.detail == "custom_data.dob: invalid ISO date"


# --- datetime -----------------------------------------------------------


def test_coerce_iso_datetime_accepts_valid() -> None:
    val = "2026-06-02T12:30:00+00:00"
    assert coerce_iso_datetime("ts", val) == val


def test_coerce_iso_datetime_rejects_non_string() -> None:
    with pytest.raises(HTTPException) as exc:
        coerce_iso_datetime("ts", 20260602)
    assert exc.value.detail == "custom_data.ts: expected ISO datetime string"


def test_coerce_iso_datetime_rejects_garbage() -> None:
    with pytest.raises(HTTPException) as exc:
        coerce_iso_datetime("ts", "not-a-ts")
    assert exc.value.detail == "custom_data.ts: invalid ISO datetime"


# --- coerce_value (top-level dispatch) ---------------------------------


def test_coerce_value_passes_none_through() -> None:
    """A `null` JSON value clears an optional field — never raises."""
    assert coerce_value(FieldType.text, "name", None) is None


def test_coerce_value_dispatches_via_table() -> None:
    """Verify the dispatch call shape end-to-end for two types."""
    assert coerce_value(FieldType.text, "name", "alpha") == "alpha"
    assert coerce_value(FieldType.number, "budget", 50) == 50


def test_coerce_value_raises_500_for_unregistered_field_type(monkeypatch) -> None:
    """Adding a new ``FieldType`` without a coercer entry must fail
    loudly — temporarily drop one to simulate the gap."""
    original = _COERCERS.pop(FieldType.text)
    try:
        with pytest.raises(HTTPException) as exc:
            coerce_value(FieldType.text, "name", "alpha")
        assert exc.value.status_code == 500
        assert "unhandled field_type" in exc.value.detail
    finally:
        _COERCERS[FieldType.text] = original
