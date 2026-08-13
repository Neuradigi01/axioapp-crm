"""Per-org HMAC key for signed chatbot reply URLs
(``tasks/chatbot-builder`` Step 11).

Adds a 32-byte random column on ``tbl_organizations`` and populates
every existing row via ``pgcrypto.gen_random_bytes(32)``. The
``chatbots/signed_reply_urls.py`` module HMACs email-reply URL
signatures with this key so:

  * A key rotation flips a single row and instantly invalidates
    every previously-issued signature for that org.
  * Cross-org signature forgery is impossible without the org's
    specific key material.

pgcrypto ships enabled on every deployment (0006_pgcrypto_extension)
so ``gen_random_bytes`` is available.

Chains after ``0193_org_ai_provider``.

Revision ID: 0194_org_signed_url_key
Revises:     0193_org_ai_provider
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0194_org_signed_url_key"
down_revision: str | None = "0193_org_ai_provider"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add nullable column so existing rows don't blow up on the
    #    NOT NULL flip.
    op.add_column(
        "tbl_organizations",
        sa.Column(
            "chatbot_signed_url_key",
            sa.LargeBinary(),
            nullable=True,
        ),
    )
    # 2. Populate every existing row with fresh 32-byte key.
    op.execute(
        """
        UPDATE tbl_organizations
           SET chatbot_signed_url_key = gen_random_bytes(32)
         WHERE chatbot_signed_url_key IS NULL
        """
    )
    # 3. Flip to NOT NULL + server_default so new orgs auto-populate.
    op.alter_column(
        "tbl_organizations",
        "chatbot_signed_url_key",
        nullable=False,
        server_default=sa.text("gen_random_bytes(32)"),
    )


def downgrade() -> None:
    op.drop_column("tbl_organizations", "chatbot_signed_url_key")
