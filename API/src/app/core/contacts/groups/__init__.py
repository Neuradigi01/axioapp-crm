"""Contact groups — saved audiences for campaign targeting (Step 3.5.7).

Two modes share the `contact_groups` table via the `is_dynamic`
discriminator:

  - Dynamic: stores a `filter_json` (q/source/tag/...) that's
    re-evaluated against the current `contacts` set every time the
    group resolves to contact IDs. New matching contacts auto-include.

  - Static: explicit member list in `contact_group_members`. Frozen
    at creation; new matching contacts NEVER auto-include. Used by
    XLSX import (Step 3.5.10) and one-off event blasts.

Public re-exports keep the import surface small for callers — the
campaign audience builder (Step 3.5.9) reaches in via these names.
"""

from src.app.core.contacts.groups.service import (
    create_group,
    delete_group,
    get_group,
    list_groups,
    preview_audience_size,
    resolve_group_contacts,
    update_group,
)

__all__ = [
    "create_group",
    "delete_group",
    "get_group",
    "list_groups",
    "preview_audience_size",
    "resolve_group_contacts",
    "update_group",
]
