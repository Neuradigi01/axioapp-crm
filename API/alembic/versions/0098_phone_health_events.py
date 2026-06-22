"""tbl_whatsapp_phone_health_events + phone-health columns on configs
(whatsapp-platform-upgrade Step 12).

Two pieces:

  1. Three new columns on ``tbl_whatsapp_account_configs`` that
     mirror the per-call snapshot from
     ``GET /{phone_id}?fields=quality_rating,name_status,throughput,
     code_verification_status,is_official_business_account``:
       * ``quality_rating VARCHAR(16)`` — Meta's GREEN/YELLOW/RED
       * ``name_status VARCHAR(32)`` — APPROVED / AVAILABLE_WITHOUT_REVIEW / NONE
       * ``throughput INT`` — Meta-published msg/sec ceiling
       * ``restrictions JSONB`` — null or `[{restriction_type, expiration}]`
       * ``health_synced_at TIMESTAMPTZ`` — last hourly refresh
     ``messaging_limit_tier`` + ``tier_synced_at`` are already there
     (Step 3.5.16); we don't duplicate them.

  2. A new ``tbl_whatsapp_phone_health_events`` audit log so the UI
     timeline (and the Step 21 analytics surface) can show the
     trajectory of quality / tier changes. RLS-enforced via the
     existing ``TenantScoped`` policy (the table inherits the global
     `app.org_id` guard at `enable_rls_on_table` time).

Event types — keep tight + Postgres-enum'd so a typo in the service
layer doesn't write a junk event:
  * ``quality_change``      — quality_rating GREEN → YELLOW etc.
  * ``tier_change``         — messaging_limit_tier TIER_1K → TIER_10K
  * ``name_status_change``  — name_status NONE → APPROVED
  * ``restriction_added``   — Meta added a restriction
  * ``restriction_lifted``  — Meta removed all restrictions

Chains after ``0097_backfill_bp_perm``.

Revision ID: 0098_phone_health_events
Revises: 0097_backfill_bp_perm
Create Date: 2026-06-22 00:06:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0098_phone_health_events"
down_revision: Union[str, None] = "0097_backfill_bp_perm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_EVENT_TYPE_ENUM = "whatsapp_phone_health_event_type"


def upgrade() -> None:
    # 1. Per-snapshot columns on the existing config row.
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column("quality_rating", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column("name_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column("throughput", sa.Integer(), nullable=True),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column("restrictions", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "tbl_whatsapp_account_configs",
        sa.Column(
            "health_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # 2. Append-only event log for the timeline chart.
    op.execute(
        f"""
        CREATE TYPE {_EVENT_TYPE_ENUM} AS ENUM (
            'quality_change',
            'tier_change',
            'name_status_change',
            'restriction_added',
            'restriction_lifted'
        )
        """
    )
    op.create_table(
        "tbl_whatsapp_phone_health_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phone_id", sa.String(length=64), nullable=False),
        sa.Column(
            "event_type",
            postgresql.ENUM(
                "quality_change",
                "tier_change",
                "name_status_change",
                "restriction_added",
                "restriction_lifted",
                name=_EVENT_TYPE_ENUM,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("old_value", postgresql.JSONB(), nullable=True),
        sa.Column("new_value", postgresql.JSONB(), nullable=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_phone_health_events_org_phone_occurred",
        "tbl_whatsapp_phone_health_events",
        ["org_id", "phone_id", "occurred_at"],
        postgresql_using="btree",
    )
    # RLS — same pattern as every other tenant-scoped table.
    op.execute(
        "ALTER TABLE tbl_whatsapp_phone_health_events ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation_phone_health_events
        ON tbl_whatsapp_phone_health_events
        USING (org_id = current_setting('app.org_id')::uuid)
        WITH CHECK (org_id = current_setting('app.org_id')::uuid)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_phone_health_events "
        "ON tbl_whatsapp_phone_health_events"
    )
    op.drop_index(
        "ix_phone_health_events_org_phone_occurred",
        table_name="tbl_whatsapp_phone_health_events",
    )
    op.drop_table("tbl_whatsapp_phone_health_events")
    op.execute(f"DROP TYPE {_EVENT_TYPE_ENUM}")
    op.drop_column("tbl_whatsapp_account_configs", "health_synced_at")
    op.drop_column("tbl_whatsapp_account_configs", "restrictions")
    op.drop_column("tbl_whatsapp_account_configs", "throughput")
    op.drop_column("tbl_whatsapp_account_configs", "name_status")
    op.drop_column("tbl_whatsapp_account_configs", "quality_rating")
