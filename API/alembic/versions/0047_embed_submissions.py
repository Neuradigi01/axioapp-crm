"""embed_submissions — per-submission log for the embeddable widget.

One row per submission attempt (accepted OR rejected). Powers the
Step 9 "Submission log" sub-tab in Settings → Embed Integrations:
Owner/Admin can see "is anyone using my embed?" and "are bots
hitting me?" without combing through the audit log.

Schema choices:

- `outcome` is a Postgres enum: `accepted | rejected_spam |
  rate_limited | invalid_payload`. **`invalid_key` is deliberately
  NOT in this enum** — we have no org context for those rows, so
  they'd violate RLS. They stay in the audit log only.
- `key_id` is nullable but UNCONSTRAINED (no FK). Post-0037
  convention: avoid FKs on actor / lookup UUIDs so the table can
  survive an `embed_keys` purge / soft-delete cleanup.
- `lead_id` is nullable + UNCONSTRAINED for the same reason.
- `ip_hash` is the 16-char SHA-256 prefix of the caller IP — same
  shape Step 1 stored in `embed_keys.last_used_ip`.
- `reason` is free-text — for spam rows it's `"honeypot"`,
  `"min_time"`, `"recaptcha_invalid"`, `"recaptcha_low_score"`; for
  rate-limit rows it's `"per_key"` or `"per_ip"`; for payload-error
  rows it's the Pydantic error summary.
- Two composite indexes: `(org_id, created_at DESC)` for the list
  endpoint's default sort, and `(org_id, outcome, created_at DESC)`
  for the outcome-filtered list + per-outcome counts in the summary.

Tenant isolation: standard `apply_rls("embed_submissions")` on
`org_id`. The submission service writes within the tenant context
that's already set during the submission flow.

Revision ID: 0047_embed_submissions
Revises: 0046_widget_configs
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, UUID

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0047_embed_submissions"
down_revision: Union[str, None] = "0046_widget_configs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Postgres enum name + values. Adding a value later requires
# `ALTER TYPE ... ADD VALUE` — write a follow-up migration.
#
# Using the dialect-specific `PgEnum` with `create_type=False` so
# `op.create_table` reuses the type already created by the DO block
# below rather than re-emitting `CREATE TYPE` (which the dev DB had
# left over from an earlier partial migration attempt and would
# otherwise blow up the upgrade).
_OUTCOME_ENUM = PgEnum(
    "accepted",
    "rejected_spam",
    "rate_limited",
    "invalid_payload",
    name="embed_submission_outcome",
    create_type=False,
)


def upgrade() -> None:
    # Idempotent CREATE TYPE — Postgres has no `CREATE TYPE IF NOT
    # EXISTS`, so wrap in a DO block that swallows the duplicate-object
    # error. Lets the migration re-run cleanly if the type leaked in
    # from a prior aborted attempt (or from a manual psql session).
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE embed_submission_outcome AS ENUM (
                'accepted',
                'rejected_spam',
                'rate_limited',
                'invalid_payload'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.create_table(
        "embed_submissions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        # No FK on key_id / lead_id (post-0037 convention).
        sa.Column("key_id", UUID(as_uuid=True), nullable=True),
        sa.Column("lead_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "outcome",
            _OUTCOME_ENUM,
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("referrer", sa.Text(), nullable=True),
        sa.Column("landing_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # List-endpoint hot path: paginated by org, newest first.
    op.create_index(
        "ix_embed_submissions_org_created",
        "embed_submissions",
        ["org_id", sa.text("created_at DESC")],
    )
    # Outcome-filtered list + per-outcome counts in the summary
    # endpoint group by (outcome, day) over recent rows.
    op.create_index(
        "ix_embed_submissions_org_outcome_created",
        "embed_submissions",
        ["org_id", "outcome", sa.text("created_at DESC")],
    )

    apply_rls("embed_submissions")


def downgrade() -> None:
    drop_rls("embed_submissions")
    op.drop_index(
        "ix_embed_submissions_org_outcome_created",
        table_name="embed_submissions",
    )
    op.drop_index(
        "ix_embed_submissions_org_created",
        table_name="embed_submissions",
    )
    op.drop_table("embed_submissions")
    op.execute("DROP TYPE IF EXISTS embed_submission_outcome")
