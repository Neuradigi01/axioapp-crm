"""WhatsApp quick-contact links + click log
(whatsapp-platform-upgrade Step 26).

Two new tables for offline-to-online QR / wa.me tracking:

  1. ``tbl_whatsapp_quick_links`` — operator-defined links carrying
     a base62 slug, the destination phone, the prefilled message,
     and denormalised counters for the stats card.
  2. ``tbl_whatsapp_quick_link_clicks`` — append-only click /
     scan log. Tracks the anonymised UA family, optional referrer,
     and the body-hash used to fingerprint attribution.

RLS-isolated via the standard ``app.org_id`` policy on both
tables. The public ``/wa/{code}`` redirect bypasses RLS via
explicit ``org_id=`` filters in the service layer (the public
endpoint never sets ``app.org_id``).

Chains after ``0113_wa_flows``.

Revision ID: 0114_quick_links
Revises: 0113_wa_flows
Create Date: 2026-06-24 07:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0114_quick_links"
down_revision: Union[str, None] = "0113_wa_flows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tbl_whatsapp_quick_links",
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
        # 8-char base62 slug — global-unique. We collision-retry on
        # insert, but the index makes the check cheap.
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        # Destination phone (E.164 digits-only, matches contact-phone
        # convention). Operators can target different numbers when
        # Step 27 ships multi-number support.
        sa.Column("phone_number", sa.String(32), nullable=False),
        sa.Column("prefilled_message", sa.Text(), nullable=True),
        # SHA-256 of the prefilled message — used by the inbound
        # webhook to fingerprint attribution within the 10-minute
        # window without scanning the raw text repeatedly.
        sa.Column("prefilled_hash", sa.String(64), nullable=True),
        sa.Column(
            "click_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "scan_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "attributed_conversation_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
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
        sa.UniqueConstraint("code", name="uq_wa_quick_links_code"),
    )
    op.create_index(
        "ix_wa_quick_links_org_created",
        "tbl_whatsapp_quick_links",
        ["org_id", "created_at"],
    )
    op.create_index(
        "ix_wa_quick_links_hash",
        "tbl_whatsapp_quick_links",
        ["prefilled_hash"],
        postgresql_where=sa.text("prefilled_hash IS NOT NULL"),
    )

    op.create_table(
        "tbl_whatsapp_quick_link_clicks",
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
        sa.Column(
            "link_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "tbl_whatsapp_quick_links.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        # Source = 'link' (human clicked the short URL) or 'qr'
        # (camera scanned the QR — Meta-side wa.me deeplink uses
        # the same redirect, but the public endpoint stamps `qr`
        # when the `?src=qr` querystring is present).
        sa.Column(
            "source", sa.String(8), nullable=False,
            server_default=sa.text("'link'"),
        ),
        sa.Column("ua_family", sa.String(64), nullable=True),
        sa.Column("region", sa.String(64), nullable=True),
        sa.Column("referrer", sa.String(2048), nullable=True),
        sa.Column("ip_hash", sa.String(64), nullable=True),
        sa.Column(
            "matched_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "Filled when the inbound-attribution match fires "
                "within the 10-minute window."
            ),
        ),
        sa.Column(
            "matched_conversation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_wa_quick_link_clicks_link_recorded",
        "tbl_whatsapp_quick_link_clicks",
        ["link_id", "recorded_at"],
    )
    # Attribution lookup path — recent rows whose match is still
    # unresolved. Partial index keeps it small.
    op.create_index(
        "ix_wa_quick_link_clicks_unmatched",
        "tbl_whatsapp_quick_link_clicks",
        ["org_id", "recorded_at"],
        postgresql_where=sa.text("matched_at IS NULL"),
    )

    # RLS — tenant isolation. The public redirect bypasses RLS via
    # explicit org_id= filters (it has no JWT to set `app.org_id`).
    for table in (
        "tbl_whatsapp_quick_links",
        "tbl_whatsapp_quick_link_clicks",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        # Two policies: an authenticated `app.org_id` match (the
        # default tenant gate) OR a service marker that the public
        # redirect path sets via `app.public_quick_link='1'` in the
        # same transaction. Mirrors the pattern used by Step 4's
        # data-deletion endpoint.
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table.replace('tbl_', '')}
                ON {table}
                USING (
                    org_id = current_setting('app.org_id', true)::uuid
                    OR current_setting('app.public_quick_link', true) = '1'
                )
                WITH CHECK (
                    org_id = current_setting('app.org_id', true)::uuid
                    OR current_setting('app.public_quick_link', true) = '1'
                )
            """
        )


def downgrade() -> None:
    for table in (
        "tbl_whatsapp_quick_link_clicks",
        "tbl_whatsapp_quick_links",
    ):
        op.execute(
            f"DROP POLICY IF EXISTS tenant_isolation_{table.replace('tbl_', '')} ON {table}"
        )
    op.drop_index(
        "ix_wa_quick_link_clicks_unmatched",
        table_name="tbl_whatsapp_quick_link_clicks",
    )
    op.drop_index(
        "ix_wa_quick_link_clicks_link_recorded",
        table_name="tbl_whatsapp_quick_link_clicks",
    )
    op.drop_table("tbl_whatsapp_quick_link_clicks")
    op.drop_index(
        "ix_wa_quick_links_hash", table_name="tbl_whatsapp_quick_links"
    )
    op.drop_index(
        "ix_wa_quick_links_org_created",
        table_name="tbl_whatsapp_quick_links",
    )
    op.drop_table("tbl_whatsapp_quick_links")
