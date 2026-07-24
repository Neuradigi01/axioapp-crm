"""Bridge: translate ``tbl_custom_field_definitions`` rows into
:class:`~core.automation.field_specs.FieldSpec` instances so custom
fields appear in the condition builder's dropdown alongside system
fields (``tasks/automation-conditions/`` Step 6).

Zero-config from the operator's side — they add a custom field
under Settings → Custom Fields once, and it shows up in every
relevant automation trigger the moment they open the editor.

Design:

* **``_CUSTOM_DATA_MOUNTS``** — code-owned const that says, per
  event type, which entity dicts on the payload carry a
  ``custom_data`` sub-dict. Every mounted entity type gets its
  definitions pulled + appended to the event's ``condition_fields``
  at ``/event-types`` response time.

  Same rationale as the base catalog for staying in code: a table
  would drift from the publisher shape without the runtime
  drift-guard check.

* **Type map** — Custom-field ``FieldType`` enum values map into
  the automation ``FieldType`` values used by the condition builder.
  Text / email / phone all collapse to ``text`` (same op set).
  ``select`` and ``multiselect`` both become ``enum`` with a
  wildcard resolver key ``custom_field_options:<entity>:<field>``
  that step-2's registry dispatches through the wildcard handler
  in :mod:`core.automation.enum_resolvers`.

* **Group naming** — custom fields land under ``"<Entity> custom
  fields"`` (Title-cased entity) so the dropdown renders them
  under their own header, matching HubSpot / Salesforce behaviour
  where system + custom fields never mix in the same section.

* **Pin test invariant** — every mount in ``_CUSTOM_DATA_MOUNTS``
  must point at a payload path that actually resolves through the
  matching event's ``sample_payload``. The pin test in
  ``test_custom_field_discovery.py`` walks the map + the catalog
  and fails CI on drift (e.g. renaming ``lead.custom_data`` on the
  publisher without updating the mount).
"""

from __future__ import annotations

from src.app.core.automation.field_specs import FieldSpec, FieldType
from src.app.core.custom_fields.models import CustomFieldDefinition
from src.app.core.custom_fields.models import FieldType as CustomFieldType

# Per-event map of (entity_type, mount_path_prefix) pairs. The
# handler walks the entities the customer's org has custom fields
# on, resolves each definition to a FieldSpec whose path is
# ``<mount_path_prefix>.<field_key>``, then appends to the event's
# condition_fields.
#
# Extending this map is a code change (matches the base catalog):
#   1. Confirm the event's sample_payload carries the entity dict
#      with a `custom_data` key (drift-guard pin catches otherwise).
#   2. Add the entry below.
#   3. Every org with matching custom_field_definitions rows sees
#      their fields in the picker on next request — no DB migration,
#      no cache invalidation.
_CUSTOM_DATA_MOUNTS: dict[str, tuple[tuple[str, str], ...]] = {
    "lead.created": (("lead", "lead.custom_data"),),
    "lead.assigned": (("lead", "lead.custom_data"),),
    "lead.status_changed": (("lead", "lead.custom_data"),),
    "lead.score_threshold": (("lead", "lead.custom_data"),),
    "lead.stale_30d": (("lead", "lead.custom_data"),),
    "contact.birthday": (("contact", "contact.custom_data"),),
    "contact.created": (("contact", "contact.custom_data"),),
    "appointment.booked": (
        ("appointment", "appointment.custom_data"),
        ("contact", "contact.custom_data"),
    ),
    "appointment.reminder_24h": (
        ("appointment", "appointment.custom_data"),
        ("contact", "contact.custom_data"),
    ),
    "appointment.reminder_1h": (
        ("appointment", "appointment.custom_data"),
        ("contact", "contact.custom_data"),
    ),
    # Step-7-follow-up appointment lifecycle events — same envelope
    # shape as booked/reminder, custom_data on both entity dicts.
    "appointment.cancelled": (
        ("appointment", "appointment.custom_data"),
        ("contact", "contact.custom_data"),
    ),
    "appointment.no_show": (
        ("appointment", "appointment.custom_data"),
        ("contact", "contact.custom_data"),
    ),
    "appointment.completed": (
        ("appointment", "appointment.custom_data"),
        ("contact", "contact.custom_data"),
    ),
    "appointment.rescheduled": (
        ("appointment", "appointment.custom_data"),
        ("contact", "contact.custom_data"),
    ),
    # Step-7-follow-up walk_in.converted — contact + lead both carry
    # custom_data since the walk-in-to-lead conversion produces both.
    "walk_in.converted": (
        ("contact", "contact.custom_data"),
        ("lead", "lead.custom_data"),
    ),
    # Step-7-follow-up invoice events — the invoice module doesn't
    # have a custom_data column on the invoice itself, but the
    # contact snapshot carries one so we mount contact's here.
    "invoice.voided": (("contact", "contact.custom_data"),),
    "invoice.overdue_14d": (("contact", "contact.custom_data"),),
    "invoice.overdue_30d": (("contact", "contact.custom_data"),),
}


