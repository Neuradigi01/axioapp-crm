"""create device tokens table

Revision ID: a1b2c3d4e5f6
Revises: 6a309b450a56
Create Date: 2026-03-26 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '6a309b450a56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('tbl_device_tokens',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('member_id', sa.BigInteger(), nullable=False),
        sa.Column('user_type', sa.Text(), nullable=False),
        sa.Column('fcm_token', sa.Text(), nullable=False),
        sa.Column('device_info', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('fcm_token'),
    )
    op.create_index('ix_tbl_device_tokens_member_id', 'tbl_device_tokens', ['member_id'])


def downgrade() -> None:
    op.drop_index('ix_tbl_device_tokens_member_id', table_name='tbl_device_tokens')
    op.drop_table('tbl_device_tokens')
