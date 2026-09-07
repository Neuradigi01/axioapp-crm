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
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.embed import log_service
from src.app.core.embed.config_service import (
    get_or_create as get_or_create_config,
)
from src.app.core.embed.config_service import (
    list_available_widget_custom_fields,
)
from src.app.core.embed.config_service import (
    public_get as public_get_config,
)
from src.app.core.embed.config_service import (
    update as update_config,
)
from src.app.core.embed import form_service
from src.app.core.embed.models import EmbedSubmissionOutcome, WidgetConfig
from src.app.core.embed.schemas import (
    AiAssistantEmbedKeyIssue,
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
    WidgetFormCreate,
    WidgetFormListItem,
    WidgetFormRead,
    WidgetFormUpdate,
)
from src.app.core.embed.service import (
    RESOURCE_TYPE_AI_ASSISTANT,
    find_by_plain_key,
    issue,
    list_keys,
    list_keys_for_resource,
    revoke,
    revoke_now,
    rotate,
)
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
    user: User = Depends(require_permissions("settings.integrations.embed.manage")),
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
    _user: User = Depends(require_permissions("settings.integrations.embed.manage")),
) -> list[EmbedKeyRead]:
    rows = await list_keys(db)
    return [EmbedKeyRead.model_validate(r) for r in rows]


@router.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_embed_key_endpoint(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.integrations.embed.manage")),
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


# --- Admin: AI-assistant scoped keys (Step 14) ------------------------


# NOTE: uses the SAME ``settings.integrations.embed.manage`` permission
# as lead-form keys — one gate covers both channel types so operators
# don't need a second permission grant to issue an AI-assistant key.


@router.post(
    "/ai-assistants/{assistant_id}/keys",
    response_model=EmbedKeyIssueResponse,
    status_code=status.HTTP_201_CREATED,
)
async def issue_ai_assistant_embed_key(
    assistant_id: uuid.UUID,
    payload: AiAssistantEmbedKeyIssue,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.integrations.embed.manage")),
) -> EmbedKeyIssueResponse:
    """Issue an embed key scoped to one AI assistant. Plaintext
    ``secret`` appears in the response ONCE — the operator must copy
    it before navigating away."""
    row, plain = await issue(
        db,
        org_id=user.org_id,
        actor_id=user.legacy_uuid,
        name=payload.name,
        resource_type=RESOURCE_TYPE_AI_ASSISTANT,
        resource_id=assistant_id,
        allowed_origins=payload.allowed_origins,
        rate_limit_per_hour=payload.rate_limit_per_hour,
    )
    return EmbedKeyIssueResponse(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        secret=plain,
        created_at=row.created_at,
    )


@router.get(
    "/ai-assistants/{assistant_id}/keys",
    response_model=list[EmbedKeyRead],
)
async def list_ai_assistant_embed_keys(
    assistant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("settings.integrations.embed.manage")),
) -> list[EmbedKeyRead]:
    """List embed keys bound to one AI assistant. Never returns
    plaintext."""
    rows = await list_keys_for_resource(
        db,
        resource_type=RESOURCE_TYPE_AI_ASSISTANT,
        resource_id=assistant_id,
    )
    return [EmbedKeyRead.model_validate(r) for r in rows]


@router.post(
    "/keys/{key_id}/rotate",
    response_model=EmbedKeyIssueResponse,
)
async def rotate_embed_key_endpoint(
    key_id: uuid.UUID,
    grace_days: int = Query(default=0, ge=0, le=7),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.integrations.embed.manage")),
) -> EmbedKeyIssueResponse:
    """Rotate: issues a fresh key with the same resource binding +
    revokes the old one. Default is immediate revoke
    (``grace_days=0``); pass ``?grace_days=<1..7>`` to keep the old
    key live during the swap."""
    new_row, plain = await rotate(
        db,
        org_id=user.org_id,
        actor_id=user.legacy_uuid,
        key_id=key_id,
        grace_days=grace_days,
    )
    return EmbedKeyIssueResponse(
        id=new_row.id,
        name=new_row.name,
        prefix=new_row.prefix,
        secret=plain,
        created_at=new_row.created_at,
    )


@router.post(
    "/keys/{key_id}/revoke-now",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_now_embed_key_endpoint(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.integrations.embed.manage")),
) -> Response:
    """Hard-revoke immediately AND close every in-flight SSE stream
    for this key. Use this when a key has leaked and must stop
    working RIGHT NOW rather than after the client's cached
    connection times out."""
    await revoke_now(
        db,
        org_id=user.org_id,
        actor_id=user.legacy_uuid,
        key_id=key_id,
    )
    # Cancel any in-flight streams. In-memory registry — single
    # worker in v1 (documented risk in the step spec).
    from src.app.core.ai_assistants.sse_registry import registry as _sse_registry

    _sse_registry.cancel_by_embed_key(key_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Admin: widget config -----------------------------------------------


@router.get("/config", response_model=WidgetConfigRead)
async def get_widget_config_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.integrations.embed.manage")),
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
    _user: User = Depends(require_permissions("settings.integrations.embed.manage")),
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
    user: User = Depends(require_permissions("settings.integrations.embed.manage")),
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


# --- Admin: multi-form CRUD (multi-form Step 2) --------------------------
#
# Every org may own many lead-capture forms — one per use case
# (Contact Us / Quote Request / Newsletter / ...). The legacy
# ``/embed/config`` endpoints continue to operate on the org's default
# form so existing UIs and embed snippets keep working; these new
# ``/embed/forms/*`` endpoints are what the multi-form Settings page
# and the future per-form snippet builder call into.
#
# All gated by the SAME ``settings.integrations.embed.manage``
# permission as the legacy config endpoints — one grant covers both
# surfaces so Owners don't need a second permission.


def _project_form(form: WidgetConfig, key_count: int) -> WidgetFormListItem:
    return WidgetFormListItem(
        id=form.id,
        name=form.name,
        slug=form.slug,
        is_default=form.is_default,
        key_count=key_count,
        created_at=form.created_at,
        updated_at=form.updated_at,
    )


def _project_form_read(form: WidgetConfig) -> WidgetFormRead:
    return WidgetFormRead(
        id=form.id,
        org_id=form.org_id,
        name=form.name,
        slug=form.slug,
        is_default=form.is_default,
        config=WidgetConfigDocument.model_validate(form.config),
        updated_by=form.updated_by,
        created_at=form.created_at,
        updated_at=form.updated_at,
    )


@router.get("/forms", response_model=list[WidgetFormListItem])
async def list_widget_forms_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("settings.integrations.embed.manage")),
) -> list[WidgetFormListItem]:
    """List every live form on the org (default first, then alphabetical
    by name). Each row carries ``key_count`` — the number of live embed
    keys pinned to that form — so the Settings → Forms list can render
    a "N keys" pill without a second round-trip."""
    pairs = await form_service.list_forms(db, org_id=_user.org_id)
    return [_project_form(form, count) for form, count in pairs]


