"""Org-level review-workflow toggles for the template library
(``tasks/template-library`` Step 4).

Two new bool columns on ``tbl_org_settings``:

* ``template_review_mandatory`` (default ``false``) — when ``true``,
  the workflow refuses direct ``draft → published`` shortcuts.
* ``template_review_self_approve_allowed`` (default ``false``) — when
  ``true``, the author of a template may also approve it. By default
  the reviewer must be a different user.

Both default ``false`` so existing tenants keep the safe-by-default
behaviour: review is optional and authors can't self-approve. Owner
flips the toggles in Settings as the team grows.

Chains after ``0118_bf_templates_perm``.

Revision ID: 0119_template_review_toggles
Revises: 0118_bf_templates_perm
Create Date: 2026-06-25 15:30:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0119_template_review_toggles"
down_revision: Union[str, None] = "0118_bf_templates_perm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_org_settings",
        sa.Column(
            "template_review_mandatory",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tbl_org_settings",
        sa.Column(
            "template_review_self_approve_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "tbl_org_settings", "template_review_self_approve_allowed"
    )
    op.drop_column("tbl_org_settings", "template_review_mandatory")
