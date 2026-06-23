"""Public tracking endpoints.

Three routes, all **unauthenticated** (the recipient's email client
fetches them with no JWT):

  GET /api/v1/track/o/{token}            → 1×1 transparent GIF
  GET /api/v1/track/c/{token}?u=<b64>    → 302 to decoded URL
  GET /api/v1/track/unsubscribe/{token}  → unsubscribe landing page

Token validation goes through `tokens.decode` (HMAC-signed). Tampered
or malformed tokens return 404 with no DB hit.

### Rate limiting

The endpoints are public — a token-fuzzing attacker can iterate
URLs. The shared in-process `InMemoryRateLimiter` caps each IP at
100 requests/min across the whole `/track/*` namespace. Single-process
only; if we ever run multi-worker prod, this graduates to
RedisRateLimiter (per `core/shared/rate_limit.py` future work).

### Privacy

`ip_hash` and `user_agent_hash` are sha256 prefixes — never raw IP /
UA. The recipient's email content is in their inbox; the tracking
URLs reveal nothing beyond the open / click event itself.

### Gmail image proxy caveat

Gmail proxies images through `googleusercontent.com`, so:
  * we see Google's IP, not the user's,
  * the proxy caches the image, so re-opens fire only once at fetch.

This makes open counts a **floor estimate** for Gmail recipients,
and the `ip_hash` is useless for them — both are documented in the
spec; treating opens as a noisy metric is the standard practice in
the industry.
"""
from __future__ import annotations

import base64
import binascii
import logging
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import data_access
from src.app.core.contacts.models import Contact
from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
    Message,
)
from src.app.core.email.tracking.models import (
    EmailMessageClick,
    EmailMessageOpen,
)
from src.app.core.email.tracking.tokens import decode
from src.app.core.email_sequences.models import (
    EmailSequenceEnrollment,
    EmailSequenceEnrollmentStep,
    EnrollmentState,
)
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.db import async_session, get_db
from src.app.shared.rate_limit import InMemoryRateLimiter


log = logging.getLogger(__name__)


router = APIRouter(prefix="/track", tags=["Email Tracking"])


# 100 hits / 60s / IP across the whole /track/* namespace. A
# token-fuzzing attacker can't enumerate valid tokens at any meaningful
# rate; a normal recipient's client makes at most a handful of hits
# per mail. Module-level singleton — instantiated once on import.
_tracking_limiter = InMemoryRateLimiter(max_hits=100, window_seconds=60.0)


# 43-byte 1×1 transparent GIF (the smallest possible GIF file).
_TRANSPARENT_GIF = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)


# --- Helpers --------------------------------------------------------------


