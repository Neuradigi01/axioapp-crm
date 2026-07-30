"""Add processing + cancelled to the contact_import_status enum.

Contacts imports now dispatch to Celery like the leads-import surface
already does (parity called out on 2026-07-30). Two new lifecycle
states:

  - ``processing`` — commit endpoint set the mapping + enqueued the
    worker; the row loop is running out-of-band.
  - ``cancelled`` — operator aborted before the worker finished.
    Worker checks status on each row batch and exits early when it
    sees this.

PostgreSQL 12+ supports ``ALTER TYPE … ADD VALUE`` inside a
transaction, so no autocommit finagling needed. Downgrade is a no-op —
Postgres has no ``ALTER TYPE … DROP VALUE`` and the risk of dropping a
value that a live row uses isn't worth the downgrade rollback story.

Revision ID: 0173_contact_import_async
Revises:     0172_contact_import_reports
Create Date: 2026-07-30
"""

from __future__ import annotations

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0173_contact_import_async"
down_revision: str | None = "0172_contact_import_reports"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE contact_import_status ADD VALUE IF NOT EXISTS 'processing'")
    op.execute("ALTER TYPE contact_import_status ADD VALUE IF NOT EXISTS 'cancelled'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE. Any row currently in
    # 'processing' / 'cancelled' would need re-mapping before a drop —
    # not worth the fragility for a downgrade. Left as a no-op.
    pass
