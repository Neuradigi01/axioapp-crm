"""Contact-import opt-in provenance.

Adds a nullable ``opt_in_source`` column to ``tbl_contact_imports`` so
the DPDP opt-in provenance the operator picks on the wizard's mapping
step actually persists to each contact row on commit.

The commit path reads this column and stamps every inserted contact's
``whatsapp_opt_in_source`` + ``whatsapp_opt_in_status`` accordingly.
NULL means "operator hasn't chosen yet" — commit falls back to the
current ``never_contacted`` default so existing in-flight imports don't
break.

Revision ID: 0164_contact_import_opt_in
Revises:     0163_catalog_extensions
Create Date: 2026-07-21
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0164_contact_import_opt_in"
down_revision: str | None = "0163_catalog_extensions"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_contact_imports",
        sa.Column("opt_in_source", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tbl_contact_imports", "opt_in_source")
