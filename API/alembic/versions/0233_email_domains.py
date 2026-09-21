"""Sending-domains foundation — ``tbl_organization_email_domains``.

Step 1 of ``tasks/email-sending-domains/``.

Backs the per-org "claim your own sending domain" flow. Every domain
is verified via Mailgun's ``/v4/domains/{name}`` endpoint; the full
Mailgun response body's DNS-record arrays are stored **verbatim** in
the ``dns_records`` JSONB column so our UI is a dumb renderer and
schema drift at Mailgun's side never breaks a customer's setup page.

Discovery notes (URLs + fetched shapes): see
``tasks/email-sending-domains/DISCOVERY-NOTES.md``.

Not wired to any code path yet — this migration is purely additive.
Steps 2–7 build the API client, service, router, cascade, cron, and
frontend on top.

Revision ID: 0233_email_domains
Revises:     0232_channel_endpoints
Create Date: 2026-09-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0233_email_domains"
down_revision: str | None = "0232_channel_endpoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_organization_email_domains",
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
        # The domain the org is claiming (RFC 1035 max label chain: 253 chars).
        # UNIQUE globally — a given domain can only be claimed by one tenant
        # at a time (Mailgun-side enforcement mirrored: they'd reject a
        # POST for a name already claimed under our account).
        sa.Column("domain", sa.String(253), nullable=False),
        # Mailgun's internal id for this domain — used in follow-up
        # API calls that need the domain reference by opaque id
        # rather than name (e.g. account-scoped listings).
        sa.Column("mailgun_domain_id", sa.String(64), nullable=False),
        # Our own state machine (distinct from Mailgun's `state` field
        # which is stored inside dns_records for audit). Values:
        #   pending    — freshly claimed; DNS records shown to customer
        #                but no positive verify yet.
        #   verified   — Mailgun's /verify returned all records valid.
        #   demoted    — verified once, then drifted; consecutive
        #                failed checks >= EMAIL_DOMAIN_DEMOTE_AFTER_FAILED_CHECKS.
        #   released   — either operator-released or auto-released
        #                after EMAIL_DOMAIN_RELEASE_AFTER_FAILED_DAYS
        #                stuck in `demoted`. Mailgun-side DELETE fires
        #                on release.
        sa.Column(
            "verification_status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        # Mailgun's response body, stored verbatim. Shape:
        #   {"sending": [{record_type, name, value, priority, valid,
        #                 cached, is_active}, ...],
        #    "receiving": [same shape]}
        # See DISCOVERY-NOTES.md for source. UI renders this without
        # any transformation.
        sa.Column(
            "dns_records",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Per-record verdict cache — populated by the Step 6 nightly
        # re-verify cron. Redundant with `dns_records[*].valid` but
        # gives us fast SQL filtering without a JSONB path predicate.
        sa.Column(
            "mx_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
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
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        # Drift counter — resets to 0 on any successful verify.
        sa.Column(
            "consecutive_failed_checks",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("demoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        # us | eu — drives the Mailgun API client's base URL selection.
        # A domain claimed under one region can't be moved to the other;
        # release-and-reclaim is the path (Mailgun-side constraint).
        # EU base URL flagged UNVERIFIED in DISCOVERY-NOTES.md — the US
        # path is production-ready; EU wiring stays behind operator
        # confirmation.
        sa.Column(
            "region",
            sa.String(4),
            nullable=False,
            server_default=sa.text("'us'"),
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
        # Global uniqueness — a domain string belongs to at most one org.
        sa.UniqueConstraint(
            "domain",
            name="uq_organization_email_domains_domain",
        ),
        sa.CheckConstraint(
            "verification_status IN ('pending', 'verified', 'demoted', 'released')",
            name="ck_organization_email_domains_status_enum",
        ),
        sa.CheckConstraint(
            "region IN ('us', 'eu')",
            name="ck_organization_email_domains_region_enum",
        ),
        sa.CheckConstraint(
            "consecutive_failed_checks >= 0",
            name="ck_organization_email_domains_failed_checks_nonneg",
        ),
    )
    # (org_id, verification_status) — the dashboard's per-org list query.
    op.create_index(
        "ix_organization_email_domains_org_status",
        "tbl_organization_email_domains",
        ["org_id", "verification_status"],
    )
    # (verification_status, demoted_at) — the hourly demoted-only sweep.
    op.create_index(
        "ix_organization_email_domains_demoted_since",
        "tbl_organization_email_domains",
        ["verification_status", "demoted_at"],
        postgresql_where=sa.text("verification_status = 'demoted'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_organization_email_domains_demoted_since",
        table_name="tbl_organization_email_domains",
    )
    op.drop_index(
        "ix_organization_email_domains_org_status",
        table_name="tbl_organization_email_domains",
    )
    op.drop_table("tbl_organization_email_domains")
