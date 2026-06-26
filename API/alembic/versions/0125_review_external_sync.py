"""templates: add 'external_sync' to template_review_action ENUM

Step 14 of ``tasks/template-library`` wires the periodic + manual
Meta status sync. Every sync writes a review row to
``tbl_message_template_reviews`` with ``action='external_sync'`` so
the editor's review-trail surfaces "synced from Meta on YYYY-MM-DD"
events alongside the operator-driven submit / approve / reject
actions.

Adds a new enum value ``external_sync`` alongside the existing
``submit / approve / reject / request_changes / publish / archive``
on the ``template_review_action`` Postgres enum.

``ALTER TYPE ... ADD VALUE IF NOT EXISTS`` is idempotent in PG 9.6+,
so re-running is safe. Wrapped in an ``autocommit_block`` because
the statement cannot run inside a transaction.

Downgrade is a **no-op** — Postgres does not support
``ALTER TYPE ... DROP VALUE``. The Python
``TemplateReviewAction.external_sync`` member will simply not be
produced by app code post-downgrade; the enum value remains defined
but unreachable.

Revision ID: 0125_review_external_sync
Revises: 0124_add_push_channel_enum
Create Date: 2026-06-26 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0125_review_external_sync"
down_revision: Union[str, None] = "0124_add_push_channel_enum"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE template_review_action ADD VALUE IF NOT EXISTS 'external_sync'"
        )


def downgrade() -> None:
    # See module docstring — Postgres can't drop an enum value safely.
    pass
