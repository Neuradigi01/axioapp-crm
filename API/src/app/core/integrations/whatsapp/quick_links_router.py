"""HTTP surface for WhatsApp quick-contact links
(whatsapp-platform-upgrade Step 26).

Two routers:

  * ``router`` — mounted under ``/api/v1/integrations``. CRUD +
    QR + stats. Gated on ``whatsapp.automation.manage`` (per the
    step spec — same Owner / Admin audience as the rest of the
    WhatsApp admin surfaces).

  * ``public_router`` — mounted at the app root (no version
    prefix). Hosts the public ``/wa/{code}`` 302 redirect. The
    public endpoint is the whole point of the link — it must be
    cacheable + scannable by phone cameras without authenticating.

The public endpoint applies an IP-based rate limit (in-process
sliding window — sufficient for the 1k-link scale we expect; if
a customer ships ten million billboards we'll move to a Redis
backend, see the risks section of the step spec)."""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.integrations.whatsapp.qr_generator import (
    render_png,
    render_svg,
)
from src.app.core.integrations.whatsapp.quick_links import (
    QuickLinksError,
    build_wa_me_url,
    create_link,
    delete_link,
    link_stats,
    list_links,
    record_click,
    resolve_by_code,
    update_link,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/whatsapp/quick-links",
    tags=["Integrations · WhatsApp · Quick Links"],
)
public_router = APIRouter(tags=["Public · WhatsApp"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class _QuickLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    label: str
    phone_number: str
    prefilled_message: str | None
    click_count: int
    scan_count: int
    attributed_conversation_count: int
    created_by_user_id: uuid.UUID | None
    created_at: Any
    updated_at: Any


class _QuickLinkListOut(BaseModel):
    items: list[_QuickLinkOut]
    total: int
    page: int
    size: int


class _QuickLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=128)
    phone_number: str = Field(min_length=4, max_length=32)
    prefilled_message: str | None = Field(default=None, max_length=2000)


class _QuickLinkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    label: str | None = Field(default=None, min_length=1, max_length=128)
    phone_number: str | None = Field(default=None, max_length=32)
    prefilled_message: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=_QuickLinkListOut)
async def list_endpoint(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("whatsapp.automation.manage")),
) -> _QuickLinkListOut:
    rows, total = await list_links(db, org_id=user.org_id, page=page, size=size)
    return _QuickLinkListOut(
        items=[_QuickLinkOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post(
    "",
    response_model=_QuickLinkOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_endpoint(
    payload: _QuickLinkCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("whatsapp.automation.manage")),
) -> _QuickLinkOut:
    try:
        row = await create_link(
            db,
            org_id=user.org_id,
            actor_user_id=user.legacy_uuid,
            label=payload.label,
            phone_number=payload.phone_number,
            prefilled_message=payload.prefilled_message,
        )
    except QuickLinksError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    return _QuickLinkOut.model_validate(row)


@router.patch("/{link_id}", response_model=_QuickLinkOut)
async def update_endpoint(
    link_id: uuid.UUID,
    payload: _QuickLinkUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("whatsapp.automation.manage")),
) -> _QuickLinkOut:
    try:
        row = await update_link(
            db,
            org_id=user.org_id,
            link_id=link_id,
            label=payload.label,
            phone_number=payload.phone_number,
            prefilled_message=payload.prefilled_message,
        )
    except QuickLinksError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return _QuickLinkOut.model_validate(row)


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("whatsapp.automation.manage")),
) -> Response:
    try:
        await delete_link(db, org_id=user.org_id, link_id=link_id)
    except QuickLinksError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{link_id}/stats")
