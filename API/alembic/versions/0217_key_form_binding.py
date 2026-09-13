"""key_form_binding — backfill legacy lead_form embed keys to their org's default form.

Migration 0201 added ``resource_type`` and ``resource_id`` to
``tbl_embed_keys`` so keys could point at either a lead form or an
AI assistant. Every ``lead_form``-typed key created BEFORE the
multi-form track (Step 1 / migration 0216) has ``resource_id=NULL``
because there was only one form per org — the association was implicit.

Post multi-form, every lead_form key must point at exactly one form
via ``resource_id`` so the public submission path can look up the
form's ``name`` (for the ``Forms · <name>`` source label) without
falling back to "the org's only form" — which no longer exists as a
concept. This migration is DATA-ONLY: for every unbound lead_form
key, set ``resource_id`` to the org's default form
(``tbl_widget_configs`` row with ``is_default=true`` AND
``deleted_at IS NULL``).

Orgs that never onboarded the widget have no ``tbl_widget_configs``
row and therefore no keys either — the UPDATE simply matches zero
rows for them. Safe on any deployment.

Downgrade: N/A for a data backfill. The columns already existed
before this migration; we don't clear ``resource_id`` back to NULL
because that would break the multi-form service layer that depends
on it being set. If someone truly needs to walk back past 0216, the
0216 downgrade handles the schema; this backfill is idempotent so
re-applying 0217 on the way back up is safe.

Revision ID: 0217_key_form_binding
Revises: 0216_widget_forms
Create Date: 2026-09-07 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0217_key_form_binding"
down_revision: Union[str, None] = "0216_widget_forms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE tbl_embed_keys AS k
        SET resource_id = f.id
        FROM tbl_widget_configs AS f
        WHERE k.resource_type = 'lead_form'
          AND k.resource_id IS NULL
          AND f.org_id = k.org_id
          AND f.is_default = true
          AND f.deleted_at IS NULL
        """
    )


def downgrade() -> None:
    # Data-only backfill — nothing to reverse. See module docstring.
    pass
