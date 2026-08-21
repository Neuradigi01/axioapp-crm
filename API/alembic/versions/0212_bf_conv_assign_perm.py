"""Backfill conversations.assign_others permission key on existing
Owner / Admin roles.

Chains after 0211_phone_e164_prefix. The key itself is registered
into tbl_permissions automatically by the app-startup module-registry
sweep (once the module.py update in this branch ships), but this
migration also inserts it directly so a downgrade of the app code
doesn't leave existing roles without the grant.

Semantics gated by the new key (enforced in
`core/conversations/service.py`):
  * Assign someone else's chat / reassign across users → requires
    this key.
  * Self-assign an *unassigned* chat, or the current assignee
    transferring their own chat → allowed without this key.
  * Reply / react / tag / close / take-over-AI on a chat owned by
    another user → requires this key.
  * Read (list + detail) stays org-wide via `conversations.read`.

Revision ID: 0212_bf_conv_assign_perm
Revises:     0211_phone_e164_prefix
Create Date: 2026-08-21
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0212_bf_conv_assign_perm"
down_revision: Union[str, None] = "0211_phone_e164_prefix"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_KEY = "conversations.assign_others"
_DELEGATING_ROLES = ("Owner", "Admin")


def upgrade() -> None:
    op.execute(
        f"INSERT INTO tbl_permissions (key, module, description) "
        f"VALUES ('{_KEY}', 'conversations', "
        f"'Assign a chat to another user, or interact with a chat owned by someone else "
        f"(Owner/Admin only by default)') "
        f"ON CONFLICT (key) DO NOTHING"
    )
    for role in _DELEGATING_ROLES:
        op.execute(
            f"INSERT INTO tbl_role_permissions (role_id, permission_id) "
            f"SELECT r.id, p.id FROM tbl_roles r CROSS JOIN tbl_permissions p "
            f"WHERE r.name = '{role}' AND p.key = '{_KEY}' "
            f"ON CONFLICT DO NOTHING"
        )


def downgrade() -> None:
    for role in _DELEGATING_ROLES:
        op.execute(
            f"DELETE FROM tbl_role_permissions "
            f"WHERE role_id IN (SELECT id FROM tbl_roles WHERE name = '{role}') "
            f"  AND permission_id IN (SELECT id FROM tbl_permissions WHERE key = '{_KEY}')"
        )
