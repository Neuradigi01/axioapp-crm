"""Seed the "Lead Confirmation" template + trigger into every
existing org (``tasks/automation-engine`` Step 6).

Mirrors the ``0129_seed_user_welcome`` pattern. New orgs from this
point forward pick up the seed via the extended
``install_default_org_seeds`` in ``core/automation/seeds.py``;
this migration catches every org that existed before Step 6
landed.

The seeded trigger carries a default condition that EXCLUDES bulk
CSV imports (``{"field": "source", "op": "ne", "value":
"bulk_import"}``). Bulk imports can fan out to thousands of
contacts; auto-firing the confirmation would surprise operators +
flood inboxes. The condition is removable via the trigger editor
once the operator confirms intent.

All three INSERTs use ``WHERE NOT EXISTS`` against the existing
functional unique indexes (``(org_id, lower(name), channel)`` on
templates + ``(org_id, lower(name))`` on triggers) so the
migration is idempotent + safe to re-run.

Chains after ``0129_seed_user_welcome``. Reversible.

Revision ID: 0130_seed_lead_confirmation
Revises: 0129_seed_user_welcome
Create Date: 2026-06-29 06:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0130_seed_lead_confirmation"
down_revision: Union[str, None] = "0129_seed_user_welcome"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TEMPLATE_NAME = "Lead Confirmation"
_TRIGGER_NAME = "Lead Confirmation"

_TEMPLATE_BODY = (
    "Hi {{ contact.full_name }},\n\n"
    "Thanks for reaching out to {{ org.name }} — we've received "
    "your details and a team member will follow up shortly.\n\n"
    "In the meantime, feel free to reply to this email with any "
    "additional context or questions.\n\n"
    "— The {{ org.name }} team"
)
_TEMPLATE_SUBJECT = "Thanks for reaching out, {{ contact.full_name }}"
# Bulk-import exclusion baked into the seeded trigger's conditions.
# Operator can remove via the trigger editor (Step 8) after
# confirming the org's policy around bulk-CSV outreach.
_TRIGGER_CONDITIONS = (
    '{"field": "source", "op": "ne", "value": "bulk_import"}'
)


def upgrade() -> None:
    # 1) Template per org — skip orgs that already have a "Lead
    #    Confirmation" email template.
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
            '{_TEMPLATE_NAME}',
            'transactional',
            'en',
            $body_text${_TEMPLATE_BODY}$body_text$,
            $subject${_TEMPLATE_SUBJECT}$subject$,
            '["contact.full_name", "org.name"]'::jsonb,
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
              AND lower(t.name) = lower('{_TEMPLATE_NAME}')
        )
        """
    )

    # 2) v=1 version row for every Lead Confirmation template we
    #    just created (or pre-existing).
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
            'seeded by migration 0130',
            NOW()
        FROM tbl_message_templates t
        WHERE t.channel = 'email'
          AND lower(t.name) = lower('{_TEMPLATE_NAME}')
          AND NOT EXISTS (
              SELECT 1 FROM tbl_message_template_versions v
              WHERE v.template_id = t.id AND v.version = 1
          )
        """
    )

    # 3) Trigger per org pointing at the new template. Skip orgs
    #    that already have a trigger named "Lead Confirmation".
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
            '{_TRIGGER_NAME}',
            TRUE,
            'lead.created',
            '{_TRIGGER_CONDITIONS}'::jsonb,
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
           AND lower(t.name) = lower('{_TEMPLATE_NAME}')
        WHERE NOT EXISTS (
            SELECT 1 FROM tbl_automation_triggers tr
            WHERE tr.org_id = o.id
              AND lower(tr.name) = lower('{_TRIGGER_NAME}')
        )
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM tbl_automation_triggers
        WHERE event_type = 'lead.created'
          AND lower(name) = lower('{_TRIGGER_NAME}')
        """
    )
    op.execute(
        f"""
        DELETE FROM tbl_message_template_versions
        WHERE template_id IN (
            SELECT id FROM tbl_message_templates
            WHERE channel = 'email'
              AND lower(name) = lower('{_TEMPLATE_NAME}')
        )
        """
    )
    op.execute(
        f"""
        DELETE FROM tbl_message_templates
        WHERE channel = 'email'
          AND lower(name) = lower('{_TEMPLATE_NAME}')
        """
    )
