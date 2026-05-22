"""Standard Field Overrides — code-defined registry of overridable
canonical fields.

Importing the package runs `registry.py` at module load, which registers
the core CRM seeds (contact, lead, walk_in, task, appointment,
catalog_item) into the in-process dict. Pack installers may call
`register(...)` to extend the registry for their own entities.
"""
from src.app.core.standard_fields import registry  # noqa: F401  - triggers seed registrations
from src.app.core.standard_fields.registry import (
    StandardFieldDef,
    get,
    get_overridable_props,
    list_all,
    list_entities,
    list_for_entity,
    register,
)

__all__ = [
    "StandardFieldDef",
    "get",
    "get_overridable_props",
    "list_all",
    "list_entities",
    "list_for_entity",
    "register",
]
