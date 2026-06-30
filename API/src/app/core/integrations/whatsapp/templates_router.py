"""HTTP routes for WhatsApp template management
(whatsapp-platform-upgrade Step 8).

  GET    /api/v1/integrations/whatsapp/templates/manage             — list with mgmt filters
  POST   /api/v1/integrations/whatsapp/templates/manage             — create draft
  PATCH  /api/v1/integrations/whatsapp/templates/manage/{id}        — edit draft / rejected
  DELETE /api/v1/integrations/whatsapp/templates/manage/{id}        — local + Meta delete
  POST   /api/v1/integrations/whatsapp/templates/manage/{id}/submit — submit to Meta
  POST   /api/v1/integrations/whatsapp/templates/manage/{id}/duplicate

The mount path differs from the existing read-only ``/templates``
surface (used by the campaign picker) on purpose — the picker stays
gated on ``campaigns.read`` and continues to return only approved
templates, while the management surface gates on the new
``whatsapp.templates.*`` keys + returns drafts.

Permissions:
  - LIST / detail        → whatsapp.templates.read
  - POST / PATCH / DELETE→ whatsapp.templates.write
  - submit               → whatsapp.templates.submit (typically Owner /
                            integration admin only; junior sales does
                            not get submit by default)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import META_APP_ID, WHATSAPP_APP_SECRET
from src.app.core.auth.dependencies import require_permissions
from src.app.core.conversations.adapters.whatsapp import WhatsAppNotConnected
from src.app.core.integrations.whatsapp.models import (
    WhatsAppTemplateSubmissionStatus,
)
from src.app.core.integrations.whatsapp.schemas import (
    WhatsAppTemplatePerformanceOut,
    WhatsAppTemplateRead,
    WhatsAppTemplateSubmissionOut,
    WhatsAppTemplateUpsert,
)
from src.app.core.integrations.whatsapp.templates_analytics import (
    get_template_performance,
)
from src.app.core.integrations.whatsapp.templates_service import (
    create_draft,
    delete_template,
    duplicate_template,
    get_template_or_404,
    list_templates_managed,
    submit_for_approval,
    update_draft,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(
    prefix="/whatsapp/templates/manage",
    tags=["Integrations · WhatsApp · Templates"],
)


def _require_app_credentials() -> tuple[str, str]:
    """Pull the Meta App credentials needed for the Graph client.

    The submit + delete paths talk to Meta via ``MetaGraphClient`` which
    requires the app id + secret. Both are loaded from the SOPS-managed
    secrets at process start; missing them is a 503 (operator can't fix
    from the UI, deploy must)."""
    if not META_APP_ID or not WHATSAPP_APP_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Server is missing Meta App credentials — set META_APP_ID and WHATSAPP_APP_SECRET."
            ),
        )
    return META_APP_ID, WHATSAPP_APP_SECRET


@router.get("", response_model=list[WhatsAppTemplateRead])
async def list_managed_endpoint(
    submission_status: str | None = Query(default=None, max_length=32),
    category: str | None = Query(default=None, max_length=32),
    language: str | None = Query(default=None, max_length=16),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("whatsapp.templates.read")),
) -> list[WhatsAppTemplateRead]:
    """Management list — includes drafts. The campaign picker keeps
    using the legacy `/templates` (`campaigns.read`-gated, approved-
    only) endpoint."""
    sub_status: WhatsAppTemplateSubmissionStatus | None = None
    if submission_status:
        try:
            sub_status = WhatsAppTemplateSubmissionStatus(submission_status)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(f"Unknown submission_status '{submission_status}'."),
            ) from None
    rows = await list_templates_managed(
        db,
        submission_status=sub_status,
        category=category,
        language=language,
    )
    return [WhatsAppTemplateRead.model_validate(r) for r in rows]


@router.post(
    "",
    response_model=WhatsAppTemplateRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_endpoint(
    payload: WhatsAppTemplateUpsert,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("whatsapp.templates.write")),
) -> WhatsAppTemplateRead:
    try:
        row = await create_draft(db, actor_id=user.legacy_uuid, payload=payload)
    except WhatsAppNotConnected as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return WhatsAppTemplateRead.model_validate(row)


@router.patch("/{template_id}", response_model=WhatsAppTemplateRead)
async def update_endpoint(
    template_id: uuid.UUID,
    payload: WhatsAppTemplateUpsert,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("whatsapp.templates.write")),
) -> WhatsAppTemplateRead:
    row = await update_draft(
        db,
        actor_id=user.legacy_uuid,
        template_id=template_id,
        payload=payload,
    )
    return WhatsAppTemplateRead.model_validate(row)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("whatsapp.templates.write")),
) -> Response:
    app_id, app_secret = _require_app_credentials()
    try:
        await delete_template(
            db,
            actor_id=user.legacy_uuid,
            template_id=template_id,
            app_id=app_id,
            app_secret=app_secret,
        )
    except WhatsAppNotConnected as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{template_id}/submit",
    response_model=WhatsAppTemplateSubmissionOut,
)
async def submit_endpoint(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("whatsapp.templates.submit")),
) -> WhatsAppTemplateSubmissionOut:
    app_id, app_secret = _require_app_credentials()
    try:
        row = await submit_for_approval(
            db,
            actor_id=user.legacy_uuid,
            template_id=template_id,
            app_id=app_id,
            app_secret=app_secret,
        )
    except WhatsAppNotConnected as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return WhatsAppTemplateSubmissionOut(
        id=row.id,
        submission_status=row.submission_status.value,
        meta_template_id=row.meta_template_id,
        meta_status=row.status,
    )


@router.post(
    "/{template_id}/duplicate",
    response_model=WhatsAppTemplateRead,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_endpoint(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("whatsapp.templates.write")),
) -> WhatsAppTemplateRead:
    row = await duplicate_template(db, actor_id=user.legacy_uuid, template_id=template_id)
    return WhatsAppTemplateRead.model_validate(row)


@router.get(
    "/{template_id}/performance",
    response_model=WhatsAppTemplatePerformanceOut,
)
async def performance_endpoint(
    template_id: uuid.UUID,
    range: str = Query(default="30d", max_length=8, alias="range"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("whatsapp.templates.read")),
) -> WhatsAppTemplatePerformanceOut:
    """Per-template performance card payload (Step 10).

    `range` accepts ``7d`` / ``30d`` / ``90d``; anything else returns
    422. The template must exist + belong to the active org (RLS
    auto-scopes the existence check)."""
    if range not in ("7d", "30d", "90d"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="range must be one of 7d, 30d, 90d.",
        )
    # Existence check — guarantees a 404 (not an empty payload) when
    # the template doesn't belong to the active org. RLS handles the
    # cross-tenant case (returns no row → 404).
    await get_template_or_404(db, template_id)
    result = await get_template_performance(
        db,
        template_id=template_id,
        range_key=range,  # type: ignore[arg-type]
    )
    return WhatsAppTemplatePerformanceOut(
        template_id=result.template_id,
        range_key=result.range_key,
        range_start=result.range_start,
        range_end=result.range_end,
        sent=result.sent,
        delivered=result.delivered,
        read=result.read,
        replied=result.replied,
        click_through=result.click_through,
        failed=result.failed,
        delivery_rate=result.delivery_rate,
        read_rate=result.read_rate,
        reply_rate=result.reply_rate,
        daily=[
            {  # type: ignore[arg-type]
                "date": b.date,
                "sent": b.sent,
                "delivered": b.delivered,
                "read": b.read,
                "failed": b.failed,
            }
            for b in result.daily
        ],
        failures=[
            {  # type: ignore[arg-type]
                "bucket": f.bucket,
                "label": f.label,
                "count": f.count,
            }
            for f in result.failures
        ],
        used_in_campaigns=result.used_in_campaigns,
    )
