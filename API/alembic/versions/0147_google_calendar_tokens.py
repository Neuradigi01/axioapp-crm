"""google calendar per-user tokens + appointment sync columns

Step 1 of the ``tasks/google-calendar-sync/`` track. Two shape changes:

1. New table ``tbl_user_google_calendar_tokens`` — one row per
   ``(org_id, user_id)`` holding each employee's Google Calendar OAuth
   refresh token (Fernet-encrypted), the cached short-lived access
   token, the granted scope set, and the connection-status metadata
   the integrations card renders.

2. Two nullable columns on ``tbl_appointments``:
     * ``google_calendar_event_id`` TEXT — the Google-side event id
       returned on create; lets the sync task PATCH / DELETE the
       right event on subsequent CRM edits.
     * ``google_calendar_etag`` TEXT — Google's ETag; stored so we can
       send ``If-Match`` on PATCH + detect concurrent Google-side
       edits (v1 refuses to overwrite in that case).

RLS on the new table: the standard ``current_setting('app.current_org_id',
true)`` gate, matching every other tenant-scoped table (see
``0141_whatsapp_web`` for the canonical policy shape).

Reversible — downgrade drops the table + drops the two appointment
columns cleanly.

Revision ID: 0147_google_calendar_tokens
Revises: 0146_workflow_system_default
Create Date: 2026-07-01 08:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0147_google_calendar_tokens"
down_revision: Union[str, None] = "0146_workflow_system_default"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUS_VALUES = ("active", "revoked", "error", "expired")


def upgrade() -> None:
    # --- 1. tbl_user_google_calendar_tokens ---------------------------------
    status_check = (
        "status IN (" + ", ".join(f"'{v}'" for v in _STATUS_VALUES) + ")"
    )

    op.create_table(
        "tbl_user_google_calendar_tokens",
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
            index=True,
        ),
        # FK matches the codebase convention (see tbl_organization_members):
        # user PK on ``tbl_user_login.id`` is BIGINT, not UUID. The FurnitureCRM
        # ORM stub in ``core/users/models.py`` re-declares ``id`` as UUID via
        # SQLAlchemy metadata tricks but the on-disk column is BIGINT.
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_user_login.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("google_email", sa.Text(), nullable=False),
        sa.Column("google_user_id", sa.Text(), nullable=False),
        # Fernet ciphertexts. refresh_token is required — without it we
        # can't refresh the access token so the connection is dead.
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "access_token_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        # ARRAY(TEXT) — the scope strings Google returned on the token
        # response, so we can detect scope-downgrade if the user grants
        # less than requested (e.g. refuses calendar.events but grants
        # openid + email).
        sa.Column(
            "scopes_granted",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("primary_calendar_id", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "connected_at",
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
        sa.CheckConstraint(
            status_check,
            name="ck_user_google_calendar_tokens_status",
        ),
        sa.UniqueConstraint(
            "org_id",
            "user_id",
            name="uq_user_google_calendar_tokens_org_user",
        ),
    )

    # Hot-path lookup: "get the user's active token" — one query per
    # sync task. Partial on active rows so revoked / errored rows don't
    # bloat the index.
    op.create_index(
        "ix_user_google_calendar_tokens_active",
        "tbl_user_google_calendar_tokens",
        ["org_id", "user_id"],
        postgresql_where=sa.text("status = 'active'"),
    )

    # --- 2. RLS ------------------------------------------------------------
    op.execute(
        "ALTER TABLE tbl_user_google_calendar_tokens "
        "ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tbl_user_google_calendar_tokens_tenant_isolation
            ON tbl_user_google_calendar_tokens
            USING (
                org_id::text = current_setting('app.current_org_id', true)
            )
            WITH CHECK (
                org_id::text = current_setting('app.current_org_id', true)
            )
        """
    )

    # --- 3. tbl_appointments extension -------------------------------------
    op.add_column(
        "tbl_appointments",
        sa.Column(
            "google_calendar_event_id",
            sa.Text(),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_appointments",
        sa.Column(
            "google_calendar_etag",
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_appointments", "google_calendar_etag")
    op.drop_column("tbl_appointments", "google_calendar_event_id")

    op.execute(
        "DROP POLICY IF EXISTS "
        "tbl_user_google_calendar_tokens_tenant_isolation "
        "ON tbl_user_google_calendar_tokens"
    )
    op.drop_index(
        "ix_user_google_calendar_tokens_active",
        table_name="tbl_user_google_calendar_tokens",
    )
    op.drop_table("tbl_user_google_calendar_tokens")
