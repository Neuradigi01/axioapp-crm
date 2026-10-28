"""Seed the "User Welcome" template + trigger into every existing org
(``tasks/automation-engine`` Step 5).

New orgs created from this point forward pick up these seeds via
``core.tenants.service.create_organization`` calling
``install_default_org_seeds``. This migration catches every org that
existed before Step 5 landed.

For each org we insert (if-not-already-present):

  1. ``tbl_message_templates`` row — channel=email,
     name='User Welcome', body uses ``{{user.full_name}}`` +
     ``{{org.name}}``, internal_status='published'.
  2. ``tbl_message_template_versions`` row — v=1 mirroring the
     template body.
  3. ``tbl_automation_triggers`` row — event_type='user.signed_up',
     channel='email', recipient_resolver='user.email',
     delay_seconds=0, enabled=true.

All three INSERTs use ``WHERE NOT EXISTS`` against the existing
functional unique indexes (``(org_id, lower(name), channel)`` on
templates + ``(org_id, lower(name))`` on triggers) so the migration
is idempotent + safe to re-run.

Note for production operators: this seeds an ENABLED trigger. If
your org already has a custom welcome flow, disable + delete the
seeded trigger via Settings → Automations after the migration runs
(it's a one-time op per org, the migration won't recreate a
deleted row on subsequent runs because the lookup is by name —
adding a new row with the same name post-delete would re-trip the
unique index, but downgrade-then-upgrade after a manual delete is
the only way to restore).

Chains after ``0128_run_event_id``. Reversible — downgrade removes
the seeded rows (matched by exact name).

Revision ID: 0129_seed_user_welcome
Revises: 0128_run_event_id
Create Date: 2026-06-29 05:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0129_seed_user_welcome"
down_revision: Union[str, None] = "0128_run_event_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TEMPLATE_NAME = "User Welcome"
_TRIGGER_NAME = "User Welcome"

_TEMPLATE_BODY = (
    "Hi {{ user.full_name }},\n\n"
    "Welcome to {{ org.name }}! Your workspace is ready — sign in any "
    "time to start adding contacts, building campaigns, and inviting "
    "your team.\n\n"
    "If you have any questions, just reply to this email.\n\n"
    "— The {{ org.name }} team"
)
_TEMPLATE_SUBJECT = "Welcome to {{ org.name }}"


def upgrade() -> None:
    # 1) Insert the template per org (skipping orgs that already
    #    have a template named 'User Welcome' on the email channel).
    #    Uses gen_random_uuid() for the id.
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
            '["user.full_name", "org.name"]'::jsonb,
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

    # 2) Insert the version row for every template we just created
    #    (or one that already exists with the same name) — guarded
    #    by NOT EXISTS on (template_id, version=1) so a re-run is
    #    a no-op.
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
            'seeded by migration 0129',
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

    # 3) Insert the trigger per org pointing at the template we
    #    just made (or the operator's pre-existing one with the
    #    matching name). Skip orgs that already have a trigger
    #    named 'User Welcome'.
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
            'user.signed_up',
            '{{}}'::jsonb,
            'email',
            t.id,
            0,
            'user.email',
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
    # Remove the seeded trigger first (FK CASCADE on runs cleans
    # those up), then the template version + template. Operator
    # edits to body/subject + renames are NOT detected by this
    # downgrade — name match only.
    op.execute(
        f"""
        DELETE FROM tbl_automation_triggers
        WHERE event_type = 'user.signed_up'
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
