"""Multi-number WhatsApp per org — schema relaxations
(whatsapp-platform-upgrade Step 27a).

Three coordinated changes lifting the "1 org = 1 WhatsApp phone"
constraint that's been baked into the schema since migration 0061:

  1. Drop ``uq_whatsapp_account_configs_integration_id`` (the
     UNIQUE index pinning each integration to a single config
     row) and replace it with ``uq_wa_config_integration_phone``
     enforcing one row per ``(integration_id, phone_id)``. The
     ``phone_id`` column was already free-form; we just teach the
     constraint to consider it part of identity.
  2. Add ``received_via_phone_id`` to ``tbl_conversations`` so
     inbound from a specific phone can be attributed back to it +
     the manual-reply composer can default the outbound back to
     the same number.
  3. Add ``send_from_phone_id`` to ``tbl_campaigns`` so a campaign
     can be pinned to a specific phone at create time. ``NULL``
     means "use the org default" — preserves backwards
     compatibility for every existing campaign row.

Safety net
----------

Pre-flight dedup check: we abort the migration if any existing
``(integration_id, phone_id)`` pair already has > 1 row. In
practice it can't (the dropped UNIQUE made duplicates impossible)
but the check protects against any migration ordering surprises.

Chains after ``0114_quick_links``.

Revision ID: 0115_multi_number
Revises: 0114_quick_links
Create Date: 2026-06-24 08:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0115_multi_number"
down_revision: Union[str, None] = "0114_quick_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Safety check ----------------------------------------------------
    # The old constraint allowed exactly one config per integration; if
    # the migration is replayed on a database where someone manually
    # inserted dupes, we refuse to proceed.
    bind = op.get_bind()
    dup = bind.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM (
                SELECT integration_id, phone_id
                FROM tbl_whatsapp_account_configs
                GROUP BY integration_id, phone_id
                HAVING COUNT(*) > 1
            ) d
            """
        )
    ).scalar() or 0
    if int(dup) > 0:
        raise RuntimeError(
            "tbl_whatsapp_account_configs has duplicate "
            "(integration_id, phone_id) pairs; resolve manually before "
            "running migration 0115_multi_number."
        )

    # --- Drop the legacy uniqueness + add the composite one --------------
    # The legacy index was created with `op.create_index(..., unique=True)`
    # so we drop it via `drop_index`, not `drop_constraint`. Add the new
    # composite as a proper UniqueConstraint so it shows up in metadata.
    op.drop_index(
        "uq_whatsapp_account_configs_integration_id",
        table_name="tbl_whatsapp_account_configs",
    )
    op.create_unique_constraint(
        "uq_wa_config_integration_phone",
        "tbl_whatsapp_account_configs",
        ["integration_id", "phone_id"],
    )

    # --- received_via_phone_id on conversations --------------------------
    op.add_column(
        "tbl_conversations",
        sa.Column(
            "received_via_phone_id",
            sa.String(64),
            nullable=True,
            comment=(
                "Meta phone_number_id the inbound message arrived on. "
                "Stamped on first inbound; NULL on conversations "
                "created before Step 27a or via the manual outbound "
                "path. Used by the composer to default Send-From "
                "back to the same number."
            ),
        ),
    )
    op.create_index(
        "ix_conversations_received_via",
        "tbl_conversations",
        ["org_id", "received_via_phone_id"],
        postgresql_where=sa.text("received_via_phone_id IS NOT NULL"),
    )

    # --- send_from_phone_id on campaigns ---------------------------------
    op.add_column(
        "tbl_campaigns",
        sa.Column(
            "send_from_phone_id",
            sa.String(64),
            nullable=True,
            comment=(
                "Meta phone_number_id the campaign dispatches from. "
                "NULL = use the org's default phone (the first "
                "connected one). Set when the operator picks a "
                "specific number on the campaign create modal."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("tbl_campaigns", "send_from_phone_id")
    op.drop_index(
        "ix_conversations_received_via", table_name="tbl_conversations"
    )
    op.drop_column("tbl_conversations", "received_via_phone_id")
    op.drop_constraint(
        "uq_wa_config_integration_phone",
        "tbl_whatsapp_account_configs",
        type_="unique",
    )
    op.create_index(
        "uq_whatsapp_account_configs_integration_id",
        "tbl_whatsapp_account_configs",
        ["integration_id"],
        unique=True,
    )
