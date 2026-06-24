"""Service layer for `email_templates`.

Six concerns:

  1. **Save-time variable validation** — every dot-path in subject +
     body_html is validated against an allowlist (static schema +
     custom-field definitions). Unknown paths reject with 400 so the
     editor surfaces the error inline; we never persist a template
     that will fail at render time.
  2. **Jinja-statement rejection** — `{% if %}` / `{% for %}` /
     `{# ... #}` constructs are not supported (Step 6 spec). The
     pure helper in `core.email.variables.reject_jinja_statements`
     does the check; this service calls it.
  3. **body_text derivation** — when the caller doesn't provide
     `body_text`, we extract a plain-text version from `body_html`
     via a tiny stdlib `HTMLParser` subclass. No new dependency.
  4. **Context building** — `build_context(contact_id, lead_id,
     sender_user_id, org)` loads each referenced row and produces
     the nested dict the variable engine consumes.
  5. **Rendering** — `render(template, context)` substitutes the
     saved subject + bodies. HTML body uses autoescape; plain-text
     body skips escape so `&amp;` doesn't slip in.
  6. **Standard CRUD** — list (paginated + name search), create,
     get, update, soft-delete. All scoped via the existing
     TenantScoped ORM filter.

Audit events are emitted on create / update / delete via
`core.audit.log`.

`variable_registry(...)` returns the allowed-path catalog Step 10's
editor sidebar consumes — static fields + the org's custom-field
keys.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.contacts import data_access
from src.app.core.contacts.models import Contact
from src.app.core.custom_fields.models import CustomFieldDefinition
from src.app.core.email.variables import (
    MissingVariable,
    TemplateSyntaxError,
    extract_variable_paths,
    reject_jinja_statements,
    render as render_text,
)
from src.app.core.email_templates.models import EmailTemplate
from src.app.core.email_templates.schemas import (
    EmailTemplateCreate,
    EmailTemplateUpdate,
    VariableRegistryEntry,
)
from src.app.core.leads.models import Lead
from src.app.core.tenants.models import Organization


# Static allowed paths — entity standard fields. `contact.custom_data.<key>`
# and `lead.custom_data.<key>` get appended dynamically per-org from
# `custom_field_definitions`.
_STATIC_PATHS: dict[str, str] = {
    # contact
    "contact.id": "Contact ID",
    "contact.first_name": "Contact first name",
    "contact.last_name": "Contact last name",
    "contact.full_name": "Contact full name",
    "contact.email": "Contact email",
    "contact.phone": "Contact phone",
    "contact.source": "Contact source",
    # lead
    "lead.id": "Lead ID",
    "lead.title": "Lead title",
    "lead.value": "Lead value",
    "lead.status": "Lead status",
    "lead.source": "Lead source",
    # user (sender)
    "user.first_name": "Your first name",
    "user.last_name": "Your last name",
    "user.full_name": "Your full name",
    "user.email": "Your email address",
    "user.signature": "Your signature",
    # org
    "org.name": "Workspace name",
    "org.support_email": "Workspace support email",
}

_STATIC_CATEGORY: dict[str, str] = {
    "contact": "Contact",
    "lead": "Lead",
    "user": "Sender",
    "org": "Workspace",
}


# --- HTML → plain-text extractor -------------------------------------


class _HtmlToText(HTMLParser):
    """Tiny stdlib-only HTML-to-plain-text extractor.

    Preserves line breaks (`<br>`, `<p>`, `<div>`, headings, lists),
    flattens emphasis, and inlines link URLs (`<a href="X">Y</a>` →
    `Y (X)`) so the plain-text body remains useful when an email
    client falls back to it.

    Not a full implementation — we don't render tables or block-
    quote nesting. The HTML body is the canonical form; the plain
    text is a graceful fallback.
    """

    _BLOCK_TAGS = {
        "p", "div", "section", "article", "li", "tr",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "blockquote", "pre",
    }
    _NEWLINE_TAGS = {"br"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._href_stack: list[Optional[str]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, Optional[str]]]
    ) -> None:
        if tag in self._NEWLINE_TAGS:
            self._out.append("\n")
        elif tag == "a":
            href = next(
                (v for (k, v) in attrs if k.lower() == "href"), None
            )
            self._href_stack.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href_stack:
            href = self._href_stack.pop()
            if href:
                self._out.append(f" ({href})")
        elif tag in self._BLOCK_TAGS:
            self._out.append("\n")

    def handle_data(self, data: str) -> None:
        self._out.append(data)

    def result(self) -> str:
        text = "".join(self._out)
        # Collapse 3+ consecutive blank lines, strip leading/trailing.
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_text(body_html: str) -> str:
    """Public: derive a plain-text body from HTML. Empty input → empty."""
    if not body_html:
        return ""
    parser = _HtmlToText()
    parser.feed(body_html)
    parser.close()
    return parser.result()


# --- Variable validation --------------------------------------------


def _wildcards_from_paths(paths: list[str]) -> set[str]:
    """Pull bare entity prefixes out of paths so callers can check
    "does this template reference a lead at all?" cheaply."""
    return {p.split(".", 1)[0] for p in paths if "." in p}


async def _allowed_paths_for_org(
    session: AsyncSession, org_id: uuid.UUID
) -> set[str]:
    """All dot-paths an org may reference: static schema +
    custom_field_definitions for `contact` and `lead`."""
    allowed: set[str] = set(_STATIC_PATHS.keys())
    rows = (
        await session.execute(
            select(
                CustomFieldDefinition.entity_type,
                CustomFieldDefinition.field_key,
            ).where(
                CustomFieldDefinition.entity_type.in_(("contact", "lead"))
            )
        )
    ).all()
    for entity_type, field_key in rows:
        allowed.add(f"{entity_type}.custom_data.{field_key}")
    return allowed


async def validate_template_text(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    subject: str,
    body_html: str,
) -> list[str]:
    """Save-time validation. Raises `HTTPException(400)` on:
      - Jinja statements / comments present.
      - Variable paths outside the allowlist.

    Returns the sorted unique list of variable paths used — caller
    stores it on the row's `variables_used` column.
    """
    try:
        reject_jinja_statements(subject)
        reject_jinja_statements(body_html)
    except TemplateSyntaxError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    used = sorted(
        set(extract_variable_paths(subject))
        | set(extract_variable_paths(body_html))
    )
    if not used:
        return []
    allowed = await _allowed_paths_for_org(session, org_id)
    unknown = sorted(p for p in used if p not in allowed)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Unknown template variables: "
                f"{unknown}. Allowed: static fields + your org's "
                "custom_field_definitions for contacts and leads."
            ),
        )
    return used


# --- Variable registry endpoint helper ------------------------------


async def variable_registry(
    session: AsyncSession,
) -> list[VariableRegistryEntry]:
    """Return the catalog Step 10's editor sidebar consumes."""
    entries: list[VariableRegistryEntry] = []
    for path, label in _STATIC_PATHS.items():
        category_key = path.split(".", 1)[0]
        entries.append(
            VariableRegistryEntry(
                path=path,
                label=label,
                category=_STATIC_CATEGORY.get(category_key, "Other"),
                source="system",
            )
        )
    rows = (
        await session.execute(
            select(
                CustomFieldDefinition.entity_type,
                CustomFieldDefinition.field_key,
                CustomFieldDefinition.field_label,
            ).where(
                CustomFieldDefinition.entity_type.in_(("contact", "lead"))
            )
        )
    ).all()
    for entity_type, field_key, field_label in rows:
        entries.append(
            VariableRegistryEntry(
                path=f"{entity_type}.custom_data.{field_key}",
                label=f"{_STATIC_CATEGORY.get(entity_type, entity_type)} "
                f"custom — {field_label or field_key}",
                category=_STATIC_CATEGORY.get(entity_type, entity_type),
                source="custom",
            )
        )
    entries.sort(key=lambda e: (e.category, e.path))
    return entries


