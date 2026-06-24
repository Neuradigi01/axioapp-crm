"""Data-access layer for the contacts module.

Pure query helpers — no transactions, no audit, no commits. Leaf
package; never imports a `service.py`.

Current sub-modules:

  - `contacts` : lookups against `tbl_contacts`.

`__init__` re-exports the union so callers see a single
`data_access.X` namespace.
"""
from src.app.core.contacts.data_access.contacts import (
    get_contact,
    get_contact_by_phone,
)

__all__ = [
    "get_contact",
    "get_contact_by_phone",
]
