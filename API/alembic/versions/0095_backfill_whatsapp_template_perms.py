"""Backfill whatsapp.templates.* permission grants on existing
Owner / Admin / Employee roles (whatsapp-platform-upgrade Step 8 follow-up).

When Step 8 introduced ``whatsapp.templates.{read,write,submit}``, the
keys were added to ``role_templates.py`` — the spec consulted at
*signup time* when a new org is created. Orgs that existed BEFORE
this code change never picked up the grants; their Owner role logs
in and gets 403 at ``/user/whatsapp/templates`` even though the
permission keys are registered in ``tbl_permissions``.

This migration fans the grants out across every existing org:

  * Owner role  → read + write + submit
  * Admin role  → read + write + submit
  * Employee    → read only

Idempotent via ``ON CONFLICT DO NOTHING`` — re-running is a no-op.

Permission rows themselves are created at app startup
(``register_permissions`` in the lifespan) — this migration relies on
that having already happened. If a deploy somehow runs this migration
before the app has booted, the INSERT skips rows whose key isn't yet
registered (the inner SELECT returns no match → INSERT inserts zero
rows). The next API startup then registers the permissions; re-run
the migration to fan the grants out.

Chains after ``0094_template_id_idx``.

Revision ID: 0095_backfill_wa_perms
Revises: 0094_template_id_idx
Create Date: 2026-06-22 00:03:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0095_backfill_wa_perms"
down_revision: Union[str, None] = "0094_template_id_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Grants per role name. Owner and Admin get the full set; Employee
# gets read so they can use templates from the campaign picker but
# can't author or submit.
_GRANTS_BY_ROLE: dict[str, list[str]] = {
    "Owner": [
        "whatsapp.templates.read",
        "whatsapp.templates.write",
        "whatsapp.templates.submit",
    ],
    "Admin": [
        "whatsapp.templates.read",
        "whatsapp.templates.write",
        "whatsapp.templates.submit",
    ],
    "Employee": [
        "whatsapp.templates.read",
    ],
}


def upgrade() -> None:
    for role_name, keys in _GRANTS_BY_ROLE.items():
        for key in keys:
            op.execute(
                f"""
                INSERT INTO tbl_role_permissions (role_id, permission_id)
                SELECT r.id, p.id
                FROM tbl_roles r
                CROSS JOIN tbl_permissions p
                WHERE r.name = '{role_name}'
                  AND p.key = '{key}'
                ON CONFLICT DO NOTHING
                """
            )


def downgrade() -> None:
    # Revoke every grant this migration created. Honours roles whose
    # operator may have hand-removed the grant in between — the
    # DELETE just removes whatever's there for these (role, perm)
    # pairs and leaves anything else untouched.
    for role_name, keys in _GRANTS_BY_ROLE.items():
        for key in keys:
            op.execute(
                f"""
                DELETE FROM tbl_role_permissions
                WHERE role_id IN (
                    SELECT id FROM tbl_roles WHERE name = '{role_name}'
                )
                AND permission_id IN (
                    SELECT id FROM tbl_permissions WHERE key = '{key}'
                )
                """
            )
