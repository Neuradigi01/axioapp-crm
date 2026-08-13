"""HMAC-signed email-reply URLs (``tasks/chatbot-builder`` Step 11 /
Decision §15).

Enables Text-Button / Media-Button / List nodes to work over email
by encoding each button as a single-use, prefetch-safe URL that
records the customer's "click" as an inbound message on the correct
conversation.

Threat model + defences:

  * **Forgery** — HMAC-SHA256 with a per-org 32-byte key. Constant-
    time compare via :func:`hmac.compare_digest`. Cross-org
    signature forgery is impossible without the target org's key.
  * **Replay** — every signed URL carries a nonce persisted in
    ``tbl_chatbot_pending_replies``. First POST flips
    ``consumed_at``; second POST sees the row consumed and returns
    ``410 Gone``.
  * **Prefetch (Gmail/Outlook safe-links, Slack unfurl)** — GET
    is a benign interstitial that never advances state. Only the
    POST from the interstitial's form consumes the nonce.
  * **Expiry** — 72 h default. ``expires_at`` on the nonce row is
    checked before verify.
  * **Enumeration** — router rate-limits GET + POST at 30 req/min
    per IP; a plaintext nonce is 32 chars of URL-safe base64
    (192 bits) so brute-force is infeasible anyway.
  * **Info leak** — invalid / expired / consumed URLs render the
    same generic error page. Interstitial shows the button label
    only — never conversation contents (Case #31).

URL scheme: ``/r/{signature}`` where signature is
``base64url(nonce).base64url(exp_ts).base64url(hmac(nonce|exp_ts, org_key))``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.chatbots.models import ChatbotPendingReply
from src.app.core.tenants.models import Organization

logger = logging.getLogger(__name__)


# --- Config --------------------------------------------------------------

# Nonce length in bytes — 24 bytes = 32 base64url chars = 192 bits of
# entropy. Overkill against brute-force + short enough for a
# reasonable URL length.
_NONCE_BYTES = 24
_DEFAULT_TTL_HOURS = 72
_ALLOWED_CHANNELS: frozenset[str] = frozenset({"email", "whatsapp"})


@dataclass(slots=True)
class SignedUrl:
    """What :func:`generate` returns."""

    url: str
    nonce: str
    expires_at: datetime


# --- Signing / verifying primitives --------------------------------------


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _sign(payload: bytes, key: bytes) -> str:
    return _b64url_encode(hmac.new(key, payload, hashlib.sha256).digest())


def _pack_signature(nonce: str, exp_ts: int, sig: str) -> str:
    """Pack the three tokens into one URL segment. Dot-separated so
    the split is trivial + not URL-encoded by mail clients."""
    return f"{nonce}.{exp_ts}.{sig}"


def _unpack_signature(signature: str) -> tuple[str, int, str] | None:
    parts = signature.split(".")
    if len(parts) != 3:
        return None
    nonce, exp_str, sig = parts
    try:
        exp_ts = int(exp_str)
    except ValueError:
        return None
    return nonce, exp_ts, sig


# --- Public API ----------------------------------------------------------


async def generate(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    run_id: uuid.UUID,
    node_id: str,
    button_id: str,
    button_label: str,
    contact_id: uuid.UUID | None,
    channel: str,
    ttl_hours: int = _DEFAULT_TTL_HOURS,
) -> SignedUrl:
    """Mint a signed reply URL. Persists a ``tbl_chatbot_pending_replies``
    row with the nonce; returns the URL for embedding in the email
    button. Caller commits the session (matches the surrounding node
    handler's transaction boundary)."""
    if channel not in _ALLOWED_CHANNELS:
        raise ValueError(f"channel {channel!r} not allowed for signed URLs")

    org = await session.get(Organization, org_id)
    if org is None:
        raise ValueError(f"organization {org_id} not found")
    key = bytes(org.chatbot_signed_url_key)
    if len(key) < 32:
        # Belt-and-braces — the migration guarantees a 32-byte key
        # but a hand-edited row could break this invariant.
        raise ValueError("org.chatbot_signed_url_key must be >= 32 bytes")

    nonce_bytes = secrets.token_bytes(_NONCE_BYTES)
    nonce = _b64url_encode(nonce_bytes)
    expires_at = datetime.now(UTC) + timedelta(hours=ttl_hours)
    exp_ts = int(expires_at.timestamp())

    payload = f"{nonce}.{exp_ts}".encode("ascii")
    sig = _sign(payload, key)
    signature = _pack_signature(nonce, exp_ts, sig)

    row = ChatbotPendingReply(
        org_id=org_id,
        run_id=run_id,
        node_id=node_id,
        button_id=button_id,
        button_label=button_label,
        contact_id=contact_id,
        nonce=nonce,
        channel=channel,
        expires_at=expires_at,
    )
    session.add(row)

    # Path chosen so accidental double-slash concatenation with a
    # base URL doesn't break the route match.
    url = f"/r/{signature}"
    return SignedUrl(url=url, nonce=nonce, expires_at=expires_at)


async def verify(
    session: AsyncSession,
    *,
    signature: str,
) -> ChatbotPendingReply | None:
    """Load the pending-reply row referenced by ``signature`` after
    all safety checks pass. Returns ``None`` on any failure — the
    caller renders the same generic error page for every failure
    mode to avoid info-leak.

    Also enforces:

      * Format: ``nonce.exp.hmac`` triple.
      * Expiry: ``exp`` claim + ``expires_at`` on the row.
      * Consumption: rows already consumed return ``None``.
      * HMAC: constant-time compare using the row's org's key.
    """
    unpacked = _unpack_signature(signature)
    if unpacked is None:
        logger.debug("signed_reply_url.verify malformed")
        return None
    nonce, exp_ts, sig = unpacked

    # Cheap expiry check before touching the DB.
    if datetime.now(UTC).timestamp() >= exp_ts:
        logger.debug("signed_reply_url.verify expired nonce=%s", nonce[:6])
        return None

    row = (
        await session.execute(
            select(ChatbotPendingReply).where(ChatbotPendingReply.nonce == nonce)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.consumed_at is not None:
        return None
    if row.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC):
        return None

    org = await session.get(Organization, row.org_id)
    if org is None:
        return None

    key = bytes(org.chatbot_signed_url_key)
    payload = f"{nonce}.{exp_ts}".encode("ascii")
    expected = _sign(payload, key)
    if not hmac.compare_digest(expected, sig):
        return None

    return row


async def consume(
    session: AsyncSession,
    *,
    nonce: str,
) -> bool:
    """Atomically flip ``consumed_at``. Returns True on success (row
    was still unconsumed); False when a concurrent POST already
    consumed it. Race-safe via ``UPDATE ... WHERE consumed_at IS NULL
    RETURNING`` — Postgres holds the row lock for the duration."""
    result = await session.execute(
        update(ChatbotPendingReply)
        .where(
            ChatbotPendingReply.nonce == nonce,
            ChatbotPendingReply.consumed_at.is_(None),
        )
        .values(consumed_at=datetime.now(UTC))
        .returning(ChatbotPendingReply.id)
    )
    return result.first() is not None


def render_error_page(title: str = "Link expired") -> str:
    """Generic error interstitial. Same shape for every failure
    (invalid / expired / consumed / forged) to avoid info-leak."""
    return _INTERSTITIAL_TEMPLATE.format(
        title=title,
        heading="This link is no longer valid",
        body=(
            "The link may have expired, already been used, or been "
            "modified. If you meant to reply, please send a new "
            "message directly."
        ),
        form_html="",
        org_line="",
    )


def render_interstitial(*, signature: str, button_label: str, org_name: str) -> str:
    """The GET landing page — form-POSTs back to the same signed URL.
    Mail-client prefetchers hit only this page and never advance
    state. Reveals the button label + org name; no conversation
    contents."""
    safe_label = _html_escape(button_label)
    safe_org = _html_escape(org_name)
    form_html = f"""
<form method="POST" action="/r/{_html_escape(signature)}">
  <button type="submit" class="btn">Confirm reply: {safe_label}</button>
</form>
""".strip()
    return _INTERSTITIAL_TEMPLATE.format(
        title=f"Reply: {safe_label}",
        heading=f"Reply: {safe_label}",
        body=f"You're about to send this reply back to <b>{safe_org}</b>.",
        form_html=form_html,
        org_line=f"<p class='muted'>You can safely close this tab if you didn't mean to click.</p>",
    )


def render_success_page(*, button_label: str, org_name: str) -> str:
    return _INTERSTITIAL_TEMPLATE.format(
        title="Reply sent",
        heading="Thanks — your reply is on its way",
        body=f"<b>{_html_escape(org_name)}</b> received your reply: <b>{_html_escape(button_label)}</b>.",
        form_html="",
        org_line="<p class='muted'>You can safely close this tab.</p>",
    )


def _html_escape(value: str) -> str:
    import html as _html_mod

    return _html_mod.escape(value or "", quote=True)


# Deliberately minimal HTML — zinc palette so it visually anchors
# with the auth pages (Decision §15) without pulling in the SPA
# stylesheet. Kept inline so no separate template loader is needed;
# this is a leaf page.
_INTERSTITIAL_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{title}</title>
<meta name="robots" content="noindex,nofollow" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<style>
  html,body {{margin:0;padding:0;height:100%;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f4f4f5;color:#18181b;}}
  .wrap {{min-height:100%;display:flex;align-items:center;justify-content:center;padding:24px;}}
  .card {{background:#fff;border:1px solid #e4e4e7;border-radius:12px;box-shadow:0 6px 24px rgba(0,0,0,.06);padding:28px 32px;max-width:420px;width:100%;}}
  h1 {{margin:0 0 12px;font-size:20px;font-weight:600;}}
  p {{margin:0 0 12px;font-size:14px;line-height:1.5;color:#3f3f46;}}
  p.muted {{color:#71717a;font-size:12px;margin-top:16px;}}
  .btn {{display:inline-block;background:#18181b;color:#fff;border:none;border-radius:8px;padding:12px 20px;font-size:14px;font-weight:600;cursor:pointer;width:100%;}}
  .btn:hover {{background:#27272a;}}
</style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>{heading}</h1>
      <p>{body}</p>
      {form_html}
      {org_line}
    </div>
  </div>
</body>
</html>
"""


__all__ = [
    "SignedUrl",
    "consume",
    "generate",
    "render_error_page",
    "render_interstitial",
    "render_success_page",
    "verify",
]
