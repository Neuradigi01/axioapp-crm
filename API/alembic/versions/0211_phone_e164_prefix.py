"""Prefix `+91` to bare 10-digit contact phones (E.164 storage flip).

`tbl_contacts.phone` used to persist as a bare 10-digit Indian mobile
(e.g. `9876543210`) because the old `validate_phone` returned only the
national number. The frontend now requires the customer to supply the
country code, and the backend validator persists the full E.164
(`+919876543210`). This migration back-fills existing rows so
lookups (WhatsApp inbound match, campaign send, dedup) stay coherent
after the switch.

Rule: rows whose current phone matches the old bare Indian mobile
shape (`^[6-9]\\d{9}$`) get `+91` prefixed. Rows that already look
E.164 (start with `+`) are left alone. Rows that match neither shape
(unusable legacy data) are left alone — the tightened form validator
will surface them next time an operator edits the contact.

Revision ID: 0211_phone_e164_prefix
Revises:     0210_convs_ai_paused
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0211_phone_e164_prefix"
down_revision: str | None = "0210_convs_ai_paused"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE tbl_contacts
               SET phone = '+91' || phone
             WHERE phone ~ '^[6-9][0-9]{9}$'
            """
        )
    )


def downgrade() -> None:
    # Reverse: strip the `+91` prefix from any 12-char `+91XXXXXXXXXX`
    # row. Rows that were already E.164 for other country codes are
    # left as-is (there is no way to tell them apart from ones we
    # prefixed on the way up).
    op.execute(
        sa.text(
            """
            UPDATE tbl_contacts
               SET phone = substring(phone from 4)
             WHERE phone ~ '^\\+91[6-9][0-9]{9}$'
            """
        )
    )
