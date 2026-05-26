"""webhook_secret + integration_subscriptions + integration_dlq.

Three additions for the Step-3 webhook receiver:

  1. `integrations.webhook_secret` (UNIQUE) — random per-row secret
     generated on connect. The Google Ads / Meta Ads platforms use it
     as the per-tenant URL discriminator (full URL becomes
     `/api/v1/integrations/google/webhook/v1/<webhook_secret>`).
     UNIQUE so an inbound URL hits at most one integration row.

  2. `integration_subscriptions` — one row per (integration, external
     form id). Maps Google Lead Form ids to the field-mapping the
     Step-3 task uses when translating the ad payload into the
     CRM's `ContactCreate` + `LeadCreate` shapes.

  3. `integration_dlq` — payloads that exhausted the Celery retry
     policy land here. The Settings page (Step 7/8) lists them and
     lets the Owner replay individual entries.

Plus a partial UNIQUE index on `leads (org_id, attribution->>
'external_lead_id')` so a replayed ad-payload can't create a
duplicate lead (idempotency key per Step-3's "Replay duplicates"
risk).

Revision ID: 0049_webhook_dlq
Revises: 0048_integrations
Create Date: 2026-05-26 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, JSONB, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0049_webhook_dlq"
down_revision: Union[str, None] = "0048_integrations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Re-use the enum declared in 0048 — never recreate.
_PROVIDER_ENUM = PgEnum(
    "google_ads",
    "meta_ads",
    name="integration_provider",
    create_type=False,
)


def upgrade() -> None:
    # --- 1. integrations.webhook_secret ---------------------------------
    op.add_column(
        "integrations",
        sa.Column("webhook_secret", sa.Text(), nullable=True),
    )
    # UNIQUE so a `WHERE webhook_secret = $1` lookup hits one row at
    # most. Partial: NULL allowed (disconnected rows clear the secret).
    op.create_index(
        "uq_integrations_webhook_secret",
        "integrations",
        ["webhook_secret"],
        unique=True,
        postgresql_where=sa.text("webhook_secret IS NOT NULL"),
    )

    # --- 2. integration_subscriptions -----------------------------------
    op.create_table(
        "integration_subscriptions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("integration_id", UUID(as_uuid=True), nullable=False),
        sa.Column("external_form_id", sa.Text(), nullable=False),
        sa.Column("external_form_label", sa.Text(), nullable=True),
        sa.Column(
            "field_mapping",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        # CASCADE so deleting the integration cleans up its subscriptions
        # — keeps an Owner from getting orphaned form-rows after
        # disconnect + future hard-delete of the integration row.
        sa.ForeignKeyConstraint(
            ["integration_id"], ["integrations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        # One subscription per (integration, form) — re-subscribing the
        # same form replaces the mapping rather than creating duplicates.
        sa.UniqueConstraint(
            "integration_id",
            "external_form_id",
            name="uq_integration_subscriptions_form",
        ),
    )
    op.create_index(
        "ix_integration_subscriptions_org",
        "integration_subscriptions",
        ["org_id"],
    )
    apply_rls("integration_subscriptions")

    # --- 3. integration_dlq --------------------------------------------
    op.create_table(
        "integration_dlq",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        # NULL when the integration row was deleted out from under a
        # DLQ entry — payload + provider survive for forensic replay.
        sa.Column("integration_id", UUID(as_uuid=True), nullable=True),
        sa.Column("provider", _PROVIDER_ENUM, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column(
            "retries_attempted",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "replayed_at", sa.DateTime(timezone=True), nullable=True
        ),
        # No FK on replayed_by — post-0037 convention (legacy `users`
        # table is on soak; new FKs to it are forbidden).
        sa.Column("replayed_by", UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["integrations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_integration_dlq_org_created",
        "integration_dlq",
        ["org_id", sa.text("created_at DESC")],
    )
    apply_rls("integration_dlq")

    # --- 4. Lead idempotency index --------------------------------------
    # Prevents a replayed Google/Meta payload from creating a second
    # lead for the same `(org_id, external_lead_id)` pair. Partial so
    # leads from manual/bulk-import/widget paths (no external_lead_id)
    # are unaffected.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
            uq_leads_org_external_lead_id
        ON leads (org_id, (attribution->>'external_lead_id'))
        WHERE attribution ? 'external_lead_id'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_leads_org_external_lead_id")

    drop_rls("integration_dlq")
    op.drop_index(
        "ix_integration_dlq_org_created", table_name="integration_dlq"
    )
    op.drop_table("integration_dlq")

    drop_rls("integration_subscriptions")
    op.drop_index(
        "ix_integration_subscriptions_org",
        table_name="integration_subscriptions",
    )
    op.drop_table("integration_subscriptions")

    op.drop_index(
        "uq_integrations_webhook_secret", table_name="integrations"
    )
    op.drop_column("integrations", "webhook_secret")
