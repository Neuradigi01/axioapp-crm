"""Custom Fields engine — rule 3 of the master prompt.

Per-org, per-entity field definitions stored in
`custom_field_definitions`. The `source` column (`system` / `pack` /
`user`) drives behaviour: which writes are allowed, which fields are
deletable, which keys are immutable. See `service.py` for the central
enforcement.
"""
from src.app.core.custom_fields.service import (
    create_managed_field,
    create_user_field,
    delete_field,
    get_field,
    list_fields,
    render_fields,
    update_field,
)

__all__ = [
    "create_managed_field",
    "create_user_field",
    "delete_field",
    "get_field",
    "list_fields",
    "render_fields",
    "update_field",
]
