"""Data-access layer for the auth module.

Pure query helpers — no transactions, no audit, no commits. Leaf
package; never imports a `service.py`.

Current sub-modules:

  - `auth_sessions` : lookups against `tbl_auth_sessions`.

`__init__` re-exports the union so callers see a single
`data_access.X` namespace.
"""
from src.app.core.auth.data_access.auth_sessions import get_auth_session

__all__ = [
    "get_auth_session",
]
