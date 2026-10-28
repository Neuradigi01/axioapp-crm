"""Seed the three appointment-cycle templates + triggers into every
existing org (``tasks/automation-engine`` Step 10).

New orgs created from this point forward pick up the seeds via the
extended ``install_default_org_seeds`` in
``core/automation/seeds.py``; this migration catches every org that
existed before Step 10 landed.

For each org we insert (if-not-already-present) three pairs of
``(tbl_message_templates, tbl_message_template_versions,
tbl_automation_triggers)`` rows — one per appointment lifecycle
event:

  * ``Appointment Booked``    → ``appointment.booked``
  * ``Appointment Reminder 24h`` → ``appointment.reminder_24h``
  * ``Appointment Reminder 1h``  → ``appointment.reminder_1h``

All seeded rows target the WhatsApp channel (the manager's locked
default for appointment messages). ``subject`` is NULL because WA
templates carry no subject line; the email-cycle seeds keep
non-null subjects so the email column convention isn't disturbed.

All INSERTs use ``WHERE NOT EXISTS`` against the functional unique
indexes (``(org_id, lower(name), channel)`` on templates +
``(org_id, lower(name))`` on triggers) so the migration is
idempotent + safe to re-run.

Chains after ``0130_seed_lead_confirmation``. Reversible — downgrade
removes the seeded rows (matched by exact name + channel).

Revision ID: 0131_seed_appointment_triggers
Revises: 0130_seed_lead_confirmation
Create Date: 2026-06-29 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0131_seed_appointment_triggers"
down_revision: Union[str, None] = "0130_seed_lead_confirmation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (name, event_type, body_text, variables_jsonb_array, recipient_resolver)
_SEEDS: list[tuple[str, str, str, str]] = [
    (
        "Appointment Booked",
        "appointment.booked",
        (
            "Hi {{ contact.full_name }}, your appointment with "
            "{{ org.name }} is confirmed for "
            "{{ appointment.scheduled_at }} at "
            "{{ appointment.location }}. Reply to this message if "
            "you need to reschedule. — {{ org.name }}"
        ),
        '["contact.full_name", "org.name", "appointment.scheduled_at", '
        '"appointment.location"]',
    ),
    (
        "Appointment Reminder 24h",
        "appointment.reminder_24h",
        (
            "Hi {{ contact.full_name }}, this is a reminder that your "
            "appointment with {{ org.name }} is tomorrow at "
            "{{ appointment.scheduled_at }} "
            "({{ appointment.location }}). Reply to this message if "
            "anything changes. — {{ org.name }}"
        ),
        '["contact.full_name", "org.name", "appointment.scheduled_at", '
        '"appointment.location"]',
    ),
    (
        "Appointment Reminder 1h",
        "appointment.reminder_1h",
        (
            "Hi {{ contact.full_name }}, just a heads-up — your "
            "appointment with {{ org.name }} starts in about an hour "
            "at {{ appointment.location }}. See you soon! — "
            "{{ org.name }}"
        ),
        '["contact.full_name", "org.name", "appointment.location"]',
    ),
]


def _insert_template(name: str, body: str, variables_json: str) -> None:
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


def _insert_template_version(name: str) -> None:
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
            'seeded by migration 0131',
            NOW()
        FROM tbl_message_templates t
        WHERE t.channel = 'whatsapp'
          AND lower(t.name) = lower('{name}')
          AND NOT EXISTS (
              SELECT 1 FROM tbl_message_template_versions v
              WHERE v.template_id = t.id AND v.version = 1
          )
        """
    )


def _insert_trigger(name: str, event_type: str) -> None:
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
            'whatsapp',
            t.id,
            0,
            'contact.phone',
            '{{}}'::jsonb,
            NOW(),
            NOW()
        FROM tbl_organizations o
        JOIN tbl_message_templates t
            ON t.org_id = o.id
           AND t.channel = 'whatsapp'
           AND lower(t.name) = lower('{name}')
        WHERE NOT EXISTS (
            SELECT 1 FROM tbl_automation_triggers tr
            WHERE tr.org_id = o.id
              AND lower(tr.name) = lower('{name}')
        )
        """
    )


def upgrade() -> None:
    # Three passes per seed so the version rows reference the
    # template rows that the prior INSERT just produced; alembic
    # runs each statement in its own implicit txn under
    # `autocommit_block` only when explicitly requested — here we
    # rely on the migration-level txn so all six INSERTs land
    # atomically.
    for name, _event_type, body, variables_json in _SEEDS:
        _insert_template(name, body, variables_json)
        _insert_template_version(name)

    for name, event_type, _body, _variables in _SEEDS:
        _insert_trigger(name, event_type)


def downgrade() -> None:
    # Remove the three seeded triggers + their template versions +
    # the templates themselves. Trigger first so the FK from runs
    # cleans correctly (CASCADE on tbl_automation_runs.trigger_id).
    for name, event_type, _body, _variables in _SEEDS:
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
                WHERE channel = 'whatsapp'
                  AND lower(name) = lower('{name}')
            )
            """
        )
        op.execute(
            f"""
            DELETE FROM tbl_message_templates
            WHERE channel = 'whatsapp'
              AND lower(name) = lower('{name}')
            """
        )
