"""Seed the three invoice-cycle templates + triggers into every
existing org (``tasks/automation-engine`` Step 11).

New orgs created from this point forward pick up the seeds via the
extended ``install_default_org_seeds`` in
``core/automation/seeds.py``; this migration catches every org that
existed before Step 11 landed.

For each org we insert (if-not-already-present) three pairs of
``(tbl_message_templates, tbl_message_template_versions,
tbl_automation_triggers)`` rows — one per invoice lifecycle event:

  * ``Invoice Sent``        → ``invoice.sent``
  * ``Invoice Paid``        → ``invoice.paid``
  * ``Invoice Overdue 7d``  → ``invoice.overdue_7d``

All seeded rows target the email channel (industry-standard for
invoices + receipts; operators who want WhatsApp variants can clone
in the editor). Subjects use ``{{ invoice.number }}`` so the
recipient's inbox shows a recognisable thread.

All INSERTs use ``WHERE NOT EXISTS`` against the functional unique
indexes (``(org_id, lower(name), channel)`` on templates +
``(org_id, lower(name))`` on triggers) so the migration is
idempotent + safe to re-run.

Chains after ``0131_seed_appointment_triggers``. Reversible —
downgrade removes the seeded rows (matched by exact name + channel).

Revision ID: 0132_seed_invoice_triggers
Revises: 0131_seed_appointment_triggers
Create Date: 2026-06-29 13:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0132_seed_invoice_triggers"
down_revision: Union[str, None] = "0131_seed_appointment_triggers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (name, event_type, subject, body, variables_jsonb_array)
_SEEDS: list[tuple[str, str, str, str, str]] = [
    (
        "Invoice Sent",
        "invoice.sent",
        "Invoice #{{ invoice.number }} from {{ org.name }}",
        (
            "Hi {{ contact.full_name }},\n\n"
            "Your invoice #{{ invoice.number }} from {{ org.name }} "
            "is attached — the total is {{ invoice.currency }} "
            "{{ invoice.total_amount }}.\n\n"
            "Please review and let us know if you have any "
            "questions. We appreciate your business.\n\n"
            "— The {{ org.name }} team"
        ),
        '["contact.full_name", "org.name", "invoice.number", '
        '"invoice.total_amount", "invoice.currency"]',
    ),
    (
        "Invoice Paid",
        "invoice.paid",
        "Payment received — invoice #{{ invoice.number }}",
        (
            "Hi {{ contact.full_name }},\n\n"
            "Thanks — we've received your payment for invoice "
            "#{{ invoice.number }} ({{ invoice.currency }} "
            "{{ invoice.total_amount }}). This email is your "
            "receipt.\n\n"
            "If you need a formal receipt with our GST details, "
            "just reply and we'll send one over.\n\n"
            "— The {{ org.name }} team"
        ),
        '["contact.full_name", "org.name", "invoice.number", '
        '"invoice.total_amount", "invoice.currency"]',
    ),
    (
        "Invoice Overdue 7d",
        "invoice.overdue_7d",
        "Reminder: invoice #{{ invoice.number }} is now overdue",
        (
            "Hi {{ contact.full_name }},\n\n"
            "This is a friendly reminder that invoice "
            "#{{ invoice.number }} from {{ org.name }} for "
            "{{ invoice.currency }} {{ invoice.total_amount }} is "
            "now more than 7 days overdue.\n\n"
            "If you've already arranged payment, please ignore "
            "this message — otherwise, reply to this email and "
            "we'll be happy to help.\n\n"
            "— The {{ org.name }} team"
        ),
        '["contact.full_name", "org.name", "invoice.number", '
        '"invoice.total_amount", "invoice.currency"]',
    ),
]


def _insert_template(name: str, subject: str, body: str, variables_json: str) -> None:
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
            'seeded by migration 0132',
            NOW()
        FROM tbl_message_templates t
        WHERE t.channel = 'email'
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
            'email',
            t.id,
            0,
            'contact.email',
            '{{}}'::jsonb,
            NOW(),
            NOW()
        FROM tbl_organizations o
        JOIN tbl_message_templates t
            ON t.org_id = o.id
           AND t.channel = 'email'
           AND lower(t.name) = lower('{name}')
        WHERE NOT EXISTS (
            SELECT 1 FROM tbl_automation_triggers tr
            WHERE tr.org_id = o.id
              AND lower(tr.name) = lower('{name}')
        )
        """
    )


def upgrade() -> None:
    for name, _event_type, subject, body, variables_json in _SEEDS:
        _insert_template(name, subject, body, variables_json)
        _insert_template_version(name)

    for name, event_type, _subject, _body, _variables in _SEEDS:
        _insert_trigger(name, event_type)


def downgrade() -> None:
    for name, event_type, _subject, _body, _variables in _SEEDS:
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
                WHERE channel = 'email'
                  AND lower(name) = lower('{name}')
            )
            """
        )
        op.execute(
            f"""
            DELETE FROM tbl_message_templates
            WHERE channel = 'email'
              AND lower(name) = lower('{name}')
            """
        )
