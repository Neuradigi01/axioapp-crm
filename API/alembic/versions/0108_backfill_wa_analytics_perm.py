"""Backfill whatsapp.analytics.read on existing Owner / Admin
(whatsapp-platform-upgrade Step 20 follow-up).

Same fanout pattern as 0095 / 0097 / 0101 / 0105. Existing orgs need
the permission grant added once; signup orgs already pick it up from
``role_templates.py``.

Chains after ``0107_wa_ai_settings``.

Revision ID: 0108_bf_wa_analytics
Revises: 0107_wa_ai_settings
Create Date: 2026-06-23 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0108_bf_wa_analytics"
down_revision: Union[str, None] = "0107_wa_ai_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_GRANT_KEY = "whatsapp.analytics.read"
_ROLE_NAMES = ("Owner", "Admin")


def upgrade() -> None:
    # The permission row is auto-seeded on app startup by the module
    # registry — but Alembic runs ahead of the FastAPI lifespan, so
    # ensure the row exists here (idempotent on conflict). Matches
    # the pattern used by 0101 / 0105.
    op.execute(
        f"""
        INSERT INTO tbl_permissions (key, description, module)
        VALUES ('{_GRANT_KEY}', 'View WhatsApp analytics dashboard', 'whatsapp')
        ON CONFLICT (key) DO NOTHING
        """
    )
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