# --- Context building --------------------------------------------------


async def build_context(
    session: AsyncSession,
    *,
    org: Optional[Organization],
    contact_id: uuid.UUID,
    lead_id: Optional[uuid.UUID] = None,
    sender_user_id: Optional[uuid.UUID] = None,
    sender_first_name: Optional[str] = None,
    sender_last_name: Optional[str] = None,
    sender_email: Optional[str] = None,
    sender_signature: Optional[str] = None,
) -> dict[str, Any]:
    """Load the contact (required), optional lead, sender, org and
    fold them into the nested dict the variable engine consumes."""
    contact = await data_access.get_contact(session, contact_id)
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contact {contact_id} not found.",
        )

    lead: Optional[Lead] = None
    if lead_id is not None:
        lead = (
            await session.execute(
                select(Lead).where(Lead.id == lead_id)
            )
        ).scalar_one_or_none()
        # A missing lead is not fatal — Step 10's preview can render
        # a template that doesn't reference a lead even with a stale
        # lead_id. The variable engine catches the lead-needed case
        # via `MissingVariable` when the template does require one.

    full_name = (
        getattr(contact, "full_name", None)
        or " ".join(
            x for x in (
                getattr(contact, "first_name", None),
                getattr(contact, "last_name", None),
            )
            if x
        )
        or contact.email
        or ""
    )

    sender_full = " ".join(
        x for x in (sender_first_name, sender_last_name) if x
    ) or (sender_email or "")

    contact_dict = {
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
        "user": {
            "first_name": sender_first_name or "",
            "last_name": sender_last_name or "",
            "full_name": sender_full,
            "email": sender_email or "",
            "signature": sender_signature or "",
        },
        "org": {
            "name": getattr(org, "name", "") if org else "",
            "support_email": getattr(org, "support_email", "")
            if org
            else "",
        },
    }
    if lead is not None:
        context["lead"] = {
            "id": str(lead.id),
            "title": getattr(lead, "title", None) or "",
            "value": getattr(lead, "value", None),
            "status": getattr(lead, "status", None) or "",
            "source": getattr(lead, "source", None) or "",
            "custom_data": dict(
                getattr(lead, "custom_data", None) or {}
            ),
        }
    return context


