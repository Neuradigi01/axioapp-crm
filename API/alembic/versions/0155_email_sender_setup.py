"""email_sender_setup — sender domain verification + bounce suppression

Ships the schema for Campaigns v1 Step 07a (backend):

  * ``tbl_email_sender_domains`` — one row per verified/pending SPF /
    DKIM / DMARC domain per org. The three verdict columns store
    the last verification result; ``*_last_checked_at`` timestamps
    let the frontend show freshness. ``dkim_selector`` and
    ``dkim_public_key`` land here so the DNS-records endpoint has a
    stable source of truth even before the operator adds records.
  * ``tbl_campaigns.excluded_bounced_count`` — populated at
    ``enqueue`` time when the audience is intersected with the
    hard-bounce list. The campaign detail page renders it as
    "N excluded (X hard-bounced, Y opted-out)".
  * ``tbl_org_settings.require_full_domain_verification`` — feature
    flag. Default ``false`` (dispatch warns but proceeds if a
    domain isn't fully verified); flipping to ``true`` turns the
    warning into a hard block at campaign start.

No new deps: the existing ``core/email/dkim_spf_check.py`` handles the
SPF/DKIM/DMARC DNS lookups (uses ``dnspython`` optionally + degrades
to ``unknown`` when it's absent). DKIM keypair generation is deferred
to the follow-up 07b — v1 stores a placeholder public key so the
DNS-records endpoint can render "public key TBD" copy until real key
generation ships.

Revision ID: 0155_sender_setup
Revises: 0154_email_opt_in
Create Date: 2026-07-16 00:20:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = "0155_sender_setup"
down_revision: Union[str, None] = "0154_email_opt_in"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tbl_email_sender_domains",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(length=253), nullable=False),
        sa.Column(
            "spf_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "dkim_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "dmarc_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "spf_last_checked_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "dkim_last_checked_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "dmarc_last_checked_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("dkim_selector", sa.String(length=64), nullable=False),
        sa.Column("dkim_public_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("org_id", "domain", name="uq_email_sender_domains_org_domain"),
    )
    op.create_index(
        "ix_email_sender_domains_org", "tbl_email_sender_domains", ["org_id"]
    )

    # Campaign excluded-count. Defaults to 0 so existing rows are
    # semantically "no exclusions computed" without a backfill window.
    op.add_column(
        "tbl_campaigns",
        sa.Column(
            "excluded_bounced_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # Feature flag on OrgSettings.
    op.add_column(
        "tbl_org_settings",
        sa.Column(
            "require_full_domain_verification",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_org_settings", "require_full_domain_verification")
    op.drop_column("tbl_campaigns", "excluded_bounced_count")
    op.drop_index("ix_email_sender_domains_org", table_name="tbl_email_sender_domains")
    op.drop_table("tbl_email_sender_domains")
