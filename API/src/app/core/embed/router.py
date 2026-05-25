"""HTTP routes for embeddable-widget.

Admin (JWT-gated) — manage keys:

  POST   /api/v1/embed/keys       → issue (returns plaintext ONCE)
  GET    /api/v1/embed/keys       → list (no plaintext, ever)
  DELETE /api/v1/embed/keys/{id}  → soft-revoke

Public (no JWT) — visitor submissions:

  POST   /api/v1/embed/leads      → submit a form (key in header or body)
  OPTIONS /api/v1/embed/leads     → CORS preflight

The admin endpoints are gated by `settings.integrations.embed.manage`.
The public endpoint authenticates via the embed key alone — no JWT —
so visitors on any third-party website can submit without first
logging into FurnitureCRM.
"""
from __future__ import annotations

import uuid
from typing import Optional

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.embed import log_service
from src.app.core.embed.config_service import (
    get_or_create as get_or_create_config,
    list_available_widget_custom_fields,
    public_get as public_get_config,
    update as update_config,
)
from src.app.core.embed.models import EmbedSubmissionOutcome
from src.app.core.embed.schemas import (
    AvailableCustomField,
    EmbedKeyIssue,
    EmbedKeyIssueResponse,
    EmbedKeyRead,
    EmbedSubmission,
    EmbedSubmissionListResponse,
    EmbedSubmissionOutcomeLiteral,
    EmbedSubmissionRead,
    EmbedSubmissionResponse,
    EmbedSubmissionSummary,
    WidgetConfigDocument,
    WidgetConfigPublic,
    WidgetConfigPublicDocument,
    WidgetConfigRead,
    WidgetConfigUpdate,
)
from src.app.core.embed.service import find_by_plain_key, issue, list_keys, revoke
from src.app.core.embed.submissions import submit as submit_widget_submission
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/embed", tags=["Embeddable Widget"])

# Separate router for the public submission + public-config endpoints.
# Same `/embed` prefix; mounted alongside the admin router in main.py.
public_router = APIRouter(prefix="/embed", tags=["Embeddable Widget — Public"])


@router.post(
    "/keys",
    response_model=EmbedKeyIssueResponse,
    status_code=status.HTTP_201_CREATED,
)
async def issue_embed_key_endpoint(
    payload: EmbedKeyIssue,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_permissions("settings.integrations.embed.manage")
    ),
) -> EmbedKeyIssueResponse:
    """Issue a new API key for the widget. The plaintext `secret`
    appears in this response ONCE — the Owner must copy it before
    navigating away. Subsequent reads only show the 11-char prefix.
    """
    row, plain = await issue(
        db,
        org_id=user.org_id,
        actor_id=user.legacy_uuid,
        name=payload.name,
    )
    return EmbedKeyIssueResponse(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        secret=plain,
        created_at=row.created_at,
    )


@router.get("/keys", response_model=list[EmbedKeyRead])
async def list_embed_keys_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("settings.integrations.embed.manage")
    ),
) -> list[EmbedKeyRead]:
    rows = await list_keys(db)
    return [EmbedKeyRead.model_validate(r) for r in rows]


@router.delete(
    "/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_embed_key_endpoint(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_permissions("settings.integrations.embed.manage")
    ),
) -> Response:
    """Soft-revoke an API key. Idempotent — re-revoking returns 204
    without emitting a second audit event."""
    await revoke(
        db,
        org_id=user.org_id,
        actor_id=user.legacy_uuid,
        key_id=key_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Admin: widget config -----------------------------------------------


@router.get("/config", response_model=WidgetConfigRead)
async def get_widget_config_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_permissions("settings.integrations.embed.manage")
    ),
) -> WidgetConfigRead:
    """Return the org's widget config, lazily seeding defaults on
    first read so Owners always see a usable starting point."""
    row = await get_or_create_config(db, org_id=user.org_id)
    return WidgetConfigRead(
        id=row.id,
        org_id=row.org_id,
        config=WidgetConfigDocument.model_validate(row.config),
        updated_by=row.updated_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get(
    "/available-custom-fields",
    response_model=list[AvailableCustomField],
)
async def list_available_custom_fields_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("settings.integrations.embed.manage")
    ),
) -> list[AvailableCustomField]:
    """Return the custom fields (contact AND lead) the Owner can opt IN
    to the widget. Drives the Settings → Embed → "Add custom field"
    picker. Unsupported types (multiselect/datetime/etc.) appear in the
    list with `widget_supported=false` so the UI can grey them out;
    each row carries `entity` so the picker can show which entity the
    field belongs to."""
    return await list_available_widget_custom_fields(db)


