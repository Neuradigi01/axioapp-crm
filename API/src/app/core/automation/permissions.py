"""Permission key constants for the automation engine.

Three keys cover every action the module gates:

* :data:`PERM_READ` — list / get triggers + read the event-type
  discovery catalog. Granted to Owner / Admin / Employee (Employee
  is read-only so the Settings → Automations sidebar entry renders
  for everyone but mutations are gated).
* :data:`PERM_WRITE` — create / patch / enable / disable / delete
  triggers. Owner + Admin by default; Employee can be granted via
  the Roles page.
* :data:`PERM_RUNS_READ` — list runs + per-run inspection. Owner +
  Admin (run payloads can contain sensitive contact data so this is
  scoped tighter than the trigger-read key).

The keys are registered into the global ``tbl_permissions`` table
by the app-startup lifespan via the module registry — see
:mod:`core.automation.module` (Step 7 lands the module descriptor;
until then, the Step 3 backfill migration registers the keys
directly so the role-template fanout JOIN finds them).

Sourced from one place so the role-template seeds in
:mod:`core.permissions.role_templates` and the backfill migration
import them by name instead of hard-coding the strings.
"""
from __future__ import annotations


PERM_READ = "automations.read"
PERM_WRITE = "automations.write"
PERM_RUNS_READ = "automations.runs.read"


#: Every permission key this module declares.
ALL_KEYS: tuple[str, ...] = (
    PERM_READ,
    PERM_WRITE,
    PERM_RUNS_READ,
)


__all__ = [
    "ALL_KEYS",
    "PERM_READ",
    "PERM_RUNS_READ",
    "PERM_WRITE",
]
