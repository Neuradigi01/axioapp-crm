"""Public webhook receiver for Google Ads Lead Form deliveries.

  POST /api/v1/integrations/google/webhook/v1/{webhook_key}

This is the only Google-side ingress for ad leads. Google's "Leads
Webhook URL" config field on each Lead Form points here. Identity is
established two ways:

  1. The path's `webhook_key` resolves to exactly one `integrations`
     row (UNIQUE column, per migration 0049). Unknown key → 401.
  2. The body MUST carry a `google_key` field whose value equals the
     path's `webhook_key`. Google's documented integrity check —
     prevents an attacker who learned the URL from replaying it after
     the secret has been rotated.

After both checks pass, the receiver enqueues `process_google_lead`
on Celery and returns 200 immediately. The actual lead-creation work
(field mapping, dedup, audit, DLQ on failure) happens on the worker
— Google retries on any non-2xx, so the receiver MUST stay fast and
MUST NOT 500 on transient downstream errors.

The endpoint always returns 200 for authenticated payloads — even if
the celery enqueue fails (which would only happen if Redis is down,
in which case we'd rather have the operator paged via metrics than
have Google retry-storm).

NO permission gate. NO JWT. NO tenant context required up-front —
the receiver learns the tenant from the integration row it just
authenticated. The Celery task pushes the tenant context for
subsequent reads/writes.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Path, Request, status
from fastapi.responses import JSONResponse

from src.app.core import audit
from src.app.core.integrations.models import IntegrationStatus
from src.app.core.integrations.service import get_by_webhook_secret
from src.app.shared.db import async_session

logger = logging.getLogger(__name__)


# Same `/google` prefix as the other Google routes — mounted under
# the parent `/integrations` router. Full path: `/api/v1/integrations
# /google/webhook/v1/{webhook_key}`. The `v1` segment is permanent —
# Google customers configure the URL once; a v2 URL is a parallel
# endpoint, not a breaking replacement.
router = APIRouter(prefix="/google", tags=["Ad Integrations — Google"])


@router.post(
    "/webhook/v1/{webhook_key}",
    include_in_schema=False,
)
async def google_webhook(
    request: Request,
    webhook_key: str = Path(..., min_length=1, max_length=128),
    body: dict = Body(...),
) -> JSONResponse:
    """Authenticate the inbound webhook, enqueue lead-creation,
    return 200. See module docstring for the threat model."""
    client_ip = request.client.host if request.client else None

    # 1. Path secret must resolve to a connected integration.
    async with async_session() as session:
        integration = await get_by_webhook_secret(session, webhook_secret=webhook_key)

    if integration is None:
        # 401 here is deliberate — Google's docs say a 4xx tells them
        # to stop retrying. Unknown key = stale URL after a rotation
        # or outright impersonation attempt. We don't want Google to
        # keep delivering to a URL that will never authenticate.
        await audit.log(
            "integration.webhook.invalid_signature",
            entity_type="webhook_attempt",
            after={
                "provider": "google_ads",
                "reason": "unknown_webhook_key",
                "key_prefix": webhook_key[:8],
            },
            org_id=None,
            ip=client_ip,
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "unknown webhook key"},
        )

    if integration.status != IntegrationStatus.connected:
        # The secret is valid but the integration was disconnected
        # after Google captured the URL. Same 401 surface so Google
        # backs off — reconnecting will mint a NEW secret, not revive
        # the old one.
        await audit.log(
            "integration.webhook.invalid_signature",
            entity_type="webhook_attempt",
            after={
                "provider": "google_ads",
                "reason": "integration_disconnected",
                "integration_id": str(integration.id),
            },
            org_id=integration.org_id,
            ip=client_ip,
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "integration disconnected"},
        )

    # 2. Body's `google_key` must match the path's `webhook_key`.
    # Google's documented integrity check — protects against an
    # attacker who guesses the URL but doesn't know the secret value
    # (defence in depth — the URL itself is already secret, but the
    # body check makes URL leakage via referer/logs less catastrophic).
    body_key = body.get("google_key") if isinstance(body, dict) else None
    if not body_key or not _constant_time_equal(body_key, webhook_key):
        await audit.log(
            "integration.webhook.invalid_signature",
            entity_type="webhook_attempt",
            after={
                "provider": "google_ads",
                "reason": "google_key_mismatch",
                "integration_id": str(integration.id),
            },
            org_id=integration.org_id,
            ip=client_ip,
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "google_key mismatch"},
        )

    # 3. Authenticated. Enqueue. Lazy import keeps a cyclic shim out
    # of the module-load path.
    from src.app.core.integrations.google.tasks import (
        HAS_CELERY,
        process_google_lead,
        process_google_lead_async,
    )

    if HAS_CELERY:
        try:
            process_google_lead.delay(str(integration.id), body)
        except Exception:
            # Redis down / broker unreachable. Log + return 200 anyway
            # — we'd rather a metric/alert catch this than have Google
            # retry-storm because we 5xx'd. Operator should see the
            # exception trace in container logs.
            logger.exception(
                "google webhook: failed to enqueue task for integration_id=%s",
                integration.id,
            )
    else:
        # Celery not installed (dev). Run the task body synchronously
        # so dev smoke tests can verify the full path. Production
        # MUST have celery installed; tests cover the eager case via
        # task_always_eager.
        try:
            await process_google_lead_async(integration_id=integration.id, payload=body)
        except Exception:
            logger.exception(
                "google webhook: inline async processing failed for integration_id=%s",
                integration.id,
            )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "accepted"},
    )


def _constant_time_equal(a: str, b: str) -> bool:
    """Timing-safe equality. `hmac.compare_digest` rejects mismatched
    lengths in constant time too — important because the `webhook_key`
    is a secret and a side-channel could leak its prefix one byte at
    a time."""
    import hmac

    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


__all__ = ["router"]
