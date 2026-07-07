"""Public webhook receiver for Meta Lead Ads.

Two methods on one URL — Meta's webhook convention:

  GET  /api/v1/integrations/meta/webhook   — verify-token handshake
  POST /api/v1/integrations/meta/webhook   — `leadgen` delivery

**Single URL per environment**, NOT per-org — unlike Google's
per-tenant webhook URL, Meta's app-level webhook subscription routes
every org's leads to the same endpoint. We discriminate by the
`page_id` field in the payload, which the Step-5 cache
(`meta_page_tokens`, populated during `subscribe_page`) maps back to
an integration + org.

Authentication:

  - **GET handshake** (one-time per env, when an operator saves the
    webhook URL in the Meta app dashboard): Meta sends `hub.mode=
    subscribe`, `hub.verify_token=<configured-token>`, `hub.challenge
    =<random>`. We echo `hub.challenge` iff the verify_token matches
    `META_WEBHOOK_VERIFY_TOKEN` from env. Mismatch → 403.

  - **POST delivery**: Meta signs every POST with `X-Hub-Signature-
    256: sha256=<hex>` of the raw body using `META_APP_SECRET`. We
    verify before parsing JSON (constant-time HMAC compare). Mismatch
    → 401 + `integration.webhook.invalid_signature` audit.

Body shape: `{object: "page", entry: [{id: page_id, time, changes:
[{field: "leadgen", value: {leadgen_id, form_id, page_id, ad_id,
created_time, ...}}]}]}`. Multiple changes per entry, multiple
entries per body — we walk the full tree and enqueue one task per
`leadgen` change.

Response is always 200 after auth — even if enqueue fails. Meta
retries on any non-2xx and we'd rather have an alert fire on a
broker outage than have Meta hammer us.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse

from config import META_APP_SECRET, META_WEBHOOK_VERIFY_TOKEN
from src.app.core import audit

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/meta", tags=["Ad Integrations — Meta"])


@router.get("/webhook", include_in_schema=False)
async def meta_verify_handshake(
    request: Request,
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> PlainTextResponse:
    """Meta's GET-time webhook verification handshake.

    Triggered once per environment when an operator saves the
    callback URL in the Meta app dashboard. Echo the challenge iff
    `hub.verify_token` matches our configured secret."""
    if (
        hub_mode == "subscribe"
        and hub_verify_token
        and hub_verify_token == META_WEBHOOK_VERIFY_TOKEN
        and hub_challenge
    ):
        # Meta wants the challenge echoed back as plain text — NOT
        # JSON-wrapped. Some setups break if `hub.challenge` is
        # returned inside a JSON envelope.
        return PlainTextResponse(content=hub_challenge, status_code=200)
    client_ip = request.client.host if request.client else None
    await audit.log(
        "integration.webhook.invalid_signature",
        entity_type="webhook_attempt",
        after={
            "provider": "meta_ads",
            "reason": "verify_token_mismatch",
            "stage": "handshake",
        },
        org_id=None,
        ip=client_ip,
    )
    return PlainTextResponse(content="forbidden", status_code=status.HTTP_403_FORBIDDEN)


@router.post("/webhook", include_in_schema=False)
async def meta_webhook(request: Request) -> JSONResponse:
    """Receive a `leadgen` delivery. Verify HMAC signature on the raw
    body, parse, enqueue one Celery task per leadgen change.

    Always returns 200 once the signature is valid — Meta retries on
    any non-2xx and we'd rather have a metrics-spike alert than have
    Meta retry-storm because the broker hiccupped.
    """
    body = await request.body()
    sig_header = request.headers.get("x-hub-signature-256")
    client_ip = request.client.host if request.client else None

    if not _verify_signature(body, sig_header):
        await audit.log(
            "integration.webhook.invalid_signature",
            entity_type="webhook_attempt",
            after={
                "provider": "meta_ads",
                "reason": "bad_signature",
                "header_present": bool(sig_header),
            },
            org_id=None,
            ip=client_ip,
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "bad signature"},
        )

    # Signature OK — parse + enqueue. Bad JSON returns 400 (Meta
    # shouldn't send us bad JSON; if they do, refusing is correct).
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "malformed JSON body"},
        )

    enqueued_leads = _enqueue_leadgen_changes(payload)
    enqueued_msgs = _enqueue_messaging_events(payload)
    logger.info(
        "meta webhook: signature ok, enqueued %d leadgen + %d messaging task(s)",
        enqueued_leads,
        enqueued_msgs,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "accepted",
            "enqueued": enqueued_leads + enqueued_msgs,
            "leadgen": enqueued_leads,
            "messaging": enqueued_msgs,
        },
    )


def _verify_signature(body: bytes, header: str | None) -> bool:
    """HMAC-SHA256 of `body` with `META_APP_SECRET` matches the
    `sha256=<hex>` prefix of the `X-Hub-Signature-256` header.
    Constant-time compared. Empty/missing header → False."""
    if not header or not header.startswith("sha256="):
        return False
    if not META_APP_SECRET:
        # Missing secret in env — refuse to authenticate anything.
        # Better than accidentally accepting unsigned payloads.
        logger.error("meta webhook: META_APP_SECRET not configured — rejecting all deliveries")
        return False
    provided = header.split("=", 1)[1]
    digest = hmac.new(
        META_APP_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(provided, digest)


def _enqueue_leadgen_changes(payload: Any) -> int:
    """Walk Meta's `entry[].changes[]` tree, enqueue one
    `process_meta_lead` task per change where `field == 'leadgen'`.
    Returns the count for the receiver's response body.

    Other change fields (e.g. `feed`, `mentions`) are silently
    skipped — we only subscribed to `leadgen`, but Meta sometimes
    bundles unrelated changes in the same envelope."""
    if not isinstance(payload, dict):
        return 0
    if payload.get("object") != "page":
        # Leadgen only rides on the "page" object. Instagram DMs come
        # in on object="instagram" and are handled by the messaging
        # fan-out below.
        return 0
    entries = payload.get("entry") or []
    if not isinstance(entries, list):
        return 0

    # Lazy import — keeps a cyclic shim out of the module-load path
    # and matches the pattern in google/webhook.py.
    from src.app.core.integrations.meta.tasks import (
        HAS_CELERY,
        process_meta_lead,
        process_meta_lead_async,
    )

    count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        page_id = entry.get("id")  # the Page id
        changes = entry.get("changes") or []
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict):
                continue
            if change.get("field") != "leadgen":
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            # Hand the worker the slice it needs. `page_id` may live
            # on either the entry (Meta's docs say so) or inside
            # value (some deliveries duplicate it); prefer value's
            # so the worker sees a self-contained envelope.
            task_payload = {
                "leadgen_id": value.get("leadgen_id"),
                "form_id": value.get("form_id"),
                "page_id": value.get("page_id") or page_id,
                "ad_id": value.get("ad_id"),
                "campaign_id": value.get("adgroup_id") or value.get("campaign_id"),
                "created_time": value.get("created_time"),
            }
            if HAS_CELERY:
                try:
                    process_meta_lead.delay(task_payload)
                except Exception:
                    logger.exception(
                        "meta webhook: failed to enqueue task for leadgen_id=%s",
                        task_payload.get("leadgen_id"),
                    )
                    continue
            else:
                # Dev fallback: celery isn't installed. Run inline so
                # smoke tests can verify the full path. Production has
                # celery installed.
                import asyncio

                try:
                    asyncio.create_task(process_meta_lead_async(payload=task_payload))
                except Exception:
                    logger.exception(
                        "meta webhook: inline async processing failed for leadgen_id=%s",
                        task_payload.get("leadgen_id"),
                    )
                    continue
            count += 1
    return count


def _enqueue_messaging_events(payload: Any) -> int:
    """Walk Meta's `entry[].messaging[]` tree, enqueue one
    `process_meta_message` task per inbound message.

    Both Messenger (`object="page"`) and Instagram Direct
    (`object="instagram"`) use the same envelope: entries carry a
    `messaging` array, each entry has `sender.id`, `recipient.id`,
    and either `message` (normal), `postback` (button tap), or
    `reaction`. Delivery/read receipts are skipped for now — v1
    doesn't reflect Messenger read state back into the inbox.
    """
    if not isinstance(payload, dict):
        return 0
    obj = payload.get("object")
    if obj not in ("page", "instagram"):
        return 0
    entries = payload.get("entry") or []
    if not isinstance(entries, list):
        return 0
    channel = "instagram" if obj == "instagram" else "facebook"

    from src.app.core.integrations.meta.tasks import (
        HAS_CELERY,
        process_meta_message,
        process_meta_message_async,
    )

    count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        endpoint_id = entry.get("id")  # Page ID or IG Business Account ID
        messaging = entry.get("messaging") or []
        if not isinstance(messaging, list):
            continue
        for event in messaging:
            if not isinstance(event, dict):
                continue
            if event.get("message") is None and event.get("postback") is None:
                # Delivery / read / echo events — skip for v1.
                continue
            if event.get("message", {}).get("is_echo"):
                # Meta echoes back our own outbound as an inbound
                # event; skip to avoid double-persisting.
                continue
            task_payload = {
                "channel": channel,
                "endpoint_id": endpoint_id,
                "event": event,
            }
            if HAS_CELERY:
                try:
                    process_meta_message.delay(task_payload)
                except Exception:
                    logger.exception(
                        "meta webhook: failed to enqueue messaging task for endpoint=%s",
                        endpoint_id,
                    )
                    continue
            else:
                import asyncio

                try:
                    asyncio.create_task(process_meta_message_async(payload=task_payload))
                except Exception:
                    logger.exception(
                        "meta webhook: inline messaging task failed for endpoint=%s",
                        endpoint_id,
                    )
                    continue
            count += 1
    return count


__all__ = ["router"]
