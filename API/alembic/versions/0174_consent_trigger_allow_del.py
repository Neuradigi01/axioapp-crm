"""tbl_consent_events — relax the immutability trigger to allow DELETE.

The original trigger (migration 0109) blocked BOTH UPDATE and DELETE
so the append-only invariant could not be violated. Correct for
UPDATE — the audit trail must not be silently rewritten. Wrong for
DELETE, for two reasons the operator hits in real workflows:

1. **Contact merge.** ``reassign_contact_references`` cannot UPDATE
   consent_events onto the primary contact (trigger blocks). If we
   fall back to letting the secondary contact's FK cascade fire, the
   trigger blocks the DELETE too. Merges therefore always fail for
   any customer who has ever given / withdrawn WhatsApp consent —
   which is anyone whose whatsapp_opt_in has ever moved. Real
   customer report on 2026-07-30.
2. **DPDP / GDPR right-to-be-forgotten.** A hard-delete of a
   contact must be able to purge their consent history too. The
   old trigger silently prevented that by design.

The right shape is: no UPDATE ever (history stays honest), DELETE
allowed (cascade + right-to-be-forgotten work). Application code
never issues DELETE directly against ``tbl_consent_events`` — the
only path there is the FK cascade from a contact deletion, so
allowing DELETE at the trigger doesn't open up any casual-write
foot-guns.

Revision ID: 0174_consent_allow_delete
Revises:     0173_contact_import_async
Create Date: 2026-07-30
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0174_consent_allow_delete"
down_revision = "0173_contact_import_async"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Same function name / trigger name — we just narrow which
    # operations fire it. Row-level BEFORE UPDATE only; DELETE now
    # bypasses the trigger entirely.
    op.execute("DROP TRIGGER IF EXISTS trg_consent_events_immutable ON tbl_consent_events")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION tbl_consent_events_immutable()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION
                'tbl_consent_events is append-only — % rejected',
                TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_consent_events_immutable
        BEFORE UPDATE ON tbl_consent_events
        FOR EACH ROW EXECUTE FUNCTION tbl_consent_events_immutable();
        """
    )


def downgrade() -> None:
    # Restore the original strict trigger (UPDATE OR DELETE).
    op.execute("DROP TRIGGER IF EXISTS trg_consent_events_immutable ON tbl_consent_events")
    op.execute(
        """
        CREATE TRIGGER trg_consent_events_immutable
        BEFORE UPDATE OR DELETE ON tbl_consent_events
        FOR EACH ROW EXECUTE FUNCTION tbl_consent_events_immutable();
        """
    )
