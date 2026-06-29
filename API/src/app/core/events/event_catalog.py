"""Shared event-type catalog — the contract between publishers
(Module B + every domain module that emits) and subscribers
(Module B's automation dispatcher + Module C's workflow trigger
handlers).

This module ships ONLY string constants + descriptions. It does
NOT hold sample payloads or per-event registry shapes — the
automation-engine track keeps its own
:mod:`core.automation.event_catalog` for those (the editor's
trigger-event picker reads it for sample-payload hints). This
shared catalog covers the question "what event-type strings does
the platform recognise?" — used by:

  * The workflows graph validator (Step 2 of ``tasks/workflows``)
    so a trigger node config can reject a typo'd event_type.
  * The workflow trigger-handler registration loop (Step 5 of
    ``tasks/workflows``) which subscribes the universal
    ``_on_event`` to each catalog entry.
  * The Step 14/15 trigger-event picker drawer (frontend) reading
    the descriptions via ``GET /api/v1/workflows/event-catalog``.

Adding a new event type:

  1. Add a string constant below (top-level so other modules can
     import by name).
  2. Add a one-line entry to :data:`EVENT_DESCRIPTIONS` — surfaced
     by the editor's trigger picker.
  3. Publish via :func:`core.events.bus.publish` from the
     originating module.
"""
from __future__ import annotations


# --- Auth + onboarding ----------------------------------------------------

USER_SIGNED_UP = "user.signed_up"
USER_INVITED = "user.invited"
USER_INVITATION_ACCEPTED = "user.invitation_accepted"
USER_FIRST_LOGIN = "user.first_login"
USER_ROLE_CHANGED = "user.role_changed"


# --- Leads + contacts -----------------------------------------------------

LEAD_CREATED = "lead.created"
LEAD_STATUS_CHANGED = "lead.status_changed"
LEAD_SCORE_THRESHOLD = "lead.score_threshold"
LEAD_ASSIGNED = "lead.assigned"
LEAD_CONVERTED = "lead.converted"
LEAD_STALE_7D = "lead.stale_7d"
LEAD_STALE_30D = "lead.stale_30d"
LEAD_STALE_90D = "lead.stale_90d"

CONTACT_CREATED = "contact.created"
CONTACT_BIRTHDAY = "contact.birthday"
CONTACT_ANNIVERSARY = "contact.anniversary"
CONTACT_OPT_IN_CHANGED = "contact.opt_in_changed"


# --- Sales ---------------------------------------------------------------

QUOTE_SENT = "quote.sent"
QUOTE_VIEWED = "quote.viewed"
QUOTE_ACCEPTED = "quote.accepted"
QUOTE_REJECTED = "quote.rejected"
QUOTE_EXPIRED = "quote.expired"

INVOICE_SENT = "invoice.sent"
INVOICE_PAID = "invoice.paid"
INVOICE_OVERDUE_7D = "invoice.overdue_7d"
INVOICE_OVERDUE_14D = "invoice.overdue_14d"
INVOICE_OVERDUE_30D = "invoice.overdue_30d"

ORDER_PLACED = "order.placed"
ORDER_DELIVERED = "order.delivered"
ORDER_REFUNDED = "order.refunded"


# --- Communications ------------------------------------------------------

EMAIL_OPENED = "email.opened"
EMAIL_CLICKED = "email.clicked"
EMAIL_REPLIED = "email.replied"

WHATSAPP_MESSAGE_RECEIVED = "whatsapp.message_received"
WHATSAPP_TEMPLATE_REPLIED = "whatsapp.template_replied"


# --- Activities ----------------------------------------------------------

PHONE_CALL_LOGGED = "phone_call.logged"
MEETING_BOOKED = "meeting.booked"
TASK_CREATED = "task.created"
TASK_ASSIGNED = "task.assigned"
TASK_COMPLETED = "task.completed"
TASK_OVERDUE = "task.overdue"
NOTE_ADDED = "note.added"


# --- Appointments + walk-ins ---------------------------------------------

APPOINTMENT_BOOKED = "appointment.booked"
APPOINTMENT_REMINDER_24H = "appointment.reminder_24h"
APPOINTMENT_REMINDER_1H = "appointment.reminder_1h"
APPOINTMENT_COMPLETED = "appointment.completed"
APPOINTMENT_MISSED = "appointment.missed"

WALK_IN_REGISTERED = "walk_in.registered"


# --- Forms ---------------------------------------------------------------

FORM_SUBMITTED = "form.submitted"
FORM_ABANDONED = "form.abandoned"


# --- Campaigns + sequences -----------------------------------------------

CAMPAIGN_SENT = "campaign.sent"
CAMPAIGN_COMPLETED = "campaign.completed"
SEQUENCE_COMPLETED = "sequence.completed"


# --- Time-based ----------------------------------------------------------

TIME_DAILY_TICK = "time.daily_tick"


# --- Canonical ordered list + helper -------------------------------------


