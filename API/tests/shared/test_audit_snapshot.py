"""Unit tests for `shared.audit.snapshot` + the per-entity helpers it backs.

The contract this step must preserve is that migrated `_snapshot(entity)`
calls produce **bit-identical** dicts to their hand-rolled predecessors —
audit dashboards downstream filter on these payloads.

We test:

1. ``_coerce`` for each primitive type the old hand-rolled snapshots
   used to convert manually.
2. ``snapshot(entity, fields=...)`` against a stand-in object — verifies
   key order, value types, None handling.
3. The migrated per-entity ``_snapshot`` functions against
   stand-in objects whose attributes mirror the pre-refactor shape.
"""

from __future__ import annotations

import uuid
from datetime import date as Date, datetime, timezone
from decimal import Decimal
from enum import Enum
from types import SimpleNamespace

import pytest

from src.app.shared.audit import snapshot
from src.app.shared.audit.snapshots import _coerce


# --- _coerce ---------------------------------------------------------------


def test_coerce_none() -> None:
    assert _coerce(None) is None


def test_coerce_uuid_to_str() -> None:
    u = uuid.UUID("11111111-1111-1111-1111-111111111111")
    assert _coerce(u) == "11111111-1111-1111-1111-111111111111"


def test_coerce_datetime_to_iso() -> None:
    dt = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)
    assert _coerce(dt) == "2026-06-02T12:00:00+00:00"


def test_coerce_date_to_iso() -> None:
    assert _coerce(Date(2026, 6, 2)) == "2026-06-02"


def test_coerce_decimal_preserves_precision() -> None:
    """Decimal → str (not float) so ₹19999.99 doesn't drift to 19999.989999999."""
    assert _coerce(Decimal("19999.99")) == "19999.99"


def test_coerce_enum_uses_value() -> None:
    class _Status(Enum):
        active = "active"
        closed = "closed"

    assert _coerce(_Status.active) == "active"


def test_coerce_tuple_to_list_recursively() -> None:
    """Tags-style ARRAY columns arrive as tuple from SQLAlchemy; old
    handwritten code called ``list(contact.tags)``."""
    assert _coerce(("a", "b")) == ["a", "b"]


def test_coerce_passes_primitives_through() -> None:
    assert _coerce(42) == 42
    assert _coerce("hello") == "hello"
    assert _coerce(True) is True
    assert _coerce({"k": 1}) == {"k": 1}  # JSONB dicts pass through


# --- snapshot --------------------------------------------------------------


def test_snapshot_returns_keys_in_fields_order() -> None:
    """Dict insertion order matches the `fields` tuple so output is
    bit-identical to the pre-refactor handwritten dict literals."""

    row = SimpleNamespace(b="beta", a="alpha", c="gamma")
    result = snapshot(row, fields=("a", "b", "c"))
    assert list(result.keys()) == ["a", "b", "c"]


def test_snapshot_coerces_each_value() -> None:
    row = SimpleNamespace(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        when=datetime(2026, 1, 1, tzinfo=timezone.utc),
        price=Decimal("9.99"),
        note=None,
    )
    result = snapshot(row, fields=("id", "when", "price", "note"))
    assert result == {
        "id": "11111111-1111-1111-1111-111111111111",
        "when": "2026-01-01T00:00:00+00:00",
        "price": "9.99",
        "note": None,
    }


def test_snapshot_missing_attr_raises_loudly() -> None:
    """Better to crash now than silently emit an empty audit payload."""

    with pytest.raises(AttributeError):
        snapshot(SimpleNamespace(a=1), fields=("a", "missing"))


# --- per-entity snapshots: bit-identity vs pre-refactor shape ------------


class _LeadStatus(Enum):
    new = "new"


class _LeadSource(Enum):
    walkin = "walkin"


def test_contact_snapshot_matches_legacy_shape() -> None:
    from src.app.core.contacts.service import _snapshot as contact_snap

    contact = SimpleNamespace(
        id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        full_name="Asha",
        phone="+91-9999999999",
        email="asha@example.com",
        source="walkin",
        tags=("vip", "loyal"),
        notes="repeat buyer",
        custom_data={"preferred_sofa": "L-shape"},
        assigned_to_id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    )

    result = contact_snap(contact)
    assert list(result.keys()) == [
        "id",
        "full_name",
        "phone",
        "email",
        "source",
        "tags",
        "notes",
        "custom_data",
        "assigned_to_id",
    ]
    assert result["id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert result["tags"] == ["vip", "loyal"]
    assert result["assigned_to_id"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert result["custom_data"] == {"preferred_sofa": "L-shape"}


def test_contact_snapshot_handles_null_assigned_to_id() -> None:
    """Unassigned contact — old code did `str(x) if x is not None else None`."""
    from src.app.core.contacts.service import _snapshot as contact_snap

    contact = SimpleNamespace(
        id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        full_name="Bina",
        phone=None,
        email=None,
        source=None,
        tags=(),
        notes=None,
        custom_data={},
        assigned_to_id=None,
    )
    assert contact_snap(contact)["assigned_to_id"] is None


def test_lead_snapshot_coerces_enums_and_decimal_and_date() -> None:
    from src.app.core.leads.service import _snapshot as lead_snap

    lead = SimpleNamespace(
        id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        contact_id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        pipeline_stage="prospect",
        status=_LeadStatus.new,
        source=_LeadSource.walkin,
        assigned_to_id=None,
        budget=Decimal("50000.00"),
        expected_close_date=Date(2026, 8, 1),
        custom_data={"interest": "sofa"},
        attribution=None,
        lost_reason=None,
        lost_reason_other=None,
    )
    result = lead_snap(lead)
    assert result["status"] == "new"
    assert result["source"] == "walkin"
    assert result["budget"] == "50000.00"
    assert result["expected_close_date"] == "2026-08-01"
    assert result["assigned_to_id"] is None
