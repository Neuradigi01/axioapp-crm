"""Email-render helpers — context builder + template renderer.

These functions used to live in ``core/email_templates/service.py``;
Step 10 of ``tasks/template-library`` moved them here so the email-
sequences scheduler + any future automation/workflow caller has a
shared dependency-light path that renders against a real contact +
optional lead.

``build_context`` loads the contact (required), optional lead,
sender, org and folds them into the nested dict the variable engine
consumes. ``render_email_template`` substitutes the subject + body
on a :class:`MessageTemplate` row using the shared strict renderer
from :mod:`core.templates.variables`.

The strict renderer (``render`` — raises ``MissingVariable``) is the
right choice here because the email-sequences scheduler treats a
missing variable as a permanent skip with a clear "render_failed"
skip-reason. The lenient ``resolve`` is reserved for automation
triggers / previews where partial payloads are normal.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.contacts import data_access as contacts_da
from src.app.core.leads.models import Lead
from src.app.core.templates.models import MessageTemplate
from src.app.core.templates.variables import MissingVariable, render
from src.app.core.tenants.models import Organization


async def build_context(
    session: AsyncSession,
    *,
    org: Organization | None,
    contact_id: uuid.UUID,
    lead_id: uuid.UUID | None = None,
    sender_user_id: uuid.UUID | None = None,
    sender_first_name: str | None = None,
    sender_last_name: str | None = None,
    sender_email: str | None = None,
    sender_signature: str | None = None,
) -> dict[str, Any]:
    """Load the contact (required), optional lead, sender, org and
    fold them into the nested dict the variable engine consumes.

    Raises HTTP 404 when ``contact_id`` doesn't resolve in the
    current org. A missing lead is not fatal — the variable engine
    surfaces ``MissingVariable`` at render time if the template
    actually references a ``lead.*`` path.
    """
    contact = await contacts_da.get_contact(session, contact_id)
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contact {contact_id} not found.",
        )

    lead: Lead | None = None
    if lead_id is not None:
        lead = (await session.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()

    full_name = (
        getattr(contact, "full_name", None)
        or " ".join(
            x
            for x in (
                getattr(contact, "first_name", None),
                getattr(contact, "last_name", None),
            )
            if x
        )
        or contact.email
        or ""
    )

    sender_full = " ".join(x for x in (sender_first_name, sender_last_name) if x) or (
        sender_email or ""
    )

    contact_dict: dict[str, Any] = {
        "id": str(contact.id),
        "first_name": getattr(contact, "first_name", None) or "",
        "last_name": getattr(contact, "last_name", None) or "",
        "full_name": full_name,
        "email": contact.email or "",
        "phone": getattr(contact, "phone", None) or "",
        "source": getattr(contact, "source", None) or "",
        "custom_data": dict(getattr(contact, "custom_data", None) or {}),
    }

    context: dict[str, Any] = {
        "contact": contact_dict,
        # `user.*` namespace — what most templates from the seeded
        # registry reference. `sender.*` kept as an alias for older
        # email templates that pre-date the user-side rename.
        "user": {
            "first_name": sender_first_name or "",
            "last_name": sender_last_name or "",
            "full_name": sender_full,
            "email": sender_email or "",
            "signature": sender_signature or "",
        },
        "sender": {
            "name": sender_full,
            "email": sender_email or "",
            "role": "",
            "signature": sender_signature or "",
        },
        "org": {
            "name": getattr(org, "name", "") if org else "",
            "support_email": getattr(org, "support_email", "") if org else "",
        },
    }
    if lead is not None:
        context["lead"] = {
            "id": str(lead.id),
            "title": getattr(lead, "title", None) or "",
            "value": getattr(lead, "value", None),
            "status": getattr(lead, "status", None) or "",
            "source": getattr(lead, "source", None) or "",
            "custom_data": dict(getattr(lead, "custom_data", None) or {}),
        }
    return context


def render_email_template(
    template: MessageTemplate,
    context: dict[str, Any],
) -> dict[str, str]:
    """Render an email template's subject + body against ``context``.

    Returns ``{subject, body_html, body_text}`` — same shape the old
    ``email_templates.render_template`` produced so the
    email-sequences scheduler (and any other caller migrated from
    that path) can swap to this helper without touching its own
    structure.

    ``body_html`` and ``body_text`` are populated from the central
    row's single ``body_text`` column — the central library stores
    one body per template (HTML or plain; treated as-is by the email
    sender). ``body_text`` is the autoescape-off plain rendering;
    ``body_html`` is the autoescape-on HTML rendering. For a pure-
    text template the two are identical except for HTML-entity
    escaping; for an HTML template the HTML side preserves operator
    markup while the text side strips it conservatively (the email
    sender uses the HTML for the multipart/alternative HTML part and
    falls back to the text side for the plain part).
    """
    subject_src = template.subject or ""
    body_src = template.body_text or ""
    try:
        subject = render(subject_src, context, autoescape=True) if subject_src else ""
        body_html = render(body_src, context, autoescape=True)
        body_text = render(body_src, context, autoescape=False)
    except MissingVariable as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Cannot render template — missing variables: "
                f"{exc.paths}. Pass a context that provides every "
                "referenced path (`lead_id` is often the culprit)."
            ),
        ) from exc
    return {
        "subject": subject,
        "body_html": body_html,
        "body_text": body_text,
    }


__all__ = ["build_context", "render_email_template"]