# --- Rendering --------------------------------------------------------


def render_template(
    template: EmailTemplate,
    context: dict[str, Any],
) -> dict[str, str]:
    """Substitute the saved subject + bodies against `context`.

    `subject` + `body_html` go through autoescape so user-typed
    content can't sneak script tags into the rendered HTML.
    `body_text` skips autoescape — encoded entities would degrade
    the plain-text fallback.

    Raises `HTTPException(400, ...)` listing every missing path
    when `context` doesn't carry every variable the template
    references.
    """
    try:
        subject = render_text(template.subject, context, autoescape=True)
        body_html = render_text(
            template.body_html, context, autoescape=True
        )
        body_text = render_text(
            template.body_text, context, autoescape=False
        )
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


# --- CRUD --------------------------------------------------------------


async def list_templates(
    session: AsyncSession,
    *,
    q: Optional[str] = None,
    is_active: Optional[bool] = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[EmailTemplate], int]:
    """Paginated list, soft-deleted rows excluded. `q` ILIKEs on name."""
    filters: list[Any] = [EmailTemplate.deleted_at.is_(None)]
    if is_active is not None:
        filters.append(EmailTemplate.is_active.is_(is_active))
    if q:
        filters.append(EmailTemplate.name.ilike(f"%{q}%"))

    count_stmt = select(func.count()).select_from(EmailTemplate).where(
        *filters
    )
    total = (await session.execute(count_stmt)).scalar_one()

    base = (
        select(EmailTemplate)
        .where(*filters)
        .order_by(EmailTemplate.updated_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    rows = (await session.execute(base)).scalars().all()
    return list(rows), int(total or 0)


async def get_template(
    session: AsyncSession, *, template_id: uuid.UUID
) -> EmailTemplate:
    """Load a single template (RLS-scoped). 404 when missing or
    soft-deleted."""
    row = (
        await session.execute(
            select(EmailTemplate).where(EmailTemplate.id == template_id)
        )
    ).scalar_one_or_none()
    if row is None or row.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Email template {template_id} not found.",
        )
    return row


async def create_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    payload: EmailTemplateCreate,
) -> EmailTemplate:
    """Validate variables + Jinja-statement absence, derive body_text
    when missing, persist. Audit-emits `email.template.created`."""
    variables_used = await validate_template_text(
        session,
        org_id=org_id,
        subject=payload.subject,
        body_html=payload.body_html,
    )
    body_text = payload.body_text or html_to_text(payload.body_html)
    row = EmailTemplate(
        org_id=org_id,
        name=payload.name,
        subject=payload.subject,
        body_html=payload.body_html,
        body_text=body_text,
        variables_used=variables_used,
        is_active=payload.is_active,
        created_by=actor_id,
    )
    session.add(row)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A template named {payload.name!r} already exists "
                "in this workspace."
            ),
        )
    await session.refresh(row)
    await audit.log(
        "email.template.created",
        entity_type="email_template",
        entity_id=row.id,
        after={
            "name": row.name,
            "variables_used": row.variables_used,
        },
        user_id=actor_id,
    )
    return row


async def update_template(
    session: AsyncSession,
    *,
    template_id: uuid.UUID,
    actor_id: uuid.UUID,
    payload: EmailTemplateUpdate,
) -> EmailTemplate:
    """Partial update. Re-runs variable validation when subject or
    body_html changes. Audit-emits `email.template.updated`."""
    row = await get_template(session, template_id=template_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return row

    if "subject" in changes or "body_html" in changes:
        next_subject = changes.get("subject", row.subject)
        next_body_html = changes.get("body_html", row.body_html)
        row.variables_used = await validate_template_text(
            session,
            org_id=row.org_id,
            subject=next_subject,
            body_html=next_body_html,
        )

    # Derive body_text if html changed and the caller didn't pass one.
    if (
        "body_html" in changes
        and "body_text" not in changes
        and not (row.body_text or "").strip()
    ):
        changes["body_text"] = html_to_text(changes["body_html"])

    for field, value in changes.items():
        setattr(row, field, value)

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A template named {row.name!r} already exists "
                "in this workspace."
            ),
        )
    await session.refresh(row)
    await audit.log(
        "email.template.updated",
        entity_type="email_template",
        entity_id=row.id,
        after=changes,
        user_id=actor_id,
    )
    return row


async def delete_template(
    session: AsyncSession,
    *,
    template_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> EmailTemplate:
    """Soft delete. The row stays so Step 7 sequences that reference
    it survive. Audit-emits `email.template.deleted`."""
    row = await get_template(session, template_id=template_id)
    row.deleted_at = datetime.now(timezone.utc)
    row.is_active = False
    await session.commit()
    await session.refresh(row)
    await audit.log(
        "email.template.deleted",
        entity_type="email_template",
        entity_id=row.id,
        after={"name": row.name},
        user_id=actor_id,
    )
    return row


__all__ = [
    "build_context",
    "create_template",
    "delete_template",
    "get_template",
    "html_to_text",
    "list_templates",
    "render_template",
    "update_template",
    "validate_template_text",
    "variable_registry",
]
