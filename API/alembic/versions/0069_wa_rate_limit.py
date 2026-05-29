"""whatsapp_account_configs.rate_limit_per_sec — per-org Meta rate cap
(Step 3.5.15).

Operator-configurable in the Settings → Integrations → WhatsApp card's
Advanced section. Default 50 msg/sec matches Meta's free-tier guidance;
business-verified accounts can bump to 1000.

The Celery dispatch path (`send_campaign_chunk_async`) acquires a
token from a per-org bucket before each per-contact send. The bucket
refills at `rate_limit_per_sec` tokens/sec and bursts up to 2× that.

Revision ID: 0069_wa_rate_limit
Revises: 0068_msg_delivery_ts
Create Date: 2026-05-29 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0069_wa_rate_limit"
down_revision: Union[str, None] = "0068_msg_delivery_ts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_account_configs",
        sa.Column(
            "rate_limit_per_sec",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("50"),
        ),
    )


def downgrade() -> None:
    op.drop_column("whatsapp_account_configs", "rate_limit_per_sec")