@router.put("/config", response_model=WidgetConfigRead)
async def update_widget_config_endpoint(
    payload: WidgetConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_permissions("settings.integrations.embed.manage")
    ),
) -> WidgetConfigRead:
    """Patch-style update — only supplied top-level fields change.
    Emits `embed.config.updated` audit event."""
    row = await update_config(
        db,
        org_id=user.org_id,
        actor_id=user.legacy_uuid,
        payload=payload,
    )
    return WidgetConfigRead(
        id=row.id,
        org_id=row.org_id,
        config=WidgetConfigDocument.model_validate(row.config),
        updated_by=row.updated_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# --- Admin: submission log (Step 9) --------------------------------------


# Cap pagination — 200 rows per response is enough for any UI without
# letting a curious operator paginate through millions of rows in a
# single request.
_LIST_PAGE_SIZE_MAX = 200


def _default_range() -> tuple[datetime, datetime]:
    """Default summary window: last 30 days, ending now (UTC)."""
    now = datetime.now(timezone.utc)
    return now - timedelta(days=30), now


@router.get(
    "/submissions",
    response_model=EmbedSubmissionListResponse,
)
async def list_embed_submissions_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("settings.integrations.embed.manage")
    ),
    outcome: EmbedSubmissionOutcomeLiteral | None = Query(default=None),
    range_from: datetime | None = Query(default=None, alias="from"),
    range_to: datetime | None = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=_LIST_PAGE_SIZE_MAX),
) -> EmbedSubmissionListResponse:
    """Paginated list of submission attempts, newest first. Optional
    `outcome` filter narrows to one bucket; `from`/`to` constrain the
    time window (defaults: whole table). Tenant context filters to
    the caller's org via RLS + ORM mixin."""
    outcome_filter = (
        EmbedSubmissionOutcome(outcome) if outcome is not None else None
    )
    rows, total = await log_service.list_rows(
        db,
        outcome=outcome_filter,
        range_from=range_from,
        range_to=range_to,
        page=page,
        page_size=page_size,
    )
    return EmbedSubmissionListResponse(
        items=[EmbedSubmissionRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/submissions/summary",
    response_model=EmbedSubmissionSummary,
)
async def submissions_summary_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(
        require_permissions("settings.integrations.embed.manage")
    ),
    range_from: datetime | None = Query(default=None, alias="from"),
    range_to: datetime | None = Query(default=None, alias="to"),
) -> EmbedSubmissionSummary:
    """Counts card + per-day stacked-bar chart payload. Defaults to
    the last 30 days when no range is supplied."""
    default_from, default_to = _default_range()
    resolved_from = range_from or default_from
    resolved_to = range_to or default_to
    return await log_service.summary(
        db, range_from=resolved_from, range_to=resolved_to
    )


# --- Public submission endpoint -------------------------------------------

# These headers go on every response from the public surface. The
# global CORS middleware already sets `Access-Control-Allow-Origin: *`,
# but we set them explicitly here too so any deployment that tightens
# the global policy doesn't accidentally block embed traffic.
_PUBLIC_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-FurniCRM-Key",
    "Access-Control-Max-Age": "3600",
}


def _client_ip(request: Request) -> str:
    """Best-effort caller IP. Prefers `X-Forwarded-For` (left-most
    hop is the original client) when a reverse proxy populates it,
    falls back to the TCP-level client. Returns 'unknown' as a last
    resort so the rate-limit bucket key is always well-defined."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


@public_router.options("/leads", include_in_schema=False)
async def submit_lead_preflight() -> Response:
    """CORS preflight for `POST /embed/leads`. Always 204 with the
    open CORS headers — the actual `POST` enforces key auth + rate
    limits."""
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=_PUBLIC_CORS_HEADERS)


@public_router.post(
    "/leads",
    response_model=EmbedSubmissionResponse,
    status_code=status.HTTP_200_OK,
)
async def submit_embed_lead_endpoint(
    payload: EmbedSubmission,
    request: Request,
    x_furnicrm_key: Optional[str] = Header(default=None, alias="X-FurniCRM-Key"),
) -> Response:
    """Public submission endpoint — no JWT, no admin auth.

    Header `X-FurniCRM-Key: pk_live_…` is the preferred auth
    transport; `embed_key` in the JSON body works as a fallback
    (some hosts strip custom headers). Spam protection (honeypot,
    min-fill-time, optional reCAPTCHA) lands in Step 8.
    """
    result = await submit_widget_submission(
        payload=payload,
        header_key=x_furnicrm_key,
        ip=_client_ip(request),
    )
    body = EmbedSubmissionResponse(
        ok=True,
        lead_id=result.lead_id,
        thank_you_url=result.thank_you_url,
    )
    return Response(
        content=body.model_dump_json(),
        media_type="application/json",
        headers=_PUBLIC_CORS_HEADERS,
    )


@public_router.options("/config/public", include_in_schema=False)
async def public_config_preflight() -> Response:
    """CORS preflight for the public config GET. Always 204."""
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={
            **_PUBLIC_CORS_HEADERS,
            "Access-Control-Allow-Methods": "GET, OPTIONS",
        },
    )


@public_router.get("/config/public", response_model=WidgetConfigPublic)
async def public_widget_config_endpoint(
    key: Optional[str] = None,
    x_furnicrm_key: Optional[str] = Header(default=None, alias="X-FurniCRM-Key"),
) -> Response:
    """Public widget-config fetch — no JWT. Resolves `key` (query OR
    header) → org via the embed-key lookup, then returns the org's
    widget config in the renderer's projection.

    `Cache-Control: public, max-age=60` lets the widget bundle cache
    the result for a minute — config changes have ~1-min propagation,
    which is fine since the Owner can hard-refresh after editing.
    """
    plain_key = x_furnicrm_key or key
    if not plain_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing embed key.",
        )
    key_row = await find_by_plain_key(plain_key)
    if key_row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked embed key.",
        )

    row = await public_get_config(key_row.org_id)
    if row is None:
        # Owner never opened the Settings tab to seed defaults. Return
        # the bundle-default shape so the widget still renders.
        from src.app.core.embed.config_service import _default_document

        document = _default_document()
    else:
        document = WidgetConfigDocument.model_validate(row.config)

    # Project to the public shape — strips `spam_protection.recaptcha_secret_key`
    # so the secret never lands in a visitor's browser. `model_dump`
    # exclude is bidirectional (recaptcha_secret_key isn't even a field
    # on `WidgetConfigSpamProtectionPublic`), so a stray field in JSONB
    # gets silently dropped on read.
    public_doc = WidgetConfigPublicDocument.model_validate(
        document.model_dump(mode="json")
    )
    body = WidgetConfigPublic(config=public_doc)
    return Response(
        content=body.model_dump_json(),
        media_type="application/json",
        headers={
            **_PUBLIC_CORS_HEADERS,
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Cache-Control": "public, max-age=60",
        },
    )
