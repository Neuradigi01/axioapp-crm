"""widget_forms — turn `tbl_widget_configs` into a multi-form store.

Migration 0046 constrained the table to one row per org
(``uq_widget_configs_org``). This one lifts that cap so every org
can create as many lead-capture forms as they need, each with its
own name, slug, JSONB config, and embed key (via ``EmbedKey.resource_id``).

Schema changes on ``tbl_widget_configs``:

  - Drop ``uq_widget_configs_org``.
  - Add ``name``           TEXT NOT NULL — display name shown in the
                          Forms list + inserted into ``attribution.form_name``
                          on every submission for the "Forms · <name>"
                          source rendering.
  - Add ``slug``           VARCHAR(64) NOT NULL — URL-safe id used in
                          the embed snippet (``data-form="<slug>"``).
                          Unique per org, reusable after soft-delete.
  - Add ``is_default``     BOOLEAN NOT NULL DEFAULT false — the form
                          the widget resolves to when a snippet omits
                          ``data-form``. Backfilled `true` on the one
                          existing row per org so legacy embeds keep
                          working unchanged.
  - Add ``deleted_at``     TIMESTAMPTZ NULL — soft-delete stamp so a
                          form can be retired without breaking every
                          historical lead that carries ``attribution.form_id``.

Uniqueness: ``UNIQUE (org_id, slug) WHERE deleted_at IS NULL`` — a
partial index so slugs are only unique among live forms. A deleted
form's slug can be re-used by a fresh one without renaming leads.

Every existing row is stamped ``name='Default form'``, ``slug='default'``,
``is_default=true``. Legacy widget-sourced leads pick up
``attribution.form_id`` retroactively in a later step so their source
column renders as "Forms · Default form" instead of the bare "Widget"
label.

Revision ID: 0216_widget_forms
Revises: 0215_mailgun_inbound_schema
Create Date: 2026-09-07 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0216_widget_forms"
down_revision: Union[str, None] = "0215_mailgun_inbound_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop the one-form-per-org cap.
    op.drop_constraint(
        "uq_widget_configs_org",
        "tbl_widget_configs",
        type_="unique",
    )

    # 2. Add the new columns with a temporary server_default so the NOT
    #    NULL doesn't blow up on existing rows. Defaults are dropped
    #    below once the backfill lands — new inserts must supply the
    #    values explicitly.
    op.add_column(
        "tbl_widget_configs",
        sa.Column(
            "name",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'Default form'"),
        ),
    )
    op.add_column(
        "tbl_widget_configs",
        sa.Column(
            "slug",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'default'"),
        ),
    )
    op.add_column(
        "tbl_widget_configs",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tbl_widget_configs",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # 3. Backfill — every pre-existing row is the org's default form.
    op.execute(
        "UPDATE tbl_widget_configs "
        "SET is_default = true, name = 'Default form', slug = 'default' "
        "WHERE is_default = false"
    )

    # 4. Drop the temporary server_defaults so new inserts must supply
    #    name/slug explicitly (service layer generates them from the
    #    Owner-supplied display name).
    op.alter_column("tbl_widget_configs", "name", server_default=None)
    op.alter_column("tbl_widget_configs", "slug", server_default=None)

    # 5. Partial UNIQUE — slugs are unique among LIVE forms per org, so
    #    a deleted form can free up its slug for a fresh one.
    op.create_index(
        "uq_widget_configs_org_slug_live",
        "tbl_widget_configs",
        ["org_id", "slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    # Reverse in inverse order — the partial UNIQUE goes first so the
    # column drops don't trip a "column referenced by index" error.
    op.drop_index("uq_widget_configs_org_slug_live", table_name="tbl_widget_configs")
    op.drop_column("tbl_widget_configs", "deleted_at")
    op.drop_column("tbl_widget_configs", "is_default")
    op.drop_column("tbl_widget_configs", "slug")
    op.drop_column("tbl_widget_configs", "name")
    op.create_unique_constraint(
        "uq_widget_configs_org",
        "tbl_widget_configs",
        ["org_id"],
    )
