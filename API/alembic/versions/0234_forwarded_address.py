"""Forwarded-address endpoint fields on ``tbl_email_endpoint_details``.

Step 2 of ``tasks/email-inbound-forwarding/``.

Adds the two config columns the ``forwarded_address`` endpoint type
needs (``auto_create_contact`` for the unknown-sender branch,
``default_assignee_user_id`` for the inbox-triage owner). Purely
additive — no existing row is touched, no code path reads the new
columns yet. Track 3 Step 3 wires the ingest task on top of them.

``default_assignee_user_id`` is a plain UUID with no FK to ``users``
per the post-migration-0037 convention (the ``users`` table is a
shim; user-side cleanup on offboarding is the staff-offboarding
flow's job, mirroring ``tbl_contacts.assigned_to_id`` /
``tbl_leads.assigned_to_id`` / ``tbl_appointments.assigned_to_id``).
A partial index restricts to rows where the assignee is set so the
inbox-triage lookup doesn't scan every endpoint row.

Revision ID: 0234_forwarded_address
Revises:     0233_email_domains
Create Date: 2026-09-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0234_forwarded_address"
down_revision: str | None = "0233_email_domains"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_email_endpoint_details",
        sa.Column(
            "auto_create_contact",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "tbl_email_endpoint_details",
        sa.Column(
            "default_assignee_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_email_endpoint_details_default_assignee",
        "tbl_email_endpoint_details",
        ["default_assignee_user_id"],
        postgresql_where=sa.text("default_assignee_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_endpoint_details_default_assignee",
        table_name="tbl_email_endpoint_details",
    )
    op.drop_column("tbl_email_endpoint_details", "default_assignee_user_id")
    op.drop_column("tbl_email_endpoint_details", "auto_create_contact")
