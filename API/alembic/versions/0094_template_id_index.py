"""tbl_campaigns.template_id index for fast performance-card joins
(whatsapp-platform-upgrade Step 10).

Adds a single-column B-tree on ``tbl_campaigns.template_id``. The
template performance endpoint pulls aggregated send / delivery /
read / fail counts via:

    SELECT cm.*
    FROM tbl_campaign_messages cm
    JOIN tbl_campaigns c ON c.id = cm.campaign_id
    WHERE c.template_id = :template_id
      AND cm.created_at >= :since

Without the index, the join scans the full ``tbl_campaigns`` table —
fine at 100 campaigns, painful at 10,000. With it, the planner picks
an index seek on ``template_id`` then a nested loop into the
``ix_campaign_messages_campaign_status`` index.

Idempotent — the migration uses ``IF NOT EXISTS`` so a re-apply after
manual creation is a no-op.

Chains after ``0093_wa_templates_mgmt``.

Revision ID: 0094_template_id_idx
Revises: 0093_wa_templates_mgmt
Create Date: 2026-06-22 00:02:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0094_template_id_idx"
down_revision: Union[str, None] = "0093_wa_templates_mgmt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_campaigns_template_id "
        "ON tbl_campaigns(template_id) "
        "WHERE template_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_campaigns_template_id")
