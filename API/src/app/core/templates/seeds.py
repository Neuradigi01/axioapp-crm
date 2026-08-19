"""Idempotent template seeders installed at org-creation time.

Step 5 of ``tasks/automation-engine/`` seeds a default "User
Welcome" email template into every new org so the
:data:`user.signed_up` event has something to render at the
moment the Owner finishes signup. Future steps add more seeded
templates (Lead Confirmation in Step 6 of the same track).

Seeds are inserted as **published** templates so the automation
dispatcher can use them without an internal-review cycle.
Operators can edit / rename / archive them via the regular
templates editor (`/user/templates`) — the seeders are idempotent
on ``(org_id, lower(name), channel)`` so re-running them never
overwrites operator changes.

Cross-track dependency: this module is imported by
:mod:`core.tenants.service.create_organization` (the canonical
new-org chokepoint) so the seeded rows land inside the same
transaction as the org row itself. A signup that rolls back also
rolls back the seeds. Backfill migration
``0129_seed_user_welcome_existing_orgs`` runs the same seeders
against every pre-existing org.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates.models import (
    MessageTemplate,
    MessageTemplateVersion,
    TemplateCategory,
    TemplateExternalStatus,
    TemplateInternalStatus,
)

logger = logging.getLogger(__name__)


_USER_WELCOME_NAME = "User Welcome"
_USER_WELCOME_SUBJECT = "Welcome to {{ org.name }}"
_USER_WELCOME_BODY = (
    "Hi {{ user.full_name }},\n\n"
    "Welcome to {{ org.name }}! Your workspace is ready — sign in any "
    "time to start adding contacts, building campaigns, and inviting "
    "your team.\n\n"
    "If you have any questions, just reply to this email.\n\n"
    "— The {{ org.name }} team"
)

_LEAD_CONFIRMATION_NAME = "Lead Confirmation"
_LEAD_CONFIRMATION_SUBJECT = "Thanks for reaching out, {{ contact.full_name }}"
_LEAD_CONFIRMATION_BODY = (
    "Hi {{ contact.full_name }},\n\n"
    "Thanks for reaching out to {{ org.name }} — we've received your "
    "details and a team member will follow up shortly.\n\n"
    "In the meantime, feel free to reply to this email with any "
    "additional context or questions.\n\n"
    "— The {{ org.name }} team"
)

# ---------------------------------------------------------------------------
# Step 10 — appointment-cycle templates (WhatsApp channel by default).
# WhatsApp is the manager's chosen channel for appointment messages
# — confirmations + reminders land more reliably in the recipient's
# attention than email. The dispatcher will skip + record a `failed`
# run if the org hasn't connected WA yet; the operator can either
# (a) connect WA via Settings → Integrations → WhatsApp, or
# (b) flip the trigger's channel to email via the trigger editor.
# ---------------------------------------------------------------------------

_APPOINTMENT_BOOKED_NAME = "Appointment Booked"
_APPOINTMENT_BOOKED_BODY = (
    "Hi {{ contact.full_name }}, your appointment with {{ org.name }} is "
    "confirmed for {{ appointment.scheduled_at }}"
    " at {{ appointment.location }}. Reply to this message if you need "
    "to reschedule. — {{ org.name }}"
)

_APPOINTMENT_REMINDER_24H_NAME = "Appointment Reminder 24h"
_APPOINTMENT_REMINDER_24H_BODY = (
    "Hi {{ contact.full_name }}, this is a reminder that your appointment "
    "with {{ org.name }} is tomorrow at {{ appointment.scheduled_at }} "
    "({{ appointment.location }}). Reply to this message if anything "
    "changes. — {{ org.name }}"
)

_APPOINTMENT_REMINDER_1H_NAME = "Appointment Reminder 1h"
_APPOINTMENT_REMINDER_1H_BODY = (
    "Hi {{ contact.full_name }}, just a heads-up — your appointment with "
    "{{ org.name }} starts in about an hour at {{ appointment.location }}. "
    "See you soon! — {{ org.name }}"
)

# ---------------------------------------------------------------------------
# Step 11 — invoice-cycle templates (email channel by default).
# Invoices carry a PDF + currency value that's easier to surface in
# an email than a WhatsApp message; the seeded templates use
# ``{{ invoice.* }}`` variables registered in
# :mod:`core.templates.variables`. Operators who want a WhatsApp
# variant can clone via the editor.
# ---------------------------------------------------------------------------

_INVOICE_SENT_NAME = "Invoice Sent"
_INVOICE_SENT_SUBJECT = "Invoice #{{ invoice.number }} from {{ org.name }}"
_INVOICE_SENT_BODY = (
    "Hi {{ contact.full_name }},\n\n"
    "Your invoice #{{ invoice.number }} from {{ org.name }} is "
    "attached — the total is {{ invoice.currency }} "
    "{{ invoice.total_amount }}.\n\n"
    "Please review and let us know if you have any questions. We "
    "appreciate your business.\n\n"
    "— The {{ org.name }} team"
)

_INVOICE_PAID_NAME = "Invoice Paid"
_INVOICE_PAID_SUBJECT = "Payment received — invoice #{{ invoice.number }}"
_INVOICE_PAID_BODY = (
    "Hi {{ contact.full_name }},\n\n"
    "Thanks — we've received your payment for invoice "
    "#{{ invoice.number }} ({{ invoice.currency }} "
    "{{ invoice.total_amount }}). This email is your receipt.\n\n"
    "If you need a formal receipt with our GST details, just reply "
    "and we'll send one over.\n\n"
    "— The {{ org.name }} team"
)

# ---------------------------------------------------------------------------
# Step 12 — time-based templates.
# Birthday: WhatsApp (personal, more eyeballs than email).
# Stale-lead: email (longer-form ask, salesperson signature).
# ---------------------------------------------------------------------------

_CONTACT_BIRTHDAY_NAME = "Contact Birthday"
_CONTACT_BIRTHDAY_BODY = (
    "Happy birthday, {{ contact.full_name }}! Wishing you a "
    "wonderful year ahead from everyone at {{ org.name }}. — "
    "{{ org.name }}"
)

_LEAD_STALE_30D_NAME = "Lead Stale 30d"
_LEAD_STALE_30D_SUBJECT = "Still interested, {{ contact.full_name }}?"
_LEAD_STALE_30D_BODY = (
    "Hi {{ contact.full_name }},\n\n"
    "It's been a few weeks since we last connected. I wanted to "
    "check in — are you still interested in working with "
    "{{ org.name }}? If now isn't the right time, just let me "
    "know and I'll follow up later.\n\n"
    "Otherwise, happy to answer any questions or jump on a quick "
    "call.\n\n"
    "— The {{ org.name }} team"
)

_INVOICE_OVERDUE_NAME = "Invoice Overdue 7d"
_INVOICE_OVERDUE_SUBJECT = "Reminder: invoice #{{ invoice.number }} is now overdue"
_INVOICE_OVERDUE_BODY = (
    "Hi {{ contact.full_name }},\n\n"
    "This is a friendly reminder that invoice #{{ invoice.number }} "
    "from {{ org.name }} for {{ invoice.currency }} "
    "{{ invoice.total_amount }} is now more than 7 days overdue.\n\n"
    "If you've already arranged payment, please ignore this message "
    "— otherwise, reply to this email and we'll be happy to help.\n\n"
    "— The {{ org.name }} team"
)

_TASK_ASSIGNED_NAME = "Task Assigned"
_TASK_ASSIGNED_SUBJECT = "New task for you: {{ task.title }}"
_TASK_ASSIGNED_BODY = (
    "Hi {{ assignee.full_name }},\n\n"
    "You've been assigned a new task in {{ org.name }}:\n\n"
    "  Task:     {{ task.title }}\n"
    "  Due:      {{ task.due_at }}\n"
    "  Priority: {{ task.priority }}\n\n"
    "{{ task.description }}\n\n"
    "Open the CRM to see the full details.\n\n"
    "— The {{ org.name }} team"
)

_TASK_COMPLETED_NAME = "Task Completed"
_TASK_COMPLETED_SUBJECT = "Task completed: {{ task.title }}"
_TASK_COMPLETED_BODY = (
    "Hi {{ assignee.full_name }},\n\n"
    "The following task has been marked complete in {{ org.name }}:\n\n"
    "  Task:     {{ task.title }}\n"
    "  Due:      {{ task.due_at }}\n"
    "  Priority: {{ task.priority }}\n\n"
    "No further action needed.\n\n"
    "— The {{ org.name }} team"
)


async def seed_user_welcome_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> MessageTemplate:
    """Insert (or return the existing) "User Welcome" email template
    for ``org_id``. Caller owns the transaction — does not commit.

    Idempotent: a second call returns the prior row unchanged, so
    operators who renamed the template won't get a duplicate at the
    next backfill run.
    """
    existing = (
        await session.execute(
            select(MessageTemplate).where(
                MessageTemplate.org_id == org_id,
                func.lower(MessageTemplate.name) == _USER_WELCOME_NAME.lower(),
                MessageTemplate.channel == ConversationChannel.email,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    template = MessageTemplate(
        org_id=org_id,
        channel=ConversationChannel.email,
        name=_USER_WELCOME_NAME,
        category=TemplateCategory.transactional,
        language="en",
        body_text=_USER_WELCOME_BODY,
        subject=_USER_WELCOME_SUBJECT,
        # Variables the renderer should resolve at send time. Kept in
        # sync with the body string above + the event_catalog payload
        # for `user.signed_up`.
        variables=["user.full_name", "org.name"],
        internal_status=TemplateInternalStatus.published,
        external_status=TemplateExternalStatus.n_a,
        current_version=1,
    )
    session.add(template)
    await session.flush()

    version = MessageTemplateVersion(
        org_id=org_id,
        template_id=template.id,
        version=1,
        body_text=template.body_text,
        subject=template.subject,
        variables=template.variables,
        change_note="seeded by automation-engine Step 5 (User Welcome)",
    )
    session.add(version)
    await session.flush()

    logger.info(
        "templates.seed user_welcome org=%s template=%s",
        org_id,
        template.id,
    )
    return template


async def seed_lead_confirmation_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> MessageTemplate:
    """Insert (or return the existing) "Lead Confirmation" email
    template — the body the seeded Step-6 trigger renders for
    every new ``lead.created`` event regardless of source.

    Idempotent on ``(org_id, lower(name), channel='email')``. Same
    pattern as :func:`seed_user_welcome_template`."""
    existing = (
        await session.execute(
            select(MessageTemplate).where(
                MessageTemplate.org_id == org_id,
                func.lower(MessageTemplate.name) == _LEAD_CONFIRMATION_NAME.lower(),
                MessageTemplate.channel == ConversationChannel.email,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    template = MessageTemplate(
        org_id=org_id,
        channel=ConversationChannel.email,
        name=_LEAD_CONFIRMATION_NAME,
        category=TemplateCategory.transactional,
        language="en",
        body_text=_LEAD_CONFIRMATION_BODY,
        subject=_LEAD_CONFIRMATION_SUBJECT,
        variables=["contact.full_name", "org.name"],
        internal_status=TemplateInternalStatus.published,
        external_status=TemplateExternalStatus.n_a,
        current_version=1,
    )
    session.add(template)
    await session.flush()

    version = MessageTemplateVersion(
        org_id=org_id,
        template_id=template.id,
        version=1,
        body_text=template.body_text,
        subject=template.subject,
        variables=template.variables,
        change_note="seeded by automation-engine Step 6 (Lead Confirmation)",
    )
    session.add(version)
    await session.flush()

    logger.info(
        "templates.seed lead_confirmation org=%s template=%s",
        org_id,
        template.id,
    )
    return template


async def _seed_whatsapp_appointment_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    name: str,
    body: str,
    variables: list[str],
    change_note: str,
) -> MessageTemplate:
    """Shared shaper for the three Step-10 WhatsApp appointment seeds.

    WhatsApp business templates require Meta approval before they can
    be sent on a verified phone number, but seeded templates are
    inserted with ``external_status=n_a`` so the dispatcher's
    template-state gate doesn't refuse them on day one. Operators who
    want Meta-approved versions can clone + submit through the normal
    templates editor; the seeded row is the operator's free starting
    point.
    """
    existing = (
        await session.execute(
            select(MessageTemplate).where(
                MessageTemplate.org_id == org_id,
                func.lower(MessageTemplate.name) == name.lower(),
                MessageTemplate.channel == ConversationChannel.whatsapp,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    template = MessageTemplate(
        org_id=org_id,
        channel=ConversationChannel.whatsapp,
        name=name,
        category=TemplateCategory.transactional,
        language="en",
        body_text=body,
        # WA templates don't carry an email-style `subject`; the
        # column is nullable so leave it None.
        subject=None,
        variables=variables,
        internal_status=TemplateInternalStatus.published,
        external_status=TemplateExternalStatus.n_a,
        current_version=1,
    )
    session.add(template)
    await session.flush()

    version = MessageTemplateVersion(
        org_id=org_id,
        template_id=template.id,
        version=1,
        body_text=template.body_text,
        subject=template.subject,
        variables=template.variables,
        change_note=change_note,
    )
    session.add(version)
    await session.flush()

    logger.info(
        "templates.seed appointment_template org=%s name=%s template=%s",
        org_id,
        name,
        template.id,
    )
    return template


async def seed_appointment_booked_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> MessageTemplate:
    """WhatsApp confirmation message — fires after a new appointment
    row commits (``appointment.booked``)."""
    return await _seed_whatsapp_appointment_template(
        session,
        org_id=org_id,
        name=_APPOINTMENT_BOOKED_NAME,
        body=_APPOINTMENT_BOOKED_BODY,
        variables=[
            "contact.full_name",
            "org.name",
            "appointment.scheduled_at",
            "appointment.location",
        ],
        change_note=("seeded by automation-engine Step 10 (Appointment Booked)"),
    )


async def seed_appointment_reminder_24h_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> MessageTemplate:
    """WhatsApp reminder — fires 24h before the appointment via the
    Celery beat sweep (``appointment.reminder_24h``)."""
    return await _seed_whatsapp_appointment_template(
        session,
        org_id=org_id,
        name=_APPOINTMENT_REMINDER_24H_NAME,
        body=_APPOINTMENT_REMINDER_24H_BODY,
        variables=[
            "contact.full_name",
            "org.name",
            "appointment.scheduled_at",
            "appointment.location",
        ],
        change_note=("seeded by automation-engine Step 10 (Appointment Reminder 24h)"),
    )


async def seed_appointment_reminder_1h_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> MessageTemplate:
    """WhatsApp reminder — fires 1h before the appointment via the
    Celery beat sweep (``appointment.reminder_1h``)."""
    return await _seed_whatsapp_appointment_template(
        session,
        org_id=org_id,
        name=_APPOINTMENT_REMINDER_1H_NAME,
        body=_APPOINTMENT_REMINDER_1H_BODY,
        variables=[
            "contact.full_name",
            "org.name",
            "appointment.location",
        ],
        change_note=("seeded by automation-engine Step 10 (Appointment Reminder 1h)"),
    )


async def _seed_email_invoice_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    name: str,
    subject: str,
    body: str,
    variables: list[str],
    change_note: str,
) -> MessageTemplate:
    """Shared shaper for the three Step-11 invoice email seeds.

    Mirrors :func:`seed_user_welcome_template` / :func:`seed_lead_confirmation_template`
    — email channel, transactional category, ``internal_status='published'``
    so the dispatcher can use the template without an internal review
    cycle. Idempotent on ``(org_id, lower(name), channel='email')``.
    """
    existing = (
        await session.execute(
            select(MessageTemplate).where(
                MessageTemplate.org_id == org_id,
                func.lower(MessageTemplate.name) == name.lower(),
                MessageTemplate.channel == ConversationChannel.email,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    template = MessageTemplate(
        org_id=org_id,
        channel=ConversationChannel.email,
        name=name,
        category=TemplateCategory.transactional,
        language="en",
        body_text=body,
        subject=subject,
        variables=variables,
        internal_status=TemplateInternalStatus.published,
        external_status=TemplateExternalStatus.n_a,
        current_version=1,
    )
    session.add(template)
    await session.flush()

    version = MessageTemplateVersion(
        org_id=org_id,
        template_id=template.id,
        version=1,
        body_text=template.body_text,
        subject=template.subject,
        variables=template.variables,
        change_note=change_note,
    )
    session.add(version)
    await session.flush()

    logger.info(
        "templates.seed invoice_template org=%s name=%s template=%s",
        org_id,
        name,
        template.id,
    )
    return template


async def seed_invoice_sent_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> MessageTemplate:
    """Email customers receive when their invoice is issued
    (``invoice.sent``)."""
    return await _seed_email_invoice_template(
        session,
        org_id=org_id,
        name=_INVOICE_SENT_NAME,
        subject=_INVOICE_SENT_SUBJECT,
        body=_INVOICE_SENT_BODY,
        variables=[
            "contact.full_name",
            "org.name",
            "invoice.number",
            "invoice.total_amount",
            "invoice.currency",
        ],
        change_note=("seeded by automation-engine Step 11 (Invoice Sent)"),
    )


async def seed_invoice_paid_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> MessageTemplate:
    """Receipt email customers receive once an invoice's outstanding
    balance reaches zero (``invoice.paid``)."""
    return await _seed_email_invoice_template(
        session,
        org_id=org_id,
        name=_INVOICE_PAID_NAME,
        subject=_INVOICE_PAID_SUBJECT,
        body=_INVOICE_PAID_BODY,
        variables=[
            "contact.full_name",
            "org.name",
            "invoice.number",
            "invoice.total_amount",
            "invoice.currency",
        ],
        change_note=("seeded by automation-engine Step 11 (Invoice Paid)"),
    )


async def seed_invoice_overdue_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> MessageTemplate:
    """Reminder email customers receive when an invoice has been
    open for more than 7 days (``invoice.overdue_7d``)."""
    return await _seed_email_invoice_template(
        session,
        org_id=org_id,
        name=_INVOICE_OVERDUE_NAME,
        subject=_INVOICE_OVERDUE_SUBJECT,
        body=_INVOICE_OVERDUE_BODY,
        variables=[
            "contact.full_name",
            "org.name",
            "invoice.number",
            "invoice.total_amount",
            "invoice.currency",
        ],
        change_note=("seeded by automation-engine Step 11 (Invoice Overdue 7d)"),
    )


async def seed_contact_birthday_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> MessageTemplate:
    """WhatsApp birthday wish — fires from the daily scheduler when
    a contact's ``date_of_birth`` matches today (``contact.birthday``).

    Routed through the shared WhatsApp shaper used by the
    appointment seeders so the same ``external_status=n_a`` +
    ``subject=None`` shape applies."""
    return await _seed_whatsapp_appointment_template(
        session,
        org_id=org_id,
        name=_CONTACT_BIRTHDAY_NAME,
        body=_CONTACT_BIRTHDAY_BODY,
        variables=["contact.full_name", "org.name"],
        change_note=("seeded by automation-engine Step 12 (Contact Birthday)"),
    )


async def seed_task_assigned_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> MessageTemplate:
    """Email notification — fires from the "Task Assigned" preset
    workflow when a task lands on a user (either at creation with an
    explicit assignee, on PATCH that changes assigned_to_id, or from
    bulk reassign).

    Reuses the shared email-invoice shaper because the column shape
    is identical (transactional category, subject set,
    ``external_status=n_a``)."""
    return await _seed_email_invoice_template(
        session,
        org_id=org_id,
        name=_TASK_ASSIGNED_NAME,
        subject=_TASK_ASSIGNED_SUBJECT,
        body=_TASK_ASSIGNED_BODY,
        variables=[
            "assignee.full_name",
            "task.title",
            "task.due_at",
            "task.priority",
            "task.description",
            "org.name",
        ],
        change_note="seeded by tasks-triggers track (Task Assigned)",
    )


async def seed_task_completed_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> MessageTemplate:
    """Email notification — fires from the "Task Completed" preset
    workflow when a task's status flips to ``done`` (via PATCH or
    bulk mark-done)."""
    return await _seed_email_invoice_template(
        session,
        org_id=org_id,
        name=_TASK_COMPLETED_NAME,
        subject=_TASK_COMPLETED_SUBJECT,
        body=_TASK_COMPLETED_BODY,
        variables=[
            "assignee.full_name",
            "task.title",
            "task.due_at",
            "task.priority",
            "org.name",
        ],
        change_note="seeded by tasks-triggers track (Task Completed)",
    )


async def seed_lead_stale_30d_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> MessageTemplate:
    """Email nudge — fires from the daily scheduler when a lead has
    had no activity in 30 days (``lead.stale_30d``).

    Routed through the shared email-invoice shaper because the
    column shape is identical (transactional category, subject set,
    ``external_status=n_a``)."""
    return await _seed_email_invoice_template(
        session,
        org_id=org_id,
        name=_LEAD_STALE_30D_NAME,
        subject=_LEAD_STALE_30D_SUBJECT,
        body=_LEAD_STALE_30D_BODY,
        variables=["contact.full_name", "org.name"],
        change_note=("seeded by automation-engine Step 12 (Lead Stale 30d)"),
    )


__all__ = [
    "seed_appointment_booked_template",
    "seed_appointment_reminder_1h_template",
    "seed_appointment_reminder_24h_template",
    "seed_ai_prompt_presets",
    "seed_contact_birthday_template",
    "seed_invoice_overdue_template",
    "seed_invoice_paid_template",
    "seed_invoice_sent_template",
    "seed_lead_confirmation_template",
    "seed_lead_stale_30d_template",
    "seed_task_assigned_template",
    "seed_task_completed_template",
    "seed_user_welcome_template",
]


# --- AI Assistants — instruction presets (Step 8) -------------------------

# Six preset system-prompt bodies surfaced in the Instructions tab's
# Preset dropdown. Bodies are adapted from Pabbly Chatflow's reference
# prompts (documented in the step spec) but rewritten for our voice
# and length constraints (all bodies < 2000 chars so they fit under
# the schema's ``max_length=20_000`` for ``AiAssistant.instructions``).
#
# Names are stable — the frontend key-selects on ``name`` when
# populating the dropdown. Bodies can be edited by operators; the
# seed is idempotent on ``(org_id, lower(name), channel='ai_prompt')``.

_AI_PROMPT_PRESETS: list[tuple[str, str]] = [
    (
        "AI Agent",
        "You are a helpful AI assistant. Answer the user's questions accurately "
        "and concisely using the knowledge provided to you. When you do not know "
        "the answer or the question falls outside your role, say so plainly and "
        "offer to connect them with a human. Keep responses friendly and "
        "professional, and never fabricate information.",
    ),
    (
        "Customer Support Agent",
        "You are a customer support agent for our company. Your role is to "
        "help customers with their questions about our products, services, and "
        "policies. Follow these guidelines:\n\n"
        "1. Greet the customer warmly and acknowledge their concern.\n"
        "2. Use the knowledge base to answer questions accurately.\n"
        "3. If you cannot resolve the issue, offer to escalate to a human "
        "agent.\n"
        "4. Stay on topic — you only answer questions related to our company, "
        "products, and policies.\n"
        "5. Be empathetic, patient, and solution-focused.",
    ),
    (
        "Sales Agent",
        "You are a sales agent for our company. Your role is to qualify leads, "
        "answer product questions, and guide prospects toward a purchase "
        "decision. Follow these guidelines:\n\n"
        "1. Ask discovery questions to understand the prospect's needs.\n"
        "2. Highlight product features and benefits that match those needs.\n"
        "3. Handle common objections with confidence and empathy.\n"
        "4. Never make claims about pricing, availability, or features that "
        "are not backed by your knowledge base.\n"
        "5. When a prospect is ready to buy, offer to connect them with a "
        "human sales rep to close the deal.",
    ),
    (
        "Language Tutor",
        "You are a language tutor. Your role is to help learners practice a "
        "target language through conversation, corrections, and gentle "
        "feedback. Follow these guidelines:\n\n"
        "1. Start by asking the learner's target language and skill level.\n"
        "2. Adapt vocabulary and grammar complexity to the learner's level.\n"
        "3. When the learner makes a mistake, offer a corrected version and "
        "briefly explain the rule.\n"
        "4. Praise progress and encourage the learner to try new phrases.\n"
        "5. Keep the conversation flowing — do not overwhelm with corrections.",
    ),
    (
        "Coding Expert",
        "You are a coding expert. Your role is to help developers write, "
        "debug, and understand code across popular languages. Follow these "
        "guidelines:\n\n"
        "1. Ask for the language and framework if the user does not specify.\n"
        "2. Provide clean, idiomatic code examples with brief explanations.\n"
        "3. When debugging, ask for the error message and relevant code "
        "before suggesting a fix.\n"
        "4. Warn about security or performance issues you notice in the "
        "user's code.\n"
        "5. Stay within programming topics — decline off-topic requests "
        "politely.",
    ),
    (
        "Life Coach",
        "You are a life coach. Your role is to help users clarify their "
        "goals, build motivation, and take practical next steps. Follow "
        "these guidelines:\n\n"
        "1. Ask open-ended questions to understand what the user wants to "
        "achieve.\n"
        "2. Reflect back what you hear so the user feels understood.\n"
        "3. Break big goals into small, achievable weekly actions.\n"
        "4. Encourage self-reflection and celebrate small wins.\n"
        "5. If the user mentions distress or crisis, gently suggest they "
        "speak with a qualified mental-health professional and provide the "
        "local crisis-line reference if available in your knowledge base.",
    ),
]


async def seed_ai_prompt_presets(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> list[MessageTemplate]:
    """Insert the 6 AI-prompt preset templates for ``org_id``.

    Idempotent on ``(org_id, lower(name), channel='ai_prompt')`` — a
    second call returns existing rows unchanged, so re-running from
    the ``0204_bf_ai_prompt_templates`` backfill or a repeated org-
    creation retry never duplicates.

    Caller owns the transaction; this function does not commit.

    Seeded as :data:`TemplateInternalStatus.published` so the
    Instructions tab's dropdown always sees them without an
    internal-review round-trip. Category is
    :data:`TemplateCategory.transactional` — these are internal
    system prompts, not customer-facing marketing sends.
    """
    installed: list[MessageTemplate] = []
    for name, body in _AI_PROMPT_PRESETS:
        existing = (
            await session.execute(
                select(MessageTemplate).where(
                    MessageTemplate.org_id == org_id,
                    func.lower(MessageTemplate.name) == name.lower(),
                    MessageTemplate.channel == ConversationChannel.ai_prompt,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            installed.append(existing)
            continue

        template = MessageTemplate(
            org_id=org_id,
            channel=ConversationChannel.ai_prompt,
            name=name,
            category=TemplateCategory.transactional,
            language="en",
            body_text=body,
            subject=None,
            variables=[],
            internal_status=TemplateInternalStatus.published,
            external_status=TemplateExternalStatus.n_a,
            current_version=1,
        )
        session.add(template)
        await session.flush()

        version = MessageTemplateVersion(
            org_id=org_id,
            template_id=template.id,
            version=1,
            body_text=body,
            subject=None,
            variables=[],
            change_note="seeded by ai-assistants Step 8 (AI prompt preset)",
        )
        session.add(version)
        installed.append(template)

    await session.flush()

    logger.info(
        "templates.seed ai_prompt_presets org=%s installed=%d",
        org_id,
        len(installed),
    )
    return installed
