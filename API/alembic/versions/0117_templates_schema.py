"""Central template library — schema.

Step 1 of ``tasks/template-library/``. Adds the four backbone tables
of the new ``core/templates/`` module:

  * ``tbl_message_templates`` — channel-agnostic template metadata.
  * ``tbl_message_template_versions`` — append-only edit history.
  * ``tbl_message_template_reviews`` — append-only workflow audit.
  * ``tbl_message_template_test_sends`` — append-only test-send audit.

Plus four new Postgres enum types: ``template_internal_status``,
``template_external_status``, ``template_category``, and
``template_review_action``. ``channel`` reuses the existing
``conversation_channel`` enum so the same channel registry powers
templates, conversations, and campaigns.

Each table:
  * is tenant-scoped via ``org_id`` FK (RESTRICT) to ``tbl_organizations``,
  * has Postgres RLS enabled + FORCED, with a single
    ``tenant_isolation_*`` policy reading ``current_setting('app.org_id')``,
  * carries hot-path indexes the Step-2 service + Step-6 list page
    will hit.

The unique ``(org_id, lower(name), channel)`` constraint is enforced
via a functional unique index because SQLAlchemy ``UniqueConstraint``
can't carry the ``lower()`` expression.

An assets table is intentionally out of scope here — this codebase
has no central ``tbl_files`` to FK to; image / PDF attachments
will land in a future step alongside the file-storage abstraction.

Chains after ``0116_campaign_ab``.

Revision ID: 0117_templates_schema
Revises: 0116_campaign_ab
Create Date: 2026-06-25 10:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0117_templates_schema"
down_revision: Union[str, None] = "0116_campaign_ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INTERNAL_STATUS_VALUES = (
    "draft",
    "in_review",
    "approved",
    "published",
    "archived",
)
_EXTERNAL_STATUS_VALUES = (
    "n_a",
    "pending",
    "approved",
    "rejected",
    "paused",
)
_CATEGORY_VALUES = ("marketing", "transactional", "service")
_REVIEW_ACTION_VALUES = (
    "submit",
    "approve",
    "reject",
    "request_changes",
    "publish",
    "archive",
)


def upgrade() -> None:
    # ---- enums --------------------------------------------------------
    internal_status_enum = postgresql.ENUM(
        *_INTERNAL_STATUS_VALUES, name="template_internal_status"
    )
    internal_status_enum.create(op.get_bind(), checkfirst=True)

    external_status_enum = postgresql.ENUM(
        *_EXTERNAL_STATUS_VALUES, name="template_external_status"
    )
    external_status_enum.create(op.get_bind(), checkfirst=True)

    category_enum = postgresql.ENUM(
        *_CATEGORY_VALUES, name="template_category"
    )
    category_enum.create(op.get_bind(), checkfirst=True)

    review_action_enum = postgresql.ENUM(
        *_REVIEW_ACTION_VALUES, name="template_review_action"
    )
    review_action_enum.create(op.get_bind(), checkfirst=True)

    # ---- tbl_message_templates ---------------------------------------
    op.create_table(
        "tbl_message_templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "channel",
            postgresql.ENUM(
                name="conversation_channel", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "category",
            postgresql.ENUM(
                *_CATEGORY_VALUES,
                name="template_category",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'marketing'"),
        ),
        sa.Column(
            "language",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'en'"),
        ),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(998), nullable=True),
        sa.Column("preview_text", sa.String(190), nullable=True),
        sa.Column(
            "variables",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "internal_status",
            postgresql.ENUM(
                *_INTERNAL_STATUS_VALUES,
                name="template_internal_status",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "external_status",
            postgresql.ENUM(
                *_EXTERNAL_STATUS_VALUES,
                name="template_external_status",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'n_a'"),
        ),
        sa.Column("external_provider_id", sa.String(255), nullable=True),
        sa.Column(
            "current_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Functional unique index — SA UniqueConstraint can't carry lower().
    op.execute(
        "CREATE UNIQUE INDEX uq_message_templates_org_name_channel "
        "ON tbl_message_templates (org_id, lower(name), channel)"
    )
    op.create_index(
        "ix_message_templates_org_channel_internal_status",
        "tbl_message_templates",
        ["org_id", "channel", "internal_status"],
    )
    op.execute(
        "CREATE INDEX ix_message_templates_org_external_status "
        "ON tbl_message_templates (org_id, external_status) "
        "WHERE external_status <> 'n_a'"
    )

    # ---- tbl_message_template_versions -------------------------------
    op.create_table(
        "tbl_message_template_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "tbl_message_templates.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(998), nullable=True),
        sa.Column(
            "variables",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "changed_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("change_note", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_message_template_versions_template_version",
        "tbl_message_template_versions",
        ["template_id", "version"],
        unique=True,
    )

    # ---- tbl_message_template_reviews --------------------------------
    op.create_table(
        "tbl_message_template_reviews",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "tbl_message_templates.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "reviewer_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "action",
            postgresql.ENUM(
                *_REVIEW_ACTION_VALUES,
                name="template_review_action",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_message_template_reviews_template_created_at",
        "tbl_message_template_reviews",
        ["template_id", "created_at"],
    )

    # ---- tbl_message_template_test_sends -----------------------------
    op.create_table(
        "tbl_message_template_test_sends",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "tbl_message_templates.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "channel",
            postgresql.ENUM(
                name="conversation_channel", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("sent_to", sa.String(255), nullable=False),
        sa.Column(
            "sent_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "channel_message_id",
            sa.String(255),
            nullable=True,
        ),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_message_template_test_sends_template_sent_at",
        "tbl_message_template_test_sends",
        ["template_id", "sent_at"],
    )

    # ---- RLS ----------------------------------------------------------
    for table in (
        "tbl_message_templates",
        "tbl_message_template_versions",
        "tbl_message_template_reviews",
        "tbl_message_template_test_sends",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table[4:]}
                ON {table}
                USING (org_id = current_setting('app.org_id', true)::uuid)
                WITH CHECK (org_id = current_setting('app.org_id', true)::uuid)
            """
        )


def downgrade() -> None:
    for table in (
        "tbl_message_template_test_sends",
        "tbl_message_template_reviews",
        "tbl_message_template_versions",
        "tbl_message_templates",
    ):
        op.execute(
            f"DROP POLICY IF EXISTS tenant_isolation_{table[4:]} ON {table}"
        )

    op.drop_index(
        "ix_message_template_test_sends_template_sent_at",
        table_name="tbl_message_template_test_sends",
    )
    op.drop_table("tbl_message_template_test_sends")

    op.drop_index(
        "ix_message_template_reviews_template_created_at",
        table_name="tbl_message_template_reviews",
    )
    op.drop_table("tbl_message_template_reviews")

    op.drop_index(
        "ix_message_template_versions_template_version",
        table_name="tbl_message_template_versions",
    )
    op.drop_table("tbl_message_template_versions")

    op.execute("DROP INDEX IF EXISTS ix_message_templates_org_external_status")
    op.drop_index(
        "ix_message_templates_org_channel_internal_status",
        table_name="tbl_message_templates",
    )
    op.execute("DROP INDEX IF EXISTS uq_message_templates_org_name_channel")
    op.drop_table("tbl_message_templates")

    for enum_name in (
        "template_review_action",
        "template_category",
        "template_external_status",
        "template_internal_status",
    ):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
