"""Registry of entity types a custom event can bind to.

Each entry declares:

  * ``model_getter`` — lazy import of the SQLAlchemy model. Lazy so a
    circular import between custom_events and (e.g.) leads doesn't
    break app boot.
  * ``label`` — human-readable name used in dropdowns.
  * ``contact_id_ref`` — attribute name to reach the related contact.
    For ``contact`` the row IS the contact (``id``). For
    ``lead`` / ``appointment`` this is the FK column.
  * ``system_date_fields`` — tuple of physical date/datetime columns
    the sweeper's system branch can watch (with a labelled name for
    the picker).
  * ``custom_fields_entity_key`` — the string used in
    ``tbl_custom_field_definitions.entity_type`` for this entity.

Adding a new entity is one entry + no other changes anywhere else.
The date-field catalog + the sweeper + the frontend picker all read
from this registry.

Design intent: keep every entity-specific knowledge in ONE place so
Contact / Lead / Appointment stay symmetric and the sweeper's branch
code is a for-loop over the registry, not a chain of ``if`` blocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class SystemDateField:
    """One physical date/datetime column that can drive a scheduled
    event. ``column`` is the SQL / ORM attribute name; ``label`` is
    the human-readable picker label; ``recurring_hint`` is a UI-only
    suggestion the frontend can preselect (e.g. yearly for birthday)."""

    column: str
    label: str
    recurring_hint: str  # 'none' | 'yearly' | 'monthly'


@dataclass(frozen=True, slots=True)
class EntitySpec:
    label: str
    model_getter: Callable
    contact_id_ref: str  # 'id' for contact, 'contact_id' otherwise
    system_date_fields: tuple[SystemDateField, ...]
    custom_fields_entity_key: str


def _contact_model():
    from src.app.core.contacts.models import Contact
    return Contact


def _lead_model():
    from src.app.core.leads.models import Lead
    return Lead


def _appointment_model():
    from src.app.core.appointments.models import Appointment
    return Appointment


ENTITY_REGISTRY: dict[str, EntitySpec] = {
    "contact": EntitySpec(
        label="Contact",
        model_getter=_contact_model,
        contact_id_ref="id",
        system_date_fields=(
            SystemDateField(
                column="date_of_birth",
                label="Date of birth",
                recurring_hint="yearly",
            ),
            SystemDateField(
                column="created_at",
                label="Created date",
                recurring_hint="none",
            ),
            SystemDateField(
                column="last_activity_at",
                label="Last activity date",
                recurring_hint="none",
            ),
        ),
        custom_fields_entity_key="contact",
    ),
    "lead": EntitySpec(
        label="Lead",
        model_getter=_lead_model,
        contact_id_ref="contact_id",
        system_date_fields=(
            SystemDateField(
                column="expected_close_date",
                label="Expected close date",
                recurring_hint="none",
            ),
            SystemDateField(
                column="close_date",
                label="Close date",
                recurring_hint="none",
            ),
            SystemDateField(
                column="last_activity_at",
                label="Last activity date",
                recurring_hint="none",
            ),
            SystemDateField(
                column="created_at",
                label="Created date",
                recurring_hint="none",
            ),
        ),
        custom_fields_entity_key="lead",
    ),
    "appointment": EntitySpec(
        label="Appointment",
        model_getter=_appointment_model,
        contact_id_ref="contact_id",
        system_date_fields=(
            SystemDateField(
                column="scheduled_at",
                label="Scheduled date",
                recurring_hint="none",
            ),
            SystemDateField(
                column="created_at",
                label="Created date",
                recurring_hint="none",
            ),
        ),
        custom_fields_entity_key="appointment",
    ),
}


SUPPORTED_ENTITY_TYPES: frozenset[str] = frozenset(ENTITY_REGISTRY)


def entity_or_400(entity_type: str) -> EntitySpec:
    """Lookup helper — raises a ``ValueError`` on unknown entity. The
    router / service should map this to a 422 for the API."""
    spec = ENTITY_REGISTRY.get(entity_type)
    if spec is None:
        raise ValueError(
            f"Unknown entity_type {entity_type!r}. Supported: "
            f"{sorted(SUPPORTED_ENTITY_TYPES)}."
        )
    return spec


__all__ = [
    "ENTITY_REGISTRY",
    "EntitySpec",
    "SUPPORTED_ENTITY_TYPES",
    "SystemDateField",
    "entity_or_400",
]
