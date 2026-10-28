"""Idempotent trigger seeders installed at org-creation time.

Step 5 of ``tasks/automation-engine/`` seeds a default "User
Welcome" trigger that fires on :data:`user.signed_up` and sends
the matching email template (see :mod:`core.templates.seeds`).
Step 6 will add a "Lead Confirmation" trigger that fires on
:data:`lead.created` from every source.

Seeds are inserted as **enabled** so the manager's "welcome mail
on signup" promise is live the moment Step 5 lands. Operators can
disable or edit them via the regular Settings → Automations
surface (Steps 7-9 wire the UI; the API is already live from
Step 3). Idempotent on ``(org_id, lower(name))`` — re-runs never
duplicate.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.automation import data_access
from src.app.core.automation.models import AutomationTrigger
from src.app.core.conversations.models import ConversationChannel

logger = logging.getLogger(__name__)


_USER_WELCOME_TRIGGER_NAME = "User Welcome"
_LEAD_CONFIRMATION_TRIGGER_NAME = "Lead Confirmation"
_APPOINTMENT_BOOKED_TRIGGER_NAME = "Appointment Booked"
_APPOINTMENT_REMINDER_24H_TRIGGER_NAME = "Appointment Reminder 24h"
_APPOINTMENT_REMINDER_1H_TRIGGER_NAME = "Appointment Reminder 1h"
_INVOICE_SENT_TRIGGER_NAME = "Invoice Sent"
_INVOICE_PAID_TRIGGER_NAME = "Invoice Paid"
_INVOICE_OVERDUE_TRIGGER_NAME = "Invoice Overdue 7d"
_CONTACT_BIRTHDAY_TRIGGER_NAME = "Contact Birthday"
_LEAD_STALE_30D_TRIGGER_NAME = "Lead Stale 30d"


async def seed_user_welcome_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> AutomationTrigger:
    """Insert (or return the existing) "User Welcome" automation
    trigger for ``org_id``. Caller owns the transaction.

    Idempotent: a second call returns the prior row unchanged —
    safe to re-run from backfill migrations + org-create hooks
    without producing duplicates.
    """
    existing = await data_access.get_trigger_by_name(
        session, org_id=org_id, name=_USER_WELCOME_TRIGGER_NAME
    )
    if existing is not None:
        return existing

    trigger = AutomationTrigger(
        org_id=org_id,
        name=_USER_WELCOME_TRIGGER_NAME,
        enabled=True,
        event_type="user.signed_up",
        conditions={},
        channel=ConversationChannel.email,
        template_id=template_id,
        delay_seconds=0,
        recipient_resolver="user.email",
        recipient_resolver_config={},
        created_by_user_id=None,
        updated_by_user_id=None,
    )
    session.add(trigger)
    await session.flush()
    logger.info(
        "automation.seed user_welcome org=%s trigger=%s template=%s",
        org_id,
        trigger.id,
        template_id,
    )
    return trigger


async def seed_lead_confirmation_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> AutomationTrigger:
    """Insert (or return the existing) "Lead Confirmation" automation
    trigger — fires on every ``lead.created`` event regardless of
    source, sending the seeded Lead Confirmation email template.

    The trigger carries a default condition that EXCLUDES bulk-CSV
    imports (``{"field": "source", "op": "ne", "value":
    "bulk_import"}``). Bulk imports can fan out to thousands of
    contacts; auto-firing the confirmation would surprise the
    operator + flood inboxes. The operator can remove the condition
    via the Settings → Automations editor (Step 8) after confirming
    intent.

    Idempotent on ``(org_id, lower(name))`` — re-runs never
    duplicate."""
    existing = await data_access.get_trigger_by_name(
        session, org_id=org_id, name=_LEAD_CONFIRMATION_TRIGGER_NAME
    )
    if existing is not None:
        return existing

    trigger = AutomationTrigger(
        org_id=org_id,
        name=_LEAD_CONFIRMATION_TRIGGER_NAME,
        enabled=True,
        event_type="lead.created",
        conditions={"field": "source", "op": "ne", "value": "bulk_import"},
        channel=ConversationChannel.email,
        template_id=template_id,
        delay_seconds=0,
        recipient_resolver="contact.email",
        recipient_resolver_config={},
        created_by_user_id=None,
        updated_by_user_id=None,
    )
    session.add(trigger)
    await session.flush()
    logger.info(
        "automation.seed lead_confirmation org=%s trigger=%s template=%s",
        org_id,
        trigger.id,
        template_id,
    )
    return trigger


async def _seed_appointment_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    name: str,
    event_type: str,
    template_id: uuid.UUID,
) -> AutomationTrigger:
    """Shared shaper for the three Step-10 appointment-cycle triggers.

    All three seed identically: WhatsApp channel, no conditions, no
    delay, recipient resolved off ``contact.phone``. The only
    difference between them is the trigger ``name`` + the
    ``event_type`` it subscribes to. Idempotent on
    ``(org_id, lower(name))``."""
    existing = await data_access.get_trigger_by_name(session, org_id=org_id, name=name)
    if existing is not None:
        return existing

    trigger = AutomationTrigger(
        org_id=org_id,
        name=name,
        enabled=True,
        event_type=event_type,
        conditions={},
        channel=ConversationChannel.whatsapp,
        template_id=template_id,
        delay_seconds=0,
        recipient_resolver="contact.phone",
        recipient_resolver_config={},
        created_by_user_id=None,
        updated_by_user_id=None,
    )
    session.add(trigger)
    await session.flush()
    logger.info(
        "automation.seed appointment_trigger org=%s name=%s trigger=%s template=%s",
        org_id,
        name,
        trigger.id,
        template_id,
    )
    return trigger


async def seed_appointment_booked_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> AutomationTrigger:
    """Fires when ``core.appointments.service.create_appointment``
    commits a new row + publishes ``appointment.booked``."""
    return await _seed_appointment_trigger(
        session,
        org_id=org_id,
        name=_APPOINTMENT_BOOKED_TRIGGER_NAME,
        event_type="appointment.booked",
        template_id=template_id,
    )


async def seed_appointment_reminder_24h_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> AutomationTrigger:
    """Fires when the Celery beat sweep
    (``core.appointments.tasks.scan_for_reminders``) finds an
    appointment whose ``scheduled_at`` is ~24 hours away."""
    return await _seed_appointment_trigger(
        session,
        org_id=org_id,
        name=_APPOINTMENT_REMINDER_24H_TRIGGER_NAME,
        event_type="appointment.reminder_24h",
        template_id=template_id,
    )


async def seed_appointment_reminder_1h_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> AutomationTrigger:
    """Fires when the Celery beat sweep finds an appointment whose
    ``scheduled_at`` is ~1 hour away."""
    return await _seed_appointment_trigger(
        session,
        org_id=org_id,
        name=_APPOINTMENT_REMINDER_1H_TRIGGER_NAME,
        event_type="appointment.reminder_1h",
        template_id=template_id,
    )


async def _seed_invoice_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    name: str,
    event_type: str,
    template_id: uuid.UUID,
) -> AutomationTrigger:
    """Shared shaper for the three Step-11 invoice-cycle triggers.

    All three seed identically: email channel, no conditions, no
    delay, recipient resolved off ``contact.email``. The only
    difference is the trigger ``name`` + the ``event_type`` it
    subscribes to. Idempotent on ``(org_id, lower(name))``."""
    existing = await data_access.get_trigger_by_name(session, org_id=org_id, name=name)
    if existing is not None:
        return existing

    trigger = AutomationTrigger(
        org_id=org_id,
        name=name,
        enabled=True,
        event_type=event_type,
        conditions={},
        channel=ConversationChannel.email,
        template_id=template_id,
        delay_seconds=0,
        recipient_resolver="contact.email",
        recipient_resolver_config={},
        created_by_user_id=None,
        updated_by_user_id=None,
    )
    session.add(trigger)
    await session.flush()
    logger.info(
        "automation.seed invoice_trigger org=%s name=%s trigger=%s template=%s",
        org_id,
        name,
        trigger.id,
        template_id,
    )
    return trigger


async def seed_invoice_sent_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> AutomationTrigger:
    """Fires when ``core.billing.service.issue`` commits + publishes
    ``invoice.sent``."""
    return await _seed_invoice_trigger(
        session,
        org_id=org_id,
        name=_INVOICE_SENT_TRIGGER_NAME,
        event_type="invoice.sent",
        template_id=template_id,
    )


async def seed_invoice_paid_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> AutomationTrigger:
    """Fires when ``core.billing.service.record_payment`` flips an
    invoice to ``paid`` + publishes ``invoice.paid``."""
    return await _seed_invoice_trigger(
        session,
        org_id=org_id,
        name=_INVOICE_PAID_TRIGGER_NAME,
        event_type="invoice.paid",
        template_id=template_id,
    )


async def seed_invoice_overdue_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> AutomationTrigger:
    """Fires when ``core.billing.tasks.scan_for_overdue`` finds an
    ``issued`` invoice older than 7 days + publishes
    ``invoice.overdue_7d``."""
    return await _seed_invoice_trigger(
        session,
        org_id=org_id,
        name=_INVOICE_OVERDUE_TRIGGER_NAME,
        event_type="invoice.overdue_7d",
        template_id=template_id,
    )


async def seed_contact_birthday_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> AutomationTrigger:
    """Fires when ``core.automation.scheduler.scan_birthdays`` finds
    a contact whose ``date_of_birth`` matches today + publishes
    ``contact.birthday``. WhatsApp channel + ``contact.phone``
    resolver."""
    existing = await data_access.get_trigger_by_name(
        session, org_id=org_id, name=_CONTACT_BIRTHDAY_TRIGGER_NAME
    )
    if existing is not None:
        return existing

    trigger = AutomationTrigger(
        org_id=org_id,
        name=_CONTACT_BIRTHDAY_TRIGGER_NAME,
        enabled=True,
        event_type="contact.birthday",
        conditions={},
        channel=ConversationChannel.whatsapp,
        template_id=template_id,
        delay_seconds=0,
        recipient_resolver="contact.phone",
        recipient_resolver_config={},
        created_by_user_id=None,
        updated_by_user_id=None,
    )
    session.add(trigger)
    await session.flush()
    logger.info(
        "automation.seed contact_birthday org=%s trigger=%s template=%s",
        org_id,
        trigger.id,
        template_id,
    )
    return trigger


async def seed_lead_stale_30d_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> AutomationTrigger:
    """Fires when ``core.automation.scheduler.scan_stale_leads``
    finds an active lead with no activity in 30 days + publishes
    ``lead.stale_30d``. Email channel + ``contact.email`` resolver
    (longer-form ask, salesperson signature)."""
    existing = await data_access.get_trigger_by_name(
        session, org_id=org_id, name=_LEAD_STALE_30D_TRIGGER_NAME
    )
    if existing is not None:
        return existing

    trigger = AutomationTrigger(
        org_id=org_id,
        name=_LEAD_STALE_30D_TRIGGER_NAME,
        enabled=True,
        event_type="lead.stale_30d",
        conditions={},
        channel=ConversationChannel.email,
        template_id=template_id,
        delay_seconds=0,
        recipient_resolver="contact.email",
        recipient_resolver_config={},
        created_by_user_id=None,
        updated_by_user_id=None,
    )
    session.add(trigger)
    await session.flush()
    logger.info(
        "automation.seed lead_stale_30d org=%s trigger=%s template=%s",
        org_id,
        trigger.id,
        template_id,
    )
    return trigger


async def install_default_org_seeds(session: AsyncSession, *, org_id: uuid.UUID) -> dict:
    """Single entry-point called by ``core.tenants.service.create_organization``
    + every backfill migration. Wires the v1 seeded triggers:

    * Welcome — fires on ``user.signed_up`` (Step 5).
    * Lead Confirmation — fires on ``lead.created`` (Step 6).
    * Appointment Booked — fires on ``appointment.booked`` (Step 10).
    * Appointment Reminder 24h — fires on
      ``appointment.reminder_24h`` (Step 10).
    * Appointment Reminder 1h — fires on
      ``appointment.reminder_1h`` (Step 10).
    * Invoice Sent — fires on ``invoice.sent`` (Step 11).
    * Invoice Paid — fires on ``invoice.paid`` (Step 11).
    * Invoice Overdue 7d — fires on ``invoice.overdue_7d`` (Step 11).
    * Contact Birthday — fires on ``contact.birthday`` (Step 12).
    * Lead Stale 30d — fires on ``lead.stale_30d`` (Step 12).

    Returns the seeded ids so backfill migrations can log per-org.
    All seeders are idempotent — safe to re-run."""
    from src.app.core.templates.seeds import (
        seed_appointment_booked_template,
        seed_appointment_reminder_1h_template,
        seed_appointment_reminder_24h_template,
        seed_contact_birthday_template,
        seed_invoice_overdue_template,
        seed_invoice_paid_template,
        seed_invoice_sent_template,
        seed_lead_confirmation_template,
        seed_lead_stale_30d_template,
        seed_user_welcome_template,
    )

    welcome_template = await seed_user_welcome_template(session, org_id=org_id)
    welcome_trigger = await seed_user_welcome_trigger(
        session, org_id=org_id, template_id=welcome_template.id
    )

    lead_template = await seed_lead_confirmation_template(session, org_id=org_id)
    lead_trigger = await seed_lead_confirmation_trigger(
        session, org_id=org_id, template_id=lead_template.id
    )

    booked_template = await seed_appointment_booked_template(session, org_id=org_id)
    booked_trigger = await seed_appointment_booked_trigger(
        session, org_id=org_id, template_id=booked_template.id
    )

    reminder_24h_template = await seed_appointment_reminder_24h_template(session, org_id=org_id)
    reminder_24h_trigger = await seed_appointment_reminder_24h_trigger(
        session,
        org_id=org_id,
        template_id=reminder_24h_template.id,
    )

    reminder_1h_template = await seed_appointment_reminder_1h_template(session, org_id=org_id)
    reminder_1h_trigger = await seed_appointment_reminder_1h_trigger(
        session,
        org_id=org_id,
        template_id=reminder_1h_template.id,
    )

    invoice_sent_template = await seed_invoice_sent_template(session, org_id=org_id)
    invoice_sent_trigger = await seed_invoice_sent_trigger(
        session,
        org_id=org_id,
        template_id=invoice_sent_template.id,
    )

    invoice_paid_template = await seed_invoice_paid_template(session, org_id=org_id)
    invoice_paid_trigger = await seed_invoice_paid_trigger(
        session,
        org_id=org_id,
        template_id=invoice_paid_template.id,
    )

    invoice_overdue_template = await seed_invoice_overdue_template(session, org_id=org_id)
    invoice_overdue_trigger = await seed_invoice_overdue_trigger(
        session,
        org_id=org_id,
        template_id=invoice_overdue_template.id,
    )

    birthday_template = await seed_contact_birthday_template(session, org_id=org_id)
    birthday_trigger = await seed_contact_birthday_trigger(
        session,
        org_id=org_id,
        template_id=birthday_template.id,
    )

    stale_30d_template = await seed_lead_stale_30d_template(session, org_id=org_id)
    stale_30d_trigger = await seed_lead_stale_30d_trigger(
        session,
        org_id=org_id,
        template_id=stale_30d_template.id,
    )

    return {
        "welcome_template_id": str(welcome_template.id),
        "welcome_trigger_id": str(welcome_trigger.id),
        "lead_template_id": str(lead_template.id),
        "lead_trigger_id": str(lead_trigger.id),
        "appointment_booked_template_id": str(booked_template.id),
        "appointment_booked_trigger_id": str(booked_trigger.id),
        "appointment_reminder_24h_template_id": str(reminder_24h_template.id),
        "appointment_reminder_24h_trigger_id": str(reminder_24h_trigger.id),
        "appointment_reminder_1h_template_id": str(reminder_1h_template.id),
        "appointment_reminder_1h_trigger_id": str(reminder_1h_trigger.id),
        "invoice_sent_template_id": str(invoice_sent_template.id),
        "invoice_sent_trigger_id": str(invoice_sent_trigger.id),
        "invoice_paid_template_id": str(invoice_paid_template.id),
        "invoice_paid_trigger_id": str(invoice_paid_trigger.id),
        "invoice_overdue_template_id": str(invoice_overdue_template.id),
        "invoice_overdue_trigger_id": str(invoice_overdue_trigger.id),
        "contact_birthday_template_id": str(birthday_template.id),
        "contact_birthday_trigger_id": str(birthday_trigger.id),
        "lead_stale_30d_template_id": str(stale_30d_template.id),
        "lead_stale_30d_trigger_id": str(stale_30d_trigger.id),
    }


__all__ = [
    "install_default_org_seeds",
    "seed_appointment_booked_trigger",
    "seed_appointment_reminder_1h_trigger",
    "seed_appointment_reminder_24h_trigger",
    "seed_contact_birthday_trigger",
    "seed_invoice_overdue_trigger",
    "seed_invoice_paid_trigger",
    "seed_invoice_sent_trigger",
    "seed_lead_confirmation_trigger",
    "seed_lead_stale_30d_trigger",
    "seed_user_welcome_trigger",
]