def _client_ip(request: Request) -> Optional[str]:
    """Best-effort client IP. Prefer `X-Forwarded-For` (set by the
    reverse proxy in prod); fall back to the socket peer."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


def _hash_prefix(value: Optional[str]) -> Optional[str]:
    """16-char sha256 prefix of a stringy value. Never store raw IP /
    UA — DPDP minimisation."""
    if not value:
        return None
    return sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


def _check_rate_limit(request: Request) -> None:
    """Apply the per-IP cap. Raises 429 on over-limit. Token-fuzzing
    DoS prevention."""
    ip = _client_ip(request) or "unknown"
    result = _tracking_limiter.check(f"track:{ip}")
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Try again shortly.",
            headers={
                "Retry-After": str(int(result.retry_after) + 1),
            },
        )


async def _resolve_message_org(
    session: AsyncSession, *, message_id: uuid.UUID
) -> Optional[uuid.UUID]:
    """Cross-org raw lookup of the message's org_id (RLS is off for
    these endpoints — no tenant context). Returns None when missing.

    We deliberately use the ORM here with no context set because the
    `messages.id` column is the primary key — no RLS bypass needed for
    a direct PK select. The result row is just an id."""
    from sqlalchemy import text as sql_text

    row = (
        await session.execute(
            sql_text("SELECT org_id FROM tbl_messages WHERE id = :mid"),
            {"mid": str(message_id)},
        )
    ).mappings().first()
    return row["org_id"] if row else None


async def _record_open(
    request: Request, *, message_id: uuid.UUID
) -> None:
    """Insert a row into `email_message_opens`. Best-effort — a DB
    failure must not break the pixel response (the recipient just
    sees the 1×1 GIF either way)."""
    try:
        async with async_session() as session:
            org_id = await _resolve_message_org(
                session, message_id=message_id
            )
            if org_id is None:
                return  # silently drop — token references a purged message
            token = set_context(
                RequestContext(org_id=org_id, user_id=None)
            )
            try:
                row = EmailMessageOpen(
                    org_id=org_id,
                    message_id=message_id,
                    ip_hash=_hash_prefix(_client_ip(request)),
                    user_agent_hash=_hash_prefix(
                        request.headers.get("user-agent")
                    ),
                )
                session.add(row)
                await session.commit()
            finally:
                reset_context(token)
    except Exception:
        log.exception(
            "tracking._record_open failed for message=%s", message_id
        )


async def _record_click(
    request: Request,
    *,
    message_id: uuid.UUID,
    target_url: str,
) -> None:
    """Insert a row into `email_message_clicks`. Best-effort — a DB
    failure must not block the 302 redirect."""
    try:
        async with async_session() as session:
            org_id = await _resolve_message_org(
                session, message_id=message_id
            )
            if org_id is None:
                return
            token = set_context(
                RequestContext(org_id=org_id, user_id=None)
            )
            try:
                row = EmailMessageClick(
                    org_id=org_id,
                    message_id=message_id,
                    # `text` column — cap at 2048 to bound row size on
                    # pathological URLs.
                    target_url=target_url[:2048],
                    ip_hash=_hash_prefix(_client_ip(request)),
                )
                session.add(row)
                await session.commit()
            finally:
                reset_context(token)
    except Exception:
        log.exception(
            "tracking._record_click failed for message=%s", message_id
        )


async def _resolve_contact_from_message(
    session: AsyncSession, *, message_id: uuid.UUID
) -> Optional[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:
    """Return `(org_id, contact_id, conversation_id)` for a message
    whose conversation has channel=email. None when not resolvable."""
    from sqlalchemy import text as sql_text

    row = (
        await session.execute(
            sql_text(
                """
                SELECT c.org_id, c.contact_id, c.id AS conversation_id
                FROM tbl_messages m
                JOIN tbl_conversations c ON c.id = m.conversation_id
                WHERE m.id = :mid
                  AND c.channel = 'email'
                  AND c.contact_id IS NOT NULL
                """
            ),
            {"mid": str(message_id)},
        )
    ).mappings().first()
    if row is None:
        return None
    return row["org_id"], row["contact_id"], row["conversation_id"]


async def _opt_out_contact(
    request: Request, *, message_id: uuid.UUID
) -> tuple[bool, Optional[uuid.UUID]]:
    """Set `contacts.email_opt_out=True` and cancel any active sequence
    enrollments for that contact. Returns `(success, contact_id)` so
    the landing page can echo confirmation."""
    try:
        async with async_session() as session:
            resolved = await _resolve_contact_from_message(
                session, message_id=message_id
            )
            if resolved is None:
                return False, None
            org_id, contact_id, _conv_id = resolved
            token = set_context(
                RequestContext(org_id=org_id, user_id=None)
            )
            try:
                contact = await data_access.get_contact(session, contact_id)
                if contact is None:
                    return False, None
                now = datetime.now(timezone.utc)
                contact.email_opt_out = True
                contact.email_opt_out_at = now

                # Cancel active or paused-on-reply enrollments for this
                # contact. Manual-paused enrollments are NOT auto-
                # cancelled — the operator may resume them after a
                # different consent signal.
                active_enrollments = (
                    await session.execute(
                        select(EmailSequenceEnrollment).where(
                            EmailSequenceEnrollment.contact_id == contact_id,
                            EmailSequenceEnrollment.state.in_(
                                [
                                    EnrollmentState.active.value,
                                    EnrollmentState.paused_on_reply.value,
                                ]
                            ),
                        )
                    )
                ).scalars().all()
                for enr in active_enrollments:
                    enr.state = EnrollmentState.cancelled.value
                    enr.state_changed_at = now
                    # Skip pending step rows so the scheduler ignores
                    # them.
                    await session.execute(
                        EmailSequenceEnrollmentStep.__table__.update()
                        .where(
                            EmailSequenceEnrollmentStep.enrollment_id == enr.id,
                            EmailSequenceEnrollmentStep.sent_at.is_(None),
                            EmailSequenceEnrollmentStep.skipped.is_(False),
                        )
                        .values(
                            skipped=True,
                            skip_reason="contact_unsubscribed",
                        )
                    )
                await session.commit()
                return True, contact_id
            finally:
                reset_context(token)
    except Exception:
        log.exception(
            "tracking._opt_out_contact failed for message=%s", message_id
        )
        return False, None


# --- Routes ---------------------------------------------------------------


@router.get("/o/{token}")
async def open_pixel_endpoint(
    token: str, request: Request
) -> Response:
    """Return the 1×1 transparent GIF and record the open."""
    _check_rate_limit(request)
    payload = decode(token)
    if payload is None or payload.get("kind") != "o":
        # Constant 404 — never leak whether the token was malformed
        # vs the wrong kind. Pixel-fuzzing returns nothing useful.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found.",
        )
    message_id = payload["message_id"]
    assert isinstance(message_id, uuid.UUID)
    await _record_open(request, message_id=message_id)
    return Response(
        content=_TRANSPARENT_GIF,
        media_type="image/gif",
        headers={
            # Some clients (Gmail proxy) cache aggressively; no-store
            # is more guidance than law but helps when we want a
            # re-fetch.
            "Cache-Control": "no-store, no-cache, must-revalidate, "
            "max-age=0",
            "Pragma": "no-cache",
            # Don't expose any framing — defence-in-depth.
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/c/{token}")
async def click_redirect_endpoint(
    token: str, u: str, request: Request
) -> RedirectResponse:
    """Decode the token + the `u=` query, record the click, redirect."""
    _check_rate_limit(request)
    payload = decode(token)
    if payload is None or payload.get("kind") != "c":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found.",
        )
    # Decode the base64url-encoded target URL.
    try:
        padding = "=" * (-len(u) % 4)
        target = base64.urlsafe_b64decode(u + padding).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found.",
        )
    # Defence: don't blindly trust the target — require http/https.
    if not (
        target.lower().startswith("http://")
        or target.lower().startswith("https://")
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found.",
        )
    message_id = payload["message_id"]
    assert isinstance(message_id, uuid.UUID)
    await _record_click(request, message_id=message_id, target_url=target)
    return RedirectResponse(url=target, status_code=302)


_UNSUB_OK = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Unsubscribed</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
        Roboto, Helvetica, Arial, sans-serif;
      max-width: 420px;
      margin: 80px auto;
      padding: 0 24px;
      color: #18181b;
      text-align: center;
    }}
    h1 {{ font-size: 20px; margin: 16px 0 8px; }}
    p  {{ font-size: 14px; color: #52525b; line-height: 1.5; }}
    .check {{
      display: inline-flex; width: 48px; height: 48px;
      border-radius: 50%; background: #d1fae5; color: #047857;
      align-items: center; justify-content: center; font-size: 24px;
    }}
  </style>
</head>
<body>
  <div class="check">✓</div>
  <h1>You're unsubscribed</h1>
  <p>You won't receive further marketing emails from this sender. Transactional emails (receipts, account notifications) may still arrive.</p>
</body>
</html>"""


_UNSUB_INVALID = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Link expired</title>
<style>body{font-family:sans-serif;max-width:420px;margin:80px auto;text-align:center;color:#18181b}</style>
</head><body><h1>Link expired</h1>
<p>This unsubscribe link is no longer valid. If you're still receiving emails, reply to one of them with "STOP" and we'll handle the request manually.</p>
</body></html>"""


@router.get("/unsubscribe/{token}", response_class=HTMLResponse)
async def unsubscribe_endpoint(
    token: str, request: Request
) -> HTMLResponse:
    """Decode the token, set `email_opt_out=true` on the contact, cancel
    active sequence enrollments, render a simple confirmation page."""
    _check_rate_limit(request)
    payload = decode(token)
    if payload is None or payload.get("kind") != "u":
        return HTMLResponse(content=_UNSUB_INVALID, status_code=200)
    message_id = payload["message_id"]
    assert isinstance(message_id, uuid.UUID)
    success, _contact_id = await _opt_out_contact(
        request, message_id=message_id
    )
    if not success:
        return HTMLResponse(content=_UNSUB_INVALID, status_code=200)
    return HTMLResponse(content=_UNSUB_OK, status_code=200)


__all__ = ["router"]
