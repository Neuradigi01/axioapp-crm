"""Contacts module — Layer 1 universal CRM contact CRUD.

Stores the canonical fields every furniture-CRM contact has (name,
phone, email, source, tags, notes) and everything else flows through
the per-org `custom_field_definitions` (rule 3, rule 4).
"""

from src.app.core.contacts.service import (
    create_contact,
    delete_contact,
    list_contacts,
    update_contact,
)

__all__ = [
    "create_contact",
    "delete_contact",
    "list_contacts",
    "update_contact",
]
