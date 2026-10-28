"""Opt-in capture: contact columns + immutable consent_events
(whatsapp-platform-upgrade Step 22).

DPDP/GDPR-ready opt-in surface. Two parts:

  1. ``tbl_contacts`` grows 6 columns capturing the WhatsApp opt-in
     state machine (status / source / who-and-when / opt-out reason).
     Backfills every existing row to ``implicit`` so the campaign
     send-guard treats legacy contacts the same way most CRMs treat
     pre-DPDP data — "warn on send", never "block on send".

  2. New ``tbl_consent_events`` table is an immutable append-only
     log of every status transition. A PG trigger BEFORE UPDATE OR
     DELETE raises an exception so neither ORM bugs nor stray DB
     scripts can rewrite history. RLS is applied via
     ``shared.rls.apply_rls`` so cross-tenant reads are blocked.

This migration intentionally violates Rule 3 (custom-field uniform
storage) on the opt-in cols — they're first-class business state
the campaign guard needs to query without unpacking ``custom_data``
JSON. The override is documented in the step spec.

Chains after ``0108_bf_wa_analytics``.

Revision ID: 0109_opt_in_consent
Revises: 0108_bf_wa_analytics
Create Date: 2026-06-24 02:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0109_opt_in_consent"
down_revision: Union[str, None] = "0108_bf_wa_analytics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OPT_IN_STATUS_VALUES = (
    "never_contacted",
    "implicit",
    "opted_in",
    "opted_out",
)
_OPT_IN_SOURCE_VALUES = (
    "form_widget",
    "bulk_import",
    "manual_entry",
    "inbound_first_message",
    "explicit_opt_in_link",
    "stop_keyword",
)


def upgrade() -> None:
    # --- ENUMs -------------------------------------------------------
    opt_in_status = postgresql.ENUM(
        *_OPT_IN_STATUS_VALUES, name="whatsapp_opt_in_status"
    )
    opt_in_source = postgresql.ENUM(
        *_OPT_IN_SOURCE_VALUES, name="whatsapp_opt_in_source"
    )
    opt_in_status.create(op.get_bind(), checkfirst=True)
    opt_in_source.create(op.get_bind(), checkfirst=True)

    # --- tbl_contacts columns ---------------------------------------
    op.add_column(
        "tbl_contacts",
        sa.Column(
            "whatsapp_opt_in_status",
            postgresql.ENUM(
                *_OPT_IN_STATUS_VALUES,
                name="whatsapp_opt_in_status",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'never_contacted'"),
        ),
    )
    op.add_column(
        "tbl_contacts",
        sa.Column(
            "whatsapp_opt_in_source",
            postgresql.ENUM(
                *_OPT_IN_SOURCE_VALUES,
                name="whatsapp_opt_in_source",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_contacts",
        sa.Column(
            "whatsapp_opt_in_recorded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_contacts",
        sa.Column(
            "whatsapp_opt_in_recorded_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_contacts",
        sa.Column(
            "whatsapp_opt_out_recorded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_contacts",
        sa.Column(
            "whatsapp_opt_out_reason",
            sa.Text(),
            nullable=True,
        ),
    )

    # Backfill: every pre-existing contact is treated as "implicit"
    # consent. This matches CRM convention — the operator already had
    # the contact's permission to store/manage them, but never
    # captured an explicit WhatsApp opt-in. Campaign guard warns on
    # implicit; it doesn't block. The Risks section of the step spec
    # documents the one-time banner that Owners should see.
    op.execute(
        """
        UPDATE tbl_contacts
        SET whatsapp_opt_in_status = 'implicit',
            whatsapp_opt_in_source = 'bulk_import',
            whatsapp_opt_in_recorded_at = COALESCE(created_at, now())
        WHERE whatsapp_opt_in_status = 'never_contacted'
        """
    )

    # Partial index — the campaign send guard filters by opt-out
    # status; a partial index on the rare-but-targeted rows keeps
    # the guard quick on large contact lists.
    op.create_index(
        "ix_contacts_opt_out",
        "tbl_contacts",
        ["org_id"],
        unique=False,
        postgresql_where=sa.text(
            "whatsapp_opt_in_status = 'opted_out'"
        ),
    )

    # --- tbl_consent_events -----------------------------------------
    op.create_table(
        "tbl_consent_events",
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
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_contacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'whatsapp'"),
        ),
        sa.Column(
            "old_status",
            postgresql.ENUM(
                *_OPT_IN_STATUS_VALUES,
                name="whatsapp_opt_in_status",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "new_status",
            postgresql.ENUM(
                *_OPT_IN_STATUS_VALUES,
                name="whatsapp_opt_in_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "source",
            postgresql.ENUM(
                *_OPT_IN_SOURCE_VALUES,
                name="whatsapp_opt_in_source",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "ip_address",
            sa.String(64),
            nullable=True,
        ),
        sa.Column(
            "reason",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "request_evidence",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_consent_events_contact",
        "tbl_consent_events",
        ["contact_id", "recorded_at"],
    )
    op.create_index(
        "ix_consent_events_org_recorded",
        "tbl_consent_events",
        ["org_id", "recorded_at"],
    )

    # --- Immutability trigger ----------------------------------------
    # Append-only: trigger BEFORE UPDATE OR DELETE always raises.
    # GRANT-based approach won't work because the API uses one DB
    # role for everything; a trigger refuses the action regardless
    # of role.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION tbl_consent_events_immutable()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION
                'tbl_consent_events is append-only — % rejected',
                TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_consent_events_immutable
        BEFORE UPDATE OR DELETE ON tbl_consent_events
        FOR EACH ROW EXECUTE FUNCTION tbl_consent_events_immutable();
        """
    )

    # --- RLS on consent events --------------------------------------
    op.execute("ALTER TABLE tbl_consent_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tbl_consent_events FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation_consent_events
            ON tbl_consent_events
            USING (org_id = current_setting('app.org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.org_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_consent_events ON tbl_consent_events")
    op.execute("DROP TRIGGER IF EXISTS trg_consent_events_immutable ON tbl_consent_events")
    op.execute("DROP FUNCTION IF EXISTS tbl_consent_events_immutable()")
    op.drop_index("ix_consent_events_org_recorded", table_name="tbl_consent_events")
    op.drop_index("ix_consent_events_contact", table_name="tbl_consent_events")
    op.drop_table("tbl_consent_events")
    op.drop_index("ix_contacts_opt_out", table_name="tbl_contacts")
    op.drop_column("tbl_contacts", "whatsapp_opt_out_reason")
    op.drop_column("tbl_contacts", "whatsapp_opt_out_recorded_at")
    op.drop_column("tbl_contacts", "whatsapp_opt_in_recorded_by_user_id")
    op.drop_column("tbl_contacts", "whatsapp_opt_in_recorded_at")
    op.drop_column("tbl_contacts", "whatsapp_opt_in_source")
    op.drop_column("tbl_contacts", "whatsapp_opt_in_status")
    sa.Enum(name="whatsapp_opt_in_source").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="whatsapp_opt_in_status").drop(op.get_bind(), checkfirst=True)
