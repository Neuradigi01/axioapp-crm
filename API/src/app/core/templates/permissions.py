"""Permission key constants for the central template library.

Five keys cover every action the module gates:

* :data:`PERM_READ` — list / get / preview / fetch variable registry.
  Granted to every CRM-staff role (Owner / Admin / Employee /
  Sales Manager / Support Agent).
* :data:`PERM_WRITE` — create / edit-draft / archive. Owner + Admin
  by default; Employee can be granted via the Roles page.
* :data:`PERM_REVIEW` — approve / reject / request-changes. Comes
  online in Step 4's workflow endpoints. Owner + Admin.
* :data:`PERM_PUBLISH` — publish an approved template (move
  ``approved → published``). Owner + Admin. Step 4 endpoint.
* :data:`PERM_SUBMIT_EXTERNAL` — submit to Meta (WhatsApp) / DLT
  (SMS, future). Wired in Steps 9 + 12. Owner + Admin.

The keys are registered into the global ``permissions`` table by the
app-startup lifespan via the module registry — see
:mod:`core.templates.module`. They are sourced from one place
(constants here) so the role-template seeds in
:mod:`core.permissions.role_templates` and the backfill migration
(``0118_bf_templates_perm``) can import them by name instead of
hard-coding the strings in three places.
"""

from __future__ import annotations

PERM_READ = "templates.read"
PERM_WRITE = "templates.write"
PERM_REVIEW = "templates.review"
PERM_PUBLISH = "templates.publish"
PERM_SUBMIT_EXTERNAL = "templates.submit_external"
#: Flip a published template active / inactive. Inactive rows are
#: hidden from every send picker (campaigns, workflows, automations,
#: conversations composer) and rejected server-side if they slip
#: through. Owner + Admin by default; grant to any custom role to
#: give them the toggle without unlocking author / publish rights.
PERM_ACTIVATE = "templates.activate"


#: Every permission key this module declares. Imported by
#: :mod:`core.templates.module` for registry registration and by
#: :mod:`core.permissions.role_templates` for role-template seeding.
ALL_KEYS: tuple[str, ...] = (
    PERM_READ,
    PERM_WRITE,
    PERM_REVIEW,
    PERM_PUBLISH,
    PERM_SUBMIT_EXTERNAL,
    PERM_ACTIVATE,
)


__all__ = [
    "ALL_KEYS",
    "PERM_ACTIVATE",
    "PERM_PUBLISH",
    "PERM_READ",
    "PERM_REVIEW",
    "PERM_SUBMIT_EXTERNAL",
    "PERM_WRITE",
]
