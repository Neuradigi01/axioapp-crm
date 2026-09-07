"""lead_form_attribution — backfill widget leads with form_id + form_name.

Every ``source='widget'`` lead created BEFORE the multi-form track
carries no ``attribution.form_id`` — there was only one form per org
so the association was implicit. Multi-form flips that around: the
source column will render as ``Forms · <form_name>`` (see the
frontend track), which requires every historical widget lead to
resolve a specific form.

Strategy: point every unbound widget lead at its org's default form
(the row with ``is_default=true`` AND ``deleted_at IS NULL`` in
``tbl_widget_configs``). Same rule the Step 3 key backfill used, so
legacy keys AND legacy leads consistently attribute to "Default form".

Update semantics — merge ``form_id`` + ``form_name`` INTO the existing
``attribution`` JSONB via ``||``. Rows without an attribution column
value (``NULL``) get a fresh object with just the two keys, so both
callers (frontend renderer, reporting drill-down) find the fields at
the same path either way.

Orgs that have zero widget leads OR zero widget-config rows land on
the ``LEFT JOIN`` no-match branch and the WHERE clause skips them —
safe on any deployment.

Downgrade: N/A for a data backfill; the schema is unchanged.

Revision ID: 0218_lead_form_attribution
Revises: 0217_key_form_binding
Create Date: 2026-09-07 00:20:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0218_lead_form_attribution"
down_revision: Union[str, None] = "0217_key_form_binding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE tbl_leads AS l
        SET attribution = COALESCE(l.attribution, '{}'::jsonb)
            || jsonb_build_object(
                'form_id', f.id::text,
                'form_name', f.name
            )
        FROM tbl_widget_configs AS f
        WHERE l.source = 'widget'
          AND f.org_id = l.org_id
          AND f.is_default = true
          AND f.deleted_at IS NULL
          AND (
              l.attribution IS NULL
              OR NOT (l.attribution ? 'form_id')
          )
        """
    )


def downgrade() -> None:
    # Data-only backfill — nothing to reverse. See module docstring.
    pass
