"""Public webhook receiver for Mailgun inbound email.

Two methods on one URL:

  POST /api/v1/webhooks/mailgun/inbound        — inbound delivery
  GET  /api/v1/webhooks/mailgun/inbound/health — Mailgun URL validator + ops

Both are UNAUTHENTICATED (no JWT / no session). The POST authenticates
via Mailgun's HMAC-SHA256 signature over ``(timestamp + token)`` —
verified in :func:`service.verify_signature`. The GET returns a
constant JSON with the configured domain (no secrets).

Signature-failure requests are rate-limited per source IP at
20 hits/minute via :func:`shared.rate_limit_shared.rate_hit`.
Signed traffic is NOT rate-limited — that would shed legit Mailgun
deliveries during reply-storms (Mailgun's egress IPs are shared /
small).

Response body: always ``{"status": "accepted"}`` on success,
regardless of whether the token resolved to a real sender / org —
this keeps the request-time constant so token existence isn't
leaked via response-time oracle.
"""

from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.auth.dependencies import require_permissions
from src.app.core.email.mailgun import data_access, service
from src.app.core.email.mailgun.schemas import (
    DlqReprocessResponse,
    DlqRowOut,
    WebhookHealthResponse,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db
from src.app.shared.rate_limit_shared import rate_hit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mailgun", tags=["Mailgun Inbound"])

# Separate router for the Owner-only DLQ admin surface — mounted at
# a different path (``/admin/email-inbound-dlq``) so it can be gated
# on a per-request permission dependency without leaking into the
# webhook router's unauthenticated surface.
dlq_admin_router = APIRouter(
    prefix="/admin/email-inbound-dlq", tags=["Email Inbound DLQ"]
)


def _dlq_row_to_out(row) -> DlqRowOut:
    """Serialise a DB row into the API-safe response shape. Never
    surfaces ``pending_inbound_path`` or ``error_details``."""
    return DlqRowOut(
        id=str(row.id),
        org_id=str(row.org_id) if row.org_id else None,
        mailgun_delivery_id=row.mailgun_delivery_id,
        error_reason=row.error_reason,
        retry_count=row.retry_count,
        created_at=row.created_at.isoformat(),
        resolved_at=row.resolved_at.isoformat() if row.resolved_at else None,
    )


@dlq_admin_router.get("", response_model=list[DlqRowOut])
async def list_email_inbound_dlq(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("mailgun.inbound.dlq.manage")),
) -> list[DlqRowOut]:
    """List failed Mailgun ingest deliveries, newest first.

    Scoping: per-org for tenant admins (Owner role only, per the
    role-templates spec). NULL-org rows (system-level failures like
    unknown recipient or malformed payload) are visible to platform
    staff only — for now, an Owner sees only their org's rows;
    surfacing NULL-org rows to any tenant would leak sender emails
    across orgs.
    """
    rows = await data_access.list_dlq_rows(
        db, org_id=user.org_id, limit=limit, offset=offset
    )
    return [_dlq_row_to_out(r) for r in rows]


@dlq_admin_router.post(
    "/{dlq_id}/reprocess", response_model=DlqReprocessResponse
)
async def reprocess_email_inbound_dlq(
    dlq_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("mailgun.inbound.dlq.manage")),
) -> DlqReprocessResponse:
    """Re-enqueue a DLQ row's original pending-inbound directory.

    Preserves the DLQ row (marks ``resolved_at`` on the reprocess
    kickoff) so the audit trail sticks around. A subsequent success
    doesn't retroactively unresolve; a subsequent failure writes a
    fresh DLQ row.

    404 (not 403) on cross-org access.
    """
    from pathlib import Path as _Path

    row = await data_access.get_dlq_row(db, dlq_id=dlq_id)
    if row is None:
        raise HTTPException(status_code=404, detail="dlq row not found")
    # Org-scope: Owner of Org A cannot reprocess a DLQ row that belongs
    # to Org B. NULL-org rows are system-level and rejected here too —
    # a future platform-admin surface can widen this.
    if row.org_id is not None and row.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="dlq row not found")
    if row.org_id is None:
        raise HTTPException(
            status_code=403, detail="system-level DLQ rows aren't reprocessable via tenant admin",
        )

    pending_path = _Path(row.pending_inbound_path)
    if not pending_path.exists():
        raise HTTPException(
            status_code=410,
            detail="pending payload no longer on disk — cannot reprocess",
        )

    reprocessed = service.enqueue_process_task(pending_path)
    if reprocessed:
        from datetime import UTC, datetime as _dt

        row.resolved_at = _dt.now(UTC)
        await db.commit()

    return DlqReprocessResponse(id=str(row.id), reprocessed=reprocessed)

