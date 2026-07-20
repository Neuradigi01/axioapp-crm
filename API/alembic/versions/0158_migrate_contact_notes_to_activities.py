"""retire ``tbl_contacts.notes`` — migrate content into ``tbl_activities``.

Two ways to attach text to a contact used to be live in parallel:

  * ``tbl_contacts.notes`` — a single unversioned TEXT column edited
    in-place via ``PATCH /contacts/{id}``. No history, no author, no
    timeline.
  * ``tbl_activities`` rows of ``type='note'`` — a versioned timeline
    with author + timestamp, posted through ``AddNoteComponent`` on
    the contact detail Activities tab.

Two paths, one concept — a data-model confusion. Activities is the
canonical timeline story (author + time + queryable), so this
migration:

  1. Copies every non-empty ``tbl_contacts.notes`` value into a
     ``tbl_activities`` row (``type='note'``, ``entity_type='contact'``,
     ``entity_id=contact.id``, ``payload={"text": <notes>,
     "migrated_from": "contact.notes"}``, ``user_id=NULL`` because
     the original column had no author, ``created_at=contact.updated_at``
     so the timeline row lands at the last-touched time rather than
     "right now").
  2. Drops the ``tbl_contacts.notes`` column.

Downgrade re-adds the column (nullable, no default) but can't restore
the original text — the migrated activity rows stay in
``tbl_activities`` as the source of truth. Explicit two-way loss is
called out here so nobody is surprised.

Revision ID: 0158_retire_contact_notes
Revises:     0155_sender_setup
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision id must be ≤32 chars — that's the width of
# ``alembic_version.version_num`` on this repo.
revision: str = "0158_retire_contact_notes"
down_revision: Union[str, None] = "0155_sender_setup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Copy non-empty notes into tbl_activities as system-emitted
    # note rows. jsonb_build_object gives us proper JSON escaping.
    op.execute(
        """
        INSERT INTO tbl_activities (org_id, entity_type, entity_id, type, payload, user_id, created_at)
        SELECT
          c.org_id,
          'contact',
          c.id,
          'note',
          jsonb_build_object('text', c.notes, 'migrated_from', 'contact.notes'),
          NULL,
          c.updated_at
        FROM tbl_contacts c
        WHERE c.notes IS NOT NULL
          AND btrim(c.notes) <> ''
        """
    )
    op.drop_column("tbl_contacts", "notes")


def downgrade() -> None:
    # Re-add the column as nullable; content is NOT restored (it lives
    # in tbl_activities now and stays there).
    op.add_column("tbl_contacts", sa.Column("notes", sa.Text(), nullable=True))