async def stats_endpoint(
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("whatsapp.automation.manage")),
) -> dict[str, Any]:
    try:
        return await link_stats(db, org_id=user.org_id, link_id=link_id)
    except QuickLinksError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get(
    "/{link_id}/qr.png",
    summary="Render the QR code as PNG (256 / 512 / 1024 px).",
    responses={200: {"content": {"image/png": {}}}},
)
async def qr_png_endpoint(
    link_id: uuid.UUID,
    size: int = Query(default=512, ge=128, le=2048),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("whatsapp.automation.manage")),
) -> Response:
    from sqlalchemy import select

    from src.app.core.integrations.whatsapp.models import (
        WhatsAppQuickLink,
    )

    row = (
        await db.execute(
            select(WhatsAppQuickLink).where(
                WhatsAppQuickLink.id == link_id,
                WhatsAppQuickLink.org_id == user.org_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="link not found")
    public_url = _public_redirect_url(request, row.code) + "?src=qr"
    try:
        blob = render_png(public_url, size_px=size)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    return Response(
        content=blob,
        media_type="image/png",
        headers={
            "Content-Disposition": (f'inline; filename="qr-{row.code}.png"'),
            "Cache-Control": "public, max-age=600",
        },
    )


@router.get(
    "/{link_id}/qr.svg",
    summary="Render the QR code as SVG (vector, ideal for print PDFs).",
    responses={200: {"content": {"image/svg+xml": {}}}},
)
async def qr_svg_endpoint(
    link_id: uuid.UUID,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("whatsapp.automation.manage")),
) -> Response:
    from sqlalchemy import select

    from src.app.core.integrations.whatsapp.models import (
        WhatsAppQuickLink,
    )

    row = (
        await db.execute(
            select(WhatsAppQuickLink).where(
                WhatsAppQuickLink.id == link_id,
                WhatsAppQuickLink.org_id == user.org_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="link not found")
    public_url = _public_redirect_url(request, row.code) + "?src=qr"
    try:
        blob = render_svg(public_url)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    return Response(
        content=blob,
        media_type="image/svg+xml",
        headers={
            "Content-Disposition": (f'inline; filename="qr-{row.code}.svg"'),
            "Cache-Control": "public, max-age=600",
        },
    )


def _public_redirect_url(request: Request | None, code: str) -> str:
    """Construct the public ``/wa/{code}`` URL the QR encodes.

    Uses the request's host header when available; falls back to a
    relative URL for tests / scripted callers. Operators behind a
    reverse proxy should rely on ``X-Forwarded-Host`` — Starlette
    surfaces that through ``request.url`` when the proxy headers
    middleware is on (default in our stack)."""
    if request is None:
        return f"/wa/{code}"
    base = str(request.base_url).rstrip("/")
    return f"{base}/wa/{code}"


# ---------------------------------------------------------------------------
# Public redirect
# ---------------------------------------------------------------------------


# In-process sliding-window rate limit. Per-IP, 60 requests per
# 60 seconds. Sufficient for the per-org scale Step 26 targets;
# future Redis-backed lift lands in `shared/cache.py` when one
# exists.
_RATE_LIMIT_WINDOW_S = 60.0
_RATE_LIMIT_HITS = 60
_rate_buckets: dict[str, deque[float]] = {}


def _rate_limit_ok(ip: str | None) -> bool:
    if not ip:
        return True
    now = time.time()
    bucket = _rate_buckets.setdefault(ip, deque())
    cutoff = now - _RATE_LIMIT_WINDOW_S
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT_HITS:
        return False
    bucket.append(now)
    return True


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    client = request.client
    return client.host if client else None


def _ua_family(ua_header: str | None) -> str | None:
    """Cheap UA categorisation — we don't ship a full UA parser
    just to bucket clicks into iOS / Android / Web / Other. Stores
    the lowercase family so the stats card can group cleanly."""
    if not ua_header:
        return None
    lower = ua_header.lower()
    if "android" in lower:
        return "android"
    if "iphone" in lower or "ipad" in lower or "ios" in lower:
        return "ios"
    if "macintosh" in lower or "mac os" in lower:
        return "macos"
    if "windows" in lower:
        return "windows"
    if "linux" in lower:
        return "linux"
    return "other"


@public_router.get(
    "/wa/{code}",
    summary="Public 302 redirect to wa.me with tracking.",
)
async def public_redirect_endpoint(
    code: str,
    request: Request,
    src: str = Query(default="link", pattern="^(link|qr)$"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Resolve a slug → wa.me URL + record the click. The public
    endpoint is the only place in the app that bypasses the
    standard RLS tenant gate; the bypass is mediated via the
    ``app.public_quick_link`` Postgres setting that the
    quick_links service flips on every transaction it owns.

    Rate-limited per IP. Unknown / deleted codes return 404 with
    a plain text body — no leaking which tenant they would have
    belonged to."""
    ip = _client_ip(request)
    if not _rate_limit_ok(ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limited — please retry shortly",
        )
    link = await resolve_by_code(db, code=code)
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="link not found",
        )
    await record_click(
        db,
        link=link,
        source=src,
        ua_family=_ua_family(request.headers.get("user-agent")),
        referrer=request.headers.get("referer"),
        ip=ip,
    )
    target = build_wa_me_url(link)
    return RedirectResponse(target, status_code=302)