# Custom-field FieldType (owned by core/custom_fields) → automation
# FieldType (owned by core/automation/field_specs). Text-like types
# collapse to the same op set; select / multiselect both become
# enum with a resolver key produced by :func:`_resolver_key`.
_CUSTOM_TO_AUTOMATION_TYPE: dict[CustomFieldType, FieldType] = {
    CustomFieldType.text: FieldType.text,
    CustomFieldType.email: FieldType.text,
    CustomFieldType.phone: FieldType.text,
    CustomFieldType.number: FieldType.number,
    CustomFieldType.currency: FieldType.currency,
    CustomFieldType.date: FieldType.date,
    CustomFieldType.datetime: FieldType.datetime,
    CustomFieldType.boolean: FieldType.boolean,
    CustomFieldType.select: FieldType.enum,
    CustomFieldType.multiselect: FieldType.enum,
}


_CUSTOM_FIELD_OPTIONS_PREFIX = "custom_field_options:"


def resolver_key_for(entity_type: str, field_key: str) -> str:
    """Build the wildcard-registry key for a select/multiselect
    custom field. The handler registered under
    ``custom_field_options:*`` in :mod:`core.automation.enum_resolvers`
    parses this back into ``(entity_type, field_key)`` at lookup
    time."""
    return f"{_CUSTOM_FIELD_OPTIONS_PREFIX}{entity_type}:{field_key}"


def parse_resolver_key(key: str) -> tuple[str, str] | None:
    """Reverse of :func:`resolver_key_for`. Returns
    ``(entity_type, field_key)`` or ``None`` when the key isn't
    a custom-field options key. The wildcard resolver handler
    calls this to figure out which definition to look up."""
    if not key.startswith(_CUSTOM_FIELD_OPTIONS_PREFIX):
        return None
    tail = key[len(_CUSTOM_FIELD_OPTIONS_PREFIX) :]
    if ":" not in tail:
        return None
    entity_type, _, field_key = tail.partition(":")
    if not entity_type or not field_key:
        return None
    return entity_type, field_key


def group_name_for(entity_type: str) -> str:
    """Section header for the field dropdown. Frontend renders
    ``── Lead custom fields ──`` etc. — always distinct from the
    system-field groups so a customer never mistakes a custom
    field for a built-in one."""
    return f"{entity_type.title()} custom fields"


def to_field_spec(definition: CustomFieldDefinition, mount_path: str) -> FieldSpec:
    """Translate one ``CustomFieldDefinition`` row into a
    ``FieldSpec`` the catalog handler can append to an event's
    ``condition_fields``.

    ``mount_path`` is the payload dot-path prefix from
    ``_CUSTOM_DATA_MOUNTS`` (e.g. ``lead.custom_data``); the
    resulting spec's path becomes ``<mount_path>.<field_key>``,
    which matches the shape the runtime evaluator expects and the
    payload the domain module publishes.

    The definition's ``field_type`` must be in
    :data:`_CUSTOM_TO_AUTOMATION_TYPE` — the mapping covers every
    ``CustomFieldType`` enum member today; adding a new one
    without updating the map raises ``KeyError`` here at import
    time and the CI pin catches it.
    """
    auto_type = _CUSTOM_TO_AUTOMATION_TYPE[definition.field_type]
    resolver = (
        resolver_key_for(definition.entity_type, definition.field_key)
        if auto_type is FieldType.enum
        else None
    )
    return FieldSpec(
        path=f"{mount_path}.{definition.field_key}",
        label=definition.field_label,
        type=auto_type,
        group=group_name_for(definition.entity_type),
        enum_resolver=resolver,
    )


def mounts_for(event_type: str) -> tuple[tuple[str, str], ...]:
    """Public read of the mount map — returns the ``(entity_type,
    mount_path)`` pairs for an event, or an empty tuple when the
    event doesn't declare any ``custom_data`` mounts."""
    return _CUSTOM_DATA_MOUNTS.get(event_type, ())


def all_mounted_entity_types() -> set[str]:
    """Union of every entity type referenced anywhere in the mount
    map. The service layer uses this to build the single batched
    SELECT that pulls definitions for every entity in one round-trip
    per catalog response."""
    return {entity for pairs in _CUSTOM_DATA_MOUNTS.values() for entity, _ in pairs}


__all__ = [
    "all_mounted_entity_types",
    "group_name_for",
    "mounts_for",
    "parse_resolver_key",
    "resolver_key_for",
    "to_field_spec",
]
