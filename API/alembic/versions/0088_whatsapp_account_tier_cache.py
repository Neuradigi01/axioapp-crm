"""tbl_whatsapp_account_configs.messaging_limit_tier + tier_synced_at —
per-org cache of Meta's `messaging_limit_tier` (Step 3.5.16).

Populated on-demand by `core.integrations.whatsapp.status.get_send_capacity`
via a single Graph API call (`GET /{phone_id}?fields=messaging_limit_tier`)
and refreshed when the cached value is older than 1 hour. The campaign
create modal reads this column (via the service) to render the
"X / Y messages remaining today" banner.

Both columns are nullable so existing rows stay valid post-migration —
NULL means "never fetched yet", which the service treats as a cache
miss and triggers an immediate Meta lookup on first call.

No backfill: the next request from each connected org populates its own
row organically. No new index either — single-row lookup keyed on
`integration_id` is already covered by the existing primary key /
unique constraint chain.

Chains after `0087_rename_to_tbl_prefix` (which renamed
`whatsapp_account_configs` → `tbl_whatsapp_account_configs`), so this
migration targets the post-rename table name.

Revision ID: 0088_whatsapp_account_tier_cache
Revises: 0087_rename_to_tbl_prefix
Create Date: 2026-06-15 07:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0088_whatsapp_account_tier_cache"
down_revision: Union[str, None] = "0087_rename_to_tbl_prefix"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column(
            "messaging_limit_tier",
            sa.Text(),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column(
            "tier_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_whatsapp_account_configs", "tier_synced_at")
    op.drop_column("tbl_whatsapp_account_configs", "messaging_limit_tier")
