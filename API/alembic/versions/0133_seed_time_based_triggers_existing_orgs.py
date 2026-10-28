"""Add ``tbl_contacts.date_of_birth`` + seed the two time-based
templates + triggers into every existing org
(``tasks/automation-engine`` Step 12).

Two concerns in one migration:

  1. ``ALTER TABLE tbl_contacts ADD COLUMN date_of_birth DATE NULL`` —
     the birthday trigger needs an anchor column. Nullable so
     existing contacts don't trip the change; operators populate as
     they capture DOB during normal contact entry.
  2. For each org, INSERT (if-not-already-present) one pair of
     ``(tbl_message_templates, tbl_message_template_versions,
     tbl_automation_triggers)`` rows per seed:

        * ``Contact Birthday``   → ``contact.birthday``     (WhatsApp)
        * ``Lead Stale 30d``     → ``lead.stale_30d``       (email)

New orgs created from this point forward pick up the seeds via the
extended ``install_default_org_seeds`` in
``core/automation/seeds.py``; this migration catches every org that
existed before Step 12 landed.

All INSERTs use ``WHERE NOT EXISTS`` against the functional unique
indexes (``(org_id, lower(name), channel)`` on templates +
``(org_id, lower(name))`` on triggers) so the migration is
idempotent + safe to re-run.

Chains after ``0132_seed_invoice_triggers``. Reversible —
downgrade removes the seeded rows + drops the column.

Revision ID: 0133_seed_time_based_triggers
Revises: 0132_seed_invoice_triggers
Create Date: 2026-06-29 14:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0133_seed_time_based_triggers"
down_revision: Union[str, None] = "0132_seed_invoice_triggers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Birthday — WhatsApp, no subject.
_BIRTHDAY_NAME = "Contact Birthday"
_BIRTHDAY_EVENT = "contact.birthday"
_BIRTHDAY_BODY = (
    "Happy birthday, {{ contact.full_name }}! Wishing you a "
    "wonderful year ahead from everyone at {{ org.name }}. — "
    "{{ org.name }}"
)
_BIRTHDAY_VARS = '["contact.full_name", "org.name"]'

# Stale-lead — email, subject set.
_STALE_NAME = "Lead Stale 30d"
_STALE_EVENT = "lead.stale_30d"
_STALE_SUBJECT = "Still interested, {{ contact.full_name }}?"
_STALE_BODY = (
    "Hi {{ contact.full_name }},\n\n"
    "It's been a few weeks since we last connected. I wanted to "
    "check in — are you still interested in working with "
    "{{ org.name }}? If now isn't the right time, just let me "
    "know and I'll follow up later.\n\n"
    "Otherwise, happy to answer any questions or jump on a quick "
    "call.\n\n"
    "— The {{ org.name }} team"
)
_STALE_VARS = '["contact.full_name", "org.name"]'


def _insert_whatsapp_template(name: str, body: str, variables_json: str) -> None:
    op.execute(
        f"""
        INSERT INTO tbl_message_templates (
            id, org_id, channel, name, category, language,
            body_text, subject, variables,
            internal_status, external_status, current_version,
            created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            o.id,
            'whatsapp',
            '{name}',
            'transactional',
            'en',
            $body_text${body}$body_text$,
            NULL,
            '{variables_json}'::jsonb,
            'published',
            'n_a',
            1,
            NOW(),
            NOW()
        FROM tbl_organizations o
        WHERE NOT EXISTS (
            SELECT 1 FROM tbl_message_templates t
            WHERE t.org_id = o.id
              AND t.channel = 'whatsapp'
              AND lower(t.name) = lower('{name}')
        )
        """
    )


def _insert_email_template(
    name: str, subject: str, body: str, variables_json: str
) -> None:
    op.execute(
        f"""
        INSERT INTO tbl_message_templates (
            id, org_id, channel, name, category, language,
            body_text, subject, variables,
            internal_status, external_status, current_version,
            created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            o.id,
            'email',
            '{name}',
            'transactional',
            'en',
            $body_text${body}$body_text$,
            $subject${subject}$subject$,
            '{variables_json}'::jsonb,
            'published',
            'n_a',
            1,
            NOW(),
            NOW()
        FROM tbl_organizations o
        WHERE NOT EXISTS (
            SELECT 1 FROM tbl_message_templates t
            WHERE t.org_id = o.id
              AND t.channel = 'email'
              AND lower(t.name) = lower('{name}')
        )
        """
    )


def _insert_template_version(channel: str, name: str) -> None:
    op.execute(
        f"""
        INSERT INTO tbl_message_template_versions (
            id, org_id, template_id, version,
            body_text, subject, variables, change_note, changed_at
        )
        SELECT
            gen_random_uuid(),
            t.org_id,
            t.id,
            1,
            t.body_text,
            t.subject,
            t.variables,
            'seeded by migration 0133',
            NOW()
        FROM tbl_message_templates t
        WHERE t.channel = '{channel}'
          AND lower(t.name) = lower('{name}')
          AND NOT EXISTS (
              SELECT 1 FROM tbl_message_template_versions v
              WHERE v.template_id = t.id AND v.version = 1
          )
        """
    )


def _insert_trigger(
    *,
    name: str,
    event_type: str,
    channel: str,
    resolver: str,
) -> None:
    op.execute(
        f"""
        INSERT INTO tbl_automation_triggers (
            id, org_id, name, enabled, event_type,
            conditions, channel, template_id, delay_seconds,
            recipient_resolver, recipient_resolver_config,
            created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            o.id,
            '{name}',
            TRUE,
            '{event_type}',
            '{{}}'::jsonb,
            '{channel}',
            t.id,
            0,
            '{resolver}',
            '{{}}'::jsonb,
            NOW(),
            NOW()
        FROM tbl_organizations o
        JOIN tbl_message_templates t
            ON t.org_id = o.id
           AND t.channel = '{channel}'
           AND lower(t.name) = lower('{name}')
        WHERE NOT EXISTS (
            SELECT 1 FROM tbl_automation_triggers tr
            WHERE tr.org_id = o.id
              AND lower(tr.name) = lower('{name}')
        )
        """
    )


def upgrade() -> None:
    # 1) Add the ``date_of_birth`` column on tbl_contacts. Nullable —
    #    existing rows pick up NULL, operators capture DOB during
    #    normal entry going forward.
    op.add_column(
        "tbl_contacts",
        sa.Column("date_of_birth", sa.Date(), nullable=True),
    )

    # 2) Birthday seed (WhatsApp).
    _insert_whatsapp_template(_BIRTHDAY_NAME, _BIRTHDAY_BODY, _BIRTHDAY_VARS)
    _insert_template_version("whatsapp", _BIRTHDAY_NAME)
    _insert_trigger(
        name=_BIRTHDAY_NAME,
        event_type=_BIRTHDAY_EVENT,
        channel="whatsapp",
        resolver="contact.phone",
    )

    # 3) Stale-lead seed (email).
    _insert_email_template(
        _STALE_NAME, _STALE_SUBJECT, _STALE_BODY, _STALE_VARS
    )
    _insert_template_version("email", _STALE_NAME)
    _insert_trigger(
        name=_STALE_NAME,
        event_type=_STALE_EVENT,
        channel="email",
        resolver="contact.email",
    )


def downgrade() -> None:
    # Remove seeded rows first so the column drop doesn't trip any
    # operator-edited copies.
    for name, event_type, channel in (
        (_BIRTHDAY_NAME, _BIRTHDAY_EVENT, "whatsapp"),
        (_STALE_NAME, _STALE_EVENT, "email"),
    ):
        op.execute(
            f"""
            DELETE FROM tbl_automation_triggers
            WHERE event_type = '{event_type}'
              AND lower(name) = lower('{name}')
            """
        )
        op.execute(
            f"""
            DELETE FROM tbl_message_template_versions
            WHERE template_id IN (
                SELECT id FROM tbl_message_templates
                WHERE channel = '{channel}'
                  AND lower(name) = lower('{name}')
            )
            """
        )
        op.execute(
            f"""
            DELETE FROM tbl_message_templates
            WHERE channel = '{channel}'
              AND lower(name) = lower('{name}')
            """
        )

    op.drop_column("tbl_contacts", "date_of_birth")
