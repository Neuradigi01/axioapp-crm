"""tbl_calls.recording_file_path — uploaded recording file storage path

One additive change on ``tbl_calls``:

  * ``recording_file_path`` VARCHAR(512) NULLABLE — filesystem path
    (relative to the storage root) of an uploaded call recording
    audio file. Kept alongside the existing ``recording_url`` column
    so operators can either upload a file directly or paste a link to
    an external host.

The UI plays back whichever is populated (path takes priority — it's
served inline via the streaming endpoint; url is an external anchor).

Non-destructive. Downgrade drops the column cleanly.

Revision ID: 0149_call_recording_file
Revises: 0148_task_type_and_missed
Create Date: 2026-07-02 09:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0149_call_recording_file"
down_revision: Union[str, None] = "0148_task_type_and_missed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_calls",
        sa.Column("recording_file_path", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tbl_calls", "recording_file_path")