_FAIL_RATE_KEY_PREFIX = "mgw:fail:"
_FAIL_RATE_LIMIT = 20
_FAIL_RATE_WINDOW_SECONDS = 60


@router.get("/inbound/health", response_model=WebhookHealthResponse)
async def mailgun_inbound_health() -> WebhookHealthResponse:
    """Health check for Mailgun's URL validator + our own ops.
    No secrets — the domain is the public receiving MX host."""
    return WebhookHealthResponse(
        ok=True,
        domain=os.getenv("MAILGUN_DOMAIN") or None,
    )


@router.post("/inbound", include_in_schema=False)
async def mailgun_inbound(request: Request) -> JSONResponse:
    """Receive one Mailgun-forwarded inbound email.

    Flow: extract signature triplet → verify HMAC → replay-cache
    check → persist raw multipart to disk → enqueue Celery task →
    return 200. All heavy work (token resolve, contact match,
    threading) lives in the Celery task so the request path is
    constant-time regardless of token validity.
    """
    client_ip = request.client.host if request.client else None
    form = await request.form()

    timestamp = str(form.get("timestamp", ""))
    token = str(form.get("token", ""))
    signature = str(form.get("signature", ""))

    if not service.verify_signature(
        timestamp=timestamp, token=token, signature=signature
    ):
        # Rate-limit ONLY signature failures — signed traffic is
        # trusted Mailgun and we don't want to shed legit deliveries
        # during a reply-storm because of shared egress IPs.
        if client_ip:
            await rate_hit(
                f"{_FAIL_RATE_KEY_PREFIX}{client_ip}",
                _FAIL_RATE_LIMIT,
                _FAIL_RATE_WINDOW_SECONDS,
            )
        await audit.log(
            "mailgun.webhook.invalid_signature",
            entity_type="webhook_attempt",
            after={
                "reason": "bad_signature",
                "timestamp_present": bool(timestamp),
                "token_present": bool(token),
                "signature_present": bool(signature),
            },
            org_id=None,  # system-level — no tenant resolved yet
            ip=client_ip,
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "bad signature"},
        )

    # Replay-cache: fail-CLOSED on Redis outage. A genuine replay of
    # a captured triplet within the 10-min window returns 401; so does
    # a Redis-down blip (Mailgun retries after we 5xx-shape response,
    # so no lost mail — just a moment of delayed delivery).
    fresh = await data_access.check_and_record_replay(token)
    if not fresh:
        await audit.log(
            "mailgun.webhook.replay_rejected",
            entity_type="webhook_attempt",
            after={"reason": "replay_or_redis_outage"},
            org_id=None,
            ip=client_ip,
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "replay"},
        )

    # Persist to disk BEFORE enqueue so broker outage after our 200
    # doesn't lose the delivery — the sweeper picks up dirs > 5min.
    try:
        pending_dir = await service.persist_pending_inbound(form)
    except Exception:  # pragma: no cover — disk-full / permissions
        logger.exception("mailgun.webhook: failed to persist pending inbound")
        await audit.log(
            "mailgun.webhook.persist_failed",
            entity_type="webhook_attempt",
            after={"reason": "disk_write_error"},
            org_id=None,
            ip=client_ip,
        )
        # 500 → Mailgun retries. Better than silently dropping.
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "persist failed"},
        )

    # Fire-and-forget enqueue; sweeper catches broker outages.
    service.enqueue_process_task(pending_dir)

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "accepted"},
    )


__all__ = ["dlq_admin_router", "router"]
