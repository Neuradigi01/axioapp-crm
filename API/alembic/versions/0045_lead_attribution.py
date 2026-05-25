"""lead.attribution — JSONB column capturing where a lead came from.

Stamped on every lead at create time when the ingestion channel
supplies attribution data:

  - widget submissions: `{referrer, landing_url, utm_source, utm_medium,
    utm_campaign, utm_content, utm_term}` from the visitor's browser
  - Google Ads / Meta Ads (ad-integrations track, future): `{
    external_form_id, external_lead_id, campaign_id, gclid}`
  - bulk imports + manual entry: typically NULL — no attribution to
    capture since the rep types directly into the form

Nullable + no backfill — every pre-existing lead just has NULL
attribution, which the reporting surface treats as "no source data
available." The column is freeform JSONB so future channels can add
fields without a schema change.

Revision ID: 0045_lead_attribution
Revises: 0044_embed_keys
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0045_lead_attribution"
down_revision: Union[str, None] = "0044_embed_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("attribution", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("leads", "attribution")
