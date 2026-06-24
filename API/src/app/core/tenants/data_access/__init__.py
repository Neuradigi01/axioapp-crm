"""Data-access layer for the tenants module.

Pure query helpers — no transactions, no audit, no commits. Leaf
package; never imports a `service.py`.

Current sub-modules:

  - `organizations` : lookups against `tbl_organizations`.

`__init__` re-exports the union so callers see a single
`data_access.X` namespace.
"""
from src.app.core.tenants.data_access.organizations import (
    get_organization_by_id,
    get_organization_by_slug,
)

__all__ = [
    "get_organization_by_id",
    "get_organization_by_slug",
]
