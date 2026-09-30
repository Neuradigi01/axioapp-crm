"""Public reply-URL router (``tasks/chatbot-builder`` Step 11).

Mounts at root (``/r/*``) rather than ``/api/v1/chatbots`` because
the customer clicks these URLs from an email client — no JWT, no
tenant context, deliberately unauthenticated. All safety comes
from the HMAC + nonce infrastructure in
:mod:`core.chatbots.signed_reply_urls`.

Two endpoints:

  * ``GET  /r/{sig}`` — benign interstitial. Mail-client
    prefetchers hit only this. Never advances state. Renders the
    Confirm-Reply page or a generic error page.
  * ``POST /r/{sig}`` — the interstitial's form submit. Consumes
    the nonce, creates the inbound Message on the correct
    conversation, publishes the ``*.message_received`` event so
    the trigger matcher resumes the parked run.

Rate-limited at 30 req/min per IP to defeat nonce enumeration.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.chatbots import signed_reply_urls as _urls
from src.app.core.events import bus as events_bus
from src.app.core.events.event_catalog import (
    EMAIL_MESSAGE_RECEIVED,
    WHATSAPP_MESSAGE_RECEIVED,
)
from src.app.core.tenants.models import Organization
from src.app.shared.db import get_db
from src.app.shared.rate_limit import InMemoryRateLimiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/r", tags=["Chat Bots · Public Reply"])

# 30 hits per minute per IP — plenty for a click flow, tight enough
# to make nonce enumeration painful.
_reply_limiter = InMemoryRateLimiter(max_hits=30, window_seconds=60.0)


def _client_key(request: Request, signature: str) -> str:
    """Rate-limit bucket key. Uses the IP alone (not signature) so a
    scanner can't win by rotating signatures — one bad actor per IP
    hits the cap regardless."""
    return f"chatbot_reply:{request.client.host if request.client else 'unknown'}"


def _check_rate_limit(request: Request, signature: str) -> HTMLResponse | None:
    result = _reply_limiter.check(_client_key(request, signature))
    if not result.allowed:
        return HTMLResponse(
            content=_urls.render_error_page("Too many requests"),
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    return None


@router.get("/{signature}", response_class=HTMLResponse)
async def reply_interstitial(
    signature: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Prefetch-safe landing. Verifies the signature + shows the
    Confirm-Reply page; renders a generic error page for every
    failure mode so a probing attacker can't distinguish
    expired-vs-forged-vs-consumed."""
    rl = _check_rate_limit(request, signature)
    if rl is not None:
        return rl

    row = await _urls.verify(db, signature=signature)
    if row is None:
        return HTMLResponse(
            content=_urls.render_error_page(),
            status_code=status.HTTP_200_OK,  # 200 not 404 — same shape as valid
        )

    org = await db.get(Organization, row.org_id)
    org_name = org.name if org is not None else "the sender"
    html = _urls.render_interstitial(
        signature=signature,
        button_label=row.button_label,
        org_name=org_name,
    )
    return HTMLResponse(content=html, status_code=status.HTTP_200_OK)


@router.post("/{signature}", response_class=HTMLResponse)
async def reply_submit(
    signature: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Consume the nonce, record the reply as an inbound Message,
    publish the trigger event so the parked run resumes."""
    rl = _check_rate_limit(request, signature)
    if rl is not None:
        return rl

    row = await _urls.verify(db, signature=signature)
    if row is None:
        return HTMLResponse(
            content=_urls.render_error_page(),
            status_code=status.HTTP_410_GONE,
        )

    # Atomic consume — a concurrent second POST loses the race.
    ok = await _urls.consume(db, nonce=row.nonce)
    if not ok:
        await db.commit()
        return HTMLResponse(
            content=_urls.render_error_page("Already used"),
            status_code=status.HTTP_410_GONE,
        )

    # Load run to find conversation + channel; the event we publish
    # tells the matcher which resume path to take.
    from src.app.core.chatbots import data_access as _dal

    run = await _dal.get_run(db, run_id=row.run_id)
    if run is None or run.conversation_id is None:
        await db.commit()
        return HTMLResponse(
            content=_urls.render_error_page(),
            status_code=status.HTTP_410_GONE,
        )

    # Insert an inbound Message that mirrors what the customer would
    # have sent via the actual channel — text = button label.
    from src.app.core.conversations.models import (
        Conversation,
        Message,
        MessageDirection,
    )
    from src.app.core.conversations.utils import wake_on_inbound

    conv = await db.get(Conversation, run.conversation_id)
    if conv is None:
        await db.commit()
        return HTMLResponse(
            content=_urls.render_error_page(),
            status_code=status.HTTP_410_GONE,
        )

    inbound = Message(
        org_id=conv.org_id,
        conversation_id=conv.id,
        direction=MessageDirection.in_,
        text=row.button_label,
        attachments=[],
        payload={
            "authored_by": "signed_reply_url",
            "run_id": str(run.id),
            "node_id": row.node_id,
            "button_id": row.button_id,
        },
        sent_at=datetime.now(UTC),
    )
    db.add(inbound)
    conv.last_message_at = inbound.sent_at
    conv.last_customer_message_at = inbound.sent_at
    conv.unread_count = (conv.unread_count or 0) + 1
    wake_on_inbound(conv)
    await db.commit()
    await db.refresh(inbound)

    # Publish the matching trigger event so the trigger matcher's
    # existing active-run path picks this up + resumes the parked run
    # with resumed_by='inbound' and last_inbound_text = button label.
    event_type = WHATSAPP_MESSAGE_RECEIVED if row.channel == "whatsapp" else EMAIL_MESSAGE_RECEIVED
    try:
        await events_bus.publish(
            event_type,
            {
                "conversation_id": str(conv.id),
                "contact_id": (str(conv.contact_id) if conv.contact_id else None),
                "message_id": str(inbound.id),
                "text": row.button_label,
                "channel": conv.channel.value,
                "is_first_message": False,
                "direction": "in",
            },
            org_id=conv.org_id,
            event_id=str(inbound.id),
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "signed_reply_url.publish_failed conv=%s run=%s",
            conv.id,
            run.id,
        )

    org = await db.get(Organization, row.org_id)
    org_name = org.name if org is not None else "the sender"
    return HTMLResponse(
        content=_urls.render_success_page(button_label=row.button_label, org_name=org_name),
        status_code=status.HTTP_200_OK,
    )
