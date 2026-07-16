"""email_opt_in — GDPR-aligned Email opt-in tri-state on Contact

Adds an ``email_opt_in_status`` enum trio on ``tbl_contacts`` mirroring
the existing WhatsApp opt-in state machine (Step 22). Non-null with a
``never_contacted`` default so every existing row has a sensible
starting value; the legacy ``email_opt_out`` boolean stays as a
belt-and-suspenders shortcut for the send-guard hot path.

Backfill rule: any contact whose legacy ``email_opt_out=true`` boots
straight to ``opted_out`` with ``email_opt_in_source='email_unsubscribe_link'``
+ ``email_opt_in_recorded_at=email_opt_out_at`` so the send guard
respects prior unsubscribes on day one.

Columns added:

  * ``email_opt_in_status`` — ENUM(``never_contacted`` / ``implicit`` /
    ``opted_in`` / ``opted_out``). Not null. GDPR requires an explicit
    consent record; the enum makes the three-way distinction
    (silent-default vs implicit-consent vs explicit-consent) queryable.
  * ``email_opt_in_source`` — how the current state was captured (an
    ENUM mirroring the WA-side set + an ``email_unsubscribe_link``
    value for footer clicks).
  * ``email_opt_in_recorded_at`` — timestamp of the last transition.

Revision ID: 0154_email_opt_in
Revises: 0153_email_tracking
Create Date: 2026-07-16 00:15:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0154_email_opt_in"
down_revision: Union[str, None] = "0153_email_tracking"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


EMAIL_OPT_IN_STATUSES = (
    "never_contacted",
    "implicit",
    "opted_in",
    "opted_out",
)


EMAIL_OPT_IN_SOURCES = (
    "form_widget",
    "bulk_import",
    "manual_entry",
    "inbound_first_message",
    "explicit_opt_in_link",
    "email_unsubscribe_link",
    "bounce_hard",
    "manual_override",
)


def upgrade() -> None:
    # Create the two ENUM types. ``create_type=True`` (default via
    # sa.Enum) — Alembic emits the CREATE TYPE.
    status_enum = sa.Enum(*EMAIL_OPT_IN_STATUSES, name="email_opt_in_status")
    source_enum = sa.Enum(*EMAIL_OPT_IN_SOURCES, name="email_opt_in_source")
    status_enum.create(op.get_bind(), checkfirst=True)
    source_enum.create(op.get_bind(), checkfirst=True)

    # Add columns. status is NOT NULL with a server_default so no
    # backfill window is needed for the enum itself.
    op.add_column(
        "tbl_contacts",
        sa.Column(
            "email_opt_in_status",
            sa.Enum(*EMAIL_OPT_IN_STATUSES, name="email_opt_in_status", create_type=False),
            nullable=False,
            server_default=sa.text("'never_contacted'"),
        ),
    )
    op.add_column(
        "tbl_contacts",
        sa.Column(
            "email_opt_in_source",
            sa.Enum(*EMAIL_OPT_IN_SOURCES, name="email_opt_in_source", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_contacts",
        sa.Column(
            "email_opt_in_recorded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Backfill: honour every legacy opt_out so the send guard blocks
    # them from day one. The unsubscribe-link source is the correct
    # attribution for the vast majority of legacy opt-outs (they came
    # in via the tracking router's endpoint).
    op.execute(
        sa.text(
            """
            UPDATE tbl_contacts
            SET
                email_opt_in_status = 'opted_out',
                email_opt_in_source = 'email_unsubscribe_link',
                email_opt_in_recorded_at = COALESCE(email_opt_out_at, now())
            WHERE email_opt_out = true
            """
        )
    )


def downgrade() -> None:
    op.drop_column("tbl_contacts", "email_opt_in_recorded_at")
    op.drop_column("tbl_contacts", "email_opt_in_source")
    op.drop_column("tbl_contacts", "email_opt_in_status")

    source_enum = sa.Enum(*EMAIL_OPT_IN_SOURCES, name="email_opt_in_source")
    status_enum = sa.Enum(*EMAIL_OPT_IN_STATUSES, name="email_opt_in_status")
    source_enum.drop(op.get_bind(), checkfirst=True)
    status_enum.drop(op.get_bind(), checkfirst=True)
