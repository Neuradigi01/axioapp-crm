"""backfill billing.manage grant onto existing Owner roles.

Step 19 (commit 4ed76c9) added the `billing.manage` permission key and
listed it in `_CORE_OWNER_KEYS`, which stamps the grant onto Owner roles
created at *signup time*. Orgs created before that commit (Ajay's
Workspace, the demo seeds, anything stood up earlier) never received
the grant — their Owners hit `permissionGuard('billing.manage')` and
land on `/access-denied` when they try to reach the Billing page.

This migration walks every existing `roles` row that is the Owner role
for its org (`is_system = TRUE AND name = 'Owner'`) and inserts a
`role_permissions` row pointing at the `billing.manage` permission. The
insert is idempotent (`ON CONFLICT DO NOTHING`) so re-running is safe.

If the `billing.manage` permission row itself is missing — which only
happens when the API has never been started after Step 19 — the
migration is a silent no-op for that key, and the module-registry
discovery will write the permission row on the next startup. The
admin then needs to re-run this migration (or call its `op.execute`
SQL by hand) to grant. The Owner-role-only target prevents the
migration from over-granting if Admin or custom roles share the name
'Owner' in some legacy org.

Revision ID: 0081_owner_billing_manage_grant
Revises:     0080_stripe_webhook_events
Create Date: 2026-06-11
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0081_owner_billing_manage_grant"
down_revision: Union[str, None] = "0080_stripe_webhook_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.is_system = TRUE
          AND r.name = 'Owner'
          AND p.key = 'billing.manage'
        ON CONFLICT (role_id, permission_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions rp
        USING roles r, permissions p
        WHERE rp.role_id = r.id
          AND rp.permission_id = p.id
          AND r.is_system = TRUE
          AND r.name = 'Owner'
          AND p.key = 'billing.manage';
        """
    )
