"""HTTP routes for the central template library.

Nine endpoints, all mounted under ``/api/v1/templates``:

  GET    /api/v1/templates                          — paginated list
  POST   /api/v1/templates                          — create draft
  GET    /api/v1/templates/{id}                     — read
  PATCH  /api/v1/templates/{id}                     — edit draft (new version)
  DELETE /api/v1/templates/{id}                     — soft-archive
  GET    /api/v1/templates/{id}/versions            — version list
  GET    /api/v1/templates/{id}/versions/{version}  — read a past version
  POST   /api/v1/templates/{id}/preview             — render with sample context
  GET    /api/v1/templates/variables/{channel}      — variable picker registry

Reads are gated on :data:`PERM_READ`; mutations (create / patch /
archive) on :data:`PERM_WRITE`. Review / publish / external-submit
endpoints come online in Steps 4 + 9; they belong to the same module
but aren't wired here so the router stays under the Rule-8 size limit.

The variable-picker endpoint is the editor's source of truth (Step
7's UI loads it once per editor open). The list is static per
channel, so the response is small + cacheable.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates import service as templates_service
from src.app.core.templates.exceptions import (
    DuplicateTemplateName,
    TemplateLocked,
    TemplateNotFound,
)
from src.app.core.templates.models import (
    TemplateExternalStatus,
    TemplateInternalStatus,
)
from src.app.core.templates.permissions import PERM_READ, PERM_WRITE
from src.app.core.templates.schemas import (
    TemplateCreate,
    TemplateRead,
    TemplateReviewRead,
    TemplateUpdate,
    TemplateVersionRead,
)
from src.app.core.templates.variables import (
    VariableDef,
    resolve,
    variables_for_channel,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/templates", tags=["Templates"])


# --- response wrappers -------------------------------------------------


class TemplateListResponse(BaseModel):
    """Paginated list response."""

    items: list[TemplateRead]
    total: int
    limit: int
    offset: int


class PreviewRequest(BaseModel):
    """Body for ``POST /templates/{id}/preview``.

    ``context`` is a nested dict matching the variable namespace shape
    (``{"contact": {"first_name": "Asha"}, "org": {"name": "Acme"}}``).
    Missing paths render as empty string per :func:`resolve` semantics
    — preview never raises on missing data, so the operator sees what
    the customer would see when the template runs against a partial
    payload.
    """

    model_config = ConfigDict(extra="forbid")

    context: dict[str, Any] = Field(default_factory=dict)


class PreviewResponse(BaseModel):
    """Rendered preview returned by ``POST /templates/{id}/preview``."""

    subject: Optional[str] = None
    body: str


class VariableDefOut(BaseModel):
    """Wire shape for one row in the variable picker."""

    key: str
    label: str
    type: str
    required: bool
    default: Optional[str] = None


# --- helpers -----------------------------------------------------------


def _to_variable_out(defn: VariableDef) -> VariableDefOut:
    return VariableDefOut(
        key=defn.key,
        label=defn.label,
        type=defn.type.value,
        required=defn.required,
        default=defn.default,
    )


# --- endpoints ---------------------------------------------------------


@router.get("", response_model=TemplateListResponse)
async def list_endpoint(
    channel: Optional[ConversationChannel] = Query(default=None),
    internal_status: Optional[TemplateInternalStatus] = Query(default=None),
    external_status: Optional[TemplateExternalStatus] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_READ)),
) -> TemplateListResponse:
    rows, total = await templates_service.list_templates(
        db,
        org_id=user.org_id,
        channel=channel,
        internal_status=internal_status,
        external_status=external_status,
        q=q,
        limit=limit,
        offset=offset,
    )
    return TemplateListResponse(
        items=[TemplateRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=TemplateRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_endpoint(
    payload: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> TemplateRead:
    try:
        template = await templates_service.create_template(
            db,
            org_id=user.org_id,
            user_id=user.legacy_uuid,
            payload=payload,
        )
    except DuplicateTemplateName as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return TemplateRead.model_validate(template)


@router.get("/variables/{channel}", response_model=list[VariableDefOut])
async def variables_endpoint(
    channel: ConversationChannel,
    _user: User = Depends(require_permissions(PERM_READ)),
) -> list[VariableDefOut]:
    """Variable picker registry for the chosen channel. Static — the
    editor (Step 7) calls this once per open. No DB hit."""
    return [_to_variable_out(v) for v in variables_for_channel(channel)]


@router.get("/{template_id}", response_model=TemplateRead)
async def get_endpoint(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_READ)),
) -> TemplateRead:
    try:
        template = await templates_service.get_template(
            db, org_id=user.org_id, template_id=template_id
        )
    except TemplateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="template not found",
        ) from exc
    return TemplateRead.model_validate(template)


@router.patch("/{template_id}", response_model=TemplateRead)
async def update_endpoint(
    template_id: uuid.UUID,
    payload: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> TemplateRead:
    try:
        template = await templates_service.update_template(
            db,
            org_id=user.org_id,
            template_id=template_id,
            user_id=user.legacy_uuid,
            payload=payload,
        )
    except TemplateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="template not found",
        ) from exc
    except TemplateLocked as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        # Channel-coherence errors (subject on a non-email template).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return TemplateRead.model_validate(template)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_endpoint(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> Response:
    try:
        await templates_service.archive_template(
            db,
            org_id=user.org_id,
            template_id=template_id,
            user_id=user.legacy_uuid,
        )
    except TemplateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="template not found",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{template_id}/versions",
    response_model=list[TemplateVersionRead],
)
async def list_versions_endpoint(
    template_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_READ)),
) -> list[TemplateVersionRead]:
    try:
        rows = await templates_service.list_versions(
            db,
            org_id=user.org_id,
            template_id=template_id,
            limit=limit,
            offset=offset,
        )
    except TemplateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="template not found",
        ) from exc
    return [TemplateVersionRead.model_validate(r) for r in rows]


@router.get(
    "/{template_id}/versions/{version}",
    response_model=TemplateVersionRead,
)
async def get_version_endpoint(
    template_id: uuid.UUID,
    version: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_READ)),
) -> TemplateVersionRead:
    try:
        row = await templates_service.get_version(
            db,
            org_id=user.org_id,
            template_id=template_id,
            version=version,
        )
    except TemplateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="template version not found",
        ) from exc
    return TemplateVersionRead.model_validate(row)


@router.post("/{template_id}/preview", response_model=PreviewResponse)
async def preview_endpoint(
    template_id: uuid.UUID,
    payload: PreviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_READ)),
) -> PreviewResponse:
    """Render the template's body (and subject, for email) against a
    sample context. Uses the lenient resolver — missing paths render
    as empty string, so previewing with an empty body returns the
    template's static content + blanks for variables.
    """
    try:
        template = await templates_service.get_template(
            db, org_id=user.org_id, template_id=template_id
        )
    except TemplateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="template not found",
        ) from exc
    body = resolve(template.body_text, payload.context)
    subject = (
        resolve(template.subject, payload.context)
        if template.subject
        else None
    )
    return PreviewResponse(subject=subject, body=body)


__all__ = ["router"]
