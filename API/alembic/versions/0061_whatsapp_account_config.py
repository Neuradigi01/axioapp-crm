"""whatsapp_account_configs — per-(org, integration) WhatsApp Business
Account credentials sidecar.

Builds on top of the existing `integrations` table by adding `whatsapp`
to the `integration_provider` enum and introducing a sidecar table for
WA-specific fields that don't fit the generic shape:

  - `phone_id`              Meta Cloud API phone number ID
  - `waba_id`               WhatsApp Business Account ID (template sync)
  - `display_phone_number`  human-readable number for the Settings UI
  - `verified_name`         business name as approved by Meta
  - `app_secret_enc`        Fernet-encrypted app secret (webhook HMAC)
  - `verify_token`          Meta GET-handshake token (per-org)
  - `api_version`           Graph API version pin (`v18.0` default)

The bearer token itself lives in the parent `integrations` row's
`access_token_enc` — same encryption scheme as Google/Meta Ads tokens.
This keeps the WA module within the existing integrations governance
(rotation, disconnect, audit) without duplicating columns.

Tenant-scoped + RLS via `apply_rls("whatsapp_account_configs")`.

Note on enum extension: `ALTER TYPE … ADD VALUE` is non-transactional on
PG < 12 — Postgres 17 (per CLAUDE.md stack pin) permits it inside a
transaction, so no autocommit_block needed. The downgrade path does NOT
attempt to drop the enum value (Postgres can't drop a single value
without recreating the type, and we don't want to risk breaking
existing references); downgrade leaves `whatsapp` as a defined-but-
unused enum member, which is safe.

Revision ID: 0061_whatsapp_account_config
Revises: 0060_tasks_last_activity
Create Date: 2026-05-27 00:00:00.000000

Slotted at the end of the chain (post-dev-branch migrations 0053–0060
pulled into this branch alongside the WhatsApp work) so the auto-
upgrade at container boot can walk the full chain. When `dev` is
formally merged into `Whatsapp-Inetgration` the chain stays intact.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0061_whatsapp_account_config"
down_revision: Union[str, None] = "0060_tasks_last_activity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE integration_provider ADD VALUE IF NOT EXISTS 'whatsapp'"
    )

    op.create_table(
        "whatsapp_account_configs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("integration_id", UUID(as_uuid=True), nullable=False),
        sa.Column("phone_id", sa.Text(), nullable=False),
        sa.Column("waba_id", sa.Text(), nullable=False),
        sa.Column("display_phone_number", sa.Text(), nullable=False),
        sa.Column("verified_name", sa.Text(), nullable=True),
        sa.Column("app_secret_enc", sa.Text(), nullable=False),
        sa.Column("verify_token", sa.Text(), nullable=False),
        sa.Column(
            "api_version",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'v18.0'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["integrations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_whatsapp_account_configs_integration_id",
        "whatsapp_account_configs",
        ["integration_id"],
        unique=True,
    )
    op.create_index(
        "ix_whatsapp_account_configs_org_id",
        "whatsapp_account_configs",
        ["org_id"],
    )

    apply_rls("whatsapp_account_configs")


def downgrade() -> None:
    drop_rls("whatsapp_account_configs")
    op.drop_index(
        "ix_whatsapp_account_configs_org_id",
        table_name="whatsapp_account_configs",
    )
    op.drop_index(
        "uq_whatsapp_account_configs_integration_id",
        table_name="whatsapp_account_configs",
    )
    op.drop_table("whatsapp_account_configs")
    # NOTE: We deliberately do NOT drop the 'whatsapp' enum value.
    # Postgres can't drop a single enum member without recreating the
    # type; leaving it in place is safe (no rows reference it once the
    # sidecar is gone) and avoids a destructive downgrade path.
