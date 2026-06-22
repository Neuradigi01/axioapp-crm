"""Backfill whatsapp.business_profile.manage grant on existing
Owner / Admin roles (whatsapp-platform-upgrade Step 11 follow-up).

Same shape as `0095_backfill_wa_perms` — newly-registered permission
keys are seeded at signup time by `role_templates.py`, so existing
orgs miss the grant until this fanout migration runs.

Owner + Admin both get the key (the page is admin-grade — junior
roles don't get a useful view of it). Idempotent via
``ON CONFLICT DO NOTHING``.

Chains after ``0096_wa_business_profile``.

Revision ID: 0097_backfill_bp_perm
Revises: 0096_wa_business_profile
Create Date: 2026-06-22 00:05:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0097_backfill_bp_perm"
down_revision: Union[str, None] = "0096_wa_business_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_GRANT_KEY = "whatsapp.business_profile.manage"
_ROLE_NAMES = ("Owner", "Admin")


def upgrade() -> None:
    for role_name in _ROLE_NAMES:
        op.execute(
            f"""
            INSERT INTO tbl_role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM tbl_roles r
            CROSS JOIN tbl_permissions p
            WHERE r.name = '{role_name}'
              AND p.key = '{_GRANT_KEY}'
            ON CONFLICT DO NOTHING
            """
        )


def downgrade() -> None:
    for role_name in _ROLE_NAMES:
        op.execute(
            f"""
            DELETE FROM tbl_role_permissions
            WHERE role_id IN (
                SELECT id FROM tbl_roles WHERE name = '{role_name}'
            )
            AND permission_id IN (
                SELECT id FROM tbl_permissions WHERE key = '{_GRANT_KEY}'
            )
            """
        )
