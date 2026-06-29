"""Permission key constants for the workflows module.

Six keys cover every action the module gates:

* :data:`PERM_READ` — list / get + view summary analytics. Granted
  to Owner / Admin / Employee (Employee is read-only so the
  Workflows sidebar entry renders for everyone but mutations are
  gated).
* :data:`PERM_WRITE` — create / patch / archive + folder CRUD.
  Owner + Admin by default; Employee can be granted via the Roles
  page.
* :data:`PERM_ACTIVATE` — flip ``draft → active`` /
  ``paused ↔ active``. Separate from ``write`` so a junior author
  can draft without going live + an Owner reviews before
  activation.
* :data:`PERM_CLONE` — clone existing workflows + clone from
  template gallery (Step 16).
* :data:`PERM_VIEW_ANALYTICS` — Step 19 analytics dashboards.
  Slightly tighter than ``read`` because aggregated conversion
  numbers can reveal pipeline shape to junior staff who shouldn't
  see them.
* :data:`PERM_VIEW_DIAGNOSTICS` — Step 19 "why didn't this fire?"
  tool. Exposes per-contact payloads + rule logic; sensitive +
  Owner/Admin only.

The keys are registered into ``tbl_permissions`` by the
app-startup module-registry sweep — see
:mod:`core.workflows.module`. The Step-3 backfill migration
(``0137_bf_workflows_perm``) registers the keys directly so the
role-template fanout JOIN finds them even before the lifespan
hook runs.

Sourced from one place so the role-template seeds in
:mod:`core.permissions.role_templates` and the backfill migration
import them by name instead of hard-coding the strings.
"""
from __future__ import annotations


PERM_READ = "workflows.read"
PERM_WRITE = "workflows.write"
PERM_ACTIVATE = "workflows.activate"
PERM_CLONE = "workflows.clone"
PERM_VIEW_ANALYTICS = "workflows.view_analytics"
PERM_VIEW_DIAGNOSTICS = "workflows.view_diagnostics"


#: Every permission key this module declares.
ALL_KEYS: tuple[str, ...] = (
    PERM_READ,
    PERM_WRITE,
    PERM_ACTIVATE,
    PERM_CLONE,
    PERM_VIEW_ANALYTICS,
    PERM_VIEW_DIAGNOSTICS,
)


#: Keys an Owner holds — every key.
OWNER_KEYS: tuple[str, ...] = ALL_KEYS

#: Keys an Admin holds — every key (same as Owner; the difference
#: between Owner + Admin lives in tenant-management keys, not in
#: workflows).
ADMIN_KEYS: tuple[str, ...] = ALL_KEYS

#: Keys an Employee holds by default — read-only view of the list
#: + analytics dashboards. Mutation + activation + diagnostics
#: stay Owner/Admin.
EMPLOYEE_KEYS: tuple[str, ...] = (
    PERM_READ,
    PERM_VIEW_ANALYTICS,
)


__all__ = [
    "ADMIN_KEYS",
    "ALL_KEYS",
    "EMPLOYEE_KEYS",
    "OWNER_KEYS",
    "PERM_ACTIVATE",
    "PERM_CLONE",
    "PERM_READ",
    "PERM_VIEW_ANALYTICS",
    "PERM_VIEW_DIAGNOSTICS",
    "PERM_WRITE",
]
