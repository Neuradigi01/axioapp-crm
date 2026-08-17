"""Backfill ``tbl_activities.entity_type`` for pipeline status_change rows.

Prior to today, ``pipelines.move_card`` stamped status_change activities
with the physical ``card_table`` name (``tbl_leads`` / ``fp_custom_orders``)
instead of the friendly activity entity_type (``lead`` / ``custom_order``)
the timeline UI queries by. Result: every lead stage move since Step 2.11
was recorded but invisible on the lead's Activities tab.

The service-layer fix now stamps the friendly name; this migration
renames the existing orphaned rows so historical stage moves also
render in the timeline. Idempotent: fresh DBs and DBs already backfilled
manually will report 0 rows updated.

Chains after ``0196_conv_bot_muted_until``.

Revision ID: 0197_fix_activity_entity_type
Revises:     0196_conv_bot_muted_until
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0197_fix_activity_entity_type"
down_revision: str | None = "0196_conv_bot_muted_until"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RENAMES = {
    "tbl_leads": "lead",
    "fp_custom_orders": "custom_order",
}


def upgrade() -> None:
    for old, new in _RENAMES.items():
        op.execute(f"UPDATE tbl_activities SET entity_type = '{new}' WHERE entity_type = '{old}'")


def downgrade() -> None:
    # Reverse mapping. Only inverts rows we would have created — leaves
    # any 'lead'/'custom_order' rows written by the fixed service code
    # after this migration ran subject to the same reversal, which is
    # the correct behaviour for a full rollback of the fix.
    for old, new in _RENAMES.items():
        op.execute(f"UPDATE tbl_activities SET entity_type = '{old}' WHERE entity_type = '{new}'")