@router.post(
    "/forms",
    response_model=WidgetFormRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_widget_form_endpoint(
    payload: WidgetFormCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.integrations.embed.manage")),
) -> WidgetFormRead:
    """Create a new form. Slug is auto-derived from name when omitted
    and de-duped against existing live slugs on the org. Newly-created
    forms are NEVER marked default — the org's default only moves via
    ``POST /forms/{form_id}/set-default``."""
    form = await form_service.create_form(
        db,
        org_id=user.org_id,
        actor_id=user.legacy_uuid,
        payload=payload,
    )
    return _project_form_read(form)


@router.get("/forms/{form_id}", response_model=WidgetFormRead)
async def get_widget_form_endpoint(
    form_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("settings.integrations.embed.manage")),
) -> WidgetFormRead:
    """Single form with its full config document. 404 on unknown or
    soft-deleted form id."""
    form = await form_service.get_form(db, form_id=form_id)
    return _project_form_read(form)


@router.put("/forms/{form_id}", response_model=WidgetFormRead)
async def update_widget_form_endpoint(
    form_id: uuid.UUID,
    payload: WidgetFormUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.integrations.embed.manage")),
) -> WidgetFormRead:
    """Patch-style update: supplied fields (name / slug / config) are
    applied; omitted fields stay as they are. The config sub-patch, if
    present, is merged into the existing document and re-validated
    (custom-field refs, select-field option lists) before persistence."""
    form = await form_service.update_form(
        db,
        org_id=user.org_id,
        form_id=form_id,
        actor_id=user.legacy_uuid,
        payload=payload,
    )
    return _project_form_read(form)


@router.post(
    "/forms/{form_id}/set-default",
    response_model=WidgetFormRead,
)
async def set_default_widget_form_endpoint(
    form_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.integrations.embed.manage")),
) -> WidgetFormRead:
    """Promote ``form_id`` to the org's default form. Atomic swap —
    the previous default is cleared in the same transaction, so the
    "exactly one default per org" invariant is never violated."""
    form = await form_service.set_default_form(
        db,
        org_id=user.org_id,
        form_id=form_id,
        actor_id=user.legacy_uuid,
    )
    return _project_form_read(form)


@router.delete(
    "/forms/{form_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_widget_form_endpoint(
    form_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.integrations.embed.manage")),
) -> Response:
    """Soft-delete the form (stamps ``deleted_at``). Historical leads
    that carry ``attribution.form_id`` still resolve a name from the
    retired row.

    422 when the target is the org's default form OR the org's only
    live form — set a different form as default (and/or create a
    replacement) first."""
    await form_service.delete_form(
        db,
        org_id=user.org_id,
        form_id=form_id,
        actor_id=user.legacy_uuid,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Admin: submission log (Step 9) --------------------------------------


# Cap pagination — 200 rows per response is enough for any UI without
# letting a curious operator paginate through millions of rows in a
# single request.
_LIST_PAGE_SIZE_MAX = 200


def _default_range() -> tuple[datetime, datetime]:
    """Default summary window: last 30 days, ending now (UTC)."""
    now = datetime.now(UTC)
    return now - timedelta(days=30), now


@router.get(
    "/submissions",
    response_model=EmbedSubmissionListResponse,
)
async def list_embed_submissions_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("settings.integrations.embed.manage")),
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
    outcome_filter = EmbedSubmissionOutcome(outcome) if outcome is not None else None
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
    _user: User = Depends(require_permissions("settings.integrations.embed.manage")),
    range_from: datetime | None = Query(default=None, alias="from"),
    range_to: datetime | None = Query(default=None, alias="to"),
) -> EmbedSubmissionSummary:
    """Counts card + per-day stacked-bar chart payload. Defaults to
    the last 30 days when no range is supplied."""
    default_from, default_to = _default_range()
    resolved_from = range_from or default_from
    resolved_to = range_to or default_to
    return await log_service.summary(db, range_from=resolved_from, range_to=resolved_to)


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
    x_furnicrm_key: str | None = Header(default=None, alias="X-FurniCRM-Key"),
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
    key: str | None = None,
    x_furnicrm_key: str | None = Header(default=None, alias="X-FurniCRM-Key"),
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
    public_doc = WidgetConfigPublicDocument.model_validate(document.model_dump(mode="json"))
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
