"""Campaign A/B testing
(whatsapp-platform-upgrade Step 29).

Six new columns on ``tbl_campaigns`` capturing the A/B-test
configuration + decision state, plus a single ``variant`` column
on ``tbl_campaign_messages`` so per-recipient analytics can split
by variant.

Backwards-compatible: every existing campaign keeps
``is_ab_test=false`` and the variant columns null, so the
dispatcher and analytics queries built for single-variant
campaigns continue to work unchanged. The variant column on
campaign_messages stays NULL for legacy rows; the per-variant
funnel aggregation falls back to "all" semantics when it's
absent.

Chains after ``0115_multi_number``.

Revision ID: 0116_campaign_ab
Revises: 0115_multi_number
Create Date: 2026-06-24 09:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0116_campaign_ab"
down_revision: Union[str, None] = "0115_multi_number"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_WINNER_METRIC_VALUES = ("reply_rate", "read_rate", "click_rate")


def upgrade() -> None:
    winner_metric_enum = postgresql.ENUM(
        *_WINNER_METRIC_VALUES, name="campaign_winner_metric"
    )
    winner_metric_enum.create(op.get_bind(), checkfirst=True)

    # --- tbl_campaigns: 6 A/B columns -----------------------------------
    op.add_column(
        "tbl_campaigns",
        sa.Column(
            "is_ab_test",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tbl_campaigns",
        sa.Column(
            "variant_a_template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "tbl_whatsapp_templates.id", ondelete="SET NULL"
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_campaigns",
        sa.Column(
            "variant_b_template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "tbl_whatsapp_templates.id", ondelete="SET NULL"
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_campaigns",
        sa.Column(
            "split_ratio",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("50"),
            comment=(
                "Percent of A/B recipients assigned to variant A. "
                "0–100. Default 50/50. Ignored when is_ab_test=false."
            ),
        ),
    )
    op.add_column(
        "tbl_campaigns",
        sa.Column(
            "winner_metric",
            postgresql.ENUM(
                *_WINNER_METRIC_VALUES,
                name="campaign_winner_metric",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_campaigns",
        sa.Column(
            "winner_holdback_hours",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("24"),
            comment=(
                "Hours to wait after the A/B holdout sends before "
                "the winner decider runs. Default 24 hours."
            ),
        ),
    )
    op.add_column(
        "tbl_campaigns",
        sa.Column(
            "winner_decided_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "tbl_campaigns",
        sa.Column(
            "winning_variant",
            sa.CHAR(length=1),
            nullable=True,
            comment="'A', 'B', or NULL until the decider runs.",
        ),
    )
    op.create_check_constraint(
        "ck_campaigns_split_ratio_range",
        "tbl_campaigns",
        "split_ratio >= 0 AND split_ratio <= 100",
    )
    op.create_check_constraint(
        "ck_campaigns_winning_variant",
        "tbl_campaigns",
        "winning_variant IS NULL OR winning_variant IN ('A', 'B')",
    )

    # --- tbl_campaign_messages: variant marker --------------------------
    op.add_column(
        "tbl_campaign_messages",
        sa.Column(
            "variant",
            sa.CHAR(length=1),
            nullable=True,
            comment=(
                "'A' or 'B' for A/B-test recipients; NULL for "
                "non-A/B campaigns + for recipients sent after a "
                "winner is decided (they get the winning template, "
                "tagged with the winning letter on the row)."
            ),
        ),
    )
    op.create_index(
        "ix_campaign_messages_variant",
        "tbl_campaign_messages",
        ["campaign_id", "variant"],
        postgresql_where=sa.text("variant IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_campaign_messages_variant", table_name="tbl_campaign_messages"
    )
    op.drop_column("tbl_campaign_messages", "variant")
    op.drop_constraint(
        "ck_campaigns_winning_variant", "tbl_campaigns", type_="check"
    )
    op.drop_constraint(
        "ck_campaigns_split_ratio_range", "tbl_campaigns", type_="check"
    )
    op.drop_column("tbl_campaigns", "winning_variant")
    op.drop_column("tbl_campaigns", "winner_decided_at")
    op.drop_column("tbl_campaigns", "winner_holdback_hours")
    op.drop_column("tbl_campaigns", "winner_metric")
    op.drop_column("tbl_campaigns", "split_ratio")
    op.drop_column("tbl_campaigns", "variant_b_template_id")
    op.drop_column("tbl_campaigns", "variant_a_template_id")
    op.drop_column("tbl_campaigns", "is_ab_test")
    sa.Enum(name="campaign_winner_metric").drop(
        op.get_bind(), checkfirst=True
    )
