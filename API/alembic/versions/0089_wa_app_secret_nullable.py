"""tbl_whatsapp_account_configs.app_secret_enc → NULLABLE.

Embedded Signup (whatsapp-platform-upgrade Step 2) introduces one
platform-level Meta App secret shared by every ES-connected org. The
secret moves from a per-org column to env (`WHATSAPP_APP_SECRET`), and
ES-connected sidecar rows leave this column NULL.

Legacy manually-connected orgs keep their per-org ciphertext intact —
the webhook signature verifier prefers env then falls back per-org,
so existing connections keep authenticating without re-onboarding.

No data backfill: every connected row today has a non-NULL value, so
the change is purely the constraint relaxation.

Downgrade: empty-string backfill any NULL rows before re-tightening,
so an accidental rollback doesn't fail the NOT NULL constraint on
ES-connected rows.

Chains after `0088_whatsapp_account_tier_cache`.

Revision ID: 0089_wa_app_secret_nullable
Revises: 0088_whatsapp_account_tier_cache
Create Date: 2026-06-19 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0089_wa_app_secret_nullable"
down_revision: Union[str, None] = "0088_whatsapp_account_tier_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "tbl_whatsapp_account_configs",
        "app_secret_enc",
        existing_type=sa.Text(),
        nullable=True,
    )


def downgrade() -> None:
    # Backfill NULLs with empty string before re-tightening — keeps
    # ES-connected rows from blocking the rollback. The signature
    # verifier handles a missing secret gracefully (500 with a
    # configuration error message), so empty values here are safe
    # until the next reconnect overwrites them.
    op.execute(
        "UPDATE tbl_whatsapp_account_configs "
        "SET app_secret_enc = '' WHERE app_secret_enc IS NULL"
    )
    op.alter_column(
        "tbl_whatsapp_account_configs",
        "app_secret_enc",
        existing_type=sa.Text(),
        nullable=False,
    )
