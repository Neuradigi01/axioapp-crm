"""Pin tests for the Step-3 event-type discovery catalog.

The catalog is the contract between the dispatcher + every
publisher's emit site. Step 5+ will add a consistency pin-test that
walks every ``bus.publish`` call and fails CI if its event_type is
not in the catalog; this file pins the catalog's own shape.
"""

from __future__ import annotations

from src.app.core.automation import event_catalog


def test_catalog_carries_manager_required_events():
    """The two events the manager explicitly called out for the v1
    default seeded triggers MUST always be in the catalog."""
    assert event_catalog.is_known("user.signed_up")
    assert event_catalog.is_known("lead.created")


def test_catalog_carries_sales_lifecycle_events():
    """Quote + invoice lifecycle events from Steps 11 / 12 of the
    automation-engine track."""
    for event_type in (
        "quote.sent",
        "quote.accepted",
        "invoice.sent",
        "invoice.overdue_7d",
    ):
        assert event_catalog.is_known(event_type), event_type


def test_catalog_carries_appointment_events():
    for event_type in (
        "appointment.booked",
        "appointment.reminder_24h",
        "appointment.reminder_1h",
    ):
        assert event_catalog.is_known(event_type), event_type


def test_get_entry_returns_none_for_unknown():
    assert event_catalog.get_entry("nope.fake") is None


def test_list_catalog_is_sorted_by_event_type():
    """Editor-side picker uses this ordering verbatim — pin so a
    refactor doesn't shuffle the operator's eyes around."""
    entries = event_catalog.list_catalog()
    event_types = [e.event_type for e in entries]
    assert event_types == sorted(event_types)


def test_every_entry_has_label_description_and_payload():
    """Operator-facing fields — guard against an empty label /
    description sneaking in (would break the picker UI)."""
    for entry in event_catalog.list_catalog():
        assert entry.label.strip(), f"empty label for {entry.event_type}"
        assert entry.description.strip(), f"empty description for {entry.event_type}"
        assert isinstance(entry.sample_payload, dict), entry.event_type
        assert entry.sample_payload, f"empty sample_payload for {entry.event_type}"


def test_catalog_entry_carries_condition_fields_shape():
    """tasks/automation-conditions/ Step 1 — every entry ships a
    ``condition_fields`` tuple of :class:`FieldSpec`. Deeper coverage
    lives in ``test_field_spec_coverage.py``; this test pins the
    shape extension so a refactor can't drop the attribute."""
    lead_created = event_catalog.get_entry("lead.created")
    assert lead_created is not None
    assert hasattr(lead_created, "condition_fields")
    assert isinstance(lead_created.condition_fields, tuple)
    assert lead_created.condition_fields, "lead.created lost its condition_fields"


def test_lead_created_payload_has_contact_and_lead_keys():
    """The `lead.created` event is the most variable-rich event in
    the v1 catalog — pin its sample_payload shape so the editor's
    variable picker can rely on ``contact.*`` + ``lead.*`` paths."""
    entry = event_catalog.get_entry("lead.created")
    assert entry is not None
    assert "contact" in entry.sample_payload
    assert "lead" in entry.sample_payload
    assert "first_name" in entry.sample_payload["contact"]
    assert "source" in entry.sample_payload["lead"]
