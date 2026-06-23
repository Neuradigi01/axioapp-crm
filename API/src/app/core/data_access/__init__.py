"""Shared data-access layer for the core/ modules.

Pure query helpers — no transactions, no audit writes, no commits. This
package is a **leaf**: it imports models from any module
(`users.models`, `permissions.models`, the five offboarding-entity
models) but NEVER imports a `service.py`. That guarantees callers can
`from src.app.core import data_access` without triggering a circular
import, regardless of which module they live in.

Sub-modules split by entity:

  - `users`        : lookups against `tbl_user_login` and `tbl_user_info`.
  - `memberships`  : lookups against `tbl_organization_members`, `tbl_roles`,
                     plus the per-entity open-record queries used by the
                     offboarding flow.

Future entities (auth sessions, organisations, etc.) get their own
sibling sub-module here as their query helpers get consolidated.

`__init__` re-exports the union so callers see a single namespace.
"""
from src.app.core.data_access.auth_sessions import get_auth_session
from src.app.core.data_access.contacts import get_contact, get_contact_by_phone
from src.app.core.data_access.organizations import (
    get_organization_by_id,
    get_organization_by_slug,
)
from src.app.core.data_access.memberships import (
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
from src.app.core.data_access.users import (
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
    "get_auth_session",
    "get_contact",
    "get_contact_by_phone",
    "get_membership",
    "get_organization_by_id",
    "get_organization_by_slug",
    "get_owner_role",
    "get_role_by_id_in_org",
    "get_role_in_org",
    "get_user_by_email",
    "get_user_by_uuid",
    "get_user_info",
    "list_open_record_ids",
    "require_membership",
]
