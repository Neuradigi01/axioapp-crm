"""HTTP routes for email-templates.

  GET    /api/v1/email/templates                  → paginated list
  GET    /api/v1/email/templates/variables        → variable registry
  POST   /api/v1/email/templates                  → create
  GET    /api/v1/email/templates/{id}             → read one
  PATCH  /api/v1/email/templates/{id}             → partial update
  DELETE /api/v1/email/templates/{id}             → soft delete
  POST   /api/v1/email/templates/{id}/render      → preview render

Write paths are gated by `email.templates.manage` (Owner / Admin /
Sales Manager). Read paths are gated by `email.read` (every role —
templates are shared across the org for use in compose).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.email_templates import service as templates_service
from src.app.core.email_templates.schemas import (
    EmailTemplateCreate,
    EmailTemplateListResponse,
    EmailTemplateRead,
    EmailTemplateRenderResponse,
    EmailTemplateUpdate,
    VariableRegistryEntry,
)
from src.app.core.tenants.models import Organization
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/email/templates", tags=["Email Templates"])


# --- 1. List + variable registry --------------------------------------


@router.get("", response_model=EmailTemplateListResponse)
async def list_templates_endpoint(
    q: str | None = Query(default=None, max_length=255),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("email.read")),
) -> EmailTemplateListResponse:
    """Paginated list of live templates for the active tenant.
    Soft-deleted templates are excluded."""
    rows, total = await templates_service.list_templates(
        db, q=q, is_active=is_active, page=page, size=size
    )
    return EmailTemplateListResponse(
        items=[EmailTemplateRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.get(
    "/variables", response_model=list[VariableRegistryEntry]
)
async def variable_registry_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("email.read")),
) -> list[VariableRegistryEntry]:
    """The catalog Step 10's editor sidebar consumes — static fields
    + the org's custom_field_definitions for contacts/leads."""
    return await templates_service.variable_registry(db)


# --- 2. CRUD ----------------------------------------------------------


@router.post(
    "",
    response_model=EmailTemplateRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_template_endpoint(
    payload: EmailTemplateCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.templates.manage")),
) -> EmailTemplateRead:
    """Create a template. Variable + Jinja-statement validation runs
    before persist; on failure the 400 lists the offending paths /
    constructs so the editor surfaces them inline."""
    row = await templates_service.create_template(
        db,
        org_id=user.org_id,
        actor_id=user.legacy_uuid,
        payload=payload,
    )
    return EmailTemplateRead.model_validate(row)


@router.get("/{template_id}", response_model=EmailTemplateRead)
async def get_template_endpoint(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("email.read")),
) -> EmailTemplateRead:
    """Read one template. 404 if soft-deleted or absent."""
    row = await templates_service.get_template(
        db, template_id=template_id
    )
    return EmailTemplateRead.model_validate(row)


@router.patch("/{template_id}", response_model=EmailTemplateRead)
async def update_template_endpoint(
    template_id: uuid.UUID,
    payload: EmailTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.templates.manage")),
) -> EmailTemplateRead:
    """Partial update. Re-runs validation on subject / body changes."""
    row = await templates_service.update_template(
        db,
        template_id=template_id,
        actor_id=user.legacy_uuid,
        payload=payload,
    )
    return EmailTemplateRead.model_validate(row)


@router.delete(
    "/{template_id}",
    response_model=EmailTemplateRead,
)
async def delete_template_endpoint(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.templates.manage")),
) -> EmailTemplateRead:
    """Soft-delete. The row stays so Step 7 sequence references
    survive. Returns the deleted row (the editor uses it to flash
    a redo affordance)."""
    row = await templates_service.delete_template(
        db,
        template_id=template_id,
        actor_id=user.legacy_uuid,
    )
    return EmailTemplateRead.model_validate(row)


# --- 3. Preview render ------------------------------------------------


@router.post(
    "/{template_id}/render",
    response_model=EmailTemplateRenderResponse,
)
async def render_template_endpoint(
    template_id: uuid.UUID,
    contact_id: uuid.UUID = Query(...),
    lead_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.read")),
) -> EmailTemplateRenderResponse:
    """Preview render — substitutes the saved template against a
    real contact (+ optional lead) + the current user as sender +
    the active org. Returns the materialised subject + bodies
    without sending or persisting anything."""
    template = await templates_service.get_template(
        db, template_id=template_id
    )
    org = (
        await db.execute(
            select(Organization).where(Organization.id == user.org_id)
        )
    ).scalar_one_or_none()
    context = await templates_service.build_context(
        db,
        org=org,
        contact_id=contact_id,
        lead_id=lead_id,
        sender_user_id=user.legacy_uuid,
        sender_first_name=getattr(user, "first_name", None),
        sender_last_name=getattr(user, "last_name", None),
        sender_email=getattr(user, "email", None),
        sender_signature=None,
    )
    rendered = templates_service.render_template(template, context)
    return EmailTemplateRenderResponse(
        subject=rendered["subject"],
        body_html=rendered["body_html"],
        body_text=rendered["body_text"],
        variables_used=template.variables_used,
    )