#: Every event-type string this catalog declares. Ordered for the
#: editor's picker (groups roughly by domain, the catalog reads
#: top-to-bottom).
ALL_EVENTS: tuple[str, ...] = (
    # Auth + onboarding
    USER_SIGNED_UP,
    USER_INVITED,
    USER_INVITATION_ACCEPTED,
    USER_FIRST_LOGIN,
    USER_ROLE_CHANGED,
    # Leads + contacts
    LEAD_CREATED,
    LEAD_STATUS_CHANGED,
    LEAD_SCORE_THRESHOLD,
    LEAD_ASSIGNED,
    LEAD_CONVERTED,
    LEAD_STALE_7D,
    LEAD_STALE_30D,
    LEAD_STALE_90D,
    CONTACT_CREATED,
    CONTACT_BIRTHDAY,
    CONTACT_ANNIVERSARY,
    CONTACT_OPT_IN_CHANGED,
    # Sales
    QUOTE_SENT,
    QUOTE_VIEWED,
    QUOTE_ACCEPTED,
    QUOTE_REJECTED,
    QUOTE_EXPIRED,
    INVOICE_SENT,
    INVOICE_PAID,
    INVOICE_OVERDUE_7D,
    INVOICE_OVERDUE_14D,
    INVOICE_OVERDUE_30D,
    ORDER_PLACED,
    ORDER_DELIVERED,
    ORDER_REFUNDED,
    # Communications
    EMAIL_OPENED,
    EMAIL_CLICKED,
    EMAIL_REPLIED,
    WHATSAPP_MESSAGE_RECEIVED,
    WHATSAPP_TEMPLATE_REPLIED,
    # Activities
    PHONE_CALL_LOGGED,
    MEETING_BOOKED,
    TASK_CREATED,
    TASK_ASSIGNED,
    TASK_COMPLETED,
    TASK_OVERDUE,
    NOTE_ADDED,
    # Appointments + walk-ins
    APPOINTMENT_BOOKED,
    APPOINTMENT_REMINDER_24H,
    APPOINTMENT_REMINDER_1H,
    APPOINTMENT_COMPLETED,
    APPOINTMENT_MISSED,
    WALK_IN_REGISTERED,
    # Forms
    FORM_SUBMITTED,
    FORM_ABANDONED,
    # Campaigns + sequences
    CAMPAIGN_SENT,
    CAMPAIGN_COMPLETED,
    SEQUENCE_COMPLETED,
    # Time-based
    TIME_DAILY_TICK,
)


#: Map of event_type → one-line description rendered in the
#: trigger-event picker drawer (Steps 14-15).
EVENT_DESCRIPTIONS: dict[str, str] = {
    USER_SIGNED_UP: "A new Owner finishes self-signup.",
    USER_INVITED: "An operator invites a new team member.",
    USER_INVITATION_ACCEPTED: "An invited user finishes signup.",
    USER_FIRST_LOGIN: "First successful login after signup.",
    USER_ROLE_CHANGED: "Membership role changes (Owner-only operation).",
    LEAD_CREATED: (
        "A new lead lands from ANY source — manual / API, embed widget, "
        "Google Ads, Meta Ads, CSV import."
    ),
    LEAD_STATUS_CHANGED: "Lead transitions between pipeline stages.",
    LEAD_SCORE_THRESHOLD: "Lead score crosses a configured threshold.",
    LEAD_ASSIGNED: "Lead owner assignment changes.",
    LEAD_CONVERTED: "Lead promoted to a confirmed contact.",
    LEAD_STALE_7D: "Lead has had no activity in 7 days.",
    LEAD_STALE_30D: "Lead has had no activity in 30 days.",
    LEAD_STALE_90D: "Lead has had no activity in 90 days.",
    CONTACT_CREATED: "A new contact is added to the CRM.",
    CONTACT_BIRTHDAY: "Daily sweep finds a contact whose birthday is today.",
    CONTACT_ANNIVERSARY: "Anniversary of contact becoming a customer.",
    CONTACT_OPT_IN_CHANGED: "Contact's marketing opt-in state changes.",
    QUOTE_SENT: "Quote dispatched to a contact.",
    QUOTE_VIEWED: "Customer opens the quote via the public link.",
    QUOTE_ACCEPTED: "Quote accepted (signature or portal action).",
    QUOTE_REJECTED: "Quote explicitly rejected.",
    QUOTE_EXPIRED: "Quote validity window lapsed without action.",
    INVOICE_SENT: "Invoice issued + sent to a contact.",
    INVOICE_PAID: "Invoice paid in full.",
    INVOICE_OVERDUE_7D: "Daily sweep finds an unpaid invoice 7 days overdue.",
    INVOICE_OVERDUE_14D: "Daily sweep finds an unpaid invoice 14 days overdue.",
    INVOICE_OVERDUE_30D: "Daily sweep finds an unpaid invoice 30 days overdue.",
    ORDER_PLACED: "Order checkout completed.",
    ORDER_DELIVERED: "Order delivery confirmed.",
    ORDER_REFUNDED: "Order refunded (full or partial).",
    EMAIL_OPENED: "Tracking pixel hit on a sent automation email.",
    EMAIL_CLICKED: "Recipient clicked a tracked link in the email.",
    EMAIL_REPLIED: "Recipient replied to the conversation thread.",
    WHATSAPP_MESSAGE_RECEIVED: "Inbound WhatsApp message from a contact.",
    WHATSAPP_TEMPLATE_REPLIED: "Contact replied to a template-initiated WA conversation.",
    PHONE_CALL_LOGGED: "Phone-call activity recorded against a contact.",
    MEETING_BOOKED: "Meeting added to a contact's timeline.",
    TASK_CREATED: "A task is created.",
    TASK_ASSIGNED: "A task is assigned (or re-assigned) to a user.",
    TASK_COMPLETED: "A task is marked complete.",
    TASK_OVERDUE: "Daily sweep finds a task past its due date.",
    NOTE_ADDED: "A free-text note is added to a contact.",
    APPOINTMENT_BOOKED: "A new appointment is scheduled.",
    APPOINTMENT_REMINDER_24H: "24 hours before scheduled appointment time.",
    APPOINTMENT_REMINDER_1H: "1 hour before scheduled appointment time.",
    APPOINTMENT_COMPLETED: "Appointment marked completed.",
    APPOINTMENT_MISSED: "Appointment marked no-show.",
    WALK_IN_REGISTERED: "A walk-in visitor is logged at reception.",
    FORM_SUBMITTED: "An embedded form submission lands.",
    FORM_ABANDONED: (
        "Form session abandoned (partial fill, timeout). Per-form variants "
        "fire as separate event_types."
    ),
    CAMPAIGN_SENT: "A campaign blast finished sending.",
    CAMPAIGN_COMPLETED: "A campaign run completes (all chunks dispatched).",
    SEQUENCE_COMPLETED: "An email sequence enrolment reaches the final step.",
    TIME_DAILY_TICK: "Org-local midnight tick — daily-cadence workflows hook here.",
}


