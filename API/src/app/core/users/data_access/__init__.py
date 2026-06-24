"""Data-access layer for the users module.

Pure query helpers — no transactions, no audit writes, no commits.
This package is a **leaf**: sub-modules import models (own + others')
but NEVER import a `service.py`. That guarantees callers can
`from src.app.core.users import data_access` without triggering a
circular import.

Sub-modules split by entity:

  - `users`        : lookups against `tbl_user_login` and `tbl_user_info`.
  - `memberships`  : lookups against `tbl_organization_members`, `tbl_roles`,
                     plus the per-entity open-record queries used by the
                     offboarding flow.

`__init__` re-exports the union so callers see a single `data_access.X`
namespace and don't have to know which sub-file owns which function.
"""
from src.app.core.users.data_access.memberships import (
    assert_not_owner_role,
    compute_open_records_counts,
    count_active_members,
    get_admin_role,
    get_membership,
    get_owner_role,
    get_role_by_id_in_org,
    get_role_in_org,
    list_open_record_ids,
    require_membership,
)
from src.app.core.users.data_access.users import (
    email_exists,
    get_user_by_email,
    get_user_by_uuid,
    get_user_info,
)

__all__ = [
    "assert_not_owner_role",
    "compute_open_records_counts",
    "count_active_members",
    "email_exists",
    "get_admin_role",
    "get_membership",
    "get_owner_role",
    "get_role_by_id_in_org",
    "get_role_in_org",
    "get_user_by_email",
    "get_user_by_uuid",
    "get_user_info",
    "list_open_record_ids",
    "require_membership",
]
