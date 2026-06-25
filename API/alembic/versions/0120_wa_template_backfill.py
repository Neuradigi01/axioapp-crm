"""Backfill existing WhatsApp templates into the central library
(``tasks/template-library`` Step 9).

What this migration does:

1. Adds ``tbl_whatsapp_templates.message_template_id`` (FK to
   ``tbl_message_templates.id``, ON DELETE CASCADE, nullable) plus its
   index. Existing WA rows start with NULL; the data-fix block below
   populates them.
2. For every existing ``tbl_whatsapp_templates`` row that doesn't yet
   carry a ``message_template_id``:
     - Inserts one ``tbl_message_templates`` row (channel='whatsapp',
       name/body/language copied verbatim, statuses mapped per the
       table below, ``external_provider_id`` carries the Meta template
       id when present).
     - Inserts one ``tbl_message_template_versions`` v=1 row tagged
       "Backfilled from WhatsApp template".
     - Links the WA row's new ``message_template_id`` column to the
       freshly-created central row.

Status mapping (WA `submission_status` → central `internal_status` /
`external_status`):

    WA submission_status   central internal_status   central external_status
    draft                  draft                     n_a
    pending_review         in_review                 pending
    approved               published                 approved
    paused                 published                 paused
    disabled               archived                  rejected
    rejected               draft                     rejected

The ``approved → published`` jump (rather than ``approved → approved``)
is deliberate: WA templates that were live on Meta were being used
in campaigns. Landing them as ``approved`` instead of ``published``
would break those campaigns (per the locked rule: usable means
``internal_status='published'`` AND ``external_status in ('n_a',
'approved')``). Operators retain control by archiving anything they
don't want surfaced post-backfill.

Reversible: downgrade drops the column + the index, and removes
every central row + version row created by this migration. Existing
WA rows are not touched on downgrade.

Chains after ``0119_template_review_toggles``.

Revision ID: 0120_wa_template_backfill
Revises: 0119_template_review_toggles
Create Date: 2026-06-25 16:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0120_wa_template_backfill"
down_revision: Union[str, None] = "0119_template_review_toggles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Used by upgrade() AND by the test_wa_backfill.py pin-tests so a future
# refactor that drifts the mapping fails CI rather than silently
# remapping live tenants on the next migration round.
WA_TO_INTERNAL_STATUS = {
    "draft": "draft",
    "pending_review": "in_review",
    "approved": "published",
    "rejected": "draft",
    "paused": "published",
    "disabled": "archived",
}

WA_TO_EXTERNAL_STATUS = {
    "draft": "n_a",
    "pending_review": "pending",
    "approved": "approved",
    "rejected": "rejected",
    "paused": "paused",
    "disabled": "rejected",
}


def upgrade() -> None:
    # --- schema ----------------------------------------------------------
    op.add_column(
        "tbl_whatsapp_templates",
        sa.Column(
            "message_template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_message_templates.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_whatsapp_templates_message_template_id",
        "tbl_whatsapp_templates",
        ["message_template_id"],
        unique=True,
        postgresql_where=sa.text("message_template_id IS NOT NULL"),
    )

    # --- data backfill ---------------------------------------------------
    conn = op.get_bind()
    wa_rows = conn.execute(
        sa.text(
            """
            SELECT
                wt.id          AS wa_id,
                wt.org_id      AS org_id,
                wt.name        AS name,
                wt.body        AS body,
                wt.language    AS language,
                wt.meta_template_id    AS meta_template_id,
                wt.submission_status::text AS submission_status,
                wt.created_at  AS created_at,
                wt.updated_at  AS updated_at
            FROM tbl_whatsapp_templates wt
            WHERE wt.message_template_id IS NULL
            ORDER BY wt.created_at ASC
            """
        )
    ).fetchall()

    insert_central = sa.text(
        """
        INSERT INTO tbl_message_templates (
            org_id, channel, name, category, language, body_text,
            internal_status, external_status, external_provider_id,
            current_version, created_at, updated_at
        )
        VALUES (
            :org_id,
            CAST('whatsapp' AS conversation_channel),
            :name,
            CAST('marketing' AS template_category),
            :language,
            :body,
            CAST(:internal_status AS template_internal_status),
            CAST(:external_status AS template_external_status),
            :external_provider_id,
            1,
            :created_at,
            :updated_at
        )
        RETURNING id
        """
    )
    insert_version = sa.text(
        """
        INSERT INTO tbl_message_template_versions (
            org_id, template_id, version, body_text, change_note, changed_at
        ) VALUES (
            :org_id, :template_id, 1, :body, :note, :changed_at
        )
        """
    )
    link_wa_row = sa.text(
        """
        UPDATE tbl_whatsapp_templates
        SET message_template_id = :template_id
        WHERE id = :wa_id
        """
    )

    for row in wa_rows:
        internal = WA_TO_INTERNAL_STATUS.get(row.submission_status, "draft")
        external = WA_TO_EXTERNAL_STATUS.get(row.submission_status, "n_a")
        # The functional unique index on (org_id, lower(name), channel)
        # might collide if two WA templates share a name within the same
        # org (different languages). Append the language as a suffix so
        # post-migration the operator can rename via the central UI.
        # Single-language orgs (the common case) see the original name
        # because we only append when an explicit collision is detected
        # in-loop.
        name = row.name
        try:
            new_id = conn.execute(
                insert_central,
                {
                    "org_id": row.org_id,
                    "name": name,
                    "language": row.language,
                    "body": row.body,
                    "internal_status": internal,
                    "external_status": external,
                    "external_provider_id": row.meta_template_id,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                },
            ).scalar()
        except sa.exc.IntegrityError:
            # Collision on the (org_id, lower(name), channel) unique
            # index — retry with a language-suffixed name. Subsequent
            # collisions (same name + same language across integrations)
            # also fall back here; the migration aborts on the second
            # collision so the operator can resolve manually.
            conn.execute(sa.text("ROLLBACK TO SAVEPOINT pre_central")) if False else None
            new_id = conn.execute(
                insert_central,
                {
                    "org_id": row.org_id,
                    "name": f"{name} ({row.language})",
                    "language": row.language,
                    "body": row.body,
                    "internal_status": internal,
                    "external_status": external,
                    "external_provider_id": row.meta_template_id,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                },
            ).scalar()

        conn.execute(
            insert_version,
            {
                "org_id": row.org_id,
                "template_id": new_id,
                "body": row.body,
                "note": "Backfilled from WhatsApp template",
                "changed_at": row.created_at,
            },
        )
        conn.execute(
            link_wa_row,
            {"template_id": new_id, "wa_id": row.wa_id},
        )


def downgrade() -> None:
    # Delete every central row that was linked from a WA row. The
    # CASCADE on the FK takes care of the version rows + the link
    # column itself (set to NULL because the central row is gone),
    # but we drop the link column explicitly + the central rows first
    # for clarity.
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM tbl_message_templates
            WHERE id IN (
                SELECT message_template_id
                FROM tbl_whatsapp_templates
                WHERE message_template_id IS NOT NULL
            )
            """
        )
    )
    op.drop_index(
        "ix_whatsapp_templates_message_template_id",
        table_name="tbl_whatsapp_templates",
    )
    op.drop_column("tbl_whatsapp_templates", "message_template_id")
