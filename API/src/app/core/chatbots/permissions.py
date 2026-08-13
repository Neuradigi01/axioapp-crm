"""Permission key constants for the chatbots module.

Four keys cover every action the module gates:

* :data:`PERM_VIEW` — list / get + version-history read + save-target
  picker. Granted to Owner / Admin / Employee so the sidebar entry
  renders for everyone; mutations are gated on the next three keys.
* :data:`PERM_EDIT` — create / patch / pause. Owner + Admin by
  default; Employee can be granted via the Roles page.
* :data:`PERM_PUBLISH` — flip ``draft → live`` + rollback to a prior
  version. Separate from ``edit`` so a junior author can draft
  without going live and Owner/Admin reviews before activation.
* :data:`PERM_DELETE` — archive a bot (soft delete). Owner + Admin
  only; the archive is reversible via the list page's "restore"
  action which uses :data:`PERM_EDIT`.

Keys land in ``tbl_permissions`` two ways:
  1. App-startup module-registry sweep — :mod:`core.chatbots.module`
     lists them in the ``ModuleDescriptor``.
  2. Alembic backfill migration ``0191_bf_chatbots_perm`` — fans
     grants out to Owner / Admin / Employee rows on existing orgs
     so live tenants pick the keys up without waiting for restart.

Role-template registrations in
:mod:`core.permissions.role_templates` import the constants below
so the seed for new orgs stays in sync.
"""

from __future__ import annotations

PERM_VIEW = "chatbots.view"
PERM_EDIT = "chatbots.edit"
PERM_PUBLISH = "chatbots.publish"
PERM_DELETE = "chatbots.delete"


#: Every permission key this module declares.
ALL_KEYS: tuple[str, ...] = (
    PERM_VIEW,
    PERM_EDIT,
    PERM_PUBLISH,
    PERM_DELETE,
)


#: Keys an Owner holds — every key.
OWNER_KEYS: tuple[str, ...] = ALL_KEYS

#: Keys an Admin holds — every key (same as Owner; the difference
#: between Owner + Admin lives in tenant-management keys, not in
#: chatbots).
ADMIN_KEYS: tuple[str, ...] = ALL_KEYS

#: Keys an Employee holds by default — read-only view of the list +
#: version history. Mutation, publish, and archive stay Owner/Admin.
EMPLOYEE_KEYS: tuple[str, ...] = (PERM_VIEW,)


__all__ = [
    "ADMIN_KEYS",
    "ALL_KEYS",
    "EMPLOYEE_KEYS",
    "OWNER_KEYS",
    "PERM_DELETE",
    "PERM_EDIT",
    "PERM_PUBLISH",
    "PERM_VIEW",
]
