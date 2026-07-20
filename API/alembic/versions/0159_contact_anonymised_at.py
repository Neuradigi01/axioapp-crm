"""add ``tbl_contacts.anonymised_at`` for the DPDP right-to-be-forgotten flow.

DPDP + GDPR both require an anonymise variant of delete. Hard-deleting
a contact would break every historical FK (appointments, leads,
invoices, workflow runs, ...) — legally we need the *personal data*
gone, not the *audit trail*. So the anonymise flow (Step U7):

  1. Wipes PII on the row (full_name → "Anonymised contact",
     phone/email → NULL, tags → [], custom_data → {}).
  2. Force-flips both opt-in channels to ``opted_out``.
  3. Stamps ``anonymised_at`` so the UI can render an "Anonymised"
     chip and the automations/campaigns send guards can early-exit.
  4. Leaves every FK (activities, tasks, leads, appointments, ...)
     pointing at the same row so history stays intact.

Non-destructive additive column. Downgrade drops it. Row-level data
wiped by upgrade is not restored on downgrade.

Revision ID: 0159_contact_anonymised_at
Revises:     0158_retire_contact_notes
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0159_contact_anonymised_at"
down_revision: Union[str, None] = "0158_retire_contact_notes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_contacts",
        sa.Column("anonymised_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial index on the "anonymised" subset — small (should be a
    # tiny minority of rows) so callers can cheaply exclude them from
    # list queries / campaign audiences with ``WHERE anonymised_at IS
    # NULL``.
    op.create_index(
        "ix_tbl_contacts_anonymised",
        "tbl_contacts",
        ["org_id", "anonymised_at"],
        postgresql_where=sa.text("anonymised_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_tbl_contacts_anonymised", table_name="tbl_contacts")
    op.drop_column("tbl_contacts", "anonymised_at")