def is_known_event(event_type: str) -> bool:
    """Pin-test + validator helper. Returns True iff ``event_type``
    is declared in the catalog. The workflows graph validator uses
    this to refuse trigger nodes carrying typo'd event types."""
    return event_type in EVENT_DESCRIPTIONS


def list_descriptions() -> list[dict[str, str]]:
    """Stable-ordered list for the editor's trigger-event picker —
    matches the order of :data:`ALL_EVENTS` so domain groupings
    surface together."""
    return [
        {"event_type": ev, "description": EVENT_DESCRIPTIONS[ev]}
        for ev in ALL_EVENTS
    ]


__all__ = [
    "ALL_EVENTS",
    "APPOINTMENT_BOOKED",
    "APPOINTMENT_COMPLETED",
    "APPOINTMENT_MISSED",
    "APPOINTMENT_REMINDER_1H",
    "APPOINTMENT_REMINDER_24H",
    "CAMPAIGN_COMPLETED",
    "CAMPAIGN_SENT",
    "CONTACT_ANNIVERSARY",
    "CONTACT_BIRTHDAY",
    "CONTACT_CREATED",
    "CONTACT_OPT_IN_CHANGED",
    "EMAIL_CLICKED",
    "EMAIL_OPENED",
    "EMAIL_REPLIED",
    "EVENT_DESCRIPTIONS",
    "FORM_ABANDONED",
    "FORM_SUBMITTED",
    "INVOICE_OVERDUE_14D",
    "INVOICE_OVERDUE_30D",
    "INVOICE_OVERDUE_7D",
    "INVOICE_PAID",
    "INVOICE_SENT",
    "LEAD_ASSIGNED",
    "LEAD_CONVERTED",
    "LEAD_CREATED",
    "LEAD_SCORE_THRESHOLD",
    "LEAD_STALE_30D",
    "LEAD_STALE_7D",
    "LEAD_STALE_90D",
    "LEAD_STATUS_CHANGED",
    "MEETING_BOOKED",
    "NOTE_ADDED",
    "ORDER_DELIVERED",
    "ORDER_PLACED",
    "ORDER_REFUNDED",
    "PHONE_CALL_LOGGED",
    "QUOTE_ACCEPTED",
    "QUOTE_EXPIRED",
    "QUOTE_REJECTED",
    "QUOTE_SENT",
    "QUOTE_VIEWED",
    "SEQUENCE_COMPLETED",
    "TASK_ASSIGNED",
    "TASK_COMPLETED",
    "TASK_CREATED",
    "TASK_OVERDUE",
    "TIME_DAILY_TICK",
    "USER_FIRST_LOGIN",
    "USER_INVITATION_ACCEPTED",
    "USER_INVITED",
    "USER_ROLE_CHANGED",
    "USER_SIGNED_UP",
    "WALK_IN_REGISTERED",
    "WHATSAPP_MESSAGE_RECEIVED",
    "WHATSAPP_TEMPLATE_REPLIED",
    "is_known_event",
    "list_descriptions",
]
