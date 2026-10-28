"""tbl_whatsapp_templates — management columns
(whatsapp-platform-upgrade Step 8).

Promotes the read-only Meta-sync cache to an editable, submittable
source-of-truth surface. New columns:

* ``body_components JSONB NULL`` — structured Meta-spec component
  array. Each element is one of HEADER / BODY / FOOTER / BUTTONS
  payload. NULL for legacy rows synced before this migration; the
  next ``sync_templates`` run repopulates from Meta's
  ``components[]`` field. New (draft) rows write here directly.

* ``submission_status`` — operator-side lifecycle enum:
    - ``draft``         — created in CRM, not yet shipped to Meta
    - ``pending_review``— submitted, awaiting Meta approval
    - ``approved``      — Meta approved (sendable)
    - ``rejected``      — Meta rejected; ``rejection_reason`` carries
                          the operator-visible cause
    - ``paused``        — Meta paused over poor delivery quality
    - ``disabled``      — Meta disabled (rate-limited / abusive)

  Backfilled from the existing Meta status text:
    APPROVED → approved · PENDING → pending_review · REJECTED →
    rejected · DISABLED → disabled. Unknown / NULL falls back to
    ``draft`` (the safest default — operator must explicitly submit).

* ``rejection_reason TEXT NULL`` — verbatim Meta rejection message;
  surfaced in the UI on rejected rows.

* ``submitted_by_user_id UUID NULL`` — actor who hit Submit; matches
  the UUID shape we use elsewhere for ``assigned_to_id``-style FKs
  (no enforced DB-side FK so a deactivated user doesn't break the
  template row).

* ``submitted_at TIMESTAMPTZ NULL`` — when the operator submitted.
  ``NULL`` for drafts; populated on every submit. Re-submitting after
  a rejection updates the timestamp.

Plus an index on ``meta_template_id`` so the webhook can locate a
template row in O(log n) when Meta sends a status update.

Chains after ``0092_messages_reply_to_reactions``.

Revision ID: 0093_wa_templates_mgmt
Revises: 0092_messages_reply_to_reactions
Create Date: 2026-06-22 00:01:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0093_wa_templates_mgmt"
down_revision: Union[str, None] = "0092_messages_reply_to_reactions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SUBMISSION_STATUS_ENUM = "whatsapp_template_submission_status"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TYPE {_SUBMISSION_STATUS_ENUM} AS ENUM (
            'draft', 'pending_review', 'approved',
            'rejected', 'paused', 'disabled'
        )
        """
    )

    op.add_column(
        "tbl_whatsapp_templates",
        sa.Column("body_components", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "tbl_whatsapp_templates",
        sa.Column(
            "submission_status",
            postgresql.ENUM(
                "draft",
                "pending_review",
                "approved",
                "rejected",
                "paused",
                "disabled",
                name=_SUBMISSION_STATUS_ENUM,
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'draft'::"
                                   + _SUBMISSION_STATUS_ENUM),
        ),
    )
    op.add_column(
        "tbl_whatsapp_templates",
        sa.Column("rejection_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "tbl_whatsapp_templates",
        sa.Column(
            "submitted_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_whatsapp_templates",
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Backfill submission_status from Meta status text for any rows
    # already synced from Meta. Idempotent — re-running the migration
    # downgrade+upgrade leaves the same final state.
    op.execute(
        """
        UPDATE tbl_whatsapp_templates
        SET submission_status = CASE UPPER(status)
            WHEN 'APPROVED' THEN 'approved'::whatsapp_template_submission_status
            WHEN 'PENDING' THEN 'pending_review'::whatsapp_template_submission_status
            WHEN 'REJECTED' THEN 'rejected'::whatsapp_template_submission_status
            WHEN 'DISABLED' THEN 'disabled'::whatsapp_template_submission_status
            WHEN 'PAUSED' THEN 'paused'::whatsapp_template_submission_status
            ELSE 'draft'::whatsapp_template_submission_status
        END
        """
    )

    op.create_index(
        "ix_whatsapp_templates_meta_id",
        "tbl_whatsapp_templates",
        ["meta_template_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_whatsapp_templates_meta_id",
        table_name="tbl_whatsapp_templates",
    )
    op.drop_column("tbl_whatsapp_templates", "submitted_at")
    op.drop_column("tbl_whatsapp_templates", "submitted_by_user_id")
    op.drop_column("tbl_whatsapp_templates", "rejection_reason")
    op.drop_column("tbl_whatsapp_templates", "submission_status")
    op.drop_column("tbl_whatsapp_templates", "body_components")
    op.execute(f"DROP TYPE {_SUBMISSION_STATUS_ENUM}")
