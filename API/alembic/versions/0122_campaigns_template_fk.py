"""Switch ``tbl_campaigns`` template FKs to the central library
(``tasks/template-library`` Step 11).

What this migration does in one transaction:

1. Remaps every non-null FK value on ``tbl_campaigns.template_id``,
   ``variant_a_template_id``, ``variant_b_template_id`` from the
   WA-template UUID to the matching central
   ``tbl_message_templates.id``. The mapping comes from Step 9's
   reciprocal link (``tbl_whatsapp_templates.message_template_id``).
   Rows whose WA template lacks a central link (shouldn't happen
   post-Step-9, but defensive) get NULL — the dispatcher fails fast
   with a clear "template no longer exists" message.
2. Drops the three FK constraints pointing at ``tbl_whatsapp_templates``
   (constraint names resolved dynamically via ``information_schema``).
3. Adds three new FK constraints pointing at
   ``tbl_message_templates(id) ON DELETE SET NULL`` — same on-delete
   semantics as before so an archived template doesn't cascade-delete
   the historical campaign row.

Reversibility: downgrade reverses the value remap (looks up the WA
extension row via ``message_template_id``) + restores the WA FKs.

Mid-flight Celery dispatcher safety: the FK swap is the only
schema change; existing in-memory campaign refs already hold a
``template_id`` UUID, and after this migration that UUID points at
the central row. The dispatcher (also being patched in this step)
looks up the WA extension via ``message_template_id`` on every load,
so the change is internally consistent.

Chains after ``0121_email_template_merge``.

Revision ID: 0122_campaigns_template_fk
Revises: 0121_email_template_merge
Create Date: 2026-06-25 18:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0122_campaigns_template_fk"
down_revision: Union[str, None] = "0121_email_template_merge"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FK_COLUMNS = ("template_id", "variant_a_template_id", "variant_b_template_id")


def _drop_template_fk(conn, column: str) -> None:
    """Find + drop whatever FK currently exists on
    ``tbl_campaigns.<column>``. Constraint name varies (autogen names
    differ across alembic revisions + the renames in 0087)."""
    conn.execute(
        sa.text(
            f"""
            DO $$
            DECLARE c_name text;
            BEGIN
                SELECT tc.constraint_name INTO c_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = 'public'
                  AND tc.table_name = 'tbl_campaigns'
                  AND tc.constraint_type = 'FOREIGN KEY'
                  AND kcu.column_name = '{column}'
                LIMIT 1;
                IF c_name IS NOT NULL THEN
                    EXECUTE 'ALTER TABLE tbl_campaigns DROP CONSTRAINT '
                            || quote_ident(c_name);
                END IF;
            END$$;
            """
        )
    )


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Drop the old FKs FIRST. Step 2's UPDATEs would otherwise
    #    violate the still-attached FK (the new values are central
    #    UUIDs not present in tbl_whatsapp_templates.id).
    for col in _FK_COLUMNS:
        _drop_template_fk(conn, col)

    # 2. Remap each column value: WA-template UUID → central UUID.
    for col in _FK_COLUMNS:
        conn.execute(
            sa.text(
                f"""
                UPDATE tbl_campaigns c
                SET {col} = wt.message_template_id
                FROM tbl_whatsapp_templates wt
                WHERE c.{col} = wt.id
                  AND wt.message_template_id IS NOT NULL
                """
            )
        )
        # Defensive: any row still pointing at a WA template whose
        # central link is NULL (shouldn't happen post-Step-9) gets
        # NULL. The dispatcher's `template_row is None` branch
        # already handles this with a clean failure message.
        conn.execute(
            sa.text(
                f"""
                UPDATE tbl_campaigns c
                SET {col} = NULL
                WHERE c.{col} IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM tbl_message_templates m
                    WHERE m.id = c.{col}
                  )
                """
            )
        )

    # 3. Add the new FKs pointing at the central library.
    op.create_foreign_key(
        "fk_campaigns_template_central",
        "tbl_campaigns",
        "tbl_message_templates",
        ["template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_campaigns_variant_a_central",
        "tbl_campaigns",
        "tbl_message_templates",
        ["variant_a_template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_campaigns_variant_b_central",
        "tbl_campaigns",
        "tbl_message_templates",
        ["variant_b_template_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Drop the central-pointing FKs first.
    for name in (
        "fk_campaigns_template_central",
        "fk_campaigns_variant_a_central",
        "fk_campaigns_variant_b_central",
    ):
        op.drop_constraint(name, "tbl_campaigns", type_="foreignkey")

    # Reverse-remap: lookup the WA extension via the central UUID.
    for col in _FK_COLUMNS:
        conn.execute(
            sa.text(
                f"""
                UPDATE tbl_campaigns c
                SET {col} = wt.id
                FROM tbl_whatsapp_templates wt
                WHERE c.{col} = wt.message_template_id
                  AND wt.message_template_id IS NOT NULL
                """
            )
        )

    # Restore the WA-pointing FKs.
    for col in _FK_COLUMNS:
        op.create_foreign_key(
            None,
            "tbl_campaigns",
            "tbl_whatsapp_templates",
            [col],
            ["id"],
            ondelete="SET NULL",
        )
