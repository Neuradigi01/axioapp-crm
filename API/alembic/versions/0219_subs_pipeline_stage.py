"""subs_pipeline_stage — per-form pipeline_stage override on subscriptions.

Adds a nullable ``pipeline_stage`` text column to
``tbl_integration_subscriptions``. When set, the ad-webhook worker
uses it as the initial stage for leads ingested through that Meta /
Google form; when NULL, the shared ``ingest_lead`` service falls back
to the org's default first stage — which is the pre-Step-10 behaviour.

Every existing subscription row is left with ``pipeline_stage=NULL``,
so worker behaviour is unchanged until an Owner deliberately sets a
stage for a specific form.

Column is plain TEXT (not an FK) because ``tbl_leads.pipeline_stage``
is also plain TEXT — the domain model identifies stages by string
``key`` (e.g. ``"qualified"``, ``"demo_scheduled"``), not by row id.
Cross-table FK enforcement lives at the service layer's write-time
validation (same pattern the leads service already uses).

Downgrade drops the column outright — nulls-only rows carry no
information that would be lost.

Revision ID: 0219_subs_pipeline_stage
Revises: 0218_lead_form_attribution
Create Date: 2026-09-07 03:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0219_subs_pipeline_stage"
down_revision: Union[str, None] = "0218_lead_form_attribution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_integration_subscriptions",
        sa.Column("pipeline_stage", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tbl_integration_subscriptions", "pipeline_stage")
